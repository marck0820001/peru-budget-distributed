package ingestion

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"

	"github.com/marck0820001/peru-budget-distributed.git/internal/domain"
)

// writeCSV crea un CSV pequeño con el esquema requerido, incluyendo casos sucios.
func writeCSV(t testing.TB, n int) string {
	t.Helper()
	cols := append(domain.RequiredColumns(), "FUNCION_NOMBRE")
	var b strings.Builder
	q := func(s string) string { return `"` + strings.ReplaceAll(s, `"`, `""`) + `"` }
	hq := make([]string, len(cols))
	for i, c := range cols {
		hq[i] = q(c)
	}
	b.WriteString(strings.Join(hq, ",") + "\n")
	for i := 0; i < n; i++ {
		nivel := "M"
		if i%4 == 0 {
			nivel = "R"
		}
		sec := fmt.Sprint(300001 + i%37)
		months := make([]string, 12)
		var total int64
		for m := 0; m < 12; m++ {
			v := int64((i*7+m*13)%5000) * 100
			if m == 3 && i%50 == 0 {
				v = -v // reversión contable
			}
			total += v
			months[m] = fmt.Sprintf("%d.%02d", v/100, abs(v%100))
		}
		anual := fmt.Sprintf("%d.%02d", total/100, abs(total%100))
		if i%97 == 0 {
			anual = "1.00" // no concilia
		}
		pia := fmt.Sprint(1000 + i)
		if i%113 == 0 {
			pia = "12,5" // ambiguo
		}
		row := []string{"2024", nivel, sec, "MUNICIPALIDAD DISTRITAL " + sec, "LIMA", "PROYECTO", fmt.Sprint(2000000 + i%11), "OBRA \"A\", B\nlinea 2", pia, fmt.Sprint(5000 + i), anual}
		row = append(row, months...)
		row = append(row, "PLANEAMIENTO, GESTION")
		for k := range row {
			row[k] = q(row[k])
		}
		line := strings.Join(row, ",")
		if i%151 == 0 {
			line = line[strings.Index(line, ",")+1:] // malformada
		}
		b.WriteString(line + "\n")
		if i%89 == 0 {
			b.WriteString(line + "\n") // duplicado exacto
		}
	}
	p := filepath.Join(t.TempDir(), "2024-Gasto-Devengado.csv")
	if err := os.WriteFile(p, []byte(b.String()), 0o644); err != nil {
		t.Fatal(err)
	}
	return p
}

func abs(v int64) int64 {
	if v < 0 {
		return -v
	}
	return v
}

func snapshot(r *Result) map[domain.Key]domain.MuniAgg {
	out := map[domain.Key]domain.MuniAgg{}
	for k, v := range r.Aggs {
		out[k] = *v
	}
	return out
}

// La versión concurrente debe producir EXACTAMENTE lo mismo que la secuencial,
// con cualquier número de workers y tamaño de bloque.
func TestConcurrentEqualsSequential(t *testing.T) {
	path := writeCSV(t, 5000)
	seq := NewResult()
	if _, err := ProcessFileSequential(path, 2024, true, false, seq, nil); err != nil {
		t.Fatal(err)
	}
	if seq.Total.Malformed == 0 || seq.Total.LocalRejected == 0 || seq.Total.Duplicates == 0 || seq.Total.NegativeRows == 0 {
		t.Fatalf("el CSV de prueba debía contener casos sucios: %+v", seq.Total)
	}
	for _, w := range []int{1, 2, 4, 8} {
		for _, chunk := range []int{1, 7, 500} {
			par := NewResult()
			var mu sync.Mutex
			incs := 0
			_, err := ProcessFile(path, 2024, Config{Workers: w, ChunkRecords: chunk, DetectDuplicates: true}, par,
				func(Incident) { mu.Lock(); incs++; mu.Unlock() })
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(seq.Total, par.Total) {
				t.Fatalf("w=%d chunk=%d: totales distintos\nseq=%+v\npar=%+v", w, chunk, seq.Total, par.Total)
			}
			if !reflect.DeepEqual(snapshot(seq), snapshot(par)) {
				t.Fatalf("w=%d chunk=%d: agregados distintos", w, chunk)
			}
			if int64(incs) != par.Total.LocalRejected+par.Total.Malformed {
				t.Fatalf("incidencias=%d esperado=%d", incs, par.Total.LocalRejected+par.Total.Malformed)
			}
		}
	}
}

func TestRowBalance(t *testing.T) {
	path := writeCSV(t, 3000)
	r := NewResult()
	if _, err := ProcessFile(path, 2024, Config{Workers: 4, ChunkRecords: 100, DetectDuplicates: true, DropDuplicates: true}, r, nil); err != nil {
		t.Fatal(err)
	}
	s := r.Total
	if s.RowsRead != s.NonLocal+s.LocalAccepted+s.LocalRejected+s.Malformed+s.DuplicatesDrop {
		t.Fatalf("balance de filas roto: %+v", s)
	}
	var dev int64
	for _, a := range r.Aggs {
		dev += a.Dev
	}
	if dev != s.DevCents {
		t.Fatalf("suma de agregados %d != total líneas %d", dev, s.DevCents)
	}
}

// Un campo entrecomillado con salto de línea no debe partirse entre bloques.
func TestSplitKeepsQuotedNewlines(t *testing.T) {
	data := "\"a\",\"b\"\n\"1\",\"x\ny\"\n\"2\",\"z\"\n"
	br := bufio.NewReader(strings.NewReader(data))
	if _, err := ReadHeader(br); err != nil {
		t.Fatal(err)
	}
	ch := make(chan Chunk, 10)
	n, err := Split(br, 1, ch, make(chan struct{}))
	if err != nil || n != 2 {
		t.Fatalf("registros=%d err=%v", n, err)
	}
	var got []Chunk
	for c := range ch {
		got = append(got, c)
	}
	if len(got) != 2 || got[1].FirstRow != 3 || !strings.Contains(string(got[0].Data), "x\ny") {
		t.Fatalf("bloques incorrectos: %+v", got)
	}
}

// El detector de duplicados es seguro con escrituras concurrentes (go test -race).
func TestDupDetectorConcurrent(t *testing.T) {
	d := NewDupDetector(1000)
	var wg sync.WaitGroup
	var mu sync.Mutex
	dups := 0
	for w := 0; w < 8; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			fps := make([]uint64, 1000)
			for i := range fps {
				fps[i] = uint64(i) * 2654435761
			}
			c := 0
			for _, dup := range d.InsertBatch(fps) {
				if dup {
					c++
				}
			}
			mu.Lock()
			dups += c
			mu.Unlock()
		}()
	}
	wg.Wait()
	if dups != 7000 { // 8 workers × 1000 huellas, solo 1000 únicas
		t.Fatalf("duplicados=%d quiero 7000", dups)
	}
}

func BenchmarkLoader(b *testing.B) {
	path := writeCSV(b, 200000)
	for _, w := range []int{0, 1, 2, 4, 8} {
		name := fmt.Sprintf("workers=%d", w)
		if w == 0 {
			name = "secuencial"
		}
		b.Run(name, func(b *testing.B) {
			for i := 0; i < b.N; i++ {
				r := NewResult()
				if w == 0 {
					ProcessFileSequential(path, 2024, true, false, r, nil)
				} else {
					ProcessFile(path, 2024, Config{Workers: w, ChunkRecords: 20000, DetectDuplicates: true}, r, nil)
				}
			}
		})
	}
}
