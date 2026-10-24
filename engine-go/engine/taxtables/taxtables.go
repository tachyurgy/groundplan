// Package taxtables ports engine/tax_tables.py: federal tax tables and the bracket-stacking rule.
//
// Stacking order for a sale: (1) ordinary taxable income + Sec 1245 recapture fill the ordinary brackets at full
// rates; (2) unrecaptured Sec 1250 gain stacks on top at min(bracket rate, 25%); (3) long-term capital gain stacks
// last at 0/15/20% by where it lands. NIIT 3.8% on min(NII, MAGI - threshold).
package taxtables

import (
	"fmt"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/figure"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

var ordinaryRates = []string{"0.10", "0.12", "0.22", "0.24", "0.32", "0.35", "0.37"}

var (
	Sec1250Cap = dec.S("0.25")
	NIITRate   = dec.S("0.038")
)

var ordinaryBrackets = map[int]map[string][]int64{
	2025: {
		"single": {11_925, 48_475, 103_350, 197_300, 250_525, 626_350},
		"mfj":    {23_850, 96_950, 206_700, 394_600, 501_050, 751_600},
		"hoh":    {17_000, 64_850, 103_350, 197_300, 250_500, 626_350},
		"mfs":    {11_925, 48_475, 103_350, 197_300, 250_525, 375_800},
	},
	2026: {
		"single": {12_400, 50_400, 105_700, 201_775, 256_225, 640_600},
		"mfj":    {24_800, 100_800, 211_400, 403_550, 512_450, 768_700},
		"hoh":    {17_700, 67_450, 105_700, 201_775, 256_200, 640_600},
		"mfs":    {12_400, 50_400, 105_700, 201_775, 256_225, 384_350},
	},
}

var standardDeduction = map[int]map[string]int64{
	2025: {"single": 15_750, "mfj": 31_500, "hoh": 23_625, "mfs": 15_750},
	2026: {"single": 16_100, "mfj": 32_200, "hoh": 24_150, "mfs": 16_100},
}

var ltcgThresholds = map[int]map[string][2]int64{
	2025: {"single": {48_350, 533_400}, "mfj": {96_700, 600_050}, "hoh": {64_750, 566_700}, "mfs": {48_350, 300_000}},
	2026: {"single": {49_450, 545_500}, "mfj": {98_900, 613_700}, "hoh": {66_200, 579_600}, "mfs": {49_450, 306_850}},
}

var niitThreshold = map[string]int64{"single": 200_000, "hoh": 200_000, "mfj": 250_000, "mfs": 125_000}

// Sources per table year.
var Sources = map[int]string{
	2025: "spec (IRS Rev. Proc. 2024-40 brackets; OBBBA 2025 standard deduction)",
	2026: "IRS Rev. Proc. 2025-32 (Oct 2025) -- verify",
}

var verify = map[int]bool{2025: false, 2026: true}

// TableYear is the nearest table year we carry.
func TableYear(taxYear int) int {
	if taxYear <= 2025 {
		return 2025
	}
	return 2026
}

func boundsCents(taxYear int, fs string) []dec.D {
	var out []dec.D
	for _, b := range ordinaryBrackets[TableYear(taxYear)][fs] {
		out = append(out, dec.I(b).Mul(dec.I(100)))
	}
	return out
}

// StandardDeductionCents is the standard deduction in cents.
func StandardDeductionCents(taxYear int, fs string) int64 {
	return standardDeduction[TableYear(taxYear)][fs] * 100
}

// Layer is one bracket slice.
type Layer struct {
	Rate        string
	LowerCents  int64
	UpperCents  int64
	AmountCents int64
	TaxCents    int64
}

// ToDict renders a layer.
func (l Layer) ToDict() *jsonx.Obj {
	return jsonx.O("rate", l.Rate, "lower_cents", l.LowerCents, "upper_cents", l.UpperCents, "amount_cents", l.AmountCents, "tax_cents", l.TaxCents)
}

// OrdinaryLayers taxes `amount` stacked on top of `from` through the ordinary brackets, each rate capped at cap.
func OrdinaryLayers(fromCents, amountCents dec.D, taxYear int, fs string, capRate *dec.D) []Layer {
	bounds := boundsCents(taxYear, fs)
	var layers []Layer
	pos := dec.Max(dec.Zero, fromCents)
	end := pos.Add(dec.Max(dec.Zero, amountCents))
	lower := dec.Zero
	for i, rs := range ordinaryRates {
		var upper *dec.D
		if i < len(bounds) {
			u := bounds[i]
			upper = &u
		}
		segLo := dec.Max(pos, lower)
		segHi := end
		if upper != nil {
			segHi = dec.Min(end, *upper)
		}
		if segHi.Gt(segLo) {
			rate := dec.S(rs)
			if capRate != nil && rate.Gt(*capRate) {
				rate = *capRate
			}
			amt := segHi.Sub(segLo)
			layers = append(layers, Layer{rate.String(), segLo.Int(), segHi.Int(), amt.Int(), amt.Mul(rate).Cents()})
		}
		if upper == nil || end.Le(*upper) {
			break
		}
		lower = *upper
	}
	return layers
}

// OrdinaryTaxCents is the bracket tax on taxable income.
func OrdinaryTaxCents(taxableCents int64, taxYear int, fs string) int64 {
	var t int64
	for _, l := range OrdinaryLayers(dec.Zero, dec.I(taxableCents), taxYear, fs, nil) {
		t += l.TaxCents
	}
	return t
}

// LTCGLayers stacks long-term gain on top of `from` through the 0/15/20 thresholds.
func LTCGLayers(fromCents, amountCents dec.D, taxYear int, fs string) []Layer {
	th := ltcgThresholds[TableYear(taxYear)][fs]
	zeroTop, fifteenTop := dec.I(th[0]).Mul(dec.I(100)), dec.I(th[1]).Mul(dec.I(100))
	var layers []Layer
	pos := dec.Max(dec.Zero, fromCents)
	end := pos.Add(dec.Max(dec.Zero, amountCents))
	type seg struct {
		rate  string
		lower dec.D
		upper *dec.D
	}
	for _, s := range []seg{{"0", dec.Zero, &zeroTop}, {"0.15", zeroTop, &fifteenTop}, {"0.20", fifteenTop, nil}} {
		segLo := dec.Max(pos, s.lower)
		segHi := end
		if s.upper != nil {
			segHi = dec.Min(end, *s.upper)
		}
		if segHi.Gt(segLo) {
			amt := segHi.Sub(segLo)
			layers = append(layers, Layer{s.rate, segLo.Int(), segHi.Int(), amt.Int(), amt.Mul(dec.S(s.rate)).Cents()})
		}
		if s.upper == nil || end.Le(*s.upper) {
			break
		}
	}
	return layers
}

// StackResult carries every federal component.
type StackResult struct {
	OrdinaryTaxableCents int64
	TaxOrdinary          *figure.Figure
	Tax1245              *figure.Figure
	Tax1250              *figure.Figure
	TaxLTCG              *figure.Figure
	Layers1250           []Layer
	LayersLTCG           []Layer
	Notes                []string
}

// ToDict renders the stack.
func (s *StackResult) ToDict() *jsonx.Obj {
	return jsonx.O("ordinary_taxable_cents", s.OrdinaryTaxableCents, "tax_ordinary", s.TaxOrdinary.ToDict(),
		"tax_1245", s.Tax1245.ToDict(), "tax_1250", s.Tax1250.ToDict(), "tax_ltcg", s.TaxLTCG.ToDict(),
		"layers_1250", LayersDicts(s.Layers1250), "layers_ltcg", LayersDicts(s.LayersLTCG), "notes", strs(s.Notes))
}

// LayersDicts renders layers.
func LayersDicts(ls []Layer) []any {
	out := make([]any, len(ls))
	for i, l := range ls {
		out[i] = l.ToDict()
	}
	return out
}

func strs(ss []string) []any {
	out := make([]any, len(ss))
	for i, s := range ss {
		out[i] = s
	}
	return out
}

func sumTax(ls []Layer) int64 {
	var t int64
	for _, l := range ls {
		t += l.TaxCents
	}
	return t
}

// ValidFilingStatus reports a known filing status.
func ValidFilingStatus(fs string) bool {
	switch fs {
	case "single", "mfj", "mfs", "hoh":
		return true
	}
	return false
}

// Stack applies the stacking order.
func Stack(ordinaryTaxableCents, sec1245Cents, sec1250Cents, ltcgCents int64, taxYear int, fs string, extra []*figure.Input) *StackResult {
	if !ValidFilingStatus(fs) {
		panic(fmt.Sprintf("unknown filing status %q", fs))
	}
	yr := TableYear(taxYear)
	tySrc := "manual"
	if verify[yr] {
		tySrc = "public_data"
	}
	base := figure.Ins(figure.L(figure.M("tax_year", int64(taxYear)), figure.Of("table_year", int64(yr), tySrc, Sources[yr]),
		figure.M("filing_status", fs)), extra)
	ordBase := max(0, ordinaryTaxableCents)
	baseTax := OrdinaryTaxCents(ordBase, taxYear, fs)
	taxOrdinary := figure.MoneyI("tax.federal.ordinary_on_other_income", baseTax,
		figure.Ins(base, figure.L(figure.M("ordinary_taxable_cents", ordinaryTaxableCents))),
		"bracket tax on (wages + other income - standard deduction - released suspended losses)", nil, nil)
	l1245 := OrdinaryLayers(dec.I(ordBase), dec.I(sec1245Cents), taxYear, fs, nil)
	tax1245 := figure.MoneyI("exit_tax.fed_1245", sumTax(l1245),
		figure.Ins(base, figure.L(figure.Of("sec1245_cents", sec1245Cents, "figure", "exit_tax.sec1245"), figure.M("stack_from_cents", ordBase))),
		"ordinary brackets on sec1245 stacked above other ordinary income (no 25% cap)", nil, nil)
	pos := dec.I(ordBase + sec1245Cents)
	capR := Sec1250Cap
	l1250 := OrdinaryLayers(pos, dec.I(sec1250Cents), taxYear, fs, &capR)
	notes := []string{fmt.Sprintf("stack: ordinary %d (+1245 %d) -> 1250 %d at min(bracket,25%%) -> LTCG %d at 0/15/20",
		ordBase, sec1245Cents, sec1250Cents, ltcgCents)}
	var underAmt int64
	under := false
	for _, l := range l1250 {
		if dec.S(l.Rate).Lt(Sec1250Cap) {
			under = true
			underAmt += l.AmountCents
		}
	}
	if under {
		notes = append(notes, fmt.Sprintf("%d cents of the 1250 gain landed in brackets below 25%% "+
			"and is taxed at the lower ordinary rate", underAmt))
	}
	tax1250 := figure.MoneyI("exit_tax.fed_1250", sumTax(l1250),
		figure.Ins(base, figure.L(figure.Of("unrecaptured_1250_cents", sec1250Cents, "figure", "exit_tax.unrecaptured_1250"),
			figure.M("stack_from_cents", pos.Int()))),
		"ordinary brackets capped at 25% on the 1250 gain stacked above ordinary income", notes[1:], nil)
	pos = pos.Add(dec.I(sec1250Cents))
	lltcg := LTCGLayers(pos, dec.I(ltcgCents), taxYear, fs)
	taxLTCG := figure.MoneyI("exit_tax.fed_ltcg", sumTax(lltcg),
		figure.Ins(base, figure.L(figure.Of("ltcg_cents", ltcgCents, "figure", "exit_tax.ltcg"), figure.M("stack_from_cents", pos.Int()))),
		"0/15/20% by where the LTCG lands on top of ordinary + 1250 income", nil, nil)
	return &StackResult{ordinaryTaxableCents, taxOrdinary, tax1245, tax1250, taxLTCG, l1250, lltcg, notes}
}

// NIIT is niit(nii, magi, filing_status, inputs).
func NIIT(niiCents, magiCents int64, fs string, inputs []*figure.Input) *figure.Figure {
	threshold := dec.I(niitThreshold[fs]).Mul(dec.I(100))
	base := dec.Max(dec.Zero, dec.Min(dec.I(niiCents), dec.I(magiCents).Sub(threshold)))
	var notes []string
	if base.Sign() <= 0 {
		notes = []string{"MAGI below the NIIT threshold or no net investment income: NIIT is 0"}
	}
	if inputs == nil {
		inputs = figure.L(figure.M("net_investment_income_cents", niiCents), figure.M("magi_cents", magiCents),
			figure.M("filing_status", fs), figure.Of("niit_threshold_cents", threshold.Int(), "manual", "IRC 1411 (not indexed)"))
	}
	return figure.Money("exit_tax.niit", base.Mul(NIITRate), inputs, "3.8% x max(0, min(NII, MAGI - threshold))", notes, nil)
}
