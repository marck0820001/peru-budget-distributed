package kmeansmr

import (
	"runtime"
	"time"
)

// ShardWorker procesa una partición fija de datos. Step recibe los centroides
// de la iteración y devuelve el parcial. En PC3 la implementación es un
// goroutine local; en PC4 será un nodo remoto que recibe/responde por TCP.
type ShardWorker interface {
	Step(centroids [][]float64) <-chan Partial
	Close()
}

// localWorker es un goroutine de larga vida dueño de la partición [lo,hi).
// Se comunica con el coordinador solo por canales: recibe centroides por
// tasks y devuelve el parcial por un canal de respuesta.
type localWorker struct {
	tasks chan task
}

type task struct {
	cents [][]float64
	reply chan Partial
}

func newLocalWorker(X [][]float64, lo, hi, shard int, labels []int) *localWorker {
	w := &localWorker{tasks: make(chan task)}
	go func() {
		for t := range w.tasks {
			t.reply <- assignRange(X, lo, hi, t.cents, labels, shard)
		}
	}()
	return w
}

func (w *localWorker) Step(cents [][]float64) <-chan Partial {
	reply := make(chan Partial, 1)
	w.tasks <- task{cents: cents, reply: reply}
	return reply
}

func (w *localWorker) Close() { close(w.tasks) }

// Partition divide n filas en p rangos contiguos de tamaño casi igual.
func Partition(n, p int) [][2]int {
	if p > n {
		p = n
	}
	out := make([][2]int, p)
	base, extra := n/p, n%p
	lo := 0
	for i := 0; i < p; i++ {
		sz := base
		if i < extra {
			sz++
		}
		out[i] = [2]int{lo, lo + sz}
		lo += sz
	}
	return out
}

// Parallel entrena K-Means con o.Workers goroutines (patrón MapReduce).
func Parallel(X [][]float64, o Options) (*Model, error) {
	if err := validate(X, &o); err != nil {
		return nil, err
	}
	if o.Workers <= 0 {
		o.Workers = runtime.NumCPU()
	}
	start := time.Now()
	labels := make([]int, len(X))
	for i := range labels {
		labels[i] = -1
	}
	ranges := Partition(len(X), o.Workers)
	workers := make([]ShardWorker, len(ranges))
	for s, r := range ranges {
		workers[s] = newLocalWorker(X, r[0], r[1], s, labels)
	}
	defer func() {
		for _, w := range workers {
			w.Close()
		}
	}()
	m, cents := Coordinate(X, workers, o)
	m.Workers = len(workers)
	finalize(X, m, cents, labels)
	m.ElapsedSec = time.Since(start).Seconds()
	return m, nil
}

// Coordinate es el bucle del coordinador: difunde centroides (broadcast),
// espera a todos los workers (barrera) y reduce. Es independiente de si los
// workers son goroutines o nodos TCP.
func Coordinate(X [][]float64, workers []ShardWorker, o Options) (*Model, [][]float64) {
	cents := InitPlusPlus(X, o.K, o.Seed)
	m := &Model{K: o.K}
	replies := make([]<-chan Partial, len(workers))
	parts := make([]Partial, len(workers))
	for it := 1; it <= o.MaxIter; it++ {
		snapshot := make([][]float64, len(cents)) // copia inmutable compartida de solo lectura
		for c := range cents {
			snapshot[c] = clone(cents[c])
		}
		for s, w := range workers { // fan-out
			replies[s] = w.Step(snapshot)
		}
		for s := range workers { // fan-in + barrera: espera a TODOS antes de reducir
			parts[s] = <-replies[s]
		}
		nc, sizes, inertia, changed, shift := reduce(X, parts, cents)
		m.History = append(m.History, IterStat{Iter: it, Inertia: inertia, Changed: changed, MaxShift: shift})
		cents, m.Sizes, m.Iterations = nc, sizes, it
		if changed == 0 || shift < o.Tol {
			m.Converged = true
			break
		}
	}
	return m, cents
}
