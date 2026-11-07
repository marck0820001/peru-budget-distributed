// Package kmeans implementa K-Means secuencial y paralelo (MapReduce).
//
// Esquema por iteración (igual al planteado en el enunciado del curso):
//
//	MAP    : cada worker recibe los centroides globales (copia de solo lectura),
//	         asigna cada punto de SU partición al centroide más cercano y
//	         acumula sumas parciales, conteos e inercia.
//	REDUCE : el coordinador suma los parciales EN ORDEN DE PARTICIÓN y
//	         recalcula los centroides. Repite hasta converger.
//
// Ningún worker escribe en memoria compartida salvo en su propio rango de
// etiquetas (índices disjuntos), por lo que no hay condiciones de carrera ni
// candados en el bucle caliente. La interfaz ShardWorker permite que en la
// PC4 el mismo coordinador hable con nodos remotos por TCP enviando Partial.
package kmeansmr

import (
	"errors"
	"math"
	"math/rand"
	"time"
)

// Options parametriza el entrenamiento.
type Options struct {
	K       int
	MaxIter int
	Tol     float64 // desplazamiento máximo de centroides para declarar convergencia
	Seed    int64
	Workers int // solo para Parallel
}

// IterStat registra la convergencia de cada iteración.
type IterStat struct {
	Iter     int     `json:"iter"`
	Inertia  float64 `json:"inertia"`
	Changed  int     `json:"changed"`
	MaxShift float64 `json:"max_shift"`
}

// Model es el resultado de un entrenamiento.
type Model struct {
	K          int         `json:"k"`
	Centroids  [][]float64 `json:"centroids"`
	Labels     []int       `json:"-"`
	Sizes      []int       `json:"sizes"`
	Inertia    float64     `json:"inertia"`
	Iterations int         `json:"iterations"`
	Converged  bool        `json:"converged"`
	Workers    int         `json:"workers"`
	ElapsedSec float64     `json:"elapsed_sec"`
	History    []IterStat  `json:"history"`
}

// Partial es la respuesta de un worker en una iteración (fase map). Tiene
// etiquetas JSON porque es el mensaje que viajará por TCP en la PC4.
type Partial struct {
	Shard   int         `json:"shard"`
	Sums    [][]float64 `json:"sums"`
	Counts  []int       `json:"counts"`
	Inertia float64     `json:"inertia"`
	Changed int         `json:"changed"`
	FarIdx  int         `json:"far_idx"` // punto más lejano a su centroide (para clusters vacíos)
	FarDist float64     `json:"far_dist"`
}

func sqDist(a, b []float64) float64 {
	var s float64
	for i := range a {
		d := a[i] - b[i]
		s += d * d
	}
	return s
}

func nearest(x []float64, cents [][]float64) (int, float64) {
	best, bd := 0, math.Inf(1)
	for c, ct := range cents {
		if d := sqDist(x, ct); d < bd {
			best, bd = c, d
		}
	}
	return best, bd
}

func validate(X [][]float64, o *Options) error {
	if len(X) == 0 {
		return errors.New("matriz vacía")
	}
	if o.K < 1 || o.K > len(X) {
		return errors.New("K fuera de rango")
	}
	if o.MaxIter <= 0 {
		o.MaxIter = 300
	}
	if o.Tol <= 0 {
		o.Tol = 1e-6
	}
	return nil
}

// InitPlusPlus elige centroides iniciales con k-means++ (determinista por semilla).
// Ambas versiones (secuencial y paralela) parten de los mismos centroides.
func InitPlusPlus(X [][]float64, k int, seed int64) [][]float64 {
	rng := rand.New(rand.NewSource(seed))
	cents := make([][]float64, 0, k)
	cents = append(cents, clone(X[rng.Intn(len(X))]))
	d2 := make([]float64, len(X))
	for i, x := range X {
		d2[i] = sqDist(x, cents[0])
	}
	for len(cents) < k {
		var total float64
		for _, d := range d2 {
			total += d
		}
		var idx int
		if total == 0 {
			idx = rng.Intn(len(X))
		} else {
			r := rng.Float64() * total
			for i, d := range d2 {
				r -= d
				if r <= 0 {
					idx = i
					break
				}
			}
		}
		c := clone(X[idx])
		cents = append(cents, c)
		for i, x := range X {
			if d := sqDist(x, c); d < d2[i] {
				d2[i] = d
			}
		}
	}
	return cents
}

func clone(v []float64) []float64 { return append([]float64(nil), v...) }

// assignRange es el "map" de una partición [lo,hi): asigna puntos y acumula.
// labels se escribe solo en [lo,hi), región exclusiva del worker.
func assignRange(X [][]float64, lo, hi int, cents [][]float64, labels []int, shard int) Partial {
	k, dim := len(cents), len(cents[0])
	p := Partial{Shard: shard, Sums: make([][]float64, k), Counts: make([]int, k), FarIdx: -1, FarDist: -1}
	for c := range p.Sums {
		p.Sums[c] = make([]float64, dim)
	}
	for i := lo; i < hi; i++ {
		c, d := nearest(X[i], cents)
		if labels[i] != c {
			p.Changed++
			labels[i] = c
		}
		p.Counts[c]++
		s := p.Sums[c]
		for j, v := range X[i] {
			s[j] += v
		}
		p.Inertia += d
		if d > p.FarDist {
			p.FarIdx, p.FarDist = i, d
		}
	}
	return p
}

// reduce combina parciales (ya ordenados por shard) y produce nuevos centroides.
// Un cluster vacío se reubica en el punto más lejano global (determinista).
func reduce(X [][]float64, parts []Partial, old [][]float64) (cents [][]float64, sizes []int, inertia float64, changed int, shift float64) {
	k, dim := len(old), len(old[0])
	sums := make([][]float64, k)
	for c := range sums {
		sums[c] = make([]float64, dim)
	}
	sizes = make([]int, k)
	farIdx, farDist := -1, -1.0
	for _, p := range parts {
		for c := 0; c < k; c++ {
			sizes[c] += p.Counts[c]
			for j := 0; j < dim; j++ {
				sums[c][j] += p.Sums[c][j]
			}
		}
		inertia += p.Inertia
		changed += p.Changed
		if p.FarDist > farDist {
			farIdx, farDist = p.FarIdx, p.FarDist
		}
	}
	cents = make([][]float64, k)
	for c := 0; c < k; c++ {
		if sizes[c] == 0 {
			if farIdx >= 0 {
				cents[c] = clone(X[farIdx])
				farDist = -1
			} else {
				cents[c] = clone(old[c])
			}
		} else {
			cents[c] = make([]float64, dim)
			for j := range cents[c] {
				cents[c][j] = sums[c][j] / float64(sizes[c])
			}
		}
		if s := math.Sqrt(sqDist(cents[c], old[c])); s > shift {
			shift = s
		}
	}
	return
}

// Sequential entrena en un solo hilo (línea base para medir el speedup).
func Sequential(X [][]float64, o Options) (*Model, error) {
	if err := validate(X, &o); err != nil {
		return nil, err
	}
	start := time.Now()
	cents := InitPlusPlus(X, o.K, o.Seed)
	labels := make([]int, len(X))
	for i := range labels {
		labels[i] = -1
	}
	m := &Model{K: o.K, Workers: 1}
	for it := 1; it <= o.MaxIter; it++ {
		p := assignRange(X, 0, len(X), cents, labels, 0)
		nc, sizes, inertia, changed, shift := reduce(X, []Partial{p}, cents)
		m.History = append(m.History, IterStat{Iter: it, Inertia: inertia, Changed: changed, MaxShift: shift})
		cents, m.Sizes, m.Iterations = nc, sizes, it
		if changed == 0 || shift < o.Tol {
			m.Converged = true
			break
		}
	}
	finalize(X, m, cents, labels)
	m.ElapsedSec = time.Since(start).Seconds()
	return m, nil
}

// finalize recalcula etiquetas e inercia con los centroides definitivos.
func finalize(X [][]float64, m *Model, cents [][]float64, labels []int) {
	m.Centroids = cents
	m.Sizes = make([]int, len(cents))
	m.Inertia = 0
	for i, x := range X {
		c, d := nearest(x, cents)
		labels[i] = c
		m.Sizes[c]++
		m.Inertia += d
	}
	m.Labels = labels
}
