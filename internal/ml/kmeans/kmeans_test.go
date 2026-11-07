package kmeans

import (
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func mockRows() [][]float64 {
	return [][]float64{{0, 0}, {0.3, 0.2}, {-0.2, 0.1}, {10, 10}, {10.2, 9.8}, {9.7, 10.1}, {20, -3}, {19.7, -3.2}, {20.1, -2.8}}
}
func TestSequentialAndParallelSame(t *testing.T) {
	data := mockRows()
	a, e := Train(data, Options{K: 3, Workers: 1, MaxIterations: 80, Tolerance: 1e-8, Seed: 42})
	if e != nil {
		t.Fatal(e)
	}
	for _, workers := range []int{2, 4, 8} {
		b, e := Train(data, Options{K: 3, Workers: workers, MaxIterations: 80, Tolerance: 1e-8, Seed: 42})
		if e != nil {
			t.Fatal(e)
		}
		if math.Abs(a.Inertia-b.Inertia) > 1e-8 {
			t.Fatalf("inertia 1 vs %d: %.12f vs %.12f", workers, a.Inertia, b.Inertia)
		}
		for i := range a.Assignments {
			if a.Assignments[i] != b.Assignments[i] {
				t.Fatalf("asignación diferente %d", i)
			}
		}
	}
	if len(a.ClusterSizes) != 3 {
		t.Fatalf("clusters=%v", a.ClusterSizes)
	}
}
func TestBadRowsFail(t *testing.T) {
	_, err := Train([][]float64{{1, 2}, {1}}, Options{K: 2, Workers: 1, MaxIterations: 10})
	if err == nil {
		t.Fatal("esperaba error de dimensión")
	}
	_, err = Train([][]float64{{1, math.NaN()}, {3, 4}}, Options{K: 2, Workers: 1, MaxIterations: 10})
	if err == nil {
		t.Fatal("esperaba error NaN")
	}
}
func TestMatrixHeaderAndKeys(t *testing.T) {
	dir := t.TempDir()
	matrixPath := filepath.Join(dir, "matrix.csv")
	keysPath := filepath.Join(dir, "keys.csv")
	input := strings.Join(ExpectedFeatures, ",") + "\n1,2,3,4,5,6\n7,8,9,10,11,12\n"
	if err := os.WriteFile(matrixPath, []byte(input), 0600); err != nil {
		t.Fatal(err)
	}
	keys := "ano_eje,sec_ejec,departamento,ejecutora_nombre,tipo_entidad\n2024,300001,LIMA,Municipalidad A,municipalidad\n2025,300001,LIMA,Municipalidad A,municipalidad\n"
	if err := os.WriteFile(keysPath, []byte(keys), 0600); err != nil {
		t.Fatal(err)
	}
	data, e := ReadMatrix(matrixPath)
	if e != nil {
		t.Fatal(e)
	}
	if len(data) != 2 || len(data[0]) != 6 {
		t.Fatal("matriz no coincide")
	}
	ks, e := ReadKeys(keysPath, len(data))
	if e != nil {
		t.Fatal(e)
	}
	if len(ks) != 2 {
		t.Fatal("claves no coinciden")
	}
}
func TestSilhouetteIsFinite(t *testing.T) {
	a, e := Train(mockRows(), Options{K: 3, Workers: 2, MaxIterations: 30, Tolerance: 1e-8, Seed: 42})
	if e != nil {
		t.Fatal(e)
	}
	x := SampleSilhouette(mockRows(), a.Assignments, 3, 9, 9, 42)
	if math.IsNaN(x) || x < -1 || x > 1 {
		t.Fatalf("silueta inválida %v", x)
	}
}
