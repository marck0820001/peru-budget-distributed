// Package kmeans implements deterministic K-Means++ initialization and Lloyd's
// algorithm with sequential or synchronous data-parallel assignment/reduction.
package kmeans

import (
	"errors"
	"fmt"
	"math"
	"math/rand"
	"sync"
	"time"
)

type Options struct {
	K             int
	Workers       int
	MaxIterations int
	Tolerance     float64
	Seed          int64
}

type Iteration struct {
	Number                int     `json:"iteration"`
	InertiaBeforeUpdate   float64 `json:"inertia_before_update"`
	MaxCentroidShift      float64 `json:"max_centroid_shift"`
	AssignmentChanges     int     `json:"assignment_changes"`
	ReinitializedClusters int     `json:"reinitialized_clusters"`
}

type Result struct {
	Centroids    [][]float64   `json:"centroids"`
	Assignments  []int         `json:"-"`
	Distances    []float64     `json:"-"`
	ClusterSizes []int         `json:"cluster_sizes"`
	Inertia      float64       `json:"inertia"`
	Iterations   int           `json:"iterations"`
	Converged    bool          `json:"converged"`
	History      []Iteration   `json:"history"`
	Duration     time.Duration `json:"-"`
}

func Validate(data [][]float64, opts Options) error {
	if len(data) == 0 {
		return errors.New("dataset vacío")
	}
	d := len(data[0])
	if d == 0 {
		return errors.New("filas sin variables")
	}
	for i, row := range data {
		if len(row) != d {
			return fmt.Errorf("fila %d: %d variables; se esperaban %d", i, len(row), d)
		}
		for j, v := range row {
			if math.IsNaN(v) || math.IsInf(v, 0) {
				return fmt.Errorf("valor no finito fila=%d columna=%d", i, j)
			}
		}
	}
	if opts.K < 2 || opts.K > len(data) {
		return fmt.Errorf("K debe estar entre 2 y %d", len(data))
	}
	if opts.Workers < 1 {
		return errors.New("workers debe ser >=1")
	}
	if opts.MaxIterations < 1 {
		return errors.New("max iterations debe ser >=1")
	}
	if opts.Tolerance < 0 || math.IsNaN(opts.Tolerance) || math.IsInf(opts.Tolerance, 0) {
		return errors.New("tolerancia inválida")
	}
	return nil
}

func squared(a, b []float64) float64 {
	var v float64
	for j := range a {
		delta := a[j] - b[j]
		v += delta * delta
	}
	return v
}

func closest(row []float64, centers [][]float64) (int, float64) {
	best := 0
	dist := squared(row, centers[0])
	for j := 1; j < len(centers); j++ {
		d := squared(row, centers[j])
		if d < dist {
			best, dist = j, d
		}
	}
	return best, dist
}

// initPlusPlus uses the same seed regardless of worker count.
func initPlusPlus(data [][]float64, k int, seed int64) [][]float64 {
	rng := rand.New(rand.NewSource(seed))
	n := len(data)
	centers := make([][]float64, 0, k)
	chosen := make([]bool, n)
	first := rng.Intn(n)
	chosen[first] = true
	centers = append(centers, append([]float64(nil), data[first]...))
	distances := make([]float64, n)
	for len(centers) < k {
		total := 0.0
		last := centers[len(centers)-1]
		for i, row := range data {
			if chosen[i] {
				distances[i] = 0
				continue
			}
			d := squared(row, last)
			if len(centers) == 1 || d < distances[i] {
				distances[i] = d
			}
			total += distances[i]
		}
		index := -1
		if total > 0 {
			target := rng.Float64() * total
			running := 0.0
			for i, dist := range distances {
				if chosen[i] {
					continue
				}
				running += dist
				if running >= target {
					index = i
					break
				}
			}
		}
		if index < 0 {
			for i := range data {
				if !chosen[i] {
					index = i
					break
				}
			}
		}
		chosen[index] = true
		centers = append(centers, append([]float64(nil), data[index]...))
	}
	return centers
}

type partial struct {
	id      int
	sums    [][]float64
	counts  []int
	inertia float64
	changes int
}

func newPartial(id, k, d int) partial {
	p := partial{id: id, counts: make([]int, k), sums: make([][]float64, k)}
	for j := 0; j < k; j++ {
		p.sums[j] = make([]float64, d)
	}
	return p
}

func evaluateChunk(data, centers [][]float64, assignments []int, dists []float64, start, end, id int) partial {
	k, d := len(centers), len(data[0])
	p := newPartial(id, k, d)
	for i := start; i < end; i++ {
		c, ds := closest(data[i], centers)
		if assignments[i] != c {
			p.changes++
		}
		assignments[i] = c
		dists[i] = ds
		p.counts[c]++
		p.inertia += ds
		for j, value := range data[i] {
			p.sums[c][j] += value
		}
	}
	return p
}

// Train shares immutable centroids per iteration, partitions observations among
// goroutines and reduces private partial sums in deterministic worker order.
// Each worker writes only to its disjoint assignment/distance segment.
func Train(data [][]float64, opts Options) (Result, error) {
	startTime := time.Now()
	if err := Validate(data, opts); err != nil {
		return Result{}, err
	}
	n, d := len(data), len(data[0])
	workers := opts.Workers
	if workers > n {
		workers = n
	}
	centers := initPlusPlus(data, opts.K, opts.Seed)
	assignments := make([]int, n)
	dists := make([]float64, n)
	for i := range assignments {
		assignments[i] = -1
	}
	result := Result{History: make([]Iteration, 0, opts.MaxIterations)}

	for iteration := 1; iteration <= opts.MaxIterations; iteration++ {
		parts := make([]partial, workers)
		if workers == 1 {
			parts[0] = evaluateChunk(data, centers, assignments, dists, 0, n, 0)
		} else {
			results := make(chan partial, workers)
			var wg sync.WaitGroup
			for w := 0; w < workers; w++ {
				from, to := w*n/workers, (w+1)*n/workers
				wg.Add(1)
				go func(id, a, b int) {
					defer wg.Done()
					results <- evaluateChunk(data, centers, assignments, dists, a, b, id)
				}(w, from, to)
			}
			wg.Wait()
			close(results)
			for p := range results {
				parts[p.id] = p
			}
		}
		totals := newPartial(-1, opts.K, d)
		for _, p := range parts { // deterministic reduction order
			totals.inertia += p.inertia
			totals.changes += p.changes
			for c := 0; c < opts.K; c++ {
				totals.counts[c] += p.counts[c]
				for j := 0; j < d; j++ {
					totals.sums[c][j] += p.sums[c][j]
				}
			}
		}
		next := make([][]float64, opts.K)
		for c := range next {
			next[c] = make([]float64, d)
			if totals.counts[c] > 0 {
				inv := 1 / float64(totals.counts[c])
				for j := 0; j < d; j++ {
					next[c][j] = totals.sums[c][j] * inv
				}
			}
		}
		// Empty clusters receive a deterministic farthest observation. Recheck
		// empties on the next iteration rather than pretending they disappeared.
		used := map[int]bool{}
		restarted := 0
		for c := range next {
			if totals.counts[c] != 0 {
				continue
			}
			farthest := -1
			maxD := -1.0
			for i, ds := range dists {
				if !used[i] && ds > maxD {
					farthest = i
					maxD = ds
				}
			}
			if farthest >= 0 {
				copy(next[c], data[farthest])
				used[farthest] = true
				restarted++
			}
		}
		maxShift := 0.0
		for c := range next {
			delta := math.Sqrt(squared(centers[c], next[c]))
			if delta > maxShift {
				maxShift = delta
			}
		}
		result.History = append(result.History, Iteration{
			Number: iteration, InertiaBeforeUpdate: totals.inertia,
			MaxCentroidShift: maxShift, AssignmentChanges: totals.changes,
			ReinitializedClusters: restarted,
		})
		centers = next
		result.Iterations = iteration
		if restarted == 0 && maxShift <= opts.Tolerance {
			result.Converged = true
			break
		}
	}
	// Reassign to FINAL centroids, so reported inertia/cluster sizes are valid.
	result.Centroids = centers
	result.Assignments = make([]int, n)
	result.Distances = make([]float64, n)
	result.ClusterSizes = make([]int, opts.K)
	for i, row := range data {
		c, dist := closest(row, centers)
		result.Assignments[i] = c
		result.Distances[i] = math.Sqrt(dist)
		result.ClusterSizes[c]++
		result.Inertia += dist
	}
	result.Duration = time.Since(startTime)
	return result, nil
}
