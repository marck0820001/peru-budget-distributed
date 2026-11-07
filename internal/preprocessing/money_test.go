package preprocessing

import "testing"

func TestParseCents(t *testing.T) {
	cases := []struct {
		in   string
		want int64
		err  string
	}{
		{"569", 56900, ""},
		{"44119.65", 4411965, ""},
		{"-3298.39", -329839, ""},
		{"0", 0, ""},
		{"1.230", 123, ""}, // ceros a la derecha no son decimales significativos
		{" 12.5 ", 1250, ""},
		{"1.5e3", 150000, ""}, // notación científica exacta
		{"", 0, ErrVacio},
		{"NULL", 0, ErrVacio},
		{"12500,50", 0, ErrAmbiguo}, // coma decimal ambigua: se rechaza
		{"12.345", 0, ErrDecimales}, // no se redondea en silencio
		{"abc", 0, ErrNoNumerico},
		{"1.2.3", 0, ErrNoNumerico},
		{"S/150.10", 15010, ""},
	}
	for _, c := range cases {
		got, err := ParseCents(c.in)
		if err != c.err || (err == "" && got != c.want) {
			t.Errorf("ParseCents(%q) = (%d,%q), quiero (%d,%q)", c.in, got, err, c.want, c.err)
		}
	}
}

func TestFormatSoles(t *testing.T) {
	for in, want := range map[int64]string{0: "0.00", 5: "0.05", 4411965: "44119.65", -329839: "-3298.39"} {
		if got := FormatSoles(in); got != want {
			t.Errorf("FormatSoles(%d)=%s quiero %s", in, got, want)
		}
	}
}
