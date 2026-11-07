// Package domain define los tipos compartidos del pipeline PeruBudget:
// columnas del dataset MEF "Gasto Devengado", agregados por ejecutora-año
// y perfiles municipales usados por K-Means.
package domain

// Months son los sufijos de las columnas MONTO_DEVENGADO_<MES> del MEF.
var Months = [12]string{
	"ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
	"JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
}

// Columnas obligatorias del CSV de Gasto Devengado (mismas que el EDA en Python).
const (
	ColAnoEje        = "ANO_EJE"
	ColNivelGobierno = "NIVEL_GOBIERNO"
	ColSecEjec       = "SEC_EJEC"
	ColEjecutora     = "EJECUTORA_NOMBRE"
	ColDepartamento  = "DEPARTAMENTO_EJECUTORA_NOMBRE"
	ColTipoActProy   = "TIPO_ACT_PROY"
	ColProducto      = "PRODUCTO_PROYECTO"
	ColProductoNom   = "PRODUCTO_PROYECTO_NOMBRE"
	ColPIA           = "MONTO_PIA"
	ColPIM           = "MONTO_PIM"
	ColDevAnual      = "MONTO_DEVENGADO_ANUAL"
)

// MonthColumn devuelve el nombre de la columna de devengado del mes m (0..11).
func MonthColumn(m int) string { return "MONTO_DEVENGADO_" + Months[m] }

// RequiredColumns lista las columnas que el cargador exige en el encabezado.
func RequiredColumns() []string {
	cols := []string{ColAnoEje, ColNivelGobierno, ColSecEjec, ColEjecutora,
		ColDepartamento, ColTipoActProy, ColProducto, ColProductoNom,
		ColPIA, ColPIM, ColDevAnual}
	for m := 0; m < 12; m++ {
		cols = append(cols, MonthColumn(m))
	}
	return cols
}

// Line es una línea presupuestaria municipal ya validada. Montos en céntimos.
type Line struct {
	Year         int
	SecEjec      string
	Ejecutora    string
	Departamento string
	IsProject    bool
	ProjectCode  string
	PIA, PIM     int64
	DevAnual     int64
	Months       [12]int64
}

// Key identifica un perfil ejecutora-año.
type Key struct {
	Year    int
	SecEjec string
}

// MuniAgg acumula las líneas de una ejecutora en un año. Todos los montos en
// céntimos (enteros), por lo que la suma es exacta y no depende del orden en
// que los workers la realicen.
type MuniAgg struct {
	Key
	Departamento  string
	Ejecutora     string
	FirstRow      int64 // fila de origen más temprana (para elegir metadatos de forma determinista)
	Rows          int64
	ProjectRows   int64
	PIA, PIM, Dev int64
	ProjectPIM    int64
	ProjectDev    int64
	Months        [12]int64
	NegMonths     int64
	NegAmounts    int64
	MissingCodes  int64
	Rejected      int64
	Inconsistent  bool
}

// Merge suma otro agregado de la misma clave (fase reduce).
func (a *MuniAgg) Merge(b *MuniAgg) {
	if b.Rows > 0 {
		if a.Rows == 0 {
			a.Departamento, a.Ejecutora, a.FirstRow = b.Departamento, b.Ejecutora, b.FirstRow
		} else {
			if a.Departamento != b.Departamento || a.Ejecutora != b.Ejecutora {
				a.Inconsistent = true
			}
			if b.FirstRow < a.FirstRow {
				a.Departamento, a.Ejecutora, a.FirstRow = b.Departamento, b.Ejecutora, b.FirstRow
			}
		}
	}
	a.Inconsistent = a.Inconsistent || b.Inconsistent
	a.Rows += b.Rows
	a.ProjectRows += b.ProjectRows
	a.PIA += b.PIA
	a.PIM += b.PIM
	a.Dev += b.Dev
	a.ProjectPIM += b.ProjectPIM
	a.ProjectDev += b.ProjectDev
	for i := range a.Months {
		a.Months[i] += b.Months[i]
	}
	a.NegMonths += b.NegMonths
	a.NegAmounts += b.NegAmounts
	a.MissingCodes += b.MissingCodes
	a.Rejected += b.Rejected
}

// Add incorpora una línea validada al agregado (fase map, local a cada worker).
func (a *MuniAgg) Add(l *Line, row int64) {
	if a.Rows == 0 {
		a.Departamento, a.Ejecutora, a.FirstRow = l.Departamento, l.Ejecutora, row
	} else if a.Departamento != l.Departamento || a.Ejecutora != l.Ejecutora {
		a.Inconsistent = true
		if row < a.FirstRow {
			a.Departamento, a.Ejecutora, a.FirstRow = l.Departamento, l.Ejecutora, row
		}
	}
	a.Rows++
	a.PIA += l.PIA
	a.PIM += l.PIM
	a.Dev += l.DevAnual
	if l.PIA < 0 {
		a.NegAmounts++
	}
	if l.PIM < 0 {
		a.NegAmounts++
	}
	if l.DevAnual < 0 {
		a.NegAmounts++
	}
	for i, v := range l.Months {
		a.Months[i] += v
		if v < 0 {
			a.NegMonths++
		}
	}
	if l.IsProject {
		a.ProjectRows++
		a.ProjectPIM += l.PIM
		a.ProjectDev += l.DevAnual
		if l.ProjectCode == "" {
			a.MissingCodes++
		}
	}
}
