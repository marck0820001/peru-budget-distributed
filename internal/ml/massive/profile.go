package massive

import (
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"sync"
	"time"
)

// ClusterProfile summarizes the ORIGINAL nine line-level features. The three
// signed_log_* columns are log-transformed amounts, NOT monetary sums in soles.
type ClusterProfile struct {
	Cluster          int       `json:"cluster"`
	Rows             int64     `json:"rows"`
	SharePct         float64   `json:"share_pct"`
	MeanOriginal     []float64 `json:"mean_original_features"`
	MeanClippedZ     []float64 `json:"mean_clipped_z_features"`
	Inertia          float64   `json:"inertia"`
	CentroidDeltaMax float64   `json:"max_abs_delta_mean_z_vs_centroid"`
}

type ProfileResult struct {
	Rows               int64            `json:"rows"`
	Features           []string         `json:"features"`
	K                  int              `json:"k"`
	Workers            int              `json:"workers"`
	Seed               int64            `json:"seed"`
	ClusterProfiles    []ClusterProfile `json:"clusters"`
	Inertia            float64          `json:"inertia"`
	MaxCentroidDelta   float64          `json:"max_centroid_delta"`
	DurationMS         int64            `json:"duration_ms"`
	InterpretationNote string           `json:"interpretation_note"`
}

// ReadTrainReport reads a K-Means report written by SaveReport.
func ReadTrainReport(path string) (TrainResult, error) {
	var t TrainResult
	file, err := os.Open(path)
	if err != nil {
		return t, err
	}
	defer file.Close()
	if err := json.NewDecoder(file).Decode(&t); err != nil {
		return t, err
	}
	return t, nil
}

type profilePartial struct {
	id      int
	counts  []int64
	rawSums [][]float64
	zSums   [][]float64
	inertia []float64
	err     error
}

func newProfilePartial(id, k int) profilePartial {
	p := profilePartial{id: id, counts: make([]int64, k), rawSums: make([][]float64, k), zSums: make([][]float64, k), inertia: make([]float64, k)}
	for c := 0; c < k; c++ {
		p.rawSums[c] = make([]float64, Dim)
		p.zSums[c] = make([]float64, Dim)
	}
	return p
}

func profileWorker(f *os.File, meta Metadata, train TrainResult, batchRows int, id int, begin, end int64) profilePartial {
	p := newProfilePartial(id, train.K)
	buffer := make([]byte, batchRows*RecordBytes)
	for pos := begin; pos < end; {
		take := batchRows
		if int64(take) > end-pos {
			take = int(end - pos)
		}
		want := take * RecordBytes
		n, err := f.ReadAt(buffer[:want], pos*RecordBytes)
		if (err != nil && err != io.EOF) || n != want {
			p.err = fmt.Errorf("worker=%d fila=%d bytes=%d/%d err=%v", id, pos, n, want, err)
			return p
		}
		for i := 0; i < take; i++ {
			raw := decode(buffer[i*RecordBytes : (i+1)*RecordBytes])
			z := normalize(raw, meta, train.ClipZ)
			cluster, d := closestCenter(z, train.Centroids)
			p.counts[cluster]++
			p.inertia[cluster] += d
			for j := 0; j < Dim; j++ {
				p.rawSums[cluster][j] += raw[j]
				p.zSums[cluster][j] += z[j]
			}
		}
		pos += int64(take)
	}
	return p
}

// ProfileAll streams the complete binary, assigns each line to its nearest FINAL
// centroid and computes observed group means. It neither modifies the training
// model nor creates millions of per-row assignments. Worker partitions do not overlap.
func ProfileAll(meta Metadata, train TrainResult, workers, batchRows int) (ProfileResult, error) {
	started := time.Now()
	result := ProfileResult{Rows: meta.Rows, Features: append([]string(nil), meta.Features...), K: train.K, Workers: workers, Seed: train.Seed,
		InterpretationNote: "Líneas presupuestarias, NO municipalidades. Los promedios de tasa y Q4 son por línea y NO equivalen a ejecución consolidada. Los importes signed_log_* siguen transformados; los flags se interpretan como proporciones."}
	if workers < 1 || batchRows < 1 || batchRows > 1<<19 {
		return result, fmt.Errorf("workers y batchRows fuera de rango")
	}
	if train.Rows != meta.Rows || train.K < 2 || train.K != len(train.Centroids) || len(train.Features) != Dim || len(train.ClusterSizes) != train.K ||
		math.IsNaN(train.ClipZ) || math.IsInf(train.ClipZ, 0) || train.ClipZ <= 0 {
		return result, fmt.Errorf("reporte de entrenamiento incompatible")
	}
	for j, name := range Names {
		if train.Features[j] != name || meta.Features[j] != name {
			return result, fmt.Errorf("orden de variables incompatible: %s", name)
		}
	}
	for c, center := range train.Centroids {
		if len(center) != Dim {
			return result, fmt.Errorf("centroide %d con dimensión incorrecta", c)
		}
		for _, v := range center {
			if math.IsNaN(v) || math.IsInf(v, 0) {
				return result, fmt.Errorf("centroide no finito")
			}
		}
	}
	file, err := os.Open(meta.DatasetPath)
	if err != nil {
		return result, err
	}
	defer file.Close()
	stat, err := file.Stat()
	if err != nil {
		return result, err
	}
	if stat.Size() != meta.Rows*RecordBytes {
		return result, fmt.Errorf("binario truncado o dimensión incorrecta")
	}
	if int64(workers) > meta.Rows {
		workers = int(meta.Rows)
	}
	result.Workers = workers
	parts := make([]profilePartial, workers)
	if workers == 1 {
		parts[0] = profileWorker(file, meta, train, batchRows, 0, 0, meta.Rows)
	} else {
		ch := make(chan profilePartial, workers)
		var wg sync.WaitGroup
		for id := 0; id < workers; id++ {
			start, end := int64(id)*meta.Rows/int64(workers), int64(id+1)*meta.Rows/int64(workers)
			wg.Add(1)
			go func(id int, a, b int64) { defer wg.Done(); ch <- profileWorker(file, meta, train, batchRows, id, a, b) }(id, start, end)
		}
		wg.Wait()
		close(ch)
		for p := range ch {
			parts[p.id] = p
		}
	}
	combined := newProfilePartial(-1, train.K)
	for _, p := range parts {
		if p.err != nil {
			return result, p.err
		}
		for c := 0; c < train.K; c++ {
			combined.counts[c] += p.counts[c]
			combined.inertia[c] += p.inertia[c]
			for j := 0; j < Dim; j++ {
				combined.rawSums[c][j] += p.rawSums[c][j]
				combined.zSums[c][j] += p.zSums[c][j]
			}
		}
	}
	var counted int64
	for c := 0; c < train.K; c++ {
		n := combined.counts[c]
		counted += n
		if n != train.ClusterSizes[c] {
			return result, fmt.Errorf("grupo %d: %d filas al perfilar vs %d en entrenamiento", c, n, train.ClusterSizes[c])
		}
		r := ClusterProfile{Cluster: c, Rows: n, SharePct: 100 * float64(n) / float64(meta.Rows),
			MeanOriginal: make([]float64, Dim), MeanClippedZ: make([]float64, Dim), Inertia: combined.inertia[c]}
		if n > 0 {
			for j := 0; j < Dim; j++ {
				r.MeanOriginal[j] = combined.rawSums[c][j] / float64(n)
				r.MeanClippedZ[j] = combined.zSums[c][j] / float64(n)
				delta := math.Abs(r.MeanClippedZ[j] - train.Centroids[c][j])
				if delta > r.CentroidDeltaMax {
					r.CentroidDeltaMax = delta
				}
			}
		}
		if r.CentroidDeltaMax > result.MaxCentroidDelta {
			result.MaxCentroidDelta = r.CentroidDeltaMax
		}
		result.ClusterProfiles = append(result.ClusterProfiles, r)
		result.Inertia += r.Inertia
	}
	if counted != meta.Rows {
		return result, fmt.Errorf("filas asignadas %d vs %d", counted, meta.Rows)
	}
	// Small floating-point differences from associativity are expected.
	tolerance := 1e-7 * math.Max(1, math.Abs(train.Inertia))
	if math.Abs(result.Inertia-train.Inertia) > tolerance {
		return result, fmt.Errorf("inercia recalculada %.9f difiere del entrenamiento %.9f", result.Inertia, train.Inertia)
	}
	result.DurationMS = time.Since(started).Milliseconds()
	return result, nil
}
