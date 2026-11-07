// Command etl ejecuta la Parte A del sistema: carga concurrente de los CSV de
// Gasto Devengado 2024 y 2025, limpieza auditable, agregación por
// ejecutora-año y construcción de la matriz de K-Means.
//
//	go run ./cmd/etl --data-dir data/raw --workers 8
//	go run ./cmd/etl --data-dir data/raw --sequential   # línea base sin goroutines
//
// Salidas en --out (por defecto data/processed/go_etl, ignorada por Git).
package main

import (
	"encoding/csv"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/marck0820001/peru-budget-distributed.git/internal/domain"
	"github.com/marck0820001/peru-budget-distributed.git/internal/features"
	"github.com/marck0820001/peru-budget-distributed.git/internal/ingestion"
	"github.com/marck0820001/peru-budget-distributed.git/internal/preprocessing"
)

func findFiles(dir string) ([][2]string, error) {
	var out [][2]string
	for _, y := range []string{"2024", "2025"} {
		m, _ := filepath.Glob(filepath.Join(dir, y+"-Gasto-Devengado*.csv"))
		if len(m) != 1 {
			return nil, fmt.Errorf("se esperaba exactamente 1 Gasto Devengado de %s en %s; encontrados: %v", y, dir, m)
		}
		out = append(out, [2]string{y, m[0]})
	}
	return out, nil
}

type report struct {
	Timestamp   string                 `json:"run_timestamp_utc"`
	Mode        string                 `json:"mode"`
	Workers     int                    `json:"workers"`
	ChunkSize   int                    `json:"chunk_records"`
	NumCPU      int                    `json:"num_cpu"`
	GoVersion   string                 `json:"go_version"`
	Files       []ingestion.FileResult `json:"files"`
	Totals      ingestion.Stats        `json:"totals"`
	ETLSeconds  float64                `json:"etl_seconds"`
	Profiles    int                    `json:"municipality_year_profiles"`
	Eligible    int                    `json:"eligible_profiles"`
	Excluded    map[string]int         `json:"excluded_by_reason"`
	EntityTypes map[string]int         `json:"entity_type_counts"`
	Features    []string               `json:"selected_features"`
	Integrity   map[string]bool        `json:"integrity"`
	Sufficiency map[string]bool        `json:"sufficiency"`
	TotalsSoles map[string]string      `json:"totals_soles"`
	ExecRate    map[string]float64     `json:"execution_rate_by_year"`
	Monthly     map[string][12]float64 `json:"monthly_devengado_soles_by_year"`
}

func main() {
	dataDir := flag.String("data-dir", "data/raw", "carpeta con los CSV del MEF")
	outDir := flag.String("out", "data/processed/go_etl", "carpeta de salida")
	workers := flag.Int("workers", runtime.NumCPU(), "goroutines de parseo/validación")
	chunk := flag.Int("chunk", 20000, "registros por bloque")
	sequential := flag.Bool("sequential", false, "línea base secuencial (sin goroutines)")
	dropDup := flag.Bool("drop-duplicates", false, "excluir copias exactas del agregado (por defecto solo se reportan)")
	noDup := flag.Bool("no-dup-check", false, "no calcular huellas de duplicados")
	flag.Parse()

	files, err := findFiles(*dataDir)
	if err != nil {
		log.Fatal(err)
	}
	if err := os.MkdirAll(*outDir, 0o755); err != nil {
		log.Fatal(err)
	}
	incF, err := os.Create(filepath.Join(*outDir, "incidencias_preprocesamiento.csv"))
	if err != nil {
		log.Fatal(err)
	}
	incW := csv.NewWriter(incF)
	incW.Write([]string{"source_file", "source_row", "ano_eje", "sec_ejec", "reason"})
	onIncident := func(i ingestion.Incident) {
		incW.Write([]string{i.File, strconv.FormatInt(i.Row, 10), i.YearText, i.SecEjec, i.Reason})
	}

	cfg := ingestion.Config{Workers: *workers, ChunkRecords: *chunk, DetectDuplicates: !*noDup, DropDuplicates: *dropDup}
	res := ingestion.NewResult()
	start := time.Now()
	mode := fmt.Sprintf("concurrente (%d workers)", *workers)
	if *sequential {
		mode = "secuencial"
	}
	log.Printf("ETL %s: %d archivos", mode, len(files))
	for _, f := range files {
		year, _ := strconv.Atoi(f[0])
		var fr ingestion.FileResult
		if *sequential {
			fr, err = ingestion.ProcessFileSequential(f[1], year, !*noDup, *dropDup, res, onIncident)
		} else {
			fr, err = ingestion.ProcessFile(f[1], year, cfg, res, onIncident)
		}
		if err != nil {
			log.Fatal(err)
		}
		log.Printf("%s: %d filas en %.2fs (%.0f filas/s) · locales=%d aceptadas=%d rechazadas=%d malformadas=%d duplicados=%d",
			fr.File, fr.Stats.RowsRead, fr.ElapsedSec, fr.RowsPerSec, fr.Stats.LocalRows,
			fr.Stats.LocalAccepted, fr.Stats.LocalRejected, fr.Stats.Malformed, fr.Stats.Duplicates)
	}
	etl := time.Since(start)
	incW.Flush()
	incF.Close()

	keys := res.SortedKeys()
	aggs := make([]*domain.MuniAgg, len(keys))
	for i, k := range keys {
		aggs[i] = res.Aggs[k]
	}
	profiles := features.BuildProfiles(aggs)
	var eligible []features.Profile
	excluded := map[string]int{}
	types := map[string]int{}
	for _, p := range profiles {
		types[p.TipoEntidad]++
		if p.Eligible {
			eligible = append(eligible, p)
		}
		for _, r := range p.Reasons {
			excluded[r]++
		}
	}
	t, err := features.Fit(eligible)
	if err != nil {
		log.Fatal(err)
	}
	must(features.WriteMunicipalityYear(filepath.Join(*outDir, "municipality_year_features.csv"), profiles))
	must(features.WriteAudit(filepath.Join(*outDir, "municipality_features_audit.csv"), profiles))
	must(features.WriteMatrix(*outDir, eligible, t))
	must(writeJSON(filepath.Join(*outDir, "feature_transformer.json"), t))

	// Conciliaciones: los agregados deben cuadrar al céntimo con los totales de líneas.
	var sPIA, sPIM, sDev, rows int64
	byYearDev, byYearPIM := map[int]int64{}, map[int]int64{}
	monthly := map[string][12]float64{}
	for _, a := range aggs {
		sPIA += a.PIA
		sPIM += a.PIM
		sDev += a.Dev
		rows += a.Rows
		byYearDev[a.Year] += a.Dev
		byYearPIM[a.Year] += a.PIM
		m := monthly[strconv.Itoa(a.Year)]
		for i, v := range a.Months {
			m[i] += float64(v) / 100
		}
		monthly[strconv.Itoa(a.Year)] = m
	}
	tot := res.Total
	rep := report{
		Timestamp: time.Now().UTC().Format(time.RFC3339), Mode: mode, Workers: *workers, ChunkSize: *chunk,
		NumCPU: runtime.NumCPU(), GoVersion: runtime.Version(), Files: res.Files, Totals: tot,
		ETLSeconds: etl.Seconds(), Profiles: len(profiles), Eligible: len(eligible),
		Excluded: excluded, EntityTypes: types, Features: t.Features,
		Integrity: map[string]bool{
			"totals_equal_aggregates": sPIA == tot.PIACents && sPIM == tot.PIMCents && sDev == tot.DevCents,
			"rows_equal_aggregates":   rows == tot.LocalAccepted,
			"row_balance": tot.RowsRead == tot.NonLocal+tot.LocalAccepted+tot.LocalRejected+
				tot.Malformed+tot.DuplicatesDrop,
		},
		Sufficiency: map[string]bool{
			"local_rows_above_2m":    tot.LocalRows > 2_000_000,
			"accepted_rows_above_1m": tot.LocalAccepted > 1_000_000,
		},
		TotalsSoles: map[string]string{
			"pia": preprocessing.FormatSoles(sPIA), "pim": preprocessing.FormatSoles(sPIM),
			"devengado": preprocessing.FormatSoles(sDev),
		},
		ExecRate: map[string]float64{},
		Monthly:  monthly,
	}
	for y, d := range byYearDev {
		if byYearPIM[y] > 0 {
			rep.ExecRate[strconv.Itoa(y)] = float64(d) / float64(byYearPIM[y])
		}
	}
	must(writeJSON(filepath.Join(*outDir, "reporte_etl.json"), rep))
	must(os.WriteFile(filepath.Join(*outDir, "resumen_etl.md"), []byte(summary(rep)), 0o644))
	log.Printf("ETL total %.2fs · perfiles=%d elegibles=%d · features=%v", etl.Seconds(), len(profiles), len(eligible), t.Features)
	log.Printf("Integridad: %v", rep.Integrity)
	for k, ok := range rep.Integrity {
		if !ok {
			log.Fatalf("ERROR: falla la conciliación %s", k)
		}
	}
}

func summary(r report) string {
	var b strings.Builder
	fmt.Fprintf(&b, "# ETL concurrente en Go — Gasto Devengado MEF\n\nModo: **%s** · CPU: %d · %s\n\n", r.Mode, r.NumCPU, r.GoVersion)
	fmt.Fprintf(&b, "| Archivo | Filas | Locales | Aceptadas | Rechazadas | Malformadas | Duplicados | Tiempo (s) | Filas/s |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|\n")
	for _, f := range r.Files {
		s := f.Stats
		fmt.Fprintf(&b, "| %s | %d | %d | %d | %d | %d | %d | %.2f | %.0f |\n", f.File, s.RowsRead, s.LocalRows, s.LocalAccepted, s.LocalRejected, s.Malformed, s.Duplicates, f.ElapsedSec, f.RowsPerSec)
	}
	fmt.Fprintf(&b, "\n- Tiempo total ETL: **%.2f s**\n- Perfiles ejecutora-año: **%d**; elegibles para K-Means: **%d**\n- Features: `%s`\n", r.ETLSeconds, r.Profiles, r.Eligible, strings.Join(r.Features, "`, `"))
	keys := make([]string, 0, len(r.Excluded))
	for k := range r.Excluded {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	b.WriteString("\n## Exclusiones\n\n")
	for _, k := range keys {
		fmt.Fprintf(&b, "- `%s`: %d\n", k, r.Excluded[k])
	}
	b.WriteString("\n## Conciliaciones\n\n")
	for k, v := range r.Integrity {
		fmt.Fprintf(&b, "- %s: **%v**\n", k, v)
	}
	return b.String()
}

func writeJSON(path string, v any) error {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, b, 0o644)
}

func must(err error) {
	if err != nil {
		log.Fatal(err)
	}
}
