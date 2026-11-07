// massivekmeans prepares and trains a genuine >2M-record experiment; it does
// not replace the previously validated municipality-year K-Means trainer.
package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"

	"github.com/marck0820001/peru-budget-distributed.git/internal/ml/massive"
)

func main() {
	mode := flag.String("mode", "all", "prepare | train | all")
	inputs := flag.String("inputs", "data/raw/2024-Gasto-Devengado.csv,data/raw/2025-Gasto-Devengado-Mensual.csv", "CSV de gasto devengado separados por coma")
	out := flag.String("out", "data/processed/massive_mef", "carpeta de artefactos")
	k := flag.Int("k", 3, "número de clusters en el experimento de LINEAS")
	workers := flag.Int("workers", 4, "goroutines por iteración")
	maxIter := flag.Int("max-iter", 25, "máximo de iteraciones Lloyd")
	tol := flag.Float64("tol", 1e-4, "tolerancia de desplazamiento de centroides")
	seed := flag.Int64("seed", 42, "semilla reproducible")
	sample := flag.Int("init-sample", 10000, "muestra uniforme para K-Means++ (inicialización solamente)")
	batch := flag.Int("batch", 8192, "filas procesadas por bloque de lectura")
	clip := flag.Float64("clip-z", 5, "máximo valor absoluto del z-score en entrenamiento")
	limit := flag.Int64("limit", 0, "solo pruebas: primeras N filas municipales; 0=todas")
	expect := flag.Int64("expect-rows", 0, "verificación opcional de filas, p.ej. 3642510")
	flag.Parse()
	if *mode != "prepare" && *mode != "train" && *mode != "all" {
		log.Fatal("-mode debe ser prepare, train o all")
	}
	if err := os.MkdirAll(*out, 0755); err != nil {
		log.Fatal(err)
	}
	dataset := filepath.Join(*out, "budget_lines.f64")
	metadataPath := filepath.Join(*out, "budget_lines_metadata.json")
	if *mode == "prepare" || *mode == "all" {
		paths := []string{}
		for _, item := range strings.Split(*inputs, ",") {
			if p := strings.TrimSpace(item); p != "" {
				paths = append(paths, p)
			}
		}
		meta, err := massive.BuildBinary(massive.BuildConfig{Inputs: paths, DatasetPath: dataset, MetadataPath: metadataPath, Limit: *limit, ExpectRows: *expect})
		if err != nil {
			log.Fatal(err)
		}
		fmt.Printf("PREPARE OK: %d líneas municipales -> %s (%d dimensiones, %d ms)\n", meta.Rows, dataset, meta.Dimensions, meta.DurationMS)
		for _, s := range meta.Sources {
			fmt.Printf("  %s: leídas=%d municipales=%d proyectos=%d\n", s.Path, s.AllRows, s.MunicipalRows, s.ProjectRows)
		}
	}
	if *mode == "train" || *mode == "all" {
		meta, err := massive.ReadMetadata(metadataPath)
		if err != nil {
			log.Fatal(err)
		}
		result, err := massive.Train(meta, massive.TrainConfig{K: *k, Workers: *workers, MaxIterations: *maxIter, Tolerance: *tol, Seed: *seed, InitSample: *sample, BatchRows: *batch, ClipZ: *clip})
		if err != nil {
			log.Fatal(err)
		}
		name := fmt.Sprintf("training_k%d_w%d_seed%d.json", *k, *workers, *seed)
		report := filepath.Join(*out, name)
		if err = massive.SaveReport(report, result); err != nil {
			log.Fatal(err)
		}
		fmt.Printf("TRAIN OK: filas=%d, K=%d, workers=%d, iteraciones=%d, convergió=%t, inercia=%.6f\n", result.Rows, result.K, result.Workers, result.Iterations, result.Converged, result.Inertia)
		fmt.Printf("Tamaño de clusters: %v; tiempo entrenamiento=%d ms\n", result.ClusterSizes, result.DurationMS)
		fmt.Println("Reporte:", report)
	}
}
