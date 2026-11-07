package massive

import (
	"fmt"
	"math"
	"strings"

	"github.com/marck0820001/peru-budget-distributed.git/internal/ingestion"
)

// Names defines the order stored in the binary file. This is NOT the
// municipality-year feature space: every vector represents one MEF budget line.
var Names = []string{
	"signed_log_pia", "signed_log_pim", "signed_log_devengado",
	"tasa_ejecucion_acotada", "participacion_q4_acotada",
	"meses_activos_fraccion", "es_proyecto", "pim_cero", "devengado_cero",
}

const Dim = 9
const RecordBytes = Dim * 8 // float64, little-endian

var months = []string{
	"MONTO_DEVENGADO_ENERO", "MONTO_DEVENGADO_FEBRERO",
	"MONTO_DEVENGADO_MARZO", "MONTO_DEVENGADO_ABRIL",
	"MONTO_DEVENGADO_MAYO", "MONTO_DEVENGADO_JUNIO",
	"MONTO_DEVENGADO_JULIO", "MONTO_DEVENGADO_AGOSTO",
	"MONTO_DEVENGADO_SEPTIEMBRE", "MONTO_DEVENGADO_OCTUBRE",
	"MONTO_DEVENGADO_NOVIEMBRE", "MONTO_DEVENGADO_DICIEMBRE",
}

func signedLog(cents int64) float64 {
	if cents < 0 {
		return -math.Log1p(math.Abs(float64(cents)) / 100)
	}
	return math.Log1p(float64(cents) / 100)
}
func clamp(x, lo, hi float64) float64 { return math.Max(lo, math.Min(hi, x)) }

// Extract requires all monetary data to be valid; it neither drops zero-amount
// rows nor silently imputes invalid values. Undefined ratios are zero with
// explicit missing-denominator flags (pim_cero, devengado_cero).
func Extract(row []string, idx map[string]int) ([Dim]float64, error) {
	var values [Dim]float64
	amount := func(name string) (int64, error) {
		v, err := ingestion.ParseCents(row[idx[name]])
		if err != nil {
			return 0, fmt.Errorf("%s: %w", name, err)
		}
		return v, nil
	}
	pia, err := amount("MONTO_PIA")
	if err != nil {
		return values, err
	}
	pim, err := amount("MONTO_PIM")
	if err != nil {
		return values, err
	}
	dev, err := amount("MONTO_DEVENGADO_ANUAL")
	if err != nil {
		return values, err
	}
	var q4 int64
	active := 0
	for i, month := range months {
		v, e := amount(month)
		if e != nil {
			return values, e
		}
		if v != 0 {
			active++
		}
		if i >= 9 {
			q4 += v
		}
	}
	values[0], values[1], values[2] = signedLog(pia), signedLog(pim), signedLog(dev)
	if pim != 0 {
		values[3] = clamp(float64(dev)/float64(pim), -2, 2)
	}
	if dev != 0 {
		values[4] = clamp(float64(q4)/float64(dev), -2, 2)
	}
	values[5] = float64(active) / 12
	if strings.EqualFold(strings.TrimSpace(row[idx["TIPO_ACT_PROY"]]), "PROYECTO") {
		values[6] = 1
	}
	if pim == 0 {
		values[7] = 1
	}
	if dev == 0 {
		values[8] = 1
	}
	for i, v := range values {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return values, fmt.Errorf("valor no finito en característica %s", Names[i])
		}
	}
	return values, nil
}
