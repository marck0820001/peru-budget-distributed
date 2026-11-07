package ingestion

import (
	"bufio"
	"bytes"
	"encoding/csv"
	"errors"
	"io"
)

// Chunk es un bloque de registros CSV completos (texto crudo) que un worker
// parsea de forma independiente. FirstRow es el número de fila del primer
// registro en el archivo (el encabezado es la fila 1), igual que en Python.
type Chunk struct {
	ID       int
	FirstRow int64
	Records  int
	Data     []byte
}

// ReadHeader lee y parsea la primera línea del archivo (encabezado).
func ReadHeader(br *bufio.Reader) ([]string, error) {
	line, err := readRecord(br)
	if len(line) == 0 && err != nil {
		if errors.Is(err, io.EOF) {
			return nil, errors.New("CSV vacío")
		}
		return nil, err
	}
	r := csv.NewReader(bytes.NewReader(line))
	r.FieldsPerRecord = -1
	return r.Read()
}

// readRecord devuelve un registro CSV completo. Si un campo entrecomillado
// contiene saltos de línea, sigue leyendo hasta cerrar las comillas, para que
// ningún registro quede partido entre dos bloques.
func readRecord(br *bufio.Reader) ([]byte, error) {
	var rec []byte
	open := false
	for {
		part, err := br.ReadSlice('\n')
		if errors.Is(err, bufio.ErrBufferFull) {
			rec = append(rec, part...)
			open = quoteParity(part, open)
			continue
		}
		rec = append(rec, part...)
		open = quoteParity(part, open)
		if err != nil {
			return rec, err
		}
		if !open {
			return rec, nil
		}
	}
}

// quoteParity alterna el estado "dentro de comillas" por cada '"' del texto.
// Las comillas escapadas ("") se cancelan entre sí, por lo que el resultado es correcto.
func quoteParity(b []byte, open bool) bool {
	if bytes.Count(b, []byte{'"'})%2 == 1 {
		return !open
	}
	return open
}

// Split lee el resto del archivo y emite bloques de hasta chunkRecords
// registros por el canal out. Es el único goroutine que toca el disco:
// los workers solo reciben bytes, así la lectura secuencial del archivo
// se solapa con el parseo paralelo (patrón pipeline con backpressure,
// porque el canal tiene capacidad acotada).
func Split(br *bufio.Reader, chunkRecords int, out chan<- Chunk, stop <-chan struct{}) (records int64, err error) {
	defer close(out)
	id := 0
	row := int64(2)
	buf := make([]byte, 0, chunkRecords*512)
	n := 0
	first := row
	flush := func() bool {
		if n == 0 {
			return true
		}
		c := Chunk{ID: id, FirstRow: first, Records: n, Data: buf}
		select {
		case out <- c:
		case <-stop:
			return false
		}
		id++
		buf = make([]byte, 0, cap(buf))
		n = 0
		first = row
		return true
	}
	for {
		rec, rerr := readRecord(br)
		if len(bytes.TrimSpace(rec)) > 0 {
			buf = append(buf, rec...)
			if rec[len(rec)-1] != '\n' {
				buf = append(buf, '\n')
			}
			n++
			row++
			records++
			if n >= chunkRecords && !flush() {
				return records, errors.New("cancelado")
			}
		}
		if rerr != nil {
			if errors.Is(rerr, io.EOF) {
				flush()
				return records, nil
			}
			return records, rerr
		}
	}
}
