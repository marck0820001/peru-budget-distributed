package kmeans

import (
	"encoding/csv"
	"fmt"
	"io"
	"math"
	"os"
	"strconv"
	"strings"
)

var ExpectedFeatures = []string{
	"tasa_ejecucion", "modificacion_log_pim_pia", "participacion_devengado_proyectos",
	"concentracion_q4", "cv_devengado_mensual", "log1p_pim",
}

type Key struct{ Year, Entity, Department, Name, Type string }

func ReadMatrix(path string) ([][]float64, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	r := csv.NewReader(f)
	r.FieldsPerRecord = -1
	header, err := r.Read()
	if err != nil {
		return nil, err
	}
	if len(header) != len(ExpectedFeatures) {
		return nil, fmt.Errorf("matriz: se esperaban %d columnas, hay %d", len(ExpectedFeatures), len(header))
	}
	for i, h := range header {
		if strings.TrimPrefix(h, "\ufeff") != ExpectedFeatures[i] {
			return nil, fmt.Errorf("columna %d: %q; se esperaba %q", i, h, ExpectedFeatures[i])
		}
	}
	matrix := make([][]float64, 0, 4000)
	for {
		record, err := r.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		if len(record) != len(header) {
			return nil, fmt.Errorf("fila %d: número incorrecto de columnas", len(matrix)+2)
		}
		row := make([]float64, len(header))
		for j, s := range record {
			value, e := strconv.ParseFloat(strings.TrimSpace(s), 64)
			if e != nil || math.IsNaN(value) || math.IsInf(value, 0) {
				return nil, fmt.Errorf("fila %d, columna %d: valor inválido %q", len(matrix)+2, j, s)
			}
			row[j] = value
		}
		matrix = append(matrix, row)
	}
	if len(matrix) == 0 {
		return nil, fmt.Errorf("matriz sin registros")
	}
	return matrix, nil
}

func ReadKeys(path string, n int) ([]Key, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	r := csv.NewReader(f)
	header, err := r.Read()
	if err != nil {
		return nil, err
	}
	expected := []string{"ano_eje", "sec_ejec", "departamento", "ejecutora_nombre", "tipo_entidad"}
	if len(header) != len(expected) {
		return nil, fmt.Errorf("claves: número de columnas inesperado")
	}
	for i, h := range header {
		if strings.TrimPrefix(h, "\ufeff") != expected[i] {
			return nil, fmt.Errorf("cabecera de claves inválida en columna %d", i)
		}
	}
	keys := make([]Key, 0, n)
	seen := make(map[string]bool, n)
	for {
		rec, e := r.Read()
		if e == io.EOF {
			break
		}
		if e != nil {
			return nil, e
		}
		key := rec[0] + "|" + rec[1]
		if seen[key] {
			return nil, fmt.Errorf("clave duplicada: %s", key)
		}
		seen[key] = true
		keys = append(keys, Key{rec[0], rec[1], rec[2], rec[3], rec[4]})
	}
	if len(keys) != n {
		return nil, fmt.Errorf("claves (%d) no coinciden con filas de matriz (%d)", len(keys), n)
	}
	return keys, nil
}
