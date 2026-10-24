package dec

import (
	"math"
	"strconv"
	"strings"
)

// PyFloatRepr is Python's repr(float): the shortest round-tripping digits, fixed notation when the decimal
// exponent is in [-4, 16), scientific otherwise, and always a ".0" on integral values in fixed notation.
func PyFloatRepr(f float64) string {
	if math.IsInf(f, 1) {
		return "inf"
	}
	if math.IsInf(f, -1) {
		return "-inf"
	}
	if math.IsNaN(f) {
		return "nan"
	}
	if f == 0 {
		if math.Signbit(f) {
			return "-0.0"
		}
		return "0.0"
	}
	s := strconv.FormatFloat(f, 'e', -1, 64) // -d.ddde±XX
	sign := ""
	if s[0] == '-' {
		sign = "-"
		s = s[1:]
	}
	ei := strings.IndexByte(s, 'e')
	mant, expS := s[:ei], s[ei+1:]
	exp, _ := strconv.Atoi(expS)
	digits := strings.Replace(mant, ".", "", 1)
	if exp >= -4 && exp < 16 {
		// fixed notation
		pointPos := exp + 1 // digits before the decimal point
		var out string
		switch {
		case pointPos <= 0:
			out = "0." + strings.Repeat("0", -pointPos) + digits
		case pointPos >= len(digits):
			out = digits + strings.Repeat("0", pointPos-len(digits)) + ".0"
		default:
			out = digits[:pointPos] + "." + digits[pointPos:]
		}
		return sign + out
	}
	m := digits[:1]
	if len(digits) > 1 {
		m += "." + digits[1:]
	}
	es := strconv.Itoa(absInt(exp))
	if len(es) < 2 {
		es = "0" + es
	}
	if exp < 0 {
		es = "-" + es
	} else {
		es = "+" + es
	}
	return sign + m + "e" + es
}

func absInt(x int) int {
	if x < 0 {
		return -x
	}
	return x
}

// PyG is Python's format(float, "g") (precision 6, trailing zeros stripped).
func PyG(f float64) string {
	s := strconv.FormatFloat(f, 'g', 6, 64)
	// Go writes e+06 like Python; both strip trailing zeros in %g.
	return s
}

// PyFixed is Python's format(float, ".<n>f").
func PyFixed(f float64, places int) string { return strconv.FormatFloat(f, 'f', places, 64) }

// Commas inserts thousands separators into the integer part of a plain number string (format spec ",").
func Commas(s string) string {
	sign := ""
	if strings.HasPrefix(s, "-") {
		sign, s = "-", s[1:]
	}
	intPart, frac := s, ""
	if i := strings.IndexByte(s, '.'); i >= 0 {
		intPart, frac = s[:i], s[i:]
	}
	var b strings.Builder
	n := len(intPart)
	for i, c := range intPart {
		if i > 0 && (n-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(c)
	}
	return sign + b.String() + frac
}

// PyRound is Python's round(float) -> int: round half to even.
func PyRound(f float64) int64 { return int64(math.RoundToEven(f)) }

// PyRoundN is Python's round(float, n) for n >= 0: correctly rounded via the shortest decimal repr, half-even
// on the exact binary value (CPython uses the exact decimal expansion of the double).
func PyRoundN(f float64, n int) float64 {
	s := strconv.FormatFloat(f, 'f', n, 64) // Go rounds the exact binary value half-even, as CPython does
	r, _ := strconv.ParseFloat(s, 64)
	return r
}
