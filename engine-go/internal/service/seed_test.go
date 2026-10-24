package service

import "testing"

// Python: basis3 = 615_000 * 0.70; allow24 = round(basis3 * 0.01970, 2); round(allow24 * 0.88); round(basis3 * 0.03636)
// -> 8480.85, 7463, 15653 (printed by CPython). The seed balances come from the loan engine: 17039869 and 44968257.
func TestSeedDerivedValues(t *testing.T) {
	allow24, claimed, dep25 := SeedDerived()
	if allow24 != 8480.85 || claimed != 7463 || dep25 != 15653 {
		t.Fatalf("got %v %v %v", allow24, claimed, dep25)
	}
	if usd(1_166.18) != 116618 || usd(2_518.73) != 251873 || usd(2_511.25) != 251125 {
		t.Fatal("usd() rounding differs from Python")
	}
}
