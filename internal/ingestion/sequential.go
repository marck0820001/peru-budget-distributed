package ingestion

import (
	"bufio"
	"encoding/csv"
	"fmt"
	"io"
	"os"
	"time"

	"github.com/marck0820001/peru-budget-distributed.git/internal/preprocessing"
)

// ProcessFileSequential es la línea base SIN goroutines: lee, valida y agrega
// fila por fila en un solo hilo. Aplica exactamente las mismas reglas que
// ProcessFile (comparten recordHandler), por lo que sirve para verificar que
// la versión concurrente produce el mismo resultado y para medir el speedup.
func ProcessFileSequential(path string, expectedYear int, detectDup, dropDup bool, res *Result, incidents func(Incident)) (FileResult, error) {
	start := time.Now()
	f, err := os.Open(path)
	if err != nil {
		return FileResult{}, err
	}
	defer f.Close()
	info, _ := f.Stat()
	br := bufio.NewReaderSize(f, 4<<20)
	header, err := ReadHeader(br)
	if err != nil {
		return FileResult{}, fmt.Errorf("%s: %w", path, err)
	}
	ix, err := preprocessing.NewIndex(header)
	if err != nil {
		return FileResult{}, fmt.Errorf("%s: %w", path, err)
	}
	if incidents == nil {
		incidents = func(Incident) {}
	}
	p := newPartial()
	h := &recordHandler{ix: ix, year: expectedYear, file: info.Name(), incident: incidents}
	seen := map[uint64]struct{}{}
	r := csv.NewReader(br)
	r.FieldsPerRecord = -1
	r.ReuseRecord = true
	keep := make([]pending, 0, 1)
	row := int64(2)
	for {
		rec, err := r.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			p.stats.RowsRead++
			p.stats.Malformed++
			incidents(Incident{File: info.Name(), Row: row, Reason: "csv_invalido: " + err.Error()})
			row++
			continue
		}
		keep = keep[:0]
		h.handle(p, rec, row, &keep, detectDup)
		row++
		if len(keep) == 0 {
			continue
		}
		pd := &keep[0]
		if detectDup {
			if _, ok := seen[pd.fp]; ok {
				p.stats.Duplicates++
				if dropDup {
					p.stats.DuplicatesDrop++
					continue
				}
			} else {
				seen[pd.fp] = struct{}{}
			}
		}
		h.accept(p, pd)
	}
	for k, a := range p.aggs {
		if dst, ok := res.Aggs[k]; ok {
			dst.Merge(a)
		} else {
			res.Aggs[k] = a
		}
	}
	res.Total.add(&p.stats)
	el := time.Since(start)
	fr := FileResult{File: info.Name(), ExpectedYear: expectedYear, SizeBytes: info.Size(), Workers: 0,
		Elapsed: el, ElapsedSec: el.Seconds(), RowsPerSec: float64(p.stats.RowsRead) / el.Seconds(), Stats: p.stats}
	res.Files = append(res.Files, fr)
	return fr, nil
}
