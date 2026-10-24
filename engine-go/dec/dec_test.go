package dec

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/cockroachdb/apd/v3"
)

// testdata/python_vectors.json is produced by CPython's decimal module (default context) and float repr.
func TestAgainstPythonVectors(t *testing.T) {
	raw, err := os.ReadFile("testdata/python_vectors.json")
	if err != nil {
		t.Fatal(err)
	}
	var v struct {
		Floats [][2]any    `json:"floats"`
		Ops    [][9]string `json:"ops"`
	}
	if err := json.Unmarshal(raw, &v); err != nil {
		t.Fatal(err)
	}
	for _, f := range v.Floats {
		if got := PyFloatRepr(f[1].(float64)); got != f[0] {
			t.Errorf("repr(%v) = %s want %s", f[1], got, f[0])
		}
	}
	for _, o := range v.Ops {
		a, b := S(o[0]), S(o[1])
		got := []string{a.Add(b).String(), a.Sub(b).String(), a.Mul(b).String(), a.Quo(b).String(), a.PowInt(3).String(),
			a.Quo(b).Fixed(2), a.Quo(b).Quantize(6, apd.RoundHalfUp).String()}
		for i, g := range got {
			if g != o[i+2] {
				t.Errorf("%s op%d %s: got %s want %s", o[0], i, o[1], g, o[i+2])
			}
		}
	}
}

func TestCentsHalfUp(t *testing.T) {
	for in, want := range map[string]int64{"0.5": 1, "1.5": 2, "2.5": 3, "-0.5": -1, "-2.5": -3, "2.4999": 2, "189619.995": 189620} {
		if got := S(in).Cents(); got != want {
			t.Errorf("cents(%s) = %d want %d", in, got, want)
		}
	}
}
