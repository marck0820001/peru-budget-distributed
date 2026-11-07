package massive

import (
	"bufio"
	"encoding/binary"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type SourceInfo struct {
	Path          string `json:"path"`
	AllRows       int64  `json:"all_rows"`
	MunicipalRows int64  `json:"municipal_rows"`
	ProjectRows   int64  `json:"project_rows"`
}

type Metadata struct {
	Version     int          `json:"version"`
	DatasetPath string       `json:"dataset_path"`
	Rows        int64        `json:"rows"`
	Dimensions  int          `json:"dimensions"`
	Features    []string     `json:"features"`
	Mean        []float64    `json:"mean"`
	Std         []float64    `json:"std"`
	Sources     []SourceInfo `json:"sources"`
	DurationMS  int64        `json:"build_duration_ms"`
	Note        string       `json:"note"`
}

type BuildConfig struct {
	Inputs       []string
	DatasetPath  string
	MetadataPath string
	Limit        int64 // 0 = full municipal dataset
	ExpectRows   int64 // optional; use 3642510 in the full project run
}

type moments struct {
	n    int64
	mean [Dim]float64
	m2   [Dim]float64
}

func (m *moments) add(x [Dim]float64) {
	m.n++
	for i, v := range x {
		delta := v - m.mean[i]
		m.mean[i] += delta / float64(m.n)
		m.m2[i] += delta * (v - m.mean[i])
	}
}
func writeJSON(path string, v any) error {
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	tmp := path + ".tmp"
	f, err := os.Create(tmp)
	if err != nil {
		return err
	}
	enc := json.NewEncoder(f)
	enc.SetIndent("", "  ")
	if err = enc.Encode(v); err != nil {
		f.Close()
		os.Remove(tmp)
		return err
	}
	if err = f.Close(); err != nil {
		os.Remove(tmp)
		return err
	}
	if err = os.Remove(path); err != nil && !os.IsNotExist(err) {
		return err
	}
	return os.Rename(tmp, path)
}

// BuildBinary streams the official 73-column MEF expense files, retaining only
// NIVEL_GOBIERNO=M and writing exactly one 9-feature record per municipal line.
// The input CSVs are never modified; full data stays outside git.
func BuildBinary(cfg BuildConfig) (Metadata, error) {
	started := time.Now()
	meta := Metadata{Version: 1, DatasetPath: cfg.DatasetPath, Dimensions: Dim, Features: append([]string(nil), Names...),
		Note: "Modelo experimental de LINEAS presupuestarias, no perfiles de municipalidades. Estandarización global y clip-z +/-5 solo al entrenar."}
	if len(cfg.Inputs) == 0 {
		return meta, fmt.Errorf("falta -inputs")
	}
	if cfg.Limit < 0 {
		return meta, fmt.Errorf("limit debe ser >=0")
	}
	if err := os.MkdirAll(filepath.Dir(cfg.DatasetPath), 0755); err != nil {
		return meta, err
	}
	tmp := cfg.DatasetPath + ".tmp"
	f, err := os.Create(tmp)
	if err != nil {
		return meta, err
	}
	cleanup := func(e error) (Metadata, error) { f.Close(); os.Remove(tmp); return meta, e }
	writer := bufio.NewWriterSize(f, 4<<20)
	var accum moments
	var buffer [RecordBytes]byte
	for _, path := range cfg.Inputs {
		input, err := os.Open(path)
		if err != nil {
			return cleanup(err)
		}
		r := csv.NewReader(bufio.NewReaderSize(input, 4<<20))
		r.FieldsPerRecord = -1
		r.ReuseRecord = true
		header, err := r.Read()
		if err != nil {
			input.Close()
			return cleanup(fmt.Errorf("%s: %w", path, err))
		}
		idx := map[string]int{}
		for i, col := range header {
			idx[strings.TrimSpace(strings.TrimPrefix(col, "\ufeff"))] = i
		}
		required := append([]string{"NIVEL_GOBIERNO", "TIPO_ACT_PROY", "MONTO_PIA", "MONTO_PIM", "MONTO_DEVENGADO_ANUAL"}, months...)
		for _, key := range required {
			if _, ok := idx[key]; !ok {
				input.Close()
				return cleanup(fmt.Errorf("%s: falta columna %s", path, key))
			}
		}
		src := SourceInfo{Path: path}
		for {
			row, e := r.Read()
			if e == io.EOF {
				break
			}
			if e != nil {
				input.Close()
				return cleanup(fmt.Errorf("%s fila %d: %w", path, src.AllRows+2, e))
			}
			src.AllRows++
			if len(row) != len(header) {
				input.Close()
				return cleanup(fmt.Errorf("%s fila %d: %d columnas, se esperaban %d", path, src.AllRows+1, len(row), len(header)))
			}
			if strings.TrimSpace(row[idx["NIVEL_GOBIERNO"]]) != "M" {
				continue
			}
			src.MunicipalRows++
			if strings.EqualFold(strings.TrimSpace(row[idx["TIPO_ACT_PROY"]]), "PROYECTO") {
				src.ProjectRows++
			}
			x, err := Extract(row, idx)
			if err != nil {
				input.Close()
				return cleanup(fmt.Errorf("%s fila %d: %w", path, src.AllRows+1, err))
			}
			accum.add(x)
			for i, v := range x {
				binary.LittleEndian.PutUint64(buffer[i*8:(i+1)*8], math.Float64bits(v))
			}
			if _, err = writer.Write(buffer[:]); err != nil {
				input.Close()
				return cleanup(err)
			}
			meta.Rows++
			if cfg.Limit > 0 && meta.Rows >= cfg.Limit {
				break
			}
		}
		if err = input.Close(); err != nil {
			return cleanup(err)
		}
		meta.Sources = append(meta.Sources, src)
		if cfg.Limit > 0 && meta.Rows >= cfg.Limit {
			break
		}
	}
	if meta.Rows == 0 {
		return cleanup(fmt.Errorf("ninguna línea municipal válida"))
	}
	if cfg.ExpectRows > 0 && meta.Rows != cfg.ExpectRows {
		return cleanup(fmt.Errorf("cantidad municipal %d, esperadas %d", meta.Rows, cfg.ExpectRows))
	}
	if err = writer.Flush(); err != nil {
		return cleanup(err)
	}
	if err = f.Sync(); err != nil {
		return cleanup(err)
	}
	if err = f.Close(); err != nil {
		os.Remove(tmp)
		return meta, err
	}
	if err = os.Remove(cfg.DatasetPath); err != nil && !os.IsNotExist(err) {
		return meta, err
	}
	if err = os.Rename(tmp, cfg.DatasetPath); err != nil {
		return meta, err
	}
	for i := 0; i < Dim; i++ {
		meta.Mean = append(meta.Mean, accum.mean[i])
		std := math.Sqrt(accum.m2[i] / float64(meta.Rows))
		if std < 1e-12 {
			std = 1
		} // constant feature: remains centered at zero
		meta.Std = append(meta.Std, std)
	}
	meta.DurationMS = time.Since(started).Milliseconds()
	if err = writeJSON(cfg.MetadataPath, meta); err != nil {
		return meta, err
	}
	return meta, nil
}

func ReadMetadata(path string) (Metadata, error) {
	var meta Metadata
	f, err := os.Open(path)
	if err != nil {
		return meta, err
	}
	defer f.Close()
	if err = json.NewDecoder(f).Decode(&meta); err != nil {
		return meta, err
	}
	if meta.Version != 1 || meta.Dimensions != Dim || len(meta.Mean) != Dim || len(meta.Std) != Dim || len(meta.Features) != Dim || meta.Rows < 1 {
		return meta, fmt.Errorf("metadata incompatible con dimensiones/versiones actuales")
	}
	for i := 0; i < Dim; i++ {
		if meta.Features[i] != Names[i] || math.IsNaN(meta.Mean[i]) || math.IsInf(meta.Mean[i], 0) || meta.Std[i] <= 0 || math.IsNaN(meta.Std[i]) || math.IsInf(meta.Std[i], 0) {
			return meta, fmt.Errorf("parámetros inválidos para %s", Names[i])
		}
	}
	stat, err := os.Stat(meta.DatasetPath)
	if err != nil {
		return meta, err
	}
	if stat.Size() != meta.Rows*RecordBytes {
		return meta, fmt.Errorf("tamaño binario inconsistente: %d bytes vs %d", stat.Size(), meta.Rows*RecordBytes)
	}
	return meta, nil
}
