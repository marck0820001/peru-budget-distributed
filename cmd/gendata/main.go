// Command gendata genera CSV SINTÉTICOS con el esquema exacto de
// "Gasto Devengado" del MEF (mismas 74 columnas y formato entrecomillado).
//
// Sirve solo para pruebas funcionales, de rendimiento y CI cuando los CSV
// oficiales (~2.6 GB cada uno) no están disponibles. NO reemplaza los datos
// reales: las cifras del informe deben regenerarse con los archivos del MEF.
//
// Inyecta intencionalmente problemas de calidad para probar la limpieza:
// filas malformadas, montos inválidos, meses que no concilian, duplicados
// exactos, ceros, negativos (reversiones) y filas de otros niveles de gobierno.
//
//	go run ./cmd/gendata --out data/raw --scale 1.0
package main

import (
	"bufio"
	"flag"
	"fmt"
	"log"
	"math"
	"math/rand"
	"os"
	"path/filepath"
	"strings"
)

var header = []string{"ANO_EJE", "NIVEL_GOBIERNO", "NIVEL_GOBIERNO_NOMBRE", "SECTOR", "SECTOR_NOMBRE", "PLIEGO", "PLIEGO_NOMBRE", "SEC_EJEC", "EJECUTORA", "EJECUTORA_NOMBRE", "DEPARTAMENTO_EJECUTORA", "DEPARTAMENTO_EJECUTORA_NOMBRE", "PROVINCIA_EJECUTORA", "PROVINCIA_EJECUTORA_NOMBRE", "DISTRITO_EJECUTORA", "DISTRITO_EJECUTORA_NOMBRE", "PROGRAMA_PPTO", "PROGRAMA_PPTO_NOMBRE", "TIPO_ACT_PROY", "PRODUCTO_PROYECTO", "PRODUCTO_PROYECTO_NOMBRE", "ACTIVIDAD_ACCION_OBRA", "ACTIVIDAD_ACCION_OBRA_NOMBRE", "FUNCION", "FUNCION_NOMBRE", "DIVISION_FUNCIONAL", "DIVISION_FUNCIONAL_NOMBRE", "GRUPO_FUNCIONAL", "GRUPO_FUNCIONAL_NOMBRE", "SEC_FUNC", "META", "FINALIDAD", "META_NOMBRE", "DEPARTAMENTO_META", "DEPARTAMENTO_META_NOMBRE", "FUENTE_FINANCIAMIENTO", "FUENTE_FINANCIAMIENTO_NOMBRE", "RUBRO", "RUBRO_NOMBRE", "TIPO_RECURSO", "TIPO_RECURSO_NOMBRE", "CATEGORIA_GASTO", "CATEGORIA_GASTO_NOMBRE", "TIPO_TRANSACCION", "TIPO_TRANSACCION_NOMBRE", "GENERICA", "GENERICA_NOMBRE", "SUBGENERICA", "SUBGENERICA_NOMBRE", "SUBGENERICA_DET", "SUBGENERICA_DET_NOMBRE", "ESPECIFICA", "ESPECIFICA_NOMBRE", "ESPECIFICA_DET", "ESPECIFICA_DET_NOMBRE", "MONTO_PIA", "MONTO_PIM", "MONTO_CERTIFICADO_ANUAL", "MONTO_COMPROMETIDO_ANUAL", "MONTO_DEVENGADO_ENERO", "MONTO_DEVENGADO_FEBRERO", "MONTO_DEVENGADO_MARZO", "MONTO_DEVENGADO_ABRIL", "MONTO_DEVENGADO_MAYO", "MONTO_DEVENGADO_JUNIO", "MONTO_DEVENGADO_JULIO", "MONTO_DEVENGADO_AGOSTO", "MONTO_DEVENGADO_SEPTIEMBRE", "MONTO_DEVENGADO_OCTUBRE", "MONTO_DEVENGADO_NOVIEMBRE", "MONTO_DEVENGADO_DICIEMBRE", "MONTO_DEVENGADO_ANUAL", "MONTO_GIRADO_ANUAL"}

var departamentos = []string{"AMAZONAS", "ANCASH", "APURIMAC", "AREQUIPA", "AYACUCHO", "CAJAMARCA", "PROVINCIA CONSTITUCIONAL DEL CALLAO", "CUSCO", "HUANCAVELICA", "HUANUCO", "ICA", "JUNIN", "LA LIBERTAD", "LAMBAYEQUE", "LIMA", "LORETO", "MADRE DE DIOS", "MOQUEGUA", "PASCO", "PIURA", "PUNO", "SAN MARTIN", "TACNA", "TUMBES", "UCAYALI"}

// archetype es un patrón latente de ejecución (el modelo NO lo conoce).
type archetype struct {
	name                       string
	tasa, q4, proj, mod, scale float64
}

var archetypes = []archetype{
	{"ejecucion_sostenida", 0.88, 0.32, 0.30, 0.25, 1.0},
	{"rezago_ejecucion", 0.55, 0.38, 0.45, 0.65, 0.8},
	{"concentrado_cierre", 0.78, 0.62, 0.40, 0.40, 1.0},
	{"intensivo_inversion", 0.74, 0.42, 0.68, 0.95, 1.2},
	{"grandes_urbanas", 0.82, 0.36, 0.22, 0.15, 6.0},
}

type entity struct {
	sec, name, dept, prov, dist string
	arch                        archetype
	lines                       int
	pimScale                    float64
	anomaly                     int
}

func q(s string) string { return `"` + strings.ReplaceAll(s, `"`, `""`) + `"` }

func cents(c int64) string {
	sign := ""
	if c < 0 {
		sign, c = "-", -c
	}
	if c%100 == 0 {
		return fmt.Sprintf("%s%d", sign, c/100)
	}
	return fmt.Sprintf("%s%d.%02d", sign, c/100, c%100)
}

func main() {
	out := flag.String("out", "data/raw", "carpeta de salida")
	scale := flag.Float64("scale", 1.0, "1.0 ≈ volumen real (2.8M filas por año); 0.001 para muestras")
	munis := flag.Int("munis", 1890, "municipalidades sintéticas")
	seed := flag.Int64("seed", 20261107, "semilla")
	years := flag.String("years", "2024,2025", "años a generar")
	flag.Parse()
	if err := os.MkdirAll(*out, 0o755); err != nil {
		log.Fatal(err)
	}
	rng := rand.New(rand.NewSource(*seed))
	ents := buildEntities(rng, *munis, *scale)
	for _, ys := range strings.Split(*years, ",") {
		var year int
		fmt.Sscan(strings.TrimSpace(ys), &year)
		name := fmt.Sprintf("%d-Gasto-Devengado.csv", year)
		if year == 2025 {
			name = "2025-Gasto-Devengado-Mensual.csv"
		}
		n, err := writeYear(filepath.Join(*out, name), year, ents, *scale, rand.New(rand.NewSource(*seed+int64(year))))
		if err != nil {
			log.Fatal(err)
		}
		log.Printf("%s: %d filas", name, n)
	}
}

func buildEntities(rng *rand.Rand, nMuni int, scale float64) []entity {
	var ents []entity
	add := func(name, dept string, a archetype, anomaly int) {
		i := len(ents)
		lines := int(math.Max(3, 740*scale*math.Exp(rng.NormFloat64()*0.55)*math.Sqrt(a.scale)))
		ents = append(ents, entity{
			sec: fmt.Sprint(300001 + i), name: name, dept: dept,
			prov: "PROV " + fmt.Sprint(i%196+1), dist: "DIST " + fmt.Sprint(i+1),
			arch: a, lines: lines, pimScale: a.scale * math.Exp(rng.NormFloat64()*0.7), anomaly: anomaly,
		})
	}
	weights := []float64{0.34, 0.20, 0.20, 0.20, 0.06}
	for i := 0; i < nMuni; i++ {
		r, k := rng.Float64(), 0
		for acc := weights[0]; r > acc && k < len(weights)-1; {
			k++
			acc += weights[k]
		}
		dept := departamentos[rng.Intn(len(departamentos))]
		kind := "DISTRITAL"
		if i%10 == 0 {
			kind = "PROVINCIAL"
		}
		anomaly := 0
		if rng.Float64() < 0.015 {
			anomaly = 1 + rng.Intn(3)
		}
		name := fmt.Sprintf("MUNICIPALIDAD %s DE %s %04d", kind, strings.Split(dept, " ")[0], i+1)
		add(name, dept, archetypes[k], anomaly)
	}
	for i := 0; i < 30; i++ {
		add(fmt.Sprintf("MANCOMUNIDAD MUNICIPAL DEL VALLE %02d", i+1), departamentos[rng.Intn(len(departamentos))], archetypes[1], 0)
	}
	for i := 0; i < 10; i++ {
		add(fmt.Sprintf("INSTITUTO VIAL PROVINCIAL %02d", i+1), departamentos[rng.Intn(len(departamentos))], archetypes[0], 0)
	}
	return ents
}

func writeYear(path string, year int, ents []entity, scale float64, rng *rand.Rand) (int, error) {
	f, err := os.Create(path)
	if err != nil {
		return 0, err
	}
	defer f.Close()
	w := bufio.NewWriterSize(f, 8<<20)
	defer w.Flush()
	hq := make([]string, len(header))
	for i, h := range header {
		hq[i] = q(h)
	}
	w.WriteString(strings.Join(hq, ",") + "\n")
	rows := 0
	shift := 0.0
	if year == 2025 {
		shift = 0.05 // 2025 ejecuta algo más (consistente con 75.8% → 80.6% del EDA real)
	}
	// 1) Otros niveles de gobierno (N y R) primero, como en los CSV del MEF.
	nonLocal := int(970000 * scale)
	for i := 0; i < nonLocal; i++ {
		lvl, lvlName := "E", "GOBIERNO NACIONAL"
		if i%3 == 0 {
			lvl, lvlName = "R", "GOBIERNOS REGIONALES"
		}
		pia := int64(rng.Intn(5000000)) * 100
		rec := line(rng, i, year, lvl, lvlName, fmt.Sprint(1000+i%900), "UNIDAD EJECUTORA "+fmt.Sprint(i%900), departamentos[i%25], "", "", false, pia, pia, 0.8, 0.35)
		w.WriteString(rec)
		rows++
	}
	// 2) Gobiernos locales.
	var dupPool []string
	for _, e := range ents {
		a := e.arch
		tasa, q4, mod := a.tasa+shift+rng.NormFloat64()*0.05, a.q4+rng.NormFloat64()*0.04, a.mod+rng.NormFloat64()*0.08
		switch e.anomaly {
		case 1:
			tasa = 0.10 + rng.Float64()*0.08 // casi no ejecuta
		case 2:
			q4 = 0.90 + rng.Float64()*0.06 // casi todo en el último trimestre
		case 3:
			mod = 2.2 + rng.Float64()*0.6 // PIM muy superior al PIA
		}
		for j := 0; j < e.lines; j++ {
			isProj := rng.Float64() < a.proj
			base := math.Exp(rng.NormFloat64()*1.3) * 18000 * e.pimScale
			if isProj {
				base *= 2.2
			}
			pia := int64(base) * 100
			r := rng.Float64()
			if r < 0.15 {
				pia = 0 // incorporaciones sin PIA
			}
			pim := int64(float64(int64(base)*100) * math.Exp(mod+rng.NormFloat64()*0.3))
			pim = pim / 100 * 100
			lt := math.Min(math.Max(tasa+rng.NormFloat64()*0.12, 0), 1.15)
			if r > 0.80 { // ~20% de líneas en cero
				pia, pim, lt = 0, 0, 0
			}
			rec := line(rng, j, year, "M", "GOBIERNOS LOCALES", e.sec, e.name, e.dept, e.prov, e.dist, isProj, pia, pim, lt, math.Min(math.Max(q4, 0.05), 0.97))
			rec = corrupt(rng, rec, year)
			w.WriteString(rec)
			rows++
			if rng.Float64() < 0.0001 {
				dupPool = append(dupPool, rec)
			}
		}
	}
	for _, d := range dupPool { // duplicados exactos al final del archivo
		w.WriteString(d)
		rows++
	}
	return rows, nil
}

// line construye un registro completo con meses que suman exactamente el anual.
func line(rng *rand.Rand, meta int, year int, lvl, lvlName, sec, name, dept, prov, dist string, isProj bool, pia, pim int64, tasa, q4 float64) string {
	dev := int64(float64(pim)*tasa) / 100 * 100
	var months [12]int64
	if dev != 0 {
		var wts [12]float64
		var tot float64
		for m := 0; m < 12; m++ {
			base := (1 - q4) / 9
			if m >= 9 {
				base = q4 / 3 * []float64{0.8, 0.9, 1.3}[m-9]
			}
			wts[m] = base * math.Exp(rng.NormFloat64()*0.25)
			tot += wts[m]
		}
		var acc int64
		for m := 0; m < 11; m++ {
			months[m] = int64(float64(dev) * wts[m] / tot)
			acc += months[m]
		}
		months[11] = dev - acc
		if rng.Float64() < 0.015 { // reversión contable: mes negativo compensado
			adj := int64(rng.Intn(50000)+1) * 100
			months[3] -= adj
			months[4] += adj
		}
	}
	tipo, prodName := "ACTIVIDAD", "SIN PRODUCTO"
	prod := "3999999"
	if isProj {
		tipo = "PROYECTO"
		prod = fmt.Sprint(2000000 + rng.Intn(600000))
		prodName = "MEJORAMIENTO DEL SERVICIO DE TRANSITABILIDAD VEHICULAR Y PEATONAL"
	}
	cert := dev + int64(float64(pim-dev)*0.4)/100*100
	f := []string{
		fmt.Sprint(year), lvl, lvlName, "99", lvlName, "465", name, sec, "001", name,
		"15", dept, "01", prov, "01", dist, "9001", "ACCIONES CENTRALES", tipo, prod, prodName,
		"5000003", "GESTION ADMINISTRATIVA", "03", "PLANEAMIENTO, GESTION Y RESERVA DE CONTINGENCIA",
		"006", "GESTION", "0008", "ASESORAMIENTO Y APOYO", fmt.Sprint(meta%400 + 1), fmt.Sprintf("%05d", meta+1), fmt.Sprintf("%07d", 9+meta), "ACCIONES ADMINISTRATIVAS",
		"15", dept, "1", "RECURSOS ORDINARIOS", "00", "RECURSOS ORDINARIOS", "0", "RECURSOS ORDINARIOS",
		"5", "GASTOS CORRIENTES", "2", "GASTOS PRESUPUESTARIOS", "3", "BIENES Y SERVICIOS", "2", "CONTRATACION DE SERVICIOS",
		"7", "SERVICIOS PROFESIONALES Y TECNICOS", "1", "SERVICIOS DIVERSOS", "99", "OTROS SERVICIOS",
		cents(pia), cents(pim), cents(cert), cents(cert),
	}
	for _, m := range months {
		f = append(f, cents(m))
	}
	f = append(f, cents(dev), cents(dev))
	for i := range f {
		f[i] = q(f[i])
	}
	return strings.Join(f, ",") + "\n"
}

// corrupt inyecta problemas de calidad en una pequeña fracción de filas.
// Los índices tras strings.Split se desplazan +1 por la coma entrecomillada de
// FUNCION_NOMBRE ("PLANEAMIENTO, GESTION..."), que además prueba el parser CSV.
func corrupt(rng *rand.Rand, rec string, year int) string {
	r := rng.Float64()
	switch {
	case r < 0.00002: // fila malformada (falta un campo)
		return rec[strings.Index(rec, ",")+1:]
	case r < 0.00005: // monto con coma decimal ambigua
		parts := strings.Split(rec, ",")
		parts[56] = `"12500,50"` // MONTO_PIA (+1 por la coma dentro de FUNCION_NOMBRE)
		return strings.Join(parts, ",")
	case r < 0.00007: // monto vacío
		parts := strings.Split(rec, ",")
		parts[57] = `""` // MONTO_PIM
		return strings.Join(parts, ",")
	case r < 0.00011: // meses no concilian con el anual
		parts := strings.Split(rec, ",")
		parts[72] = `"999999.99"` // MONTO_DEVENGADO_ANUAL (columna 71)
		return strings.Join(parts, ",")
	case r < 0.00012: // año que no corresponde al archivo
		return strings.Replace(rec, fmt.Sprintf(`"%d"`, year), fmt.Sprintf(`"%d"`, year-1), 1)
	}
	return rec
}
