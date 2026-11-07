package massive

import (
	"encoding/binary"
	"fmt"
	"io"
	"math"
	"math/rand"
	"os"
	"sync"
	"time"
)

type TrainConfig struct {
	K             int
	Workers       int
	MaxIterations int
	Tolerance     float64
	Seed          int64
	InitSample    int // approximate K-Means++ initialization from a uniform sample
	BatchRows     int
	ClipZ         float64
}

type Step struct {
	Iteration           int     `json:"iteration"`
	InertiaBeforeUpdate float64 `json:"inertia_before_update"`
	MaxShift            float64 `json:"max_centroid_shift"`
	EmptyClusters       int     `json:"empty_clusters"`
}

type TrainResult struct {
	Rows         int64       `json:"rows"`
	Features     []string    `json:"features"`
	K            int         `json:"k"`
	Workers      int         `json:"workers"`
	Seed         int64       `json:"seed"`
	ClipZ        float64     `json:"clip_z"`
	InitSample   int         `json:"initialization_sample"`
	Centroids    [][]float64 `json:"centroids_scaled"`
	ClusterSizes []int64     `json:"cluster_sizes"`
	Inertia      float64     `json:"inertia"`
	Iterations   int         `json:"iterations"`
	Converged    bool        `json:"converged"`
	DurationMS   int64       `json:"training_duration_ms"`
	History      []Step      `json:"history"`
	Note         string      `json:"note"`
}

func normalize(values [Dim]float64, meta Metadata, clip float64) [Dim]float64 {
	for i := 0; i < Dim; i++ {
		values[i] = clamp((values[i]-meta.Mean[i])/meta.Std[i], -clip, clip)
	}
	return values
}
func sqDist(a [Dim]float64, b []float64) float64 {
	sum := 0.0
	for j := 0; j < Dim; j++ {
		d := a[j] - b[j]
		sum += d * d
	}
	return sum
}
func closestCenter(x [Dim]float64, centers [][]float64) (int, float64) {
	index := 0
	min := sqDist(x, centers[0])
	for i := 1; i < len(centers); i++ {
		v := sqDist(x, centers[i])
		if v < min {
			index, min = i, v
		}
	}
	return index, min
}
func decode(buf []byte) [Dim]float64 {
	var x [Dim]float64
	for i := 0; i < Dim; i++ {
		x[i] = math.Float64frombits(binary.LittleEndian.Uint64(buf[i*8:]))
	}
	return x
}

// initSample draws a deterministic uniform reservoir sample from all rows.
// K-Means++ is then applied to this sample, not to the entire 3.64M rows.
// All subsequent Lloyd iterations do process every original observation.
func initSample(f *os.File, meta Metadata, amount int, seed int64, clip float64) ([][Dim]float64, error) {
	if amount > int(meta.Rows) {
		amount = int(meta.Rows)
	}
	if amount < 2 {
		return nil, fmt.Errorf("muestra de inicialización insuficiente")
	}
	rng := rand.New(rand.NewSource(seed))
	sample := make([][Dim]float64, 0, amount)
	const batch = 4096
	buffer := make([]byte, batch*RecordBytes)
	var n int64
	for n < meta.Rows {
		take := batch
		if int64(take) > meta.Rows-n {
			take = int(meta.Rows - n)
		}
		size := take * RecordBytes
		read, e := f.ReadAt(buffer[:size], n*RecordBytes)
		if e != nil && e != io.EOF {
			return nil, e
		}
		if read != size {
			return nil, fmt.Errorf("archivo truncado en fila %d", n)
		}
		for i := 0; i < take; i++ {
			point := normalize(decode(buffer[i*RecordBytes:(i+1)*RecordBytes]), meta, clip)
			n++
			if len(sample) < amount {
				sample = append(sample, point)
			} else {
				j := rng.Int63n(n)
				if j < int64(amount) {
					sample[j] = point
				}
			}
		}
	}
	return sample, nil
}

func plusPlus(sample [][Dim]float64, k int, seed int64) [][]float64 {
	rng := rand.New(rand.NewSource(seed))
	center := make([][]float64, 0, k)
	first := rng.Intn(len(sample))
	center = append(center, append([]float64(nil), sample[first][:]...))
	nearest := make([]float64, len(sample))
	chosen := make([]bool, len(sample))
	chosen[first] = true
	for len(center) < k {
		total := 0.0
		last := center[len(center)-1]
		for i, p := range sample {
			if chosen[i] {
				nearest[i] = 0
				continue
			}
			d := sqDist(p, last)
			if len(center) == 1 || d < nearest[i] {
				nearest[i] = d
			}
			total += nearest[i]
		}
		index := -1
		if total > 0 {
			r := rng.Float64() * total
			for i, d := range nearest {
				if !chosen[i] {
					r -= d
					if r <= 0 {
						index = i
						break
					}
				}
			}
		}
		if index < 0 {
			for i := range sample {
				if !chosen[i] {
					index = i
					break
				}
			}
		}
		if index < 0 {
			break
		}
		chosen[index] = true
		center = append(center, append([]float64(nil), sample[index][:]...))
	}
	return center
}

type partial struct {
	id      int
	counts  []int64
	sums    [][]float64
	inertia float64
	err     error
}

func makePartial(id, k int) partial {
	p := partial{id: id, counts: make([]int64, k), sums: make([][]float64, k)}
	for i := 0; i < k; i++ {
		p.sums[i] = make([]float64, Dim)
	}
	return p
}

// One partition per worker, each backed by an independent ReadAt region.
// Communication is limited to one partial per worker and iteration.
func scanWorker(f *os.File, meta Metadata, centers [][]float64, cfg TrainConfig, id, start, end int64) partial {
	p := makePartial(int(id), len(centers))
	buffer := make([]byte, cfg.BatchRows*RecordBytes)
	for pos := start; pos < end; {
		take := cfg.BatchRows
		if int64(take) > end-pos {
			take = int(end - pos)
		}
		nBytes := take * RecordBytes
		n, e := f.ReadAt(buffer[:nBytes], pos*RecordBytes)
		if (e != nil && e != io.EOF) || n != nBytes {
			p.err = fmt.Errorf("worker %d: lectura %d: %d bytes, err=%v", id, pos, n, e)
			return p
		}
		for i := 0; i < take; i++ {
			x := normalize(decode(buffer[i*RecordBytes:(i+1)*RecordBytes]), meta, cfg.ClipZ)
			c, d := closestCenter(x, centers)
			p.counts[c]++
			p.inertia += d
			for j, v := range x {
				p.sums[c][j] += v
			}
		}
		pos += int64(take)
	}
	return p
}

// scanParallel uses disjoint partitions and goroutines. No worker writes to
// another worker's partial state; the coordinator reduces in worker-ID order.
func scanParallel(f *os.File, meta Metadata, centers [][]float64, cfg TrainConfig) (partial, error) {
	workers := cfg.Workers
	if int64(workers) > meta.Rows {
		workers = int(meta.Rows)
	}
	parts := make([]partial, workers)
	if workers == 1 {
		parts[0] = scanWorker(f, meta, centers, cfg, 0, 0, meta.Rows)
	} else {
		ch := make(chan partial, workers)
		var wg sync.WaitGroup
		for w := 0; w < workers; w++ {
			begin, end := int64(w)*meta.Rows/int64(workers), int64(w+1)*meta.Rows/int64(workers)
			wg.Add(1)
			go func(id int, a, b int64) { defer wg.Done(); ch <- scanWorker(f, meta, centers, cfg, int64(id), a, b) }(w, begin, end)
		}
		wg.Wait()
		close(ch)
		for p := range ch {
			parts[p.id] = p
		}
	}
	combined := makePartial(-1, len(centers))
	for _, p := range parts {
		if p.err != nil {
			return combined, p.err
		}
		combined.inertia += p.inertia
		for c := range combined.counts {
			combined.counts[c] += p.counts[c]
			for j := 0; j < Dim; j++ {
				combined.sums[c][j] += p.sums[c][j]
			}
		}
	}
	return combined, nil
}

func Train(meta Metadata, cfg TrainConfig) (TrainResult, error) {
	started := time.Now()
	result := TrainResult{Rows: meta.Rows, Features: append([]string(nil), Names...), K: cfg.K, Workers: cfg.Workers, Seed: cfg.Seed,
		ClipZ: cfg.ClipZ, InitSample: cfg.InitSample,
		Note: "Modelo exploratorio sobre LINEAS presupuestarias (no municipios). K-Means++ aproximado sobre muestra uniforme; Lloyd y cálculo final de inercia sobre TODAS las filas. Silueta no estimada."}
	if cfg.Workers < 1 || cfg.K < 2 || cfg.MaxIterations < 1 || cfg.BatchRows < 1 || cfg.InitSample < cfg.K || cfg.InitSample < 2 ||
		math.IsNaN(cfg.ClipZ) || math.IsInf(cfg.ClipZ, 0) || cfg.ClipZ <= 0 ||
		math.IsNaN(cfg.Tolerance) || math.IsInf(cfg.Tolerance, 0) || cfg.Tolerance < 0 {
		return result, fmt.Errorf("parámetros de entrenamiento inválidos")
	}
	if meta.Rows < int64(cfg.K) {
		return result, fmt.Errorf("K mayor que número de filas")
	}
	f, err := os.Open(meta.DatasetPath)
	if err != nil {
		return result, err
	}
	defer f.Close()
	sample, err := initSample(f, meta, cfg.InitSample, cfg.Seed, cfg.ClipZ)
	if err != nil {
		return result, err
	}
	centers := plusPlus(sample, cfg.K, cfg.Seed+97)
	for iter := 1; iter <= cfg.MaxIterations; iter++ {
		partial, e := scanParallel(f, meta, centers, cfg)
		if e != nil {
			return result, e
		}
		next := make([][]float64, cfg.K)
		empty := 0
		for c := range next {
			next[c] = make([]float64, Dim)
			if partial.counts[c] > 0 {
				for j := 0; j < Dim; j++ {
					next[c][j] = partial.sums[c][j] / float64(partial.counts[c])
				}
			} else {
				// Choose the sample observation farthest from its nearest center.
				// This remains deterministic and avoids selecting a fabricated point.
				farthest := -1.0
				idx := 0
				for i, p := range sample {
					_, d := closestCenter(p, centers)
					if d > farthest {
						farthest = d
						idx = i
					}
				}
				copy(next[c], sample[idx][:])
				empty++
			}
		}
		maxShift := 0.0
		for c := range next {
			shift := 0.0
			for j := 0; j < Dim; j++ {
				d := next[c][j] - centers[c][j]
				shift += d * d
			}
			if math.Sqrt(shift) > maxShift {
				maxShift = math.Sqrt(shift)
			}
		}
		result.History = append(result.History, Step{Iteration: iter, InertiaBeforeUpdate: partial.inertia, MaxShift: maxShift, EmptyClusters: empty})
		centers = next
		result.Iterations = iter
		if empty == 0 && maxShift <= cfg.Tolerance {
			result.Converged = true
			break
		}
	}
	// The final extra scan is mandatory: report inertia and group sizes for
	// the FINAL centroid locations, rather than a stale pre-update state.
	last, e := scanParallel(f, meta, centers, cfg)
	if e != nil {
		return result, e
	}
	result.Centroids = centers
	result.ClusterSizes = last.counts
	result.Inertia = last.inertia
	result.DurationMS = time.Since(started).Milliseconds()
	return result, nil
}

func SaveReport(path string, report TrainResult) error { return writeJSON(path, report) }
