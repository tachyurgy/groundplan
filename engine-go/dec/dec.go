// Package dec is the arithmetic contract shared with the Python engine.
//
// Python's engine computes with decimal.Decimal under the default context (28 significant digits,
// ROUND_HALF_EVEN for every intermediate operation) and rounds a money value HALF-UP to the cent exactly once,
// when it becomes the value of a Figure or a schedule row. This package reproduces that rule on top of
// github.com/cockroachdb/apd (an implementation of the same General Decimal Arithmetic spec that libmpdec
// implements), so every intermediate result is the identical 28-digit decimal and every cent is identical.
//
//   - Add/Sub/Mul/Quo: exact result rounded to 28 significant digits, half-even (Python default context).
//   - PowInt: the exact integer power, rounded once to 28 digits half-even (what libmpdec returns for x**n).
//   - Cents(): quantize to an integer, ROUND_HALF_UP (Python engine.figure.cents).
//   - String(): GDA to-scientific-string, byte-identical to Python str(Decimal).
//
// Arithmetic errors (division by zero, invalid operation) panic with *ArithmeticError; HTTP handlers recover it
// into the same 422 problem Python raises for ArithmeticError.
package dec

import (
	"fmt"
	"math/big"
	"strconv"
	"strings"

	"github.com/cockroachdb/apd/v3"
)

// Ctx mirrors Python's decimal.DefaultContext.
var Ctx = apd.Context{
	Precision:   28,
	MaxExponent: 999999,
	MinExponent: -999999,
	Rounding:    apd.RoundHalfEven,
	Traps:       apd.DivisionByZero | apd.InvalidOperation | apd.Overflow,
}

// ArithmeticError is the Go stand-in for Python's decimal.DecimalException / ArithmeticError.
type ArithmeticError struct{ Msg string }

func (e *ArithmeticError) Error() string { return e.Msg }

func check(_ apd.Condition, err error) {
	if err != nil {
		panic(&ArithmeticError{Msg: err.Error()})
	}
}

// D is an immutable decimal value.
type D struct{ v apd.Decimal }

// Zero and One are convenience constants.
var (
	Zero = I(0)
	One  = I(1)
)

// I builds a decimal from an integer (exponent 0, like Decimal(int)).
func I(x int64) D {
	var d D
	d.v.SetInt64(x)
	return d
}

// BigI builds a decimal from a big integer.
func BigI(x *big.Int) D {
	var d D
	d.v.Coeff.SetMathBigInt(x)
	if x.Sign() < 0 {
		d.v.Coeff.Neg(&d.v.Coeff)
		d.v.Negative = true
	}
	return d
}

// Parse builds a decimal from a string exactly like Decimal(str) (leading/trailing whitespace allowed).
func Parse(s string) (D, error) {
	var d D
	t := strings.TrimSpace(s)
	t = strings.ReplaceAll(t, "_", "")
	if t == "" {
		return d, &ArithmeticError{Msg: "[<class 'decimal.ConversionSyntax'>]"}
	}
	_, _, err := d.v.SetString(t)
	if err != nil || d.v.Form != apd.Finite {
		if err == nil && (strings.EqualFold(t, "nan") || strings.Contains(strings.ToLower(t), "inf")) {
			return d, &ArithmeticError{Msg: "non-finite decimal not supported"}
		}
		return d, &ArithmeticError{Msg: "[<class 'decimal.ConversionSyntax'>]"}
	}
	return d, nil
}

// S parses a string that is known to be valid (constants); it panics otherwise.
func S(s string) D {
	d, err := Parse(s)
	if err != nil {
		panic(err)
	}
	return d
}

// F builds a decimal from a float64 the way the Python engine does: Decimal(repr(x)).
func F(x float64) D { return S(PyFloatRepr(x)) }

func (a D) ptr() *apd.Decimal { return &a.v }

// Add returns a+b.
func (a D) Add(b D) D {
	var r D
	check(Ctx.Add(&r.v, a.ptr(), b.ptr()))
	return r
}

// Sub returns a-b.
func (a D) Sub(b D) D {
	var r D
	check(Ctx.Sub(&r.v, a.ptr(), b.ptr()))
	return r
}

// Mul returns a*b.
func (a D) Mul(b D) D {
	var r D
	check(Ctx.Mul(&r.v, a.ptr(), b.ptr()))
	return r
}

// Quo returns a/b (panics with ArithmeticError on division by zero, like Python).
func (a D) Quo(b D) D {
	var r D
	if b.IsZero() {
		panic(&ArithmeticError{Msg: "[<class 'decimal.DivisionByZero'>]"})
	}
	check(Ctx.Quo(&r.v, a.ptr(), b.ptr()))
	return r
}

// Neg returns -a.
func (a D) Neg() D {
	var r D
	r.v.Neg(a.ptr())
	return r
}

// Abs returns |a|.
func (a D) Abs() D {
	var r D
	r.v.Abs(a.ptr())
	return r
}

// PowInt returns a**n for an integer n >= 0: exact power, rounded once to 28 digits half-even.
func (a D) PowInt(n int) D {
	if n < 0 {
		return One.Quo(a.PowInt(-n))
	}
	if n == 0 {
		return I(1)
	}
	coeff := a.v.Coeff.MathBigInt()
	p := new(big.Int).Exp(coeff, big.NewInt(int64(n)), nil)
	var exact D
	exact.v.Coeff.SetMathBigInt(p)
	exact.v.Exponent = a.v.Exponent * int32(n)
	exact.v.Negative = a.v.Negative && n%2 == 1
	var r D
	check(Ctx.Round(&r.v, &exact.v))
	return r
}

// Pow returns a**b for a decimal exponent (used only for CAGR, quantized to 6 places afterwards).
func (a D) Pow(b D) D {
	var r D
	check(Ctx.Pow(&r.v, a.ptr(), b.ptr()))
	return r
}

// Cmp compares a and b.
func (a D) Cmp(b D) int { return a.v.Cmp(b.ptr()) }

// Sign returns -1, 0 or 1.
func (a D) Sign() int { return a.v.Sign() }

// IsZero reports a == 0.
func (a D) IsZero() bool { return a.v.IsZero() }

// Lt etc. are readability helpers.
func (a D) Lt(b D) bool { return a.Cmp(b) < 0 }
func (a D) Le(b D) bool { return a.Cmp(b) <= 0 }
func (a D) Gt(b D) bool { return a.Cmp(b) > 0 }
func (a D) Ge(b D) bool { return a.Cmp(b) >= 0 }
func (a D) Eq(b D) bool { return a.Cmp(b) == 0 }

// Max / Min follow Python's max()/min(): the first argument wins ties.
func Max(a, b D) D {
	if b.Gt(a) {
		return b
	}
	return a
}

func Min(a, b D) D {
	if b.Lt(a) {
		return b
	}
	return a
}

// Quantize returns a quantized to `places` decimal places using the given rounding.
func (a D) Quantize(places int, rounding apd.Rounder) D {
	c := Ctx
	c.Rounding = rounding
	var r D
	check(c.Quantize(&r.v, a.ptr(), int32(-places)))
	return r
}

// Cents rounds HALF-UP to an integer number of cents (the only rounding point in the engine).
func (a D) Cents() int64 {
	q := a.Quantize(0, apd.RoundHalfUp)
	return q.Int()
}

// Int truncates toward zero, like Python int(Decimal).
func (a D) Int() int64 {
	var t apd.Decimal
	c := Ctx
	c.Rounding = apd.RoundDown
	check(c.Quantize(&t, a.ptr(), 0))
	i, err := t.Int64()
	if err != nil {
		panic(&ArithmeticError{Msg: err.Error()})
	}
	return i
}

// Float64 is float(Decimal) (correctly rounded).
func (a D) Float64() float64 {
	f, err := strconv.ParseFloat(a.v.Text('E'), 64)
	if err != nil {
		panic(&ArithmeticError{Msg: err.Error()})
	}
	return f
}

// String is Python's str(Decimal): the GDA to-scientific-string.
func (a D) String() string {
	digits := a.v.Coeff.String()
	exp := int(a.v.Exponent)
	sign := ""
	if a.v.Negative {
		sign = "-"
	}
	adj := exp + len(digits) - 1
	if exp <= 0 && adj >= -6 {
		if exp == 0 {
			return sign + digits
		}
		k := -exp
		if len(digits) > k {
			return sign + digits[:len(digits)-k] + "." + digits[len(digits)-k:]
		}
		return sign + "0." + strings.Repeat("0", k-len(digits)) + digits
	}
	m := digits[:1]
	if len(digits) > 1 {
		m += "." + digits[1:]
	}
	es := strconv.Itoa(adj)
	if adj >= 0 {
		es = "+" + es
	}
	return sign + m + "E" + es
}

// Fixed formats like Python format(Decimal, ".<n>f") (ROUND_HALF_EVEN, the context rounding).
func (a D) Fixed(places int) string {
	q := a.Quantize(places, apd.RoundHalfEven)
	digits := q.v.Coeff.String()
	sign := ""
	if q.v.Negative && !q.v.IsZero() {
		sign = "-"
	} else if q.v.Negative {
		sign = "-" // Python keeps the sign of a negative zero: format(Decimal('-0.0001'), '.2f') == '-0.00'
	}
	if places == 0 {
		return sign + digits
	}
	if len(digits) <= places {
		digits = strings.Repeat("0", places-len(digits)+1) + digits
	}
	return sign + digits[:len(digits)-places] + "." + digits[len(digits)-places:]
}

// Pct formats like Python format(Decimal, ".<n>%").
func (a D) Pct(places int) string { return a.Mul(I(100)).Fixed(places) + "%" }

// RateStr is engine.figure.rate_str: quantize HALF-UP to `places` and str().
func (a D) RateStr(places int) string { return a.Quantize(places, apd.RoundHalfUp).String() }

// FromPct is engine.figure.pct: "3.485" -> 0.03485.
func FromPct(s string) D { return S(s).Quo(I(100)) }

// Sum adds a list of decimals.
func Sum(xs ...D) D {
	r := I(0)
	for _, x := range xs {
		r = r.Add(x)
	}
	return r
}

// GoString aids debugging.
func (a D) GoString() string { return fmt.Sprintf("dec.S(%q)", a.String()) }

// MarshalText lets encoding/json render a decimal as its Python str().
func (a D) MarshalText() ([]byte, error) { return []byte(a.String()), nil }
