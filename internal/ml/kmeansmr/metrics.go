package kmeansmr

import (
	"math"
	"sort"
	"sync"
)

// Silhouette calcula el coeficiente de silueta medio en paralelo. Cada
// goroutine procesa un rango de puntos y escribe en su propia posición del
// slice de resultados (sin candados). Costo O(n^2): para n grande pasar una
// muestra de índices en sample (nil = todos).
func Silhouette(X [][]float64, labels []int, k, workers int, sample []int) float64 {
	idx := sample
	if idx == nil {
		idx = make([]int, len(X))
		for i := range idx {
			idx[i] = i
		}
	}
	if workers <= 0 {
		workers = 1
	}
	sizes := make([]int, k)
	for _, l := range labels {
		sizes[l]++
	}
	partial := make([]float64, workers)
	var wg sync.WaitGroup
	for w, r := range Partition(len(idx), workers) {
		wg.Add(1)
		go func(w, lo, hi int) {
			defer wg.Done()
			sum := make([]float64, k)
			var acc float64
			for _, i := range idx[lo:hi] {
				for c := range sum {
					sum[c] = 0
				}
				for j, x := range X {
					if j != i {
						sum[labels[j]] += math.Sqrt(sqDist(X[i], x))
					}
				}
				own := labels[i]
				if sizes[own] <= 1 {
					continue // silueta 0 por convención
				}
				a := sum[own] / float64(sizes[own]-1)
				b := math.Inf(1)
				for c := 0; c < k; c++ {
					if c != own && sizes[c] > 0 {
						b = math.Min(b, sum[c]/float64(sizes[c]))
					}
				}
				if mx := math.Max(a, b); mx > 0 {
					acc += (b - a) / mx
				}
			}
			partial[w] = acc
		}(w, r[0], r[1])
	}
	wg.Wait()
	var total float64
	for _, v := range partial {
		total += v
	}
	return total / float64(len(idx))
}

// DaviesBouldin: menor es mejor (separación vs dispersión de clusters).
func DaviesBouldin(X [][]float64, labels []int, cents [][]float64) float64 {
	k := len(cents)
	scatter := make([]float64, k)
	n := make([]int, k)
	for i, x := range X {
		scatter[labels[i]] += math.Sqrt(sqDist(x, cents[labels[i]]))
		n[labels[i]]++
	}
	for c := range scatter {
		if n[c] > 0 {
			scatter[c] /= float64(n[c])
		}
	}
	var db float64
	for i := 0; i < k; i++ {
		worst := 0.0
		for j := 0; j < k; j++ {
			if i == j {
				continue
			}
			if d := math.Sqrt(sqDist(cents[i], cents[j])); d > 0 {
				worst = math.Max(worst, (scatter[i]+scatter[j])/d)
			}
		}
		db += worst
	}
	return db / float64(k)
}

// Anomaly es un perfil con distancia atípica a su centroide.
type Anomaly struct {
	Index     int
	Cluster   int
	Distance  float64
	Threshold float64
	Score     float64 // distancia / umbral (>1 = atípico); +Inf en micro-clusters
	Reason    string  // "distancia_atipica" o "micro_cluster"
}

// Distances devuelve la distancia euclidiana de cada punto a su centroide.
func Distances(X [][]float64, labels []int, cents [][]float64) []float64 {
	d := make([]float64, len(X))
	for i, x := range X {
		d[i] = math.Sqrt(sqDist(x, cents[labels[i]]))
	}
	return d
}

// DetectAnomalies marca puntos cuya distancia a su centroide supera
// Q3 + 1.5·IQR de las distancias DE SU PROPIO cluster (regla de Tukey).
// Los miembros de micro-clusters (menos de 4 perfiles) también se marcan:
// un grupo tan pequeño es en sí mismo un comportamiento aislado.
// Una desviación atípica es un aviso para revisión, no prueba de irregularidad.
func DetectAnomalies(X [][]float64, labels []int, cents [][]float64) ([]Anomaly, []float64) {
	dist := Distances(X, labels, cents)
	k := len(cents)
	byC := make([][]float64, k)
	for i, l := range labels {
		byC[l] = append(byC[l], dist[i])
	}
	thr := make([]float64, k)
	for c := range byC {
		v := append([]float64(nil), byC[c]...)
		if len(v) < 4 {
			thr[c] = 0 // micro-cluster
			continue
		}
		sort.Float64s(v)
		q1, q3 := quantile(v, 0.25), quantile(v, 0.75)
		thr[c] = q3 + 1.5*(q3-q1)
	}
	var out []Anomaly
	for i, l := range labels {
		switch {
		case thr[l] == 0 && len(byC[l]) < 4:
			out = append(out, Anomaly{Index: i, Cluster: l, Distance: dist[i], Score: math.Inf(1), Reason: "micro_cluster"})
		case dist[i] > thr[l]:
			out = append(out, Anomaly{Index: i, Cluster: l, Distance: dist[i], Threshold: thr[l], Score: dist[i] / thr[l], Reason: "distancia_atipica"})
		}
	}
	sort.Slice(out, func(a, b int) bool { return out[a].Score > out[b].Score })
	return out, thr
}

func quantile(sorted []float64, q float64) float64 {
	x := float64(len(sorted)-1) * q
	lo, hi := int(math.Floor(x)), int(math.Ceil(x))
	if lo == hi {
		return sorted[lo]
	}
	return sorted[lo]*(float64(hi)-x) + sorted[hi]*(x-float64(lo))
}
