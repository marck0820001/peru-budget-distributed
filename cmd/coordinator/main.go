package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/marck0820001/peru-budget-distributed.git/internal/ml/massive"
)

func main() {
	metadata := flag.String("metadata", "data/processed/massive_mef/budget_lines_metadata.json", "archivo de metadatos PC3")
	data := flag.String("data", "data/processed/massive_mef/budget_lines.f64", "binario PC3")
	nodes := flag.String("nodes", "127.0.0.1:9101,127.0.0.1:9102", "nodos TCP separados por coma")
	out := flag.String("out", "data/processed/massive_mef/training_distributed_k3_nodes2_seed42.json", "JSON de resultados sin sobrescribir PC3")
	k := flag.Int("k", 3, "número de clústeres")
	seed := flag.Int64("seed", 42, "semilla")
	maxIter := flag.Int("max-iter", 25, "iteraciones máximas")
	tol := flag.Float64("tol", 1e-4, "tolerancia")
	sample := flag.Int("init-sample", 10000, "tamaño de muestra para K-Means++")
	batch := flag.Int("batch", 8192, "filas por bloque")
	clip := flag.Float64("clip-z", 5, "truncamiento Z-score")
	timeout := flag.Duration("timeout", 120*time.Second, "tiempo máximo de respuesta por nodo")
	flag.Parse()
	m, err := massive.OpenPortableMetadata(*metadata, *data)
	if err != nil {
		log.Fatal(err)
	}
	addrs := []string{}
	for _, a := range strings.Split(*nodes, ",") {
		a = strings.TrimSpace(a)
		if a != "" {
			addrs = append(addrs, a)
		}
	}
	if len(addrs) < 2 {
		log.Fatal("se requieren >=2 nodos TCP")
	}
	cfg := massive.TrainConfig{K: *k, Workers: len(addrs), MaxIterations: *maxIter, Tolerance: *tol,
		Seed: *seed, InitSample: *sample, BatchRows: *batch, ClipZ: *clip}
	fmt.Printf("PC4: K-Means TCP | filas=%d | K=%d | nodos=%v\n", m.Rows, *k, addrs)
	// Docker services can be running but not listening yet. Retry briefly.
	var report massive.TrainResult
	for attempt := 0; attempt < 20; attempt++ {
		report, err = massive.DistributedTrain(m, cfg, addrs, *timeout)
		if err == nil {
			break
		}
		// Retry only on initial connection failure, never after partial training.
		if !strings.Contains(err.Error(), "connect: connection refused") && !strings.Contains(err.Error(), "no such host") {
			break
		}
		log.Printf("Nodos iniciándose, reintento %d/20: %v", attempt+1, err)
		time.Sleep(time.Second)
	}
	if err != nil {
		log.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Dir(*out), 0755); err != nil {
		log.Fatal(err)
	}
	if err := massive.SaveReport(*out, report); err != nil {
		log.Fatal(err)
	}
	fmt.Printf("PC4 OK: filas=%d | K=%d | nodos=%d | iteraciones=%d | convergió=%t | inercia=%.9f | tiempos=%d ms\n",
		report.Rows, report.K, len(addrs), report.Iterations, report.Converged, report.Inertia, report.DurationMS)
	fmt.Printf("Clusters=%v\nReporte=%s\n", report.ClusterSizes, *out)
}
