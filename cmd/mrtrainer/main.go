// Command trainer ejecuta la Parte B (versión concurrente, PC3): entrena
// K-Means paralelo sobre la matriz de perfiles municipales, selecciona K,
// y marca perfiles con desviación atípica respecto de su grupo.
//
//	go run ./cmd/trainer --in data/processed/go_etl --kmin 2 --kmax 10 --workers 8
//	go run ./cmd/trainer --in data/processed/go_etl --k 5
//
// Acepta la matriz generada por cmd/etl o por scripts/eda/feature_engineering.py.
package main

import (
	"encoding/csv"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"math"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"

	"github.com/marck0820001/peru-budget-distributed.git/internal/features"
	"github.com/marck0820001/peru-budget-distributed.git/internal/ml/kmeansmr"
)

type kRow struct {
	K             int     `json:"k"`
	Inertia       float64 `json:"inertia"`
	Silhouette    float64 `json:"silhouette"`
	DaviesBouldin float64 `json:"davies_bouldin"`
	Iterations    int     `json:"iterations"`
	Seconds       float64 `json:"seconds"`
}

type clusterProfile struct {
	Cluster   int                `json:"cluster"`
	Size      int                `json:"size"`
	Share     float64            `json:"share"`
	CentroidZ map[string]float64 `json:"centroid_scaled"`
	MedianRaw map[string]float64 `json:"median_raw"`
	Anomalies int                `json:"anomalies"`
	Threshold float64            `json:"distance_threshold"`
}

func main() {
	in := flag.String("in", "data/processed/go_etl", "carpeta con kmeans_matrix.csv y kmeans_keys.csv")
	out := flag.String("out", "", "carpeta de salida (por defecto <in>/kmeans)")
	k := flag.Int("k", 0, "número de clusters (0 = elegir por silueta entre kmin y kmax)")
	kmin := flag.Int("kmin", 2, "K mínimo a evaluar")
	kmax := flag.Int("kmax", 10, "K máximo a evaluar")
	workers := flag.Int("workers", runtime.NumCPU(), "goroutines de K-Means")
	seed := flag.Int64("seed", 42, "semilla k-means++")
	maxIter := flag.Int("max-iter", 300, "iteraciones máximas")
	flag.Parse()
	if *out == "" {
		*out = filepath.Join(*in, "kmeans")
	}
	must(os.MkdirAll(*out, 0o755))
	names, X, keys, keyHeader, err := features.ReadMatrix(*in)
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("Matriz: %d perfiles × %d features %v · workers=%d", len(X), len(names), names, *workers)

	// 1) Selección de K: curva del codo + silueta (y Davies-Bouldin).
	var sel []kRow
	if *k == 0 {
		for kk := *kmin; kk <= *kmax; kk++ {
			m, err := kmeansmr.Parallel(X, kmeansmr.Options{K: kk, MaxIter: *maxIter, Seed: *seed, Workers: *workers})
			if err != nil {
				log.Fatal(err)
			}
			sil := kmeansmr.Silhouette(X, m.Labels, kk, *workers, nil)
			db := kmeansmr.DaviesBouldin(X, m.Labels, m.Centroids)
			sel = append(sel, kRow{K: kk, Inertia: m.Inertia, Silhouette: sil, DaviesBouldin: db, Iterations: m.Iterations, Seconds: m.ElapsedSec})
			log.Printf("K=%2d inercia=%.1f silueta=%.4f DB=%.3f iter=%d", kk, m.Inertia, sil, db, m.Iterations)
		}
		best := sel[0]
		for _, r := range sel {
			if r.Silhouette > best.Silhouette {
				best = r
			}
		}
		*k = best.K
		log.Printf("K seleccionado por silueta máxima: %d", *k)
		writeSelection(filepath.Join(*out, "k_selection.csv"), sel)
	}

	// 2) Entrenamiento final + comparación con la versión secuencial.
	opts := kmeansmr.Options{K: *k, MaxIter: *maxIter, Seed: *seed, Workers: *workers}
	seq, err := kmeansmr.Sequential(X, opts)
	if err != nil {
		log.Fatal(err)
	}
	par, err := kmeansmr.Parallel(X, opts)
	if err != nil {
		log.Fatal(err)
	}
	same := 0
	for i := range seq.Labels {
		if seq.Labels[i] == par.Labels[i] {
			same++
		}
	}
	log.Printf("Secuencial: %.4fs, Paralelo(%d): %.4fs · etiquetas iguales %d/%d · inercia %.6f vs %.6f",
		seq.ElapsedSec, par.Workers, par.ElapsedSec, same, len(X), seq.Inertia, par.Inertia)

	sil := kmeansmr.Silhouette(X, par.Labels, *k, *workers, nil)
	anoms, thr := kmeansmr.DetectAnomalies(X, par.Labels, par.Centroids)
	dist := kmeansmr.Distances(X, par.Labels, par.Centroids)
	isAnom := map[int]kmeansmr.Anomaly{}
	for _, a := range anoms {
		isAnom[a.Index] = a
	}

	// 3) Interpretación: medianas de indicadores SIN escalar por cluster.
	raw := loadRaw(filepath.Join(*in, "municipality_features_audit.csv"))
	profiles := make([]clusterProfile, *k)
	for c := range profiles {
		profiles[c] = clusterProfile{Cluster: c, CentroidZ: map[string]float64{}, MedianRaw: map[string]float64{}, Threshold: thr[c]}
		for j, n := range names {
			profiles[c].CentroidZ[n] = par.Centroids[c][j]
		}
	}
	vals := make([]map[string][]float64, *k)
	for c := range vals {
		vals[c] = map[string][]float64{}
	}
	for i, l := range par.Labels {
		profiles[l].Size++
		if _, ok := isAnom[i]; ok {
			profiles[l].Anomalies++
		}
		if r, ok := raw[keys[i][0]+"|"+keys[i][1]]; ok {
			for n, v := range r {
				vals[l][n] = append(vals[l][n], v)
			}
		}
	}
	for c := range profiles {
		profiles[c].Share = float64(profiles[c].Size) / float64(len(X))
		for n, v := range vals[c] {
			sort.Float64s(v)
			profiles[c].MedianRaw[n] = features.Percentile(v, 0.5)
		}
	}

	// 4) Salidas.
	cf, _ := os.Create(filepath.Join(*out, "clusters.csv"))
	cw := csv.NewWriter(cf)
	cw.Write(append(append([]string{}, keyHeader...), "cluster", "distancia_centroide", "umbral_cluster", "atipico"))
	for i := range X {
		flag := "0"
		if _, ok := isAnom[i]; ok {
			flag = "1"
		}
		cw.Write(append(append([]string{}, keys[i]...), strconv.Itoa(par.Labels[i]), f(dist[i]), f(thr[par.Labels[i]]), flag))
	}
	cw.Flush()
	cf.Close()

	af, _ := os.Create(filepath.Join(*out, "anomalias.csv"))
	aw := csv.NewWriter(af)
	aw.Write(append(append([]string{}, keyHeader...), "cluster", "distancia", "umbral", "score", "motivo"))
	for _, a := range anoms {
		aw.Write(append(append([]string{}, keys[a.Index]...), strconv.Itoa(a.Cluster), f(a.Distance), f(a.Threshold), f(a.Score), a.Reason))
	}
	aw.Flush()
	af.Close()

	must(writeJSON(filepath.Join(*out, "modelo.json"), map[string]any{
		"k": *k, "features": names, "n_profiles": len(X), "seed": *seed, "workers": par.Workers,
		"inertia": par.Inertia, "silhouette": sil, "davies_bouldin": kmeansmr.DaviesBouldin(X, par.Labels, par.Centroids),
		"iterations": par.Iterations, "converged": par.Converged, "centroids_scaled": par.Centroids,
		"sizes": par.Sizes, "history": par.History, "clusters": profiles, "anomalies": len(anoms),
		"sequential_seconds": seq.ElapsedSec, "parallel_seconds": par.ElapsedSec,
		"labels_equal_sequential": same, "sequential_inertia": seq.Inertia,
		"anomaly_rule": "distancia al centroide > Q3 + 1.5·IQR de las distancias del propio cluster",
	}))
	log.Printf("K=%d silueta=%.4f · atípicos=%d (%.2f%%) · salida en %s", *k, sil, len(anoms), 100*float64(len(anoms))/float64(len(X)), *out)
}

// loadRaw lee los indicadores sin escalar del archivo de auditoría (si existe).
func loadRaw(path string) map[string]map[string]float64 {
	out := map[string]map[string]float64{}
	fh, err := os.Open(path)
	if err != nil {
		return out
	}
	defer fh.Close()
	rows, err := csv.NewReader(fh).ReadAll()
	if err != nil || len(rows) < 2 {
		return out
	}
	idx := map[string]int{}
	for i, h := range rows[0] {
		idx[h] = i
	}
	for _, r := range rows[1:] {
		m := map[string]float64{}
		for _, n := range features.Names {
			if j, ok := idx[n]; ok {
				if v, err := strconv.ParseFloat(r[j], 64); err == nil {
					m[n] = v
				}
			}
		}
		out[r[idx["ano_eje"]]+"|"+r[idx["sec_ejec"]]] = m
	}
	return out
}

func writeSelection(path string, rows []kRow) {
	fh, err := os.Create(path)
	must(err)
	defer fh.Close()
	w := csv.NewWriter(fh)
	w.Write([]string{"k", "inertia", "silhouette", "davies_bouldin", "iterations", "seconds"})
	for _, r := range rows {
		w.Write([]string{strconv.Itoa(r.K), f(r.Inertia), f(r.Silhouette), f(r.DaviesBouldin), strconv.Itoa(r.Iterations), f(r.Seconds)})
	}
	w.Flush()
}

func f(v float64) string {
	if math.IsInf(v, 0) || math.IsNaN(v) {
		return ""
	}
	return strconv.FormatFloat(v, 'f', 6, 64)
}

func writeJSON(path string, v any) error {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return fmt.Errorf("json: %w", err)
	}
	return os.WriteFile(path, b, 0o644)
}

func must(err error) {
	if err != nil {
		log.Fatal(err)
	}
}
