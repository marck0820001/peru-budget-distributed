// Package preprocessing contiene las reglas auditables de limpieza del MEF:
// conversión exacta de montos a céntimos y validación de cada línea.
// Replica las reglas documentadas en docs/datasets/03-preprocesamiento-mef.md.
package preprocessing

import (
	"math/big"
	"strings"
)

// Códigos de error de un monto (mismos nombres que el preprocesamiento en Python).
const (
	ErrVacio        = "vacio"
	ErrAmbiguo      = "formato_ambiguo"
	ErrNoNumerico   = "no_numerico"
	ErrDecimales    = "mas_de_dos_decimales"
	ErrFueraDeRango = "fuera_de_rango"
)

var nullTokens = map[string]struct{}{
	"": {}, "NULL": {}, "N/A": {}, "NA": {}, "NAN": {}, "NONE": {}, "S/D": {}, "SIN DATO": {},
}

// ParseCents convierte un monto textual a céntimos enteros SIN redondear.
// Devuelve un código de error si el valor es vacío, ambiguo (coma decimal),
// no numérico o tiene más de dos decimales significativos.
// Los ceros y los negativos válidos se conservan.
func ParseCents(raw string) (int64, string) {
	s := strings.TrimSpace(raw)
	if strings.ContainsAny(s, "  ") {
		s = strings.NewReplacer(" ", "", " ", "").Replace(s)
	}
	if _, ok := nullTokens[strings.ToUpper(s)]; ok {
		return 0, ErrVacio
	}
	s = strings.TrimPrefix(s, "S/")
	s = strings.TrimPrefix(s, "$")
	if strings.Contains(s, ",") {
		return 0, ErrAmbiguo
	}
	if s == "" {
		return 0, ErrNoNumerico
	}
	if strings.ContainsAny(s, "eE") {
		return parseCentsBig(s)
	}
	neg := false
	switch s[0] {
	case '-':
		neg = true
		s = s[1:]
	case '+':
		s = s[1:]
	}
	intPart, frac := s, ""
	if dot := strings.IndexByte(s, '.'); dot >= 0 {
		intPart, frac = s[:dot], s[dot+1:]
	}
	if intPart == "" && frac == "" {
		return 0, ErrNoNumerico
	}
	if !allDigits(intPart) || !allDigits(frac) {
		return 0, ErrNoNumerico
	}
	frac = strings.TrimRight(frac, "0") // "1.230" == 1.23 exacto
	if len(frac) > 2 {
		return 0, ErrDecimales
	}
	for len(frac) < 2 {
		frac += "0"
	}
	intPart = strings.TrimLeft(intPart, "0")
	if len(intPart) > 16 { // evita overflow de int64 en céntimos
		return 0, ErrFueraDeRango
	}
	var v int64
	for _, c := range intPart + frac {
		v = v*10 + int64(c-'0')
	}
	if neg {
		v = -v
	}
	return v, ""
}

func allDigits(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return true
}

// parseCentsBig cubre la notación científica con aritmética racional exacta.
func parseCentsBig(s string) (int64, string) {
	r, ok := new(big.Rat).SetString(s)
	if !ok {
		return 0, ErrNoNumerico
	}
	r.Mul(r, big.NewRat(100, 1))
	if !r.IsInt() {
		return 0, ErrDecimales
	}
	n := r.Num()
	if !n.IsInt64() {
		return 0, ErrFueraDeRango
	}
	return n.Int64(), ""
}

// FormatSoles imprime céntimos como soles con dos decimales exactos.
func FormatSoles(c int64) string {
	sign := ""
	if c < 0 {
		sign = "-"
		c = -c
	}
	frac := c % 100
	s := sign + itoa(c/100) + "."
	if frac < 10 {
		s += "0"
	}
	return s + itoa(frac)
}

func itoa(v int64) string {
	if v == 0 {
		return "0"
	}
	var b [20]byte
	i := len(b)
	for v > 0 {
		i--
		b[i] = byte('0' + v%10)
		v /= 10
	}
	return string(b[i:])
}
