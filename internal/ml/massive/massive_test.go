package massive

import (
	"encoding/csv"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strconv"
	"testing"
)

func fixture(t *testing.T, n int) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "gasto_mef_sample.csv")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	w := csv.NewWriter(f)
	header := []string{"ANO_EJE", "NIVEL_GOBIERNO", "TIPO_ACT_PROY", "MONTO_PIA", "MONTO_PIM", "MONTO_DEVENGADO_ANUAL"}
	header = append(header, months...)
	if err = w.Write(header); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < n; i++ {
		kind := "ACTIVIDAD"
		if i%3 == 0 {
			kind = "PROYECTO"
		}
		pim := float64(100 + (i%101)*8)
		dev := 0.0
		if i%4 != 0 {
			dev = pim * (0.25 + float64(i%3)*0.25)
		}
		if i%11 == 0 {
			pim = 0
		}
		pia := pim * 0.8
		if i%19 == 0 {
			pia = 0
		}
		if i%23 == 0 {
			dev = -4.50
		} // accounting adjustment, not invalid
		r := []string{"2024", "M", kind,
			strconv.FormatFloat(pia, 'f', 2, 64), strconv.FormatFloat(pim, 'f', 2, 64), strconv.FormatFloat(dev, 'f', 2, 64)}
		for m := 0; m < 12; m++ {
			amount := 0.0
			if m == 9 {
				amount = dev
			}
			if i%5 == 0 && m == 0 {
				amount = 0.01
			} // monthly sum need not equal annual in test
			r = append(r, fmt.Sprintf("%.2f", amount))
		}
		if err = w.Write(r); err != nil {
			t.Fatal(err)
		}
	}
	// Non-local row must be ignored.
	other := []string{"2024", "R", "ACTIVIDAD", "0", "100", "50"}
	for i := 0; i < 12; i++ {
		other = append(other, "0")
	}
	if err = w.Write(other); err != nil {
		t.Fatal(err)
	}
	w.Flush()
	if err = w.Error(); err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestBuildAndValidateMetadata(t *testing.T) {
	source := fixture(t, 125)
	root := t.TempDir()
	bin := filepath.Join(root, "records.f64")
	metaPath := filepath.Join(root, "meta.json")
	meta, err := BuildBinary(BuildConfig{Inputs: []string{source}, DatasetPath: bin, MetadataPath: metaPath, ExpectRows: 125})
	if err != nil {
		t.Fatal(err)
	}
	if meta.Rows != 125 || len(meta.Sources) != 1 || meta.Sources[0].AllRows != 126 || meta.Sources[0].MunicipalRows != 125 || meta.Sources[0].ProjectRows != 42 {
		t.Fatalf("conteos incorrectos: %+v", meta)
	}
	loaded, err := ReadMetadata(metaPath)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < Dim; i++ {
		if math.IsNaN(loaded.Mean[i]) || math.IsInf(loaded.Mean[i], 0) || loaded.Std[i] <= 0 {
			t.Fatalf("estadísticos inválidos, col %d", i)
		}
	}
	stat, err := os.Stat(bin)
	if err != nil {
		t.Fatal(err)
	}
	if stat.Size() != 125*RecordBytes {
		t.Fatalf("tamaño erróneo: %d", stat.Size())
	}
	if _, err = BuildBinary(BuildConfig{Inputs: []string{source}, DatasetPath: bin, MetadataPath: metaPath, ExpectRows: 126}); err == nil {
		t.Fatal("esperaba error ante discrepancia de filas")
	}
}

func TestSequentialParallelAgreement(t *testing.T) {
	source := fixture(t, 311)
	root := t.TempDir()
	dataset := filepath.Join(root, "records.f64")
	metadata := filepath.Join(root, "meta.json")
	meta, err := BuildBinary(BuildConfig{Inputs: []string{source}, DatasetPath: dataset, MetadataPath: metadata})
	if err != nil {
		t.Fatal(err)
	}
	opt := TrainConfig{K: 3, Workers: 1, MaxIterations: 30, Tolerance: 1e-6, Seed: 42, InitSample: 110, BatchRows: 13, ClipZ: 5}
	sequential, err := Train(meta, opt)
	if err != nil {
		t.Fatal(err)
	}
	opt.Workers = 4
	parallel, err := Train(meta, opt)
	if err != nil {
		t.Fatal(err)
	}
	if sequential.Iterations != parallel.Iterations {
		t.Fatalf("iteraciones diferentes: %d y %d", sequential.Iterations, parallel.Iterations)
	}
	if math.Abs(sequential.Inertia-parallel.Inertia) > 1e-7*math.Max(1, sequential.Inertia) {
		t.Fatalf("inercia sec=%.12f par=%.12f", sequential.Inertia, parallel.Inertia)
	}
	var total int64
	for _, size := range parallel.ClusterSizes {
		total += size
	}
	if total != meta.Rows {
		t.Fatalf("cluster sizes suman %d vs %d", total, meta.Rows)
	}
}

func TestInvalidSourceRejected(t *testing.T) {
	root := t.TempDir()
	path := filepath.Join(root, "bad.csv")
	header := "ANO_EJE,NIVEL_GOBIERNO,TIPO_ACT_PROY,MONTO_PIA,MONTO_PIM,MONTO_DEVENGADO_ANUAL,"
	for i, month := range months {
		if i > 0 {
			header += ","
		}
		header += month
	}
	bad := "2024,M,PROYECTO,0,NaN,300"
	for i := 0; i < 12; i++ {
		bad += ",0"
	}
	if err := os.WriteFile(path, []byte(header+"\n"+bad+"\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := BuildBinary(BuildConfig{Inputs: []string{path}, DatasetPath: filepath.Join(root, "out.bin"), MetadataPath: filepath.Join(root, "m.json")}); err == nil {
		t.Fatal("el preprocesamiento debió rechazar NaN")
	}
}
func TestCheckBinaryLength(t *testing.T) {
	source := fixture(t, 12)
	root := t.TempDir()
	binaryPath := filepath.Join(root, "data.f64")
	metadataPath := filepath.Join(root, "data.json")
	_, err := BuildBinary(BuildConfig{Inputs: []string{source}, DatasetPath: binaryPath, MetadataPath: metadataPath})
	if err != nil {
		t.Fatal(err)
	}
	if err = os.Truncate(binaryPath, RecordBytes*11); err != nil {
		t.Fatal(err)
	}
	if _, err = ReadMetadata(metadataPath); err == nil {
		t.Fatal("archivo incompleto no detectado")
	}
}
