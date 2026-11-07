package massive

import (
	"math"
	"os"
	"path/filepath"
	"testing"
)

func TestProfileAllMatchesTraining(t *testing.T) {
	source := fixture(t, 1257)
	folder := t.TempDir()
	path := filepath.Join(folder, "data.f64")
	mp := filepath.Join(folder, "meta.json")
	m, err := BuildBinary(BuildConfig{Inputs: []string{source}, DatasetPath: path, MetadataPath: mp, ExpectRows: 1257})
	if err != nil {
		t.Fatal(err)
	}
	opts := TrainConfig{K: 3, Workers: 4, MaxIterations: 30, Tolerance: 1e-4, Seed: 42, InitSample: 220, BatchRows: 23, ClipZ: 5}
	result, err := Train(m, opts)
	if err != nil {
		t.Fatal(err)
	}
	p1, err := ProfileAll(m, result, 1, 37)
	if err != nil {
		t.Fatal(err)
	}
	p4, err := ProfileAll(m, result, 4, 37)
	if err != nil {
		t.Fatal(err)
	}
	if len(p4.ClusterProfiles) != 3 || p4.Rows != 1257 {
		t.Fatalf("conteos generales inválidos: %+v", p4)
	}
	for c := 0; c < 3; c++ {
		if p1.ClusterProfiles[c].Rows != p4.ClusterProfiles[c].Rows || p4.ClusterProfiles[c].Rows != result.ClusterSizes[c] {
			t.Fatalf("diferencia de conteos en clúster %d", c)
		}
		for j := 0; j < Dim; j++ {
			if math.Abs(p1.ClusterProfiles[c].MeanOriginal[j]-p4.ClusterProfiles[c].MeanOriginal[j]) > 1e-10 {
				t.Fatalf("medias distintas para clúster %d, col %d", c, j)
			}
		}
	}
	if math.Abs(p4.Inertia-result.Inertia) > 1e-7 {
		t.Fatal("inercia distinta")
	}
}
func TestProfileRejectsCorruptReportAndBinary(t *testing.T) {
	source := fixture(t, 32)
	folder := t.TempDir()
	data := filepath.Join(folder, "data.f64")
	m, err := BuildBinary(BuildConfig{Inputs: []string{source}, DatasetPath: data, MetadataPath: filepath.Join(folder, "meta.json")})
	if err != nil {
		t.Fatal(err)
	}
	opt := TrainConfig{K: 2, Workers: 1, MaxIterations: 20, Tolerance: 1e-4, Seed: 9, InitSample: 20, BatchRows: 8, ClipZ: 5}
	result, err := Train(m, opt)
	if err != nil {
		t.Fatal(err)
	}
	bad := result
	bad.Rows++
	if _, err = ProfileAll(m, bad, 1, 8); err == nil {
		t.Fatal("debe rechazar conteo de filas distinto")
	}
	bad = result
	bad.ClusterSizes = append([]int64(nil), result.ClusterSizes...)
	bad.ClusterSizes[0]++
	if _, err = ProfileAll(m, bad, 1, 8); err == nil {
		t.Fatal("debe rechazar totales de cluster")
	}
	if err = os.Truncate(data, int64(31*RecordBytes)); err != nil {
		t.Fatal(err)
	}
	if _, err = ProfileAll(m, result, 1, 8); err == nil {
		t.Fatal("debe rechazar binario truncado")
	}
}
