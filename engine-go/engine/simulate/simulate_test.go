package simulate

import (
	"math"
	"testing"
)

func TestPowIntCorrectlyRounded(t *testing.T) {
	// values from CPython (glibc/libm pow): 1.065 ** -30 and 1.0425 ** 12
	if got := PowInt(1.065, -30); got != 0.15118606610981275 && math.Abs(got-0.15118606610981275) > 1e-17 {
		t.Fatalf("1.065**-30 = %v", got)
	}
	if PowInt(2, 10) != 1024 || PowInt(1.5, 0) != 1 {
		t.Fatal("exact powers")
	}
}
