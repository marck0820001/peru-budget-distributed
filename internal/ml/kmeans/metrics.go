package kmeans

import (
	"math"
	"math/rand"
)

// SampleSilhouette estimates silhouette on a random subset of anchors, against
// at most maxReference randomly selected reference observations. It is NOT the
// exact silhouette of a multi-million-row dataset.
func SampleSilhouette(data [][]float64, labels []int, k, anchors, maxReference int, seed int64) float64 {
	if len(data) < 3 || anchors <= 0 {
		return math.NaN()
	}
	n := len(data)
	rng := rand.New(rand.NewSource(seed))
	shuffled := rng.Perm(n)
	if anchors > n {
		anchors = n
	}
	if maxReference > n {
		maxReference = n
	}
	if maxReference < anchors {
		maxReference = anchors
	}
	reference := shuffled[:maxReference]
	counts := make([]int, k)
	for _, j := range reference {
		counts[labels[j]]++
	}
	score := 0.0
	used := 0
	for _, i := range shuffled[:anchors] {
		sums := make([]float64, k)
		ns := make([]int, k)
		for _, j := range reference {
			if i == j {
				continue
			}
			c := labels[j]
			sums[c] += math.Sqrt(squared(data[i], data[j]))
			ns[c]++
		}
		own := labels[i]
		if ns[own] == 0 {
			continue
		}
		a := sums[own] / float64(ns[own])
		b := math.Inf(1)
		for c := 0; c < k; c++ {
			if c != own && ns[c] > 0 {
				avg := sums[c] / float64(ns[c])
				if avg < b {
					b = avg
				}
			}
		}
		if math.IsInf(b, 1) {
			continue
		}
		denom := math.Max(a, b)
		if denom == 0 {
			continue
		}
		score += (b - a) / denom
		used++
	}
	if used == 0 {
		return math.NaN()
	}
	return score / float64(used)
}
