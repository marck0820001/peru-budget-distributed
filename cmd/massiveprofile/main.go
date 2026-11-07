// massiveprofile characterizes the FINAL K-Means solution on every raw line.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"

	"github.com/marck0820001/peru-budget-distributed.git/internal/ml/massive"
)

func main() {
	out := flag.String("out", "data/processed/massive_mef", "Carpeta que contiene budget_lines.f64 y sus metadatos")
	report := flag.String("report", "training_k3_w4_seed42.json", "Reporte existente de entrenamiento (nombre relativo a -out o ruta completa)")
	workers := flag.Int("workers", 4, "Número de workers de lectura y agregación")
	batch := flag.Int("batch", 8192, "Filas por lectura ReadAt")
	flag.Parse()
	meta, err := massive.ReadMetadata(filepath.Join(*out, "budget_lines_metadata.json"))
	if err != nil {
		log.Fatal(err)
	}
	reportPath := *report
	if !filepath.IsAbs(reportPath) && !strings.ContainsAny(reportPath, "/\\") {
		reportPath = filepath.Join(*out, reportPath)
	}
	trained, err := massive.ReadTrainReport(reportPath)
	if err != nil {
		log.Fatal(err)
	}
	prof, err := massive.ProfileAll(meta, trained, *workers, *batch)
	if err != nil {
		log.Fatal(err)
	}
	path := filepath.Join(*out, fmt.Sprintf("profile_k%d_seed%d.json", trained.K, trained.Seed))
	f, err := os.Create(path)
	if err != nil {
		log.Fatal(err)
	}
	enc := json.NewEncoder(f)
	enc.SetIndent("", "  ")
	if err = enc.Encode(prof); err != nil {
		f.Close()
		log.Fatal(err)
	}
	if err = f.Close(); err != nil {
		log.Fatal(err)
	}
	fmt.Printf("PROFILE OK: filas=%d K=%d workers=%d, duracion=%d ms, inercia=%.6f\n", prof.Rows, prof.K, prof.Workers, prof.DurationMS, prof.Inertia)
	fmt.Printf("%-10s %11s %11s %12s %12s %12s %12s %12s\n", "Cluster", "Filas", "% filas", "% proyectos", "% PIM=0", "% DEV=0", "% Q4 medio", "% meses act.")
	for _, c := range prof.ClusterProfiles {
		fmt.Printf("%-10d %11d %10.2f%% %11.2f%% %11.2f%% %11.2f%% %11.2f%% %11.2f%%\n",
			c.Cluster, c.Rows, c.SharePct, 100*c.MeanOriginal[6], 100*c.MeanOriginal[7], 100*c.MeanOriginal[8], 100*c.MeanOriginal[4], 100*c.MeanOriginal[5])
	}
	fmt.Println("NOTA: porcentajes medios POR LINEA; no representan tasas consolidadas municipales.")
	fmt.Println("Reporte:", path)
}
