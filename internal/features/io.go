package features

import (
	"encoding/csv"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/marck0820001/peru-budget-distributed.git/internal/preprocessing"
)

func ratio(a, b int64) string {
	if b <= 0 {
		return ""
	}
	return strconv.FormatFloat(float64(a)/float64(b), 'f', 8, 64)
}

func f8(v float64) string {
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return ""
	}
	return strconv.FormatFloat(v, 'f', 8, 64)
}

// WriteMunicipalityYear escribe municipality_year_features.csv con las mismas
// columnas que scripts/eda/preprocess_data.py (para poder contrastarlos).
func WriteMunicipalityYear(path string, profiles []Profile) error {
	cols := []string{"ano_eje", "sec_ejec", "departamento", "ejecutora_nombre", "n_lineas",
		"n_lineas_proyecto", "pia_soles", "pim_soles", "devengado_soles",
		"pim_proyectos_soles", "devengado_proyectos_soles", "tasa_ejecucion", "modificacion_sobre_pia",
		"participacion_devengado_proyectos", "concentracion_q4", "cv_devengado_mensual", "log1p_pim",
		"n_ajustes_mensuales_negativos", "n_montos_negativos", "n_lineas_excluidas",
		"n_codigos_proyecto_faltantes"}
	return writeCSV(path, cols, len(profiles), func(i int) []string {
		a := profiles[i].Agg
		var q4 int64
		for _, m := range a.Months[9:] {
			q4 += m
		}
		_, cv, _ := Indicators(a)
		lp := ""
		if a.PIM >= 0 {
			lp = f8(math.Log1p(float64(a.PIM) / 100))
		}
		return []string{strconv.Itoa(a.Year), a.SecEjec, a.Departamento, a.Ejecutora,
			strconv.FormatInt(a.Rows, 10), strconv.FormatInt(a.ProjectRows, 10),
			preprocessing.FormatSoles(a.PIA), preprocessing.FormatSoles(a.PIM), preprocessing.FormatSoles(a.Dev),
			preprocessing.FormatSoles(a.ProjectPIM), preprocessing.FormatSoles(a.ProjectDev),
			ratio(a.Dev, a.PIM), ratio(a.PIM-a.PIA, a.PIA), ratio(a.ProjectDev, a.Dev), ratio(q4, a.Dev),
			f8(cv), lp, strconv.FormatInt(a.NegMonths, 10), strconv.FormatInt(a.NegAmounts, 10),
			strconv.FormatInt(a.Rejected, 10), strconv.FormatInt(a.MissingCodes, 10)}
	})
}

// WriteAudit escribe todos los perfiles con su elegibilidad y motivos.
func WriteAudit(path string, profiles []Profile) error {
	cols := append([]string{"ano_eje", "sec_ejec", "departamento", "ejecutora_nombre", "tipo_entidad",
		"eligible", "exclusion_reasons", "warnings", "n_lineas", "pia_soles", "pim_soles", "devengado_soles"}, Names...)
	return writeCSV(path, cols, len(profiles), func(i int) []string {
		p := profiles[i]
		el := "0"
		if p.Eligible {
			el = "1"
		}
		row := []string{strconv.Itoa(p.Year), p.SecEjec, p.Departamento, p.Ejecutora, p.TipoEntidad, el,
			strings.Join(p.Reasons, ";"), strings.Join(p.Warnings, ";"), strconv.FormatInt(p.Agg.Rows, 10),
			preprocessing.FormatSoles(p.Agg.PIA), preprocessing.FormatSoles(p.Agg.PIM), preprocessing.FormatSoles(p.Agg.Dev)}
		for _, v := range p.Raw {
			row = append(row, f8(v))
		}
		return row
	})
}

// KeyCols son las columnas de identificación (NO son features numéricas).
var KeyCols = []string{"ano_eje", "sec_ejec", "departamento", "ejecutora_nombre", "tipo_entidad"}

// WriteMatrix escribe kmeans_matrix.csv y kmeans_keys.csv en el mismo orden
// (mismo formato que scripts/eda/feature_engineering.py).
func WriteMatrix(dir string, eligible []Profile, t *Transformer) error {
	if err := writeCSV(filepath.Join(dir, "kmeans_keys.csv"), KeyCols, len(eligible), func(i int) []string {
		p := eligible[i]
		return []string{strconv.Itoa(p.Year), p.SecEjec, p.Departamento, p.Ejecutora, p.TipoEntidad}
	}); err != nil {
		return err
	}
	return writeCSV(filepath.Join(dir, "kmeans_matrix.csv"), t.Features, len(eligible), func(i int) []string {
		x := t.Transform(eligible[i].Raw)
		row := make([]string, len(x))
		for j, v := range x {
			row[j] = strconv.FormatFloat(v, 'g', 12, 64)
		}
		return row
	})
}

func writeCSV(path string, cols []string, n int, row func(int) []string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	if err := w.Write(cols); err != nil {
		return err
	}
	for i := 0; i < n; i++ {
		if err := w.Write(row(i)); err != nil {
			return err
		}
	}
	w.Flush()
	return w.Error()
}

// ReadMatrix lee kmeans_matrix.csv (+ kmeans_keys.csv) producidos por el ETL
// en Go o por feature_engineering.py.
func ReadMatrix(dir string) (names []string, X [][]float64, keys [][]string, keyHeader []string, err error) {
	read := func(p string) ([][]string, error) {
		f, err := os.Open(p)
		if err != nil {
			return nil, err
		}
		defer f.Close()
		r := csv.NewReader(f)
		return r.ReadAll()
	}
	m, err := read(filepath.Join(dir, "kmeans_matrix.csv"))
	if err != nil {
		return
	}
	k, err := read(filepath.Join(dir, "kmeans_keys.csv"))
	if err != nil {
		return
	}
	if len(m) < 2 || len(m) != len(k) {
		err = fmt.Errorf("matriz (%d filas) y claves (%d filas) no coinciden", len(m), len(k))
		return
	}
	names = m[0]
	for i, line := range m[1:] {
		v := make([]float64, len(line))
		for j, s := range line {
			if v[j], err = strconv.ParseFloat(strings.TrimSpace(s), 64); err != nil {
				err = fmt.Errorf("kmeans_matrix fila %d col %d: %w", i+2, j+1, err)
				return
			}
		}
		X = append(X, v)
	}
	return names, X, k[1:], k[0], nil
}
