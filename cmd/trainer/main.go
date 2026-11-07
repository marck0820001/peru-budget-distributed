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
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/marck0820001/peru-budget-distributed.git/internal/ml/kmeans"
)

type Benchmark struct {
	Workers            int       `json:"workers"`
	RunsMilliseconds   []float64 `json:"runs_ms"`
	MedianMilliseconds float64   `json:"median_ms"`
	Speedup            float64   `json:"speedup_vs_single"`
	Efficiency         float64   `json:"parallel_efficiency"`
	Inertia            float64   `json:"inertia"`
	Iterations         int       `json:"iterations"`
}

type Report struct {
	DatasetRows      int           `json:"dataset_rows"`
	Features         []string      `json:"features"`
	K                int           `json:"k"`
	Seed             int64         `json:"seed"`
	MaxIterations    int           `json:"max_iterations"`
	Tolerance        float64       `json:"tolerance"`
	Result           kmeans.Result `json:"training"`
	SilhouetteSample *float64      `json:"silhouette_sample,omitempty"`
	SilhouetteNote   string        `json:"silhouette_note"`
	Benchmarks       []Benchmark   `json:"benchmarks"`
	Warning          string        `json:"warning"`
}

func parseWorkers(s string, defaultValue int) ([]int, error) {
	if strings.TrimSpace(s) == "" {
		return []int{defaultValue}, nil
	}
	seen := map[int]bool{}
	out := []int{}
	for _, chunk := range strings.Split(s, ",") {
		n, err := strconv.Atoi(strings.TrimSpace(chunk))
		if err != nil || n < 1 {
			return nil, fmt.Errorf("lista inválida: %q", chunk)
		}
		if !seen[n] {
			out = append(out, n)
			seen[n] = true
		}
	}
	if !seen[1] {
		out = append(out, 1)
	}
	return out, nil
}

func median(xs []float64) float64 {
	cp := append([]float64(nil), xs...)
	sort.Float64s(cp)
	if len(cp)%2 == 1 {
		return cp[len(cp)/2]
	}
	return (cp[len(cp)/2-1] + cp[len(cp)/2]) / 2
}

func writeJSON(path string, v any) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	enc := json.NewEncoder(f)
	enc.SetIndent("", "  ")
	return enc.Encode(v)
}

func writeAssignments(path string, keys []kmeans.Key, r kmeans.Result) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	if err := w.Write([]string{"ano_eje", "sec_ejec", "departamento", "ejecutora_nombre", "tipo_entidad", "cluster", "distancia_centroide"}); err != nil {
		return err
	}
	for i, key := range keys {
		record := []string{key.Year, key.Entity, key.Department, key.Name, key.Type,
			strconv.Itoa(r.Assignments[i]), strconv.FormatFloat(r.Distances[i], 'f', 10, 64)}
		if err := w.Write(record); err != nil {
			return err
		}
	}
	w.Flush()
	return w.Error()
}

func main() {
	matrixPath := flag.String("matrix", "data/processed/features_mef/kmeans_matrix.csv", "CSV numérico producido por feature engineering")
	keysPath := flag.String("keys", "data/processed/features_mef/kmeans_keys.csv", "CSV con claves alineadas a la matriz")
	outDir := flag.String("out", "data/processed/kmeans_go", "directorio de resultados")
	k := flag.Int("k", 4, "número de clústeres")
	workerCount := flag.Int("workers", 4, "goroutines por iteración (1 = referencia secuencial)")
	workerList := flag.String("benchmark-workers", "", "lista de workers separada por comas, ej. 1,2,4,8")
	repeats := flag.Int("repeats", 3, "repeticiones por configuración para el benchmark")
	seed := flag.Int64("seed", 42, "semilla fija de inicialización K-Means++")
	maxIter := flag.Int("max-iter", 100, "límite de iteraciones")
	tol := flag.Float64("tol", 1e-6, "tolerancia del desplazamiento máximo del centroide")
	silhouette := flag.Int("silhouette-sample", 200, "anclas para silueta estimada; 0 = omitir")
	flag.Parse()
	if *repeats < 1 {
		log.Fatal("repeats debe ser positivo")
	}
	data, err := kmeans.ReadMatrix(*matrixPath)
	if err != nil {
		log.Fatal(err)
	}
	keys, err := kmeans.ReadKeys(*keysPath, len(data))
	if err != nil {
		log.Fatal(err)
	}
	workers, err := parseWorkers(*workerList, *workerCount)
	if err != nil {
		log.Fatal(err)
	}
	if err := os.MkdirAll(*outDir, 0755); err != nil {
		log.Fatal(err)
	}
	benchmarks := make([]Benchmark, 0, len(workers))
	var primary kmeans.Result
	// First benchmark the sequential reference regardless of the order requested.
	ordered := append([]int(nil), workers...)
	sort.Ints(ordered)
	for _, w := range ordered {
		opts := kmeans.Options{K: *k, Workers: w, MaxIterations: *maxIter, Tolerance: *tol, Seed: *seed}
		times := make([]float64, 0, *repeats)
		var lastResult kmeans.Result
		for rep := 0; rep < *repeats; rep++ {
			start := time.Now()
			result, e := kmeans.Train(data, opts)
			if e != nil {
				log.Fatal(e)
			}
			ms := float64(time.Since(start).Microseconds()) / 1000
			times = append(times, ms)
			lastResult = result
			if primary.Assignments == nil || w == *workerCount && rep == 0 {
				primary = result
			}
			if len(benchmarks) > 0 {
				reference := benchmarks[0].Inertia
				if math.Abs(reference-result.Inertia) > 1e-6*math.Max(1, reference) {
					log.Fatalf("inercia distinta con %d workers: %.10g vs %.10g", w, result.Inertia, reference)
				}
			}
		}
		benchmarks = append(benchmarks, Benchmark{Workers: w, RunsMilliseconds: times, MedianMilliseconds: median(times), Inertia: lastResult.Inertia, Iterations: lastResult.Iterations})
	}
	// Ensure published assignments match the user-requested worker count.
	primary, err = kmeans.Train(data, kmeans.Options{K: *k, Workers: *workerCount, MaxIterations: *maxIter, Tolerance: *tol, Seed: *seed})
	if err != nil {
		log.Fatal(err)
	}
	reference := benchmarks[0].MedianMilliseconds
	for i := range benchmarks {
		b := &benchmarks[i]
		b.Speedup = reference / b.MedianMilliseconds
		b.Efficiency = b.Speedup / float64(b.Workers)
	}
	report := Report{DatasetRows: len(data), Features: kmeans.ExpectedFeatures, K: *k, Seed: *seed, MaxIterations: *maxIter, Tolerance: *tol, Result: primary, Benchmarks: benchmarks,
		SilhouetteNote: "Silueta aproximada por muestreo (no representa evaluación exhaustiva).",
		Warning:        "El entrenamiento usa perfiles municipales (~3.8k), no las 3.64M filas; la carga masiva en Go se evalúa aparte con cmd/etl."}
	if *silhouette > 0 {
		v := kmeans.SampleSilhouette(data, primary.Assignments, *k, *silhouette, 5000, *seed)
		if !math.IsNaN(v) {
			report.SilhouetteSample = &v
		}
	}
	if err := writeJSON(filepath.Join(*outDir, "training_report.json"), report); err != nil {
		log.Fatal(err)
	}
	if err := writeAssignments(filepath.Join(*outDir, "assignments.csv"), keys, primary); err != nil {
		log.Fatal(err)
	}
	fmt.Printf("Matriz: %d perfiles x %d variables, K=%d, iteraciones=%d, convergió=%t, inercia=%.6f\n", len(data), len(data[0]), *k, primary.Iterations, primary.Converged, primary.Inertia)
	fmt.Printf("Tamaño de clústeres: %v\n", primary.ClusterSizes)
	if report.SilhouetteSample != nil {
		fmt.Printf("Silueta estimada: %.4f\n", *report.SilhouetteSample)
	}
	for _, b := range benchmarks {
		fmt.Printf("workers=%d, mediana=%.3f ms, speedup=%.3fx, eficiencia=%.1f%%\n", b.Workers, b.MedianMilliseconds, b.Speedup, b.Efficiency*100)
	}
	fmt.Printf("Archivos guardados en %s\n", *outDir)
}
