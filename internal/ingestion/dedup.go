package ingestion

import (
	"hash/fnv"
	"sync"
)

// dupShards define en cuántas particiones se divide el conjunto de huellas.
// Con 64 candados independientes, dos workers casi nunca compiten por el mismo.
const dupShards = 64

// DupDetector detecta registros municipales EXACTAMENTE repetidos entre todos
// los workers. Es el único estado compartido del cargador, por eso se protege
// con un sync.Mutex por partición (lock striping) en vez de un candado global.
type DupDetector struct {
	shards [dupShards]struct {
		mu  sync.Mutex
		set map[uint64]struct{}
	}
}

// NewDupDetector crea el detector con capacidad inicial para n huellas.
func NewDupDetector(n int) *DupDetector {
	d := &DupDetector{}
	for i := range d.shards {
		d.shards[i].set = make(map[uint64]struct{}, n/dupShards+1)
	}
	return d
}

// Fingerprint calcula una huella FNV-1a de 64 bits de todos los campos del registro.
func Fingerprint(rec []string) uint64 {
	h := fnv.New64a()
	for _, f := range rec {
		h.Write([]byte(f))
		h.Write([]byte{0x1f}) // separador de unidad: "a,b" != "ab,"
	}
	return h.Sum64()
}

// InsertBatch registra un lote de huellas y devuelve, para cada una, si ya
// existía (duplicado). Agrupa por partición para tomar cada candado una sola
// vez por lote: menos contención que bloquear por fila.
func (d *DupDetector) InsertBatch(fps []uint64) []bool {
	dup := make([]bool, len(fps))
	var byShard [dupShards][]int
	for i, fp := range fps {
		s := fp % dupShards
		byShard[s] = append(byShard[s], i)
	}
	for s := range byShard {
		if len(byShard[s]) == 0 {
			continue
		}
		sh := &d.shards[s]
		sh.mu.Lock()
		for _, i := range byShard[s] {
			if _, ok := sh.set[fps[i]]; ok {
				dup[i] = true
			} else {
				sh.set[fps[i]] = struct{}{}
			}
		}
		sh.mu.Unlock()
	}
	return dup
}
