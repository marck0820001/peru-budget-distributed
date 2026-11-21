package massive

import (
	"encoding/binary"
	"encoding/json"
	"math"
	"net"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"
)

func TestDistributedTCPMatchesLocal(t *testing.T) {
	dir := t.TempDir()
	binaryPath := filepath.Join(dir, "data.f64")
	metadataPath := filepath.Join(dir, "meta.json")
	file, err := os.Create(binaryPath)
	if err != nil {
		t.Fatal(err)
	}
	const n = 240
	var buf [RecordBytes]byte
	for i := 0; i < n; i++ {
		for d := 0; d < Dim; d++ {
			v := float64((i*7+d*3)%37)/10 + float64(i%3)*5
			binary.LittleEndian.PutUint64(buf[d*8:], math.Float64bits(v))
		}
		if _, err := file.Write(buf[:]); err != nil {
			t.Fatal(err)
		}
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	mean, std := make([]float64, Dim), make([]float64, Dim)
	for i := range std {
		std[i] = 1
	}
	meta := Metadata{Version: 1, Rows: n, Dimensions: Dim, Features: append([]string(nil), Names...), Mean: mean, Std: std, DatasetPath: "windows\\path\\not_in_container.f64"}
	b, _ := json.Marshal(meta)
	if err := os.WriteFile(metadataPath, b, 0600); err != nil {
		t.Fatal(err)
	}
	m, err := OpenPortableMetadata(metadataPath, binaryPath)
	if err != nil {
		t.Fatal(err)
	}
	cfg := TrainConfig{K: 3, Workers: 2, MaxIterations: 25, Tolerance: 1e-4, Seed: 42, InitSample: 100, BatchRows: 32, ClipZ: 5}
	local, err := Train(m, cfg)
	if err != nil {
		t.Fatal(err)
	}
	listeners := make([]net.Listener, 2)
	var wg sync.WaitGroup
	for i := range listeners {
		ln, e := net.Listen("tcp", "127.0.0.1:0")
		if e != nil {
			t.Fatal(e)
		}
		listeners[i] = ln
		wg.Add(1)
		go func(i int) { defer wg.Done(); _ = ServeShardTCP(listeners[i], m, "node-"+string(rune('a'+i))) }(i)
	}
	t.Cleanup(func() {
		for _, ln := range listeners {
			_ = ln.Close()
		}
		wg.Wait()
	})
	got, err := DistributedTrain(m, cfg, []string{listeners[0].Addr().String(), listeners[1].Addr().String()}, 10*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	if local.Iterations != got.Iterations || local.Converged != got.Converged {
		t.Fatalf("iterations: local=%d, dist=%d", local.Iterations, got.Iterations)
	}
	for i := range local.ClusterSizes {
		if local.ClusterSizes[i] != got.ClusterSizes[i] {
			t.Fatalf("cluster %d: local=%d dist=%d", i, local.ClusterSizes[i], got.ClusterSizes[i])
		}
	}
	if math.Abs(local.Inertia-got.Inertia) > 1e-6 {
		t.Fatalf("inertia local=%v dist=%v", local.Inertia, got.Inertia)
	}
	for k := range local.Centroids {
		for j := range local.Centroids[k] {
			if math.Abs(local.Centroids[k][j]-got.Centroids[k][j]) > 1e-8 {
				t.Fatalf("centroid mismatch k=%d j=%d", k, j)
			}
		}
	}
	bad := ProcessShard(m, "x", ShardTask{Version: ProtocolVersion, Signature: "wrong", Start: 0, End: n, Centers: local.Centroids, BatchRows: 32, ClipZ: 5})
	if bad.Error == "" {
		t.Fatal("must reject mismatch metadata signature")
	}
}
