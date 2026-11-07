package kmeansmr

import (
	"fmt"
	"math"
	"math/rand"
	"testing"
)

func blobs(n, k, dim int, seed int64) [][]float64 {
	rng := rand.New(rand.NewSource(seed))
	centers := make([][]float64, k)
	for c := range centers {
		centers[c] = make([]float64, dim)
		for j := range centers[c] {
			centers[c][j] = float64(c*6) + rng.NormFloat64()
		}
	}
	X := make([][]float64, n)
	for i := range X {
		c := i % k
		X[i] = make([]float64, dim)
		for j := range X[i] {
			X[i][j] = centers[c][j] + rng.NormFloat64()*0.5
		}
	}
	return X
}

// El K-Means paralelo debe converger a la misma solución que el secuencial.
func TestParallelEqualsSequential(t *testing.T) {
	X := blobs(5000, 4, 6, 1)
	for _, w := range []int{1, 2, 3, 4, 8} {
		o := Options{K: 4, MaxIter: 100, Seed: 7, Workers: w}
		s, _ := Sequential(X, o)
		p, _ := Parallel(X, o)
		for i := range s.Labels {
			if s.Labels[i] != p.Labels[i] {
				t.Fatalf("workers=%d: etiqueta %d distinta", w, i)
			}
		}
		if math.Abs(s.Inertia-p.Inertia) > 1e-6*s.Inertia {
			t.Fatalf("workers=%d: inercia %f vs %f", w, s.Inertia, p.Inertia)
		}
	}
}

func TestRecoversBlobs(t *testing.T) {
	X := blobs(3000, 3, 4, 2)
	m, err := Parallel(X, Options{K: 3, Seed: 1, Workers: 4})
	if err != nil {
		t.Fatal(err)
	}
	if !m.Converged {
		t.Fatal("no convergió")
	}
	for _, s := range m.Sizes {
		if s != 1000 {
			t.Fatalf("tamaños %v, esperaba 1000 por cluster", m.Sizes)
		}
	}
	if sil := Silhouette(X, m.Labels, 3, 4, nil); sil < 0.7 {
		t.Fatalf("silueta baja: %f", sil)
	}
}

func TestPartition(t *testing.T) {
	r := Partition(10, 3)
	if len(r) != 3 || r[0] != [2]int{0, 4} || r[2] != [2]int{7, 10} {
		t.Fatalf("particiones %v", r)
	}
	if len(Partition(2, 8)) != 2 {
		t.Fatal("no debe crear particiones vacías")
	}
}

func TestDetectAnomalies(t *testing.T) {
	X := blobs(1000, 2, 3, 3)
	X = append(X, []float64{100, 100, 100})
	m, _ := Parallel(X, Options{K: 2, Seed: 1, Workers: 2})
	an, _ := DetectAnomalies(X, m.Labels, m.Centroids)
	if len(an) == 0 || an[0].Index != len(X)-1 {
		t.Fatalf("el punto extremo debía ser el atípico principal: %+v", an)
	}
}

func TestEmptyClusterReseed(t *testing.T) {
	X := [][]float64{{0}, {0}, {0}, {10}}
	m, err := Parallel(X, Options{K: 3, Seed: 1, Workers: 2})
	if err != nil {
		t.Fatal(err)
	}
	if len(m.Centroids) != 3 {
		t.Fatal("centroides faltantes")
	}
}

func BenchmarkKMeans(b *testing.B) {
	// Clusters solapados (ruido alto) para forzar muchas iteraciones: así se
	// mide el bucle MapReduce y no solo la inicialización k-means++.
	X := blobs(500000, 5, 6, 9)
	rng := rand.New(rand.NewSource(10))
	for _, x := range X {
		for j := range x {
			x[j] += rng.NormFloat64() * 4
		}
	}
	for _, w := range []int{0, 1, 2, 4, 8} {
		name := fmt.Sprintf("workers=%d", w)
		if w == 0 {
			name = "secuencial"
		}
		b.Run(name, func(b *testing.B) {
			for i := 0; i < b.N; i++ {
				o := Options{K: 5, MaxIter: 20, Tol: 1e-12, Seed: 3, Workers: w}
				if w == 0 {
					Sequential(X, o)
				} else {
					Parallel(X, o)
				}
			}
		})
	}
}
