package features

import (
	"math"
	"testing"

	"github.com/marck0820001/peru-budget-distributed.git/internal/domain"
)

func TestEntityType(t *testing.T) {
	for in, want := range map[string]string{
		"MUNICIPALIDAD DISTRITAL DE SAN JOSÉ": "municipalidad",
		"MUNICIPALIDAD PROVINCIAL DE HUANUCO": "municipalidad",
		"MANCOMUNIDAD MUNICIPAL DEL VALLE":    "mancomunidad",
		"INSTITUTO VIAL PROVINCIAL":           "otra_ejecutora_local",
	} {
		if got := EntityType(in); got != want {
			t.Errorf("EntityType(%q)=%s quiero %s", in, got, want)
		}
	}
}

func TestPercentile(t *testing.T) {
	v := []float64{1, 2, 3, 4, 5}
	if Percentile(v, 0.5) != 3 || Percentile(v, 0.25) != 2 || math.Abs(Percentile(v, 0.1)-1.4) > 1e-12 {
		t.Fatal("percentil por interpolación lineal incorrecto")
	}
}

func agg(pia, pim, dev, projDev int64, q4share float64) *domain.MuniAgg {
	a := &domain.MuniAgg{PIA: pia, PIM: pim, Dev: dev, ProjectDev: projDev, Rows: 10,
		Key: domain.Key{Year: 2024, SecEjec: "1"}, Ejecutora: "MUNICIPALIDAD X", Departamento: "LIMA"}
	q4 := int64(float64(dev) * q4share)
	for m := 0; m < 9; m++ {
		a.Months[m] = (dev - q4) / 9
	}
	a.Months[8] += (dev - q4) - (dev-q4)/9*9
	a.Months[11] = q4
	return a
}

func TestIndicators(t *testing.T) {
	v, _, ok := Indicators(agg(0, 100000, 80000, 40000, 0.5)) // PIA=0 es válido
	if !ok {
		t.Fatal("PIA=0 no debe invalidar el perfil")
	}
	if math.Abs(v[0]-0.8) > 1e-12 || math.Abs(v[2]-0.5) > 1e-12 || math.Abs(v[3]-0.5) > 1e-12 {
		t.Fatalf("indicadores incorrectos: %v", v)
	}
	if _, _, ok := Indicators(agg(100, 0, 0, 0, 0)); ok {
		t.Fatal("PIM=0 debe dejar indicadores sin definir")
	}
}

func TestFitTransform(t *testing.T) {
	var ps []Profile
	for i := 0; i < 100; i++ {
		a := agg(int64(1000+i), int64(2000+10*i), int64(1000+9*i), int64(300+i), 0.3+float64(i)/1000)
		ps = append(ps, BuildProfiles([]*domain.MuniAgg{a})...)
	}
	tr, err := Fit(ps)
	if err != nil {
		t.Fatal(err)
	}
	// La mediana escalada de cada feature usada debe ser ~0.
	for j, name := range tr.Features {
		vals := make([]float64, len(ps))
		for i, p := range ps {
			vals[i] = tr.Transform(p.Raw)[j]
		}
		sortFloats(vals)
		if math.Abs(Percentile(vals, 0.5)) > 1e-9 {
			t.Errorf("%s: mediana escalada %.3g", name, Percentile(vals, 0.5))
		}
	}
}

func sortFloats(v []float64) {
	for i := 1; i < len(v); i++ {
		for j := i; j > 0 && v[j] < v[j-1]; j-- {
			v[j], v[j-1] = v[j-1], v[j]
		}
	}
}
