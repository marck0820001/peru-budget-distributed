package preprocessing

import (
	"strings"
	"testing"

	"github.com/marck0820001/peru-budget-distributed.git/internal/domain"
)

func header() []string { return append(domain.RequiredColumns(), "EXTRA") }

func record(nivel, year, sec string, pia, pim string, months []string, anual string) []string {
	h := header()
	r := make([]string, len(h))
	set := func(col, v string) {
		for i, c := range h {
			if c == col {
				r[i] = v
			}
		}
	}
	set(domain.ColNivelGobierno, nivel)
	set(domain.ColAnoEje, year)
	set(domain.ColSecEjec, sec)
	set(domain.ColEjecutora, "MUNICIPALIDAD DISTRITAL DE PRUEBA")
	set(domain.ColDepartamento, "LIMA")
	set(domain.ColTipoActProy, "PROYECTO")
	set(domain.ColProducto, "2000351")
	set(domain.ColPIA, pia)
	set(domain.ColPIM, pim)
	set(domain.ColDevAnual, anual)
	for m := 0; m < 12; m++ {
		set(domain.MonthColumn(m), months[m])
	}
	return r
}

func zeros() []string { return strings.Split("0,0,0,0,0,0,0,0,0,0,0,0", ",") }

func TestValidate(t *testing.T) {
	ix, err := NewIndex(header())
	if err != nil {
		t.Fatal(err)
	}
	m := zeros()
	m[11] = "100.50"
	var l domain.Line
	if r := ix.Validate(record("M", "2024", "300001", "100", "200", m, "100.50"), 2024, &l); r.Outcome != Accepted {
		t.Fatalf("esperaba aceptada, obtuve %+v", r)
	}
	if !l.IsProject || l.PIM != 20000 || l.Months[11] != 10050 {
		t.Fatalf("línea mal convertida: %+v", l)
	}
	if r := ix.Validate(record("R", "2024", "1", "1", "1", m, "100.50"), 2024, &l); r.Outcome != NonLocal {
		t.Fatalf("nivel R debe descartarse: %+v", r)
	}
	if r := ix.Validate(record("M", "2024", "300001", "1", "1", m, "99"), 2024, &l); r.Reason != "suma_meses_difiere_devengado_anual" {
		t.Fatalf("debía detectar meses que no concilian: %+v", r)
	}
	if r := ix.Validate(record("M", "2023", "300001", "1", "1", m, "100.50"), 2024, &l); r.Reason != "ano_eje_no_coincide_archivo" {
		t.Fatalf("debía detectar año distinto: %+v", r)
	}
	if r := ix.Validate(record("M", "2024", "300001", "1,5", "1", m, "100.50"), 2024, &l); r.Outcome != Rejected || len(r.MoneyErrors) != 1 {
		t.Fatalf("debía rechazar monto ambiguo: %+v", r)
	}
	if r := ix.Validate([]string{"a", "b"}, 2024, &l); r.Outcome != Malformed {
		t.Fatalf("debía marcar fila malformada: %+v", r)
	}
}

func TestNewIndexMissing(t *testing.T) {
	if _, err := NewIndex([]string{"ANO_EJE"}); err == nil {
		t.Fatal("debía fallar por columnas faltantes")
	}
}
