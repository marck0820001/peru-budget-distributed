package massive

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"math"
	"net"
	"os"
	"sort"
	"sync"
	"time"
)

// The external protocol is intentionally minimal: a fixed shard of the
// preprocessed binary, common centroids and one reduced partial per round.
const ProtocolVersion = 1

type ShardTask struct {
	Version   int         `json:"version"`
	Signature string      `json:"metadata_signature"`
	Iteration int         `json:"iteration"`
	Start     int64       `json:"start"`
	End       int64       `json:"end"`
	Centers   [][]float64 `json:"centroids"`
	BatchRows int         `json:"batch_rows"`
	ClipZ     float64     `json:"clip_z"`
}

type ShardResult struct {
	Version   int         `json:"version"`
	NodeID    string      `json:"node_id"`
	Iteration int         `json:"iteration"`
	Start     int64       `json:"start"`
	End       int64       `json:"end"`
	Counts    []int64     `json:"counts"`
	Sums      [][]float64 `json:"sums"`
	Inertia   float64     `json:"inertia"`
	Error     string      `json:"error,omitempty"`
}

// OpenPortableMetadata fixes the Windows path stored in PC3 metadata when the
// exact same binary is mounted at /dataset/... inside Linux containers.
func OpenPortableMetadata(metadataPath, binaryPath string) (Metadata, error) {
	var m Metadata
	b, err := os.ReadFile(metadataPath)
	if err != nil {
		return m, err
	}
	if err = json.Unmarshal(b, &m); err != nil {
		return m, err
	}
	if m.Version != 1 || m.Rows < 1 || m.Dimensions != Dim || len(m.Features) != Dim || len(m.Mean) != Dim || len(m.Std) != Dim {
		return m, fmt.Errorf("metadatos incompatibles")
	}
	for i := 0; i < Dim; i++ {
		if m.Features[i] != Names[i] || math.IsNaN(m.Mean[i]) || math.IsInf(m.Mean[i], 0) ||
			math.IsNaN(m.Std[i]) || math.IsInf(m.Std[i], 0) || m.Std[i] <= 0 {
			return m, fmt.Errorf("estadistica inválida en feature %d", i)
		}
	}
	m.DatasetPath = binaryPath
	st, err := os.Stat(binaryPath)
	if err != nil {
		return m, err
	}
	if st.Size() != m.Rows*RecordBytes {
		return m, fmt.Errorf("binario incompatible: tamaño=%d, esperado=%d", st.Size(), m.Rows*RecordBytes)
	}
	return m, nil
}

func MetadataSignature(m Metadata) string {
	// Exclude the platform-specific path; require the statistical parameters,
	// feature order, version and row count to be identical on all machines.
	data, _ := json.Marshal(struct {
		Version  int       `json:"version"`
		Rows     int64     `json:"rows"`
		Features []string  `json:"features"`
		Mean     []float64 `json:"mean"`
		Std      []float64 `json:"std"`
	}{m.Version, m.Rows, m.Features, m.Mean, m.Std})
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func ProcessShard(m Metadata, nodeID string, task ShardTask) ShardResult {
	out := ShardResult{Version: ProtocolVersion, NodeID: nodeID, Iteration: task.Iteration,
		Start: task.Start, End: task.End}
	if task.Version != ProtocolVersion || task.Signature != MetadataSignature(m) {
		out.Error = "versión de protocolo o metadatos distintos"
		return out
	}
	if task.Start < 0 || task.End <= task.Start || task.End > m.Rows || task.BatchRows < 1 || task.BatchRows > 65536 ||
		math.IsNaN(task.ClipZ) || math.IsInf(task.ClipZ, 0) || task.ClipZ <= 0 || task.ClipZ > 100 ||
		len(task.Centers) < 2 || len(task.Centers) > 64 {
		out.Error = "rango o parámetros inválidos"
		return out
	}
	for _, center := range task.Centers {
		if len(center) != Dim {
			out.Error = "dimensión de centroides incorrecta"
			return out
		}
		for _, v := range center {
			if math.IsNaN(v) || math.IsInf(v, 0) {
				out.Error = "centroide no finito"
				return out
			}
		}
	}
	f, err := os.Open(m.DatasetPath)
	if err != nil {
		out.Error = err.Error()
		return out
	}
	defer f.Close()
	cfg := TrainConfig{BatchRows: task.BatchRows, ClipZ: task.ClipZ}
	p := scanWorker(f, m, task.Centers, cfg, 0, task.Start, task.End)
	if p.err != nil {
		out.Error = p.err.Error()
		return out
	}
	out.Counts = p.counts
	out.Sums = p.sums
	out.Inertia = p.inertia
	return out
}

func ServeShardTCP(listener net.Listener, m Metadata, nodeID string) error {
	for {
		conn, err := listener.Accept()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return nil
			}
			return err
		}
		go func(c net.Conn) {
			defer c.Close()
			_ = c.SetDeadline(time.Now().Add(5 * time.Minute))
			var task ShardTask
			if err := json.NewDecoder(io.LimitReader(c, 1<<20)).Decode(&task); err != nil {
				_ = json.NewEncoder(c).Encode(ShardResult{Version: ProtocolVersion, NodeID: nodeID, Error: "JSON inválido: " + err.Error()})
				return
			}
			started := time.Now()
			result := ProcessShard(m, nodeID, task)
			if result.Error == "" {
				log.Printf("TCP nodo=%s iter=%d shard=[%d,%d) filas=%d inercia=%.6f duracion=%s", nodeID, task.Iteration, task.Start, task.End, task.End-task.Start, result.Inertia, time.Since(started))
			}
			_ = json.NewEncoder(c).Encode(result)
		}(conn)
	}
}

func requestNode(address string, t ShardTask, timeout time.Duration) (ShardResult, error) {
	var r ShardResult
	conn, err := net.DialTimeout("tcp", address, timeout)
	if err != nil {
		return r, err
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(timeout))
	if err := json.NewEncoder(conn).Encode(t); err != nil {
		return r, err
	}
	if err := json.NewDecoder(io.LimitReader(conn, 1<<20)).Decode(&r); err != nil {
		return r, err
	}
	if r.Error != "" {
		return r, fmt.Errorf("nodo %s: %s", address, r.Error)
	}
	if r.Version != ProtocolVersion || r.Iteration != t.Iteration || r.Start != t.Start || r.End != t.End || r.NodeID == "" {
		return r, fmt.Errorf("respuesta inesperada de %s", address)
	}
	return r, nil
}

// RemoteScan divides the full binary into disjoint shards. Each node scans
// only its allocated interval. Results are reduced in stable node order.
func RemoteScan(m Metadata, centers [][]float64, cfg TrainConfig, addresses []string, iteration int, timeout time.Duration) (ShardResult, error) {
	combined := ShardResult{Counts: make([]int64, len(centers)), Sums: make([][]float64, len(centers))}
	for c := range combined.Sums {
		combined.Sums[c] = make([]float64, Dim)
	}
	if len(addresses) < 2 || int64(len(addresses)) > m.Rows {
		return combined, fmt.Errorf("se requieren al menos dos nodos, no más que filas")
	}
	pieces := make([]ShardResult, len(addresses))
	errorsByNode := make([]error, len(addresses))
	signature := MetadataSignature(m)
	var wg sync.WaitGroup
	for i, address := range addresses {
		start, end := int64(i)*m.Rows/int64(len(addresses)), int64(i+1)*m.Rows/int64(len(addresses))
		wg.Add(1)
		go func(i int, host string, start, end int64) {
			defer wg.Done()
			t := ShardTask{Version: ProtocolVersion, Signature: signature, Iteration: iteration,
				Start: start, End: end, Centers: centers, BatchRows: cfg.BatchRows, ClipZ: cfg.ClipZ}
			pieces[i], errorsByNode[i] = requestNode(host, t, timeout)
		}(i, address, start, end)
	}
	wg.Wait()
	totalRows := int64(0)
	uniqueNodes := map[string]struct{}{}
	for i, p := range pieces {
		if errorsByNode[i] != nil {
			return combined, fmt.Errorf("nodo %d (%s): %w", i, addresses[i], errorsByNode[i])
		}
		if _, ok := uniqueNodes[p.NodeID]; ok {
			return combined, fmt.Errorf("ID de nodo duplicado: %s", p.NodeID)
		}
		uniqueNodes[p.NodeID] = struct{}{}
		if len(p.Counts) != len(centers) || len(p.Sums) != len(centers) || math.IsNaN(p.Inertia) || math.IsInf(p.Inertia, 0) || p.Inertia < 0 {
			return combined, fmt.Errorf("parcial incompatible en %s", addresses[i])
		}
		var localRows int64
		for c, n := range p.Counts {
			if n < 0 || len(p.Sums[c]) != Dim {
				return combined, fmt.Errorf("conteos/dimensiones inválidos del nodo %d", i)
			}
			localRows += n
			combined.Counts[c] += n
			for j, v := range p.Sums[c] {
				if math.IsNaN(v) || math.IsInf(v, 0) {
					return combined, fmt.Errorf("sumas no finitas del nodo %d", i)
				}
				combined.Sums[c][j] += v
			}
		}
		if localRows != p.End-p.Start {
			return combined, fmt.Errorf("conteos no cuadran en nodo %d", i)
		}
		totalRows += localRows
		combined.Inertia += p.Inertia
	}
	if totalRows != m.Rows {
		return combined, fmt.Errorf("filas incompletas: %d vs %d", totalRows, m.Rows)
	}
	return combined, nil
}

// DistributedTrain preserves the PC3 K-Means++ initialization, Lloyd updates,
// empty-cluster policy and mandatory final scan; only the scan changes to TCP.
func DistributedTrain(m Metadata, cfg TrainConfig, nodes []string, timeout time.Duration) (TrainResult, error) {
	begin := time.Now()
	result := TrainResult{Rows: m.Rows, Features: append([]string(nil), Names...), K: cfg.K,
		Workers: len(nodes), Seed: cfg.Seed, ClipZ: cfg.ClipZ, InitSample: cfg.InitSample,
		Note: "Entrenamiento K-Means DISTRIBUIDO TCP con shards disjuntos. Igual inicialización K-Means++ que PC3. Resultados parciales sumados por coordinador."}
	if cfg.K < 2 || cfg.MaxIterations < 1 || cfg.BatchRows < 1 || cfg.InitSample < cfg.K || cfg.Tolerance < 0 ||
		cfg.ClipZ <= 0 || math.IsNaN(cfg.ClipZ) || math.IsInf(cfg.ClipZ, 0) || timeout <= 0 {
		return result, fmt.Errorf("parámetros de entrenamiento inválidos")
	}
	// Stable ordering also prevents accidental non-deterministic reductions.
	nodes = append([]string(nil), nodes...)
	sort.Strings(nodes)
	f, err := os.Open(m.DatasetPath)
	if err != nil {
		return result, err
	}
	sample, err := initSample(f, m, cfg.InitSample, cfg.Seed, cfg.ClipZ)
	_ = f.Close()
	if err != nil {
		return result, err
	}
	centers := plusPlus(sample, cfg.K, cfg.Seed+97)
	for iter := 1; iter <= cfg.MaxIterations; iter++ {
		parts, err := RemoteScan(m, centers, cfg, nodes, iter, timeout)
		if err != nil {
			return result, err
		}
		next := make([][]float64, cfg.K)
		empty := 0
		for c := range next {
			next[c] = make([]float64, Dim)
			if parts.Counts[c] > 0 {
				for j := 0; j < Dim; j++ {
					next[c][j] = parts.Sums[c][j] / float64(parts.Counts[c])
				}
			} else {
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
			var shift float64
			for j := 0; j < Dim; j++ {
				d := next[c][j] - centers[c][j]
				shift += d * d
			}
			if x := math.Sqrt(shift); x > maxShift {
				maxShift = x
			}
		}
		result.History = append(result.History, Step{Iteration: iter, InertiaBeforeUpdate: parts.Inertia, MaxShift: maxShift, EmptyClusters: empty})
		centers = next
		result.Iterations = iter
		if empty == 0 && maxShift <= cfg.Tolerance {
			result.Converged = true
			break
		}
	}
	final, err := RemoteScan(m, centers, cfg, nodes, result.Iterations+1, timeout)
	if err != nil {
		return result, err
	}
	result.Centroids = centers
	result.ClusterSizes = final.Counts
	result.Inertia = final.Inertia
	result.DurationMS = time.Since(begin).Milliseconds()
	return result, nil
}
