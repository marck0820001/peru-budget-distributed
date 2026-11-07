// Package ingestion implementa la Parte A del sistema: el cargador
// concurrente de los CSV de Gasto Devengado del MEF.
//
// Arquitectura (pipeline + fan-out/fan-in + map-reduce):
//
//	disco ──► [Split: 1 goroutine] ──chunks──► [worker 1..N: parse + valida + agrega local]
//	                                                     │ incidencias ──► [writer: 1 goroutine]
//	                                                     └─ parciales ──► [reduce: merge final]
//
// Cada worker mantiene su propio mapa de agregados (sin candados); el único
// estado compartido es el detector de duplicados, protegido por particiones.
// Los montos son enteros (céntimos), así que el resultado es idéntico al
// secuencial sin importar el orden en que terminen los workers.
package ingestion

import (
	"bufio"
	"bytes"
	"encoding/csv"
	"fmt"
	"io"
	"os"
	"runtime"
	"sort"
	"sync"
	"time"

	"github.com/marck0820001/peru-budget-distributed.git/internal/domain"
	"github.com/marck0820001/peru-budget-distributed.git/internal/preprocessing"
)

// Config parametriza el cargador.
type Config struct {
	Workers          int  // goroutines de parseo/validación (0 = NumCPU)
	ChunkRecords     int  // registros por bloque enviado a un worker
	DetectDuplicates bool // calcula huellas de líneas aceptadas
	DropDuplicates   bool // excluye del agregado las copias exactas (por defecto solo se reportan)
}

// DefaultConfig devuelve parámetros razonables para millones de filas.
func DefaultConfig() Config {
	return Config{Workers: runtime.NumCPU(), ChunkRecords: 20000, DetectDuplicates: true}
}

// Incident es una fila municipal rechazada (o malformada) para auditoría.
type Incident struct {
	File, YearText, SecEjec, Reason string
	Row                             int64
}

// Stats son los contadores de calidad por archivo (o totales).
type Stats struct {
	RowsRead        int64            `json:"rows_read"`
	NonLocal        int64            `json:"non_local_rows"`
	LocalRows       int64            `json:"local_rows"`
	LocalAccepted   int64            `json:"local_accepted"`
	LocalRejected   int64            `json:"local_rejected"`
	Malformed       int64            `json:"malformed_rows"`
	InvalidMoney    int64            `json:"local_rows_invalid_monetary"`
	MonthlyMismatch int64            `json:"local_monthly_mismatches"`
	ProjectRows     int64            `json:"local_project_rows"`
	MissingCode     int64            `json:"local_project_rows_missing_code"`
	ZeroRows        int64            `json:"local_rows_all_zero"`
	NegativeRows    int64            `json:"local_rows_with_negative_amounts"`
	Duplicates      int64            `json:"exact_duplicates_accepted"`
	DuplicatesDrop  int64            `json:"exact_duplicates_dropped"`
	PIACents        int64            `json:"local_pia_cents"`
	PIMCents        int64            `json:"local_pim_cents"`
	DevCents        int64            `json:"local_dev_cents"`
	MoneyErrors     map[string]int64 `json:"money_errors"`
}

func (s *Stats) add(o *Stats) {
	s.RowsRead += o.RowsRead
	s.NonLocal += o.NonLocal
	s.LocalRows += o.LocalRows
	s.LocalAccepted += o.LocalAccepted
	s.LocalRejected += o.LocalRejected
	s.Malformed += o.Malformed
	s.InvalidMoney += o.InvalidMoney
	s.MonthlyMismatch += o.MonthlyMismatch
	s.ProjectRows += o.ProjectRows
	s.MissingCode += o.MissingCode
	s.ZeroRows += o.ZeroRows
	s.NegativeRows += o.NegativeRows
	s.Duplicates += o.Duplicates
	s.DuplicatesDrop += o.DuplicatesDrop
	s.PIACents += o.PIACents
	s.PIMCents += o.PIMCents
	s.DevCents += o.DevCents
	if s.MoneyErrors == nil {
		s.MoneyErrors = map[string]int64{}
	}
	for k, v := range o.MoneyErrors {
		s.MoneyErrors[k] += v
	}
}

// FileResult resume el procesamiento de un archivo.
type FileResult struct {
	File         string        `json:"file"`
	ExpectedYear int           `json:"expected_year"`
	SizeBytes    int64         `json:"size_bytes"`
	Workers      int           `json:"workers"`
	Chunks       int           `json:"chunks"`
	Elapsed      time.Duration `json:"-"`
	ElapsedSec   float64       `json:"elapsed_sec"`
	RowsPerSec   float64       `json:"rows_per_sec"`
	Stats        Stats         `json:"stats"`
}

// Result es la salida acumulada de uno o varios archivos.
type Result struct {
	Files []FileResult                   `json:"files"`
	Total Stats                          `json:"totals"`
	Aggs  map[domain.Key]*domain.MuniAgg `json:"-"`
}

// NewResult crea un resultado vacío.
func NewResult() *Result {
	return &Result{Aggs: map[domain.Key]*domain.MuniAgg{}, Total: Stats{MoneyErrors: map[string]int64{}}}
}

// SortedKeys devuelve las claves ejecutora-año ordenadas (salida determinista).
func (r *Result) SortedKeys() []domain.Key {
	keys := make([]domain.Key, 0, len(r.Aggs))
	for k := range r.Aggs {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool {
		if keys[i].Year != keys[j].Year {
			return keys[i].Year < keys[j].Year
		}
		return keys[i].SecEjec < keys[j].SecEjec
	})
	return keys
}

// partial es el estado local de un worker (fase map).
type partial struct {
	stats Stats
	aggs  map[domain.Key]*domain.MuniAgg
}

func newPartial() *partial {
	return &partial{aggs: map[domain.Key]*domain.MuniAgg{}, stats: Stats{MoneyErrors: map[string]int64{}}}
}

func (p *partial) bucket(k domain.Key) *domain.MuniAgg {
	a := p.aggs[k]
	if a == nil {
		a = &domain.MuniAgg{Key: k}
		p.aggs[k] = a
	}
	return a
}

// recordHandler valida un registro y lo acumula en el parcial. Se comparte
// entre la versión concurrente y la secuencial para que ambas apliquen
// exactamente las mismas reglas.
type recordHandler struct {
	ix       *preprocessing.Index
	year     int
	file     string
	incident func(Incident)
}

type pending struct {
	line domain.Line
	row  int64
	fp   uint64
}

func (h *recordHandler) handle(p *partial, rec []string, row int64, keep *[]pending, wantFP bool) {
	p.stats.RowsRead++
	var line domain.Line
	res := h.ix.Validate(rec, h.year, &line)
	switch res.Outcome {
	case preprocessing.Malformed:
		p.stats.Malformed++
		h.incident(Incident{File: h.file, Row: row, Reason: res.Reason})
		return
	case preprocessing.NonLocal:
		p.stats.NonLocal++
		return
	}
	p.stats.LocalRows++
	if res.Outcome == preprocessing.Rejected {
		p.stats.LocalRejected++
		if len(res.MoneyErrors) > 0 {
			p.stats.InvalidMoney++
			for _, e := range res.MoneyErrors {
				p.stats.MoneyErrors[e]++
			}
		} else if res.Reason == "suma_meses_difiere_devengado_anual" {
			p.stats.MonthlyMismatch++
		}
		if res.YearText == fmt.Sprint(h.year) && res.SecEjec != "" {
			p.bucket(domain.Key{Year: h.year, SecEjec: res.SecEjec}).Rejected++
		}
		h.incident(Incident{File: h.file, Row: row, YearText: res.YearText, SecEjec: res.SecEjec, Reason: res.Reason})
		return
	}
	pd := pending{line: line, row: row}
	if wantFP {
		pd.fp = Fingerprint(rec)
	}
	*keep = append(*keep, pd)
}

func (h *recordHandler) accept(p *partial, pd *pending) {
	l := &pd.line
	p.stats.LocalAccepted++
	p.stats.PIACents += l.PIA
	p.stats.PIMCents += l.PIM
	p.stats.DevCents += l.DevAnual
	zero, neg := l.PIA == 0 && l.PIM == 0 && l.DevAnual == 0, l.PIA < 0 || l.PIM < 0 || l.DevAnual < 0
	for _, v := range l.Months {
		if v != 0 {
			zero = false
		}
		if v < 0 {
			neg = true
		}
	}
	if zero {
		p.stats.ZeroRows++
	}
	if neg {
		p.stats.NegativeRows++
	}
	if l.IsProject {
		p.stats.ProjectRows++
		if l.ProjectCode == "" {
			p.stats.MissingCode++
		}
	}
	p.bucket(domain.Key{Year: l.Year, SecEjec: l.SecEjec}).Add(l, pd.row)
}

// ProcessFile carga un CSV de forma concurrente y acumula en res.
// incidents puede ser nil (las incidencias se descartan).
func ProcessFile(path string, expectedYear int, cfg Config, res *Result, incidents func(Incident)) (FileResult, error) {
	start := time.Now()
	if cfg.Workers <= 0 {
		cfg.Workers = runtime.NumCPU()
	}
	if cfg.ChunkRecords <= 0 {
		cfg.ChunkRecords = 20000
	}
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

	// Las incidencias de todos los workers se serializan en un único goroutine
	// escritor: el callback del usuario nunca se ejecuta en paralelo.
	incCh := make(chan Incident, 1024)
	var incWG sync.WaitGroup
	incWG.Add(1)
	go func() {
		defer incWG.Done()
		for inc := range incCh {
			if incidents != nil {
				incidents(inc)
			}
		}
	}()

	var dups *DupDetector
	if cfg.DetectDuplicates {
		dups = NewDupDetector(1 << 20)
	}

	chunks := make(chan Chunk, cfg.Workers*2) // capacidad acotada = backpressure
	stop := make(chan struct{})
	partials := make(chan *partial, cfg.Workers)
	errCh := make(chan error, cfg.Workers+1)
	nChunks := 0
	var chunkMu sync.Mutex

	var wg sync.WaitGroup
	for w := 0; w < cfg.Workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			p := newPartial()
			h := &recordHandler{ix: ix, year: expectedYear, file: info.Name(),
				incident: func(i Incident) { incCh <- i }}
			keep := make([]pending, 0, cfg.ChunkRecords)
			fps := make([]uint64, 0, cfg.ChunkRecords)
			for c := range chunks {
				chunkMu.Lock()
				nChunks++
				chunkMu.Unlock()
				r := csv.NewReader(bytes.NewReader(c.Data))
				r.FieldsPerRecord = -1
				r.ReuseRecord = true
				keep = keep[:0]
				row := c.FirstRow
				for {
					rec, err := r.Read()
					if err == io.EOF {
						break
					}
					if err != nil { // registro con comillas rotas: se audita como malformado
						p.stats.RowsRead++
						p.stats.Malformed++
						h.incident(Incident{File: info.Name(), Row: row, Reason: "csv_invalido: " + err.Error()})
						row++
						continue
					}
					h.handle(p, rec, row, &keep, dups != nil)
					row++
				}
				var isDup []bool
				if dups != nil && len(keep) > 0 {
					fps = fps[:0]
					for i := range keep {
						fps = append(fps, keep[i].fp)
					}
					isDup = dups.InsertBatch(fps)
				}
				for i := range keep {
					if isDup != nil && isDup[i] {
						p.stats.Duplicates++
						if cfg.DropDuplicates {
							p.stats.DuplicatesDrop++
							continue
						}
					}
					h.accept(p, &keep[i])
				}
			}
			partials <- p
		}()
	}

	// Productor: un solo goroutine lee el disco.
	go func() {
		if _, err := Split(br, cfg.ChunkRecords, chunks, stop); err != nil {
			errCh <- err
		}
	}()

	go func() { wg.Wait(); close(partials) }()

	// Reduce (fan-in): fusiona los parciales de cada worker.
	fileStats := Stats{MoneyErrors: map[string]int64{}}
	for p := range partials {
		fileStats.add(&p.stats)
		for k, a := range p.aggs {
			if dst, ok := res.Aggs[k]; ok {
				dst.Merge(a)
			} else {
				res.Aggs[k] = a
			}
		}
	}
	close(incCh)
	incWG.Wait()
	close(stop)
	select {
	case err := <-errCh:
		return FileResult{}, err
	default:
	}
	res.Total.add(&fileStats)
	el := time.Since(start)
	fr := FileResult{File: info.Name(), ExpectedYear: expectedYear, SizeBytes: info.Size(),
		Workers: cfg.Workers, Chunks: nChunks, Elapsed: el, ElapsedSec: el.Seconds(),
		RowsPerSec: float64(fileStats.RowsRead) / el.Seconds(), Stats: fileStats}
	res.Files = append(res.Files, fr)
	return fr, nil
}
