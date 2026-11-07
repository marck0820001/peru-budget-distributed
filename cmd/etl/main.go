package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"strings"

	"github.com/marck0820001/peru-budget-distributed.git/internal/ingestion"
)

func main() {
	paths := flag.String("inputs", "data/raw/2024-Gasto-Devengado.csv,data/raw/2025-Gasto-Devengado-Mensual.csv", "rutas CSV separadas por coma")
	workers := flag.Int("workers", 4, "número de workers concurrentes")
	output := flag.String("out", "data/processed/go_ingestion/auditoria_go.json", "ruta del reporte")
	flag.Parse()
	reports := make([]ingestion.Totals, 0)
	for _, path := range strings.Split(*paths, ",") {
		path = strings.TrimSpace(path)
		if path == "" {
			continue
		}
		report, err := ingestion.AuditFile(path, *workers)
		if err != nil {
			log.Fatal(err)
		}
		reports = append(reports, report)
		fmt.Printf("%s: leídas=%d, locales=%d, aceptadas=%d, proyectos=%d, inválidas=%d, duración=%d ms\n", path, report.RowsRead, report.LocalRows, report.AcceptedLocalRows, report.ProjectLocalRows, report.InvalidLocalAmounts, report.DurationMilliseconds)
	}
	if err := os.MkdirAll(filepath.Dir(*output), 0755); err != nil {
		log.Fatal(err)
	}
	f, err := os.Create(*output)
	if err != nil {
		log.Fatal(err)
	}
	defer f.Close()
	enc := json.NewEncoder(f)
	enc.SetIndent("", "  ")
	if err := enc.Encode(struct {
		Workers int                `json:"workers"`
		Reports []ingestion.Totals `json:"reports"`
	}{*workers, reports}); err != nil {
		log.Fatal(err)
	}
	fmt.Println("Reporte:", *output)
}
