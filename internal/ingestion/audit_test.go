package ingestion

import (
	"os"
	"path/filepath"
	"testing"
)

func TestCents(t *testing.T) {
	examples := map[string]int64{"0": 0, "-3.29": -329, "1000.50": 100050, "1.2300": 123, "+.4": 40, "1.": 100}
	for input, want := range examples {
		got, err := ParseCents(input)
		if err != nil || got != want {
			t.Fatalf("%q = %d %v, want %d", input, got, err, want)
		}
	}
	for _, v := range []string{"1,000", "12.345", "", "NaN"} {
		if _, e := ParseCents(v); e == nil {
			t.Fatalf("esperaba error para %q", v)
		}
	}
}
func TestAuditFile(t *testing.T) {
	p := filepath.Join(t.TempDir(), "sample.csv")
	payload := "ANO_EJE,NIVEL_GOBIERNO,TIPO_ACT_PROY,MONTO_PIA,MONTO_PIM,MONTO_DEVENGADO_ANUAL\n" +
		"2024,M,PROYECTO,0,100,-10.50\n2024,R,ACTIVIDAD,10,10,10\n2024,M,ACTIVIDAD,5.00,8.00,7.00\n"
	if err := os.WriteFile(p, []byte(payload), 0600); err != nil {
		t.Fatal(err)
	}
	result, err := AuditFile(p, 4)
	if err != nil {
		t.Fatal(err)
	}
	if result.RowsRead != 3 || result.LocalRows != 2 || result.AcceptedLocalRows != 2 || result.ProjectLocalRows != 1 {
		t.Fatalf("conteos incorrectos: %+v", result)
	}
	if result.PIACents != 500 || result.PIMCents != 10800 || result.DevCents != -350 {
		t.Fatalf("montos incorrectos: %+v", result)
	}
}
