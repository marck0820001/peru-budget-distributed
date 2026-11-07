// Package features construye la matriz de K-Means a partir de los agregados
// ejecutora-año. Replica docs/datasets/04-feature-engineering-mef.md:
// elegibilidad, 6 indicadores, winsorización p01–p99 y escalamiento robusto
// (mediana / IQR). Los parámetros se guardan para reutilizarlos con datos nuevos.
package features

import (
	"errors"
	"math"
	"sort"
	"strings"

	"github.com/marck0820001/peru-budget-distributed.git/internal/domain"
)

// Names son los 6 indicadores candidatos, en el orden de la matriz.
var Names = []string{
	"tasa_ejecucion",
	"modificacion_log_pim_pia",
	"participacion_devengado_proyectos",
	"concentracion_q4",
	"cv_devengado_mensual",
	"log1p_pim",
}

// Profile es un perfil ejecutora-año con indicadores sin escalar.
type Profile struct {
	Year         int
	SecEjec      string
	Departamento string
	Ejecutora    string
	TipoEntidad  string
	Agg          *domain.MuniAgg
	Eligible     bool
	Reasons      []string
	Warnings     []string
	Raw          []float64 // NaN si el indicador no está definido
}

// EntityType clasifica la ejecutora por su nombre normalizado (sin tildes).
func EntityType(name string) string {
	n := stripAccents(strings.ToUpper(strings.TrimSpace(name)))
	switch {
	case strings.Contains(n, "MANCOMUNIDAD"):
		return "mancomunidad"
	case strings.HasPrefix(n, "MUNICIPALIDAD"):
		return "municipalidad"
	default:
		return "otra_ejecutora_local"
	}
}

var accentReplacer = strings.NewReplacer(
	"Á", "A", "É", "E", "Í", "I", "Ó", "O", "Ú", "U", "Ü", "U", "Ñ", "N",
	"À", "A", "È", "E", "Ì", "I", "Ò", "O", "Ù", "U",
)

// stripAccents elimina tildes y diéresis (texto ya en mayúsculas), equivalente
// a la normalización NFD sin marcas diacríticas del script de Python.
func stripAccents(s string) string { return accentReplacer.Replace(s) }

// Indicators calcula los 6 indicadores de un agregado. ok=false si algún
// denominador no es positivo (PIM<=0, devengado<=0 o PIA<0).
func Indicators(a *domain.MuniAgg) (vals []float64, cv float64, ok bool) {
	pia, pim, dev := float64(a.PIA)/100, float64(a.PIM)/100, float64(a.Dev)/100
	cv = math.NaN()
	if dev > 0 {
		mean := dev / 12
		var ss float64
		for _, m := range a.Months {
			d := float64(m)/100 - mean
			ss += d * d
		}
		cv = math.Sqrt(ss/12) / mean
	}
	if pia < 0 || pim <= 0 || dev <= 0 {
		return nil, cv, false
	}
	var q4 int64
	for _, m := range a.Months[9:] {
		q4 += m
	}
	vals = []float64{
		dev / pim,
		math.Log1p(pim) - math.Log1p(pia), // sin dividir entre PIA (PIA=0 es válido)
		float64(a.ProjectDev) / 100 / dev,
		float64(q4) / 100 / dev,
		cv,
		math.Log1p(pim),
	}
	for _, v := range vals {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return nil, cv, false
		}
	}
	return vals, cv, true
}

// BuildProfiles evalúa elegibilidad para cada agregado (ordenados por clave).
func BuildProfiles(aggs []*domain.MuniAgg) []Profile {
	out := make([]Profile, 0, len(aggs))
	for _, a := range aggs {
		p := Profile{Year: a.Year, SecEjec: a.SecEjec, Departamento: a.Departamento,
			Ejecutora: a.Ejecutora, TipoEntidad: EntityType(a.Ejecutora), Agg: a}
		if p.TipoEntidad != "municipalidad" {
			p.Reasons = append(p.Reasons, "tipo_entidad_no_municipalidad")
		}
		if strings.TrimSpace(a.Departamento) == "" {
			p.Reasons = append(p.Reasons, "departamento_vacio")
		}
		if strings.TrimSpace(a.Ejecutora) == "" {
			p.Reasons = append(p.Reasons, "nombre_vacio")
		}
		if a.Rejected > 0 {
			p.Reasons = append(p.Reasons, "agregado_incompleto")
		}
		if a.Inconsistent {
			p.Reasons = append(p.Reasons, "metadatos_inconsistentes")
		}
		if a.MissingCodes > 0 {
			p.Warnings = append(p.Warnings, "proyecto_sin_codigo_incluido_en_agregado")
		}
		if a.NegAmounts > 0 {
			p.Warnings = append(p.Warnings, "montos_negativos")
		}
		if a.NegMonths > 0 {
			p.Warnings = append(p.Warnings, "ajustes_mensuales_negativos")
		}
		vals, _, ok := Indicators(a)
		if !ok {
			p.Reasons = append(p.Reasons, "indicadores_no_definidos")
			p.Raw = []float64{math.NaN(), math.NaN(), math.NaN(), math.NaN(), math.NaN(), math.NaN()}
		} else {
			p.Raw = vals
			if vals[2] < 0 || vals[2] > 1 {
				p.Warnings = append(p.Warnings, "participacion_proyectos_fuera_0_1_por_ajustes")
			}
			if vals[3] < 0 || vals[3] > 1 {
				p.Warnings = append(p.Warnings, "concentracion_q4_fuera_0_1_por_ajustes")
			}
			if vals[0] > 1 {
				p.Warnings = append(p.Warnings, "tasa_ejecucion_superior_a_1")
			}
		}
		sort.Strings(p.Reasons)
		p.Eligible = len(p.Reasons) == 0
		out = append(out, p)
	}
	return out
}

// FeatureParam guarda la transformación de un indicador.
type FeatureParam struct {
	Used         bool    `json:"used"`
	Reason       string  `json:"reason,omitempty"`
	P01          float64 `json:"p01"`
	P99          float64 `json:"p99"`
	Median       float64 `json:"center_median"`
	Scale        float64 `json:"scale"`
	ScaleMethod  string  `json:"scale_method,omitempty"`
	ClippedBelow int     `json:"clipped_below"`
	ClippedAbove int     `json:"clipped_above"`
}

// Transformer contiene los parámetros ajustados (winsor + robust scaling).
type Transformer struct {
	Method     string                  `json:"method"`
	Features   []string                `json:"features"`
	Parameters map[string]FeatureParam `json:"parameters"`
}

// Percentile por interpolación lineal (igual a feature_engineering.py).
func Percentile(sorted []float64, q float64) float64 {
	if len(sorted) == 1 {
		return sorted[0]
	}
	x := float64(len(sorted)-1) * q
	lo, hi := math.Floor(x), math.Ceil(x)
	if lo == hi {
		return sorted[int(lo)]
	}
	return sorted[int(lo)]*(hi-x) + sorted[int(hi)]*(x-lo)
}

// Fit ajusta winsorización p01–p99 y escalamiento robusto sobre los perfiles elegibles.
func Fit(eligible []Profile) (*Transformer, error) {
	if len(eligible) < 10 {
		return nil, errors.New("menos de 10 perfiles elegibles: revisar criterios")
	}
	t := &Transformer{Method: "winsor_p01_p99_then_robust_median_iqr", Parameters: map[string]FeatureParam{}}
	for j, name := range Names {
		vals := make([]float64, len(eligible))
		for i, p := range eligible {
			vals[i] = p.Raw[j]
		}
		sort.Float64s(vals)
		low, high := Percentile(vals, 0.01), Percentile(vals, 0.99)
		if high-low < 1e-12 {
			t.Parameters[name] = FeatureParam{Reason: "sin_variacion", P01: low, P99: high}
			continue
		}
		clipped := make([]float64, len(vals))
		fp := FeatureParam{Used: true, P01: low, P99: high}
		for i, v := range vals {
			if v < low {
				fp.ClippedBelow++
			}
			if v > high {
				fp.ClippedAbove++
			}
			clipped[i] = math.Min(math.Max(v, low), high)
		}
		sort.Float64s(clipped)
		fp.Median = Percentile(clipped, 0.5)
		iqr := Percentile(clipped, 0.75) - Percentile(clipped, 0.25)
		if iqr < 1e-12 {
			fp.Scale, fp.ScaleMethod = pstdev(clipped), "std_fallback"
		} else {
			fp.Scale, fp.ScaleMethod = iqr, "iqr"
		}
		if fp.Scale < 1e-12 {
			t.Parameters[name] = FeatureParam{Reason: "escala_cero", P01: low, P99: high}
			continue
		}
		t.Parameters[name] = fp
		t.Features = append(t.Features, name)
	}
	if len(t.Features) < 2 {
		return nil, errors.New("menos de 2 features con variabilidad")
	}
	return t, nil
}

// Transform aplica la transformación a un vector de indicadores crudos (orden Names).
func (t *Transformer) Transform(raw []float64) []float64 {
	out := make([]float64, 0, len(t.Features))
	for j, name := range Names {
		p, ok := t.Parameters[name]
		if !ok || !p.Used {
			continue
		}
		w := math.Min(math.Max(raw[j], p.P01), p.P99)
		out = append(out, (w-p.Median)/p.Scale)
	}
	return out
}

func pstdev(v []float64) float64 {
	var m float64
	for _, x := range v {
		m += x
	}
	m /= float64(len(v))
	var ss float64
	for _, x := range v {
		ss += (x - m) * (x - m)
	}
	return math.Sqrt(ss / float64(len(v)))
}
