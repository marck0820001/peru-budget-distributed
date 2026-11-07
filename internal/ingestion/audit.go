// Package ingestion provides a bounded-memory concurrent auditor for MEF CSVs.
package ingestion

import (
	"encoding/csv"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

type Totals struct {
	Path                 string `json:"path"`
	RowsRead             int64  `json:"rows_read"`
	LocalRows            int64  `json:"local_rows"`
	AcceptedLocalRows    int64  `json:"accepted_local_rows"`
	ProjectLocalRows     int64  `json:"project_local_rows"`
	InvalidWidth         int64  `json:"invalid_width"`
	InvalidLocalAmounts  int64  `json:"invalid_local_amounts"`
	PIACents             int64  `json:"pia_cents"`
	PIMCents             int64  `json:"pim_cents"`
	DevCents             int64  `json:"dev_cents"`
	DurationMilliseconds int64  `json:"duration_ms"`
}

type task struct{ kind, pia, pim, dev string }

// parseCents rejects ambiguous comma-grouped numbers and any fractional amount
// whose significant precision exceeds two decimals, as in the Python ETL.
func ParseCents(input string) (int64, error) {
	s := strings.TrimSpace(strings.TrimPrefix(strings.TrimPrefix(strings.TrimSpace(input), "S/"), "$"))
	if s == "" {
		return 0, fmt.Errorf("monto vacío")
	}
	if strings.Contains(s, ",") {
		return 0, fmt.Errorf("formato ambiguo: %q", s)
	}
	sign := int64(1)
	if strings.HasPrefix(s, "-") {
		sign = -1
		s = s[1:]
	} else if strings.HasPrefix(s, "+") {
		s = s[1:]
	}
	parts := strings.Split(s, ".")
	if len(parts) > 2 || len(parts) == 0 {
		return 0, fmt.Errorf("monto inválido")
	}
	whole := parts[0]
	if whole == "" {
		whole = "0"
	}
	value, err := strconv.ParseInt(whole, 10, 64)
	if err != nil {
		return 0, err
	}
	fraction := ""
	if len(parts) == 2 {
		fraction = parts[1]
	}
	if len(fraction) > 2 {
		if strings.Trim(fraction[2:], "0") != "" {
			return 0, fmt.Errorf("más de dos decimales: %q", input)
		}
		fraction = fraction[:2]
	}
	for len(fraction) < 2 {
		fraction += "0"
	}
	cents, err := strconv.ParseInt(fraction, 10, 64)
	if err != nil {
		return 0, err
	}
	if value > (int64(^uint64(0)>>1)-cents)/100 {
		return 0, fmt.Errorf("desbordamiento")
	}
	return sign * (value*100 + cents), nil
}

func AuditFile(path string, workers int) (Totals, error) {
	started := time.Now()
	out := Totals{Path: path}
	if workers < 1 {
		return out, fmt.Errorf("workers debe ser >=1")
	}
	f, err := os.Open(path)
	if err != nil {
		return out, err
	}
	defer f.Close()
	reader := csv.NewReader(f)
	reader.FieldsPerRecord = -1
	header, err := reader.Read()
	if err != nil {
		return out, err
	}
	index := map[string]int{}
	for i, s := range header {
		index[strings.TrimPrefix(s, "\ufeff")] = i
	}
	required := []string{"NIVEL_GOBIERNO", "TIPO_ACT_PROY", "MONTO_PIA", "MONTO_PIM", "MONTO_DEVENGADO_ANUAL"}
	for _, name := range required {
		if _, ok := index[name]; !ok {
			return out, fmt.Errorf("falta columna %s", name)
		}
	}
	tasks := make(chan task, workers*32)
	parts := make(chan Totals, workers)
	var wg sync.WaitGroup
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			p := Totals{}
			for item := range tasks {
				pia, e1 := ParseCents(item.pia)
				pim, e2 := ParseCents(item.pim)
				dev, e3 := ParseCents(item.dev)
				if e1 != nil || e2 != nil || e3 != nil {
					p.InvalidLocalAmounts++
					continue
				}
				p.AcceptedLocalRows++
				p.PIACents += pia
				p.PIMCents += pim
				p.DevCents += dev
				if strings.EqualFold(strings.TrimSpace(item.kind), "PROYECTO") {
					p.ProjectLocalRows++
				}
			}
			parts <- p
		}()
	}
	for {
		row, e := reader.Read()
		if e == io.EOF {
			break
		}
		if e != nil {
			close(tasks)
			wg.Wait()
			close(parts)
			return out, e
		}
		out.RowsRead++
		if len(row) != len(header) {
			out.InvalidWidth++
			continue
		}
		if strings.TrimSpace(row[index["NIVEL_GOBIERNO"]]) != "M" {
			continue
		}
		out.LocalRows++
		tasks <- task{row[index["TIPO_ACT_PROY"]], row[index["MONTO_PIA"]], row[index["MONTO_PIM"]], row[index["MONTO_DEVENGADO_ANUAL"]]}
	}
	close(tasks)
	wg.Wait()
	close(parts)
	for p := range parts {
		out.AcceptedLocalRows += p.AcceptedLocalRows
		out.ProjectLocalRows += p.ProjectLocalRows
		out.InvalidLocalAmounts += p.InvalidLocalAmounts
		out.PIACents += p.PIACents
		out.PIMCents += p.PIMCents
		out.DevCents += p.DevCents
	}
	out.DurationMilliseconds = time.Since(started).Milliseconds()
	return out, nil
}
