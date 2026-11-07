package preprocessing

import (
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/marck0820001/peru-budget-distributed.git/internal/domain"
)

// Index mapea el nombre de cada columna requerida a su posición en el CSV.
type Index struct {
	NCols                                        int
	anoEje, nivel, secEjec, ejecutora, depto     int
	tipo, producto, productoNom, pia, pim, anual int
	months                                       [12]int
}

// NewIndex valida el encabezado y resuelve posiciones. Ignora columnas vacías
// al final (algunos CSV del MEF terminan cada línea con comas sobrantes).
func NewIndex(header []string) (*Index, error) {
	pos := make(map[string]int, len(header))
	for i, h := range header {
		h = strings.TrimSpace(strings.TrimPrefix(h, "\ufeff"))
		if h == "" {
			continue
		}
		if _, dup := pos[h]; dup {
			return nil, fmt.Errorf("columna duplicada en encabezado: %s", h)
		}
		pos[h] = i
	}
	var missing []string
	for _, c := range domain.RequiredColumns() {
		if _, ok := pos[c]; !ok {
			missing = append(missing, c)
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		return nil, fmt.Errorf("faltan columnas: %v", missing)
	}
	ix := &Index{
		NCols: len(header), anoEje: pos[domain.ColAnoEje], nivel: pos[domain.ColNivelGobierno],
		secEjec: pos[domain.ColSecEjec], ejecutora: pos[domain.ColEjecutora],
		depto: pos[domain.ColDepartamento], tipo: pos[domain.ColTipoActProy],
		producto: pos[domain.ColProducto], productoNom: pos[domain.ColProductoNom],
		pia: pos[domain.ColPIA], pim: pos[domain.ColPIM], anual: pos[domain.ColDevAnual],
	}
	for m := 0; m < 12; m++ {
		ix.months[m] = pos[domain.MonthColumn(m)]
	}
	return ix, nil
}

// Outcome clasifica el resultado de validar un registro.
type Outcome uint8

const (
	Accepted  Outcome = iota // línea municipal válida, entra al agregado
	NonLocal                 // NIVEL_GOBIERNO distinto de M: se descarta
	Rejected                 // línea municipal con incidencia: se audita, no se suma
	Malformed                // número de columnas incorrecto
)

// Result describe la validación de un registro.
type Result struct {
	Outcome     Outcome
	Reason      string
	MoneyErrors []string // "COLUMNA:codigo" para estadísticas
	YearText    string
	SecEjec     string
}

var moneyCols = func() []string {
	c := []string{domain.ColPIA, domain.ColPIM, domain.ColDevAnual}
	for m := 0; m < 12; m++ {
		c = append(c, domain.MonthColumn(m))
	}
	return c
}()

// Validate aplica las reglas auditables a un registro y, si es válido, llena line.
//  1. NIVEL_GOBIERNO = M (gobiernos locales), el resto se descarta.
//  2. ANO_EJE debe coincidir con el año del archivo y SEC_EJEC no vacío.
//  3. Todos los montos se convierten a céntimos exactos; un error invalida la línea.
//  4. La suma de los 12 meses debe ser igual al devengado anual.
func (ix *Index) Validate(rec []string, expectedYear int, line *domain.Line) Result {
	if len(rec) != ix.NCols {
		return Result{Outcome: Malformed, Reason: fmt.Sprintf("columnas_%d_esperadas_%d", len(rec), ix.NCols)}
	}
	if !strings.EqualFold(strings.TrimSpace(rec[ix.nivel]), "M") {
		return Result{Outcome: NonLocal}
	}
	res := Result{YearText: strings.TrimSpace(rec[ix.anoEje]), SecEjec: strings.TrimSpace(rec[ix.secEjec])}
	if res.YearText != strconv.Itoa(expectedYear) {
		res.Outcome, res.Reason = Rejected, "ano_eje_no_coincide_archivo"
		return res
	}
	if res.SecEjec == "" {
		res.Outcome, res.Reason = Rejected, "sec_ejec_vacio"
		return res
	}
	var vals [15]int64
	for i, col := range moneyCols {
		var pos int
		switch i {
		case 0:
			pos = ix.pia
		case 1:
			pos = ix.pim
		case 2:
			pos = ix.anual
		default:
			pos = ix.months[i-3]
		}
		v, err := ParseCents(rec[pos])
		if err != "" {
			res.MoneyErrors = append(res.MoneyErrors, col+":"+err)
			continue
		}
		vals[i] = v
	}
	if len(res.MoneyErrors) > 0 {
		res.Outcome, res.Reason = Rejected, "montos_invalidos: "+strings.Join(res.MoneyErrors, ";")
		return res
	}
	var sum int64
	for m := 0; m < 12; m++ {
		sum += vals[3+m]
	}
	if sum != vals[2] {
		res.Outcome, res.Reason = Rejected, "suma_meses_difiere_devengado_anual"
		return res
	}
	*line = domain.Line{
		Year: expectedYear, SecEjec: res.SecEjec,
		Ejecutora:    strings.TrimSpace(rec[ix.ejecutora]),
		Departamento: strings.TrimSpace(rec[ix.depto]),
		IsProject:    strings.EqualFold(strings.TrimSpace(rec[ix.tipo]), "PROYECTO"),
		ProjectCode:  strings.TrimSpace(rec[ix.producto]),
		PIA:          vals[0], PIM: vals[1], DevAnual: vals[2],
	}
	copy(line.Months[:], vals[3:])
	res.Outcome = Accepted
	return res
}
