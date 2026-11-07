// Command benchmark mide el speedup del ETL concurrente y del K-Means
// paralelo con distintos números de workers y guarda los tiempos en CSV.
//
//	go run ./cmd/benchmark --data-dir data/raw --matrix data/processed/go_etl --workers 1,2,4,8
//
// ETL: procesa los dos CSV completos (secuencial + cada configuración).
// K-Means: la matriz municipal (~3.6k perfiles) es pequeña, así que además se
// evalúa la escalabilidad sobre N puntos remuestreados (bootstrap + ruido)
// de la misma matriz, que es el volumen esperado al distribuirlo en la PC4.
package main

import (
	"encoding/csv"
	"flag"
	"fmt"
	"log"
	"math/rand"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/marck0820001/peru-budget-distributed.git/internal/features"
	"github.com/marck0820001/peru-budget-distributed.git/internal/ingestion"
	"github.com/marck0820001/peru-budget-distributed.git/internal/ml/kmeansmr"
)

func main() {
	dataDir := flag.String("data-dir", "data/raw", "CSV del MEF")
	matrix := flag.String("matrix", "data/processed/go_etl", "carpeta con kmeans_matrix.csv")
	out := flag.String("out", "data/processed/benchmarks", "salida")
	wl := flag.String("workers", "1,2,4,8", "lista de workers")
	reps := flag.Int("reps", 3, "repeticiones (se reporta la mediana)")
	n := flag.Int("kmeans-n", 1000000, "puntos para la prueba de escalabilidad de K-Means")
	k := flag.Int("k", 4, "K para el benchmark de K-Means")
	skipETL := flag.Bool("skip-etl", false, "omitir benchmark del ETL")
	flag.Parse()
	var workers []int
	for _, s := range strings.Split(*wl, ",") {
		w, _ := strconv.Atoi(strings.TrimSpace(s))
		workers = append(workers, w)
	}
	must(os.MkdirAll(*out, 0o755))
	f, err := os.Create(filepath.Join(*out, "speedup.csv"))
	must(err)
	defer f.Close()
	w := csv.NewWriter(f)
	defer w.Flush()
	w.Write([]string{"etapa", "configuracion", "workers", "n", "segundos_mediana", "speedup", "eficiencia", "num_cpu"})
	cpu := runtime.NumCPU()

	if !*skipETL {
		files := [][2]string{}
		for _, y := range []string{"2024", "2025"} {
			m, _ := filepath.Glob(filepath.Join(*dataDir, y+"-Gasto-Devengado*.csv"))
			if len(m) != 1 {
				log.Fatalf("falta Gasto Devengado %s en %s", y, *dataDir)
			}
			files = append(files, [2]string{y, m[0]})
		}
		run := func(wk int) (float64, int64) {
			r := ingestion.NewResult()
			t := time.Now()
			for _, fl := range files {
				y, _ := strconv.Atoi(fl[0])
				var err error
				if wk == 0 {
					_, err = ingestion.ProcessFileSequential(fl[1], y, true, false, r, nil)
				} else {
					_, err = ingestion.ProcessFile(fl[1], y, ingestion.Config{Workers: wk, ChunkRecords: 20000, DetectDuplicates: true}, r, nil)
				}
				must(err)
			}
			return time.Since(t).Seconds(), r.Total.RowsRead
		}
		base, rows := median(*reps, func() float64 { s, _ := run(0); return s }), int64(0)
		_, rows = run(1)
		log.Printf("ETL secuencial: %.2fs (%d filas)", base, rows)
		w.Write([]string{"etl", "secuencial", "0", fmt.Sprint(rows), f3(base), "1.000", "", fmt.Sprint(cpu)})
		for _, wk := range workers {
			s := median(*reps, func() float64 { t, _ := run(wk); return t })
			log.Printf("ETL %d workers: %.2fs speedup=%.2fx", wk, s, base/s)
			w.Write([]string{"etl", "concurrente", fmt.Sprint(wk), fmt.Sprint(rows), f3(s), f3(base / s), f3(base / s / float64(wk)), fmt.Sprint(cpu)})
			w.Flush()
		}
	}

	_, X, _, _, err := features.ReadMatrix(*matrix)
	must(err)
	rng := rand.New(rand.NewSource(1))
	big := make([][]float64, *n)
	for i := range big {
		src := X[rng.Intn(len(X))]
		p := make([]float64, len(src))
		for j, v := range src {
			p[j] = v + rng.NormFloat64()*0.05
		}
		big[i] = p
	}
	o := kmeansmr.Options{K: *k, MaxIter: 30, Tol: 1e-12, Seed: 42}
	base := median(*reps, func() float64 { m, _ := kmeansmr.Sequential(big, o); return m.ElapsedSec })
	log.Printf("K-Means secuencial N=%d: %.2fs", *n, base)
	w.Write([]string{"kmeans", "secuencial", "0", fmt.Sprint(*n), f3(base), "1.000", "", fmt.Sprint(cpu)})
	for _, wk := range workers {
		o.Workers = wk
		s := median(*reps, func() float64 { m, _ := kmeansmr.Parallel(big, o); return m.ElapsedSec })
		log.Printf("K-Means %d workers: %.2fs speedup=%.2fx", wk, s, base/s)
		w.Write([]string{"kmeans", "paralelo", fmt.Sprint(wk), fmt.Sprint(*n), f3(s), f3(base / s), f3(base / s / float64(wk)), fmt.Sprint(cpu)})
		w.Flush()
	}
	log.Printf("Resultados en %s", filepath.Join(*out, "speedup.csv"))
}

func median(reps int, fn func() float64) float64 {
	v := make([]float64, reps)
	for i := range v {
		v[i] = fn()
	}
	for i := 1; i < len(v); i++ {
		for j := i; j > 0 && v[j] < v[j-1]; j-- {
			v[j], v[j-1] = v[j-1], v[j]
		}
	}
	return v[len(v)/2]
}

func f3(v float64) string { return strconv.FormatFloat(v, 'f', 3, 64) }

func must(err error) {
	if err != nil {
		log.Fatal(err)
	}
}
