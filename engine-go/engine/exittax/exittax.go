// Package exittax ports engine/exit_tax.py: exit tax on a fully taxable sale (and on recognized boot in a 1031).
//
//	amount_realized = sale_price - selling_costs; net_before_tax = amount_realized - loan payoffs
//	adjusted_basis = purchase + improvements - accumulated depreciation (allowed or allowable)
//	total_gain = amount_realized - adjusted_basis; unrecaptured_1250 = min(gain, accumulated SL); 1245 = bonus part
//	federal = stacking on other taxable income; NIIT; state
//	released_loss_benefit = ordinary fed + state tax saved by released suspended losses (IRC 469(g))
//	exit_tax_total = fed_1250 + fed_1245 + fed_ltcg + niit + state - released_loss_benefit
//	Section 121 for a converted former residence sold within 3 years of move-out.
package exittax

import (
	"fmt"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/engine/figure"
	"github.com/tachyurgy/groundplan/engine-go/engine/statetax"
	"github.com/tachyurgy/groundplan/engine-go/engine/taxtables"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

var sec121Exclusion = map[string]int64{"single": 25_000_000, "mfs": 25_000_000, "hoh": 25_000_000, "mfj": 50_000_000}

// HouseholdTax is the household side of the sale.
type HouseholdTax struct {
	FilingStatus                 string
	State                        string
	TaxYear                      int
	WagesCents                   int64
	OtherIncomeCents             int64
	MagiCents                    int64
	ReleasedSuspendedLossesCents int64
	RentalNIICents               int64
	Sources                      map[string]*figure.Input
}

// NewHouseholdTax returns the Python dataclass defaults.
func NewHouseholdTax() HouseholdTax {
	return HouseholdTax{FilingStatus: "mfj", State: "CA", TaxYear: 2025}
}

func (h *HouseholdTax) inp(key string, v int64) *figure.Input {
	if in := h.Sources[key]; in != nil {
		return in
	}
	return figure.M(key, v)
}

// SaleInput is the property side of the sale.
type SaleInput struct {
	SalePriceCents               int64
	SellingCostRate              dec.D
	LoanPayoffCents              int64
	PurchasePriceCents           int64
	ImprovementsCents            int64
	AccumulatedDepreciationCents int64
	Sec1245Cents                 int64
	SaleDate                     *dates.Date
	FormerResidenceUntil         *dates.Date
	ReplacementState             *string
	Disposition                  string
	RecognizedGainCapCents       *int64
	Sources                      map[string]*figure.Input
}

func (s *SaleInput) inp(key string, v int64) *figure.Input {
	if in := s.Sources[key]; in != nil {
		return in
	}
	return figure.M(key, v)
}

// Result is ExitTaxResult; Order keeps the Python dict insertion order of the figures.
type Result struct {
	Figures  map[string]*figure.Figure
	Order    []string
	Findings []*jsonx.Obj
	Stack    *taxtables.StackResult
}

func (r *Result) set(k string, f *figure.Figure) {
	if _, ok := r.Figures[k]; !ok {
		r.Order = append(r.Order, k)
	}
	r.Figures[k] = f
}

// F returns a figure by key.
func (r *Result) F(k string) *figure.Figure { return r.Figures[k] }

// TotalCents is exit_tax.total.
func (r *Result) TotalCents() int64 { return r.Figures["exit_tax.total"].VC() }

// NetProceedsCents is exit_tax.net_proceeds.
func (r *Result) NetProceedsCents() int64 { return r.Figures["exit_tax.net_proceeds"].VC() }

// ToDict is ExitTaxResult.to_dict().
func (r *Result) ToDict() *jsonx.Obj {
	out := jsonx.O()
	for _, k := range r.Order {
		short := k[len("exit_tax."):]
		out.Set(short, r.Figures[k].ToDict())
	}
	out.Set("stack", r.Stack.ToDict())
	out.Set("findings", objs(r.Findings))
	out.Set("exit_tax_total_cents", r.TotalCents())
	out.Set("net_proceeds_cents", r.NetProceedsCents())
	return out
}

func objs(xs []*jsonx.Obj) []any {
	out := make([]any, len(xs))
	for i, x := range xs {
		out[i] = x
	}
	return out
}

// Compute is compute_exit_tax(sale, hh, blocked).
func Compute(sale *SaleInput, hh *HouseholdTax, blocked figure.KeySet) *Result {
	r := &Result{Figures: map[string]*figure.Figure{}}
	f := r.F
	rate := sale.SellingCostRate
	price := dec.I(sale.SalePriceCents)
	r.set("exit_tax.selling_costs", figure.Money("exit_tax.selling_costs", price.Mul(rate),
		figure.L(sale.inp("sale_price_cents", sale.SalePriceCents), figure.Of("selling_cost_rate", rate, "default")),
		"sale_price * selling_cost_rate", nil, nil))
	amountRealized := price.Sub(f("exit_tax.selling_costs").Dec())
	r.set("exit_tax.amount_realized", figure.Money("exit_tax.amount_realized", amountRealized,
		figure.L(sale.inp("sale_price_cents", sale.SalePriceCents), figure.Fig(f("exit_tax.selling_costs"))),
		"sale_price - selling_costs", nil, blocked))
	r.set("exit_tax.net_before_tax", figure.Money("exit_tax.net_before_tax", amountRealized.Sub(dec.I(sale.LoanPayoffCents)),
		figure.L(figure.Fig(f("exit_tax.amount_realized")), figure.Of("loan_payoff_cents", sale.LoanPayoffCents, "figure", "loans.schedule")),
		"amount_realized - loan payoffs", nil, nil))
	acc := dec.I(sale.AccumulatedDepreciationCents)
	adjustedBasis := dec.I(sale.PurchasePriceCents).Add(dec.I(sale.ImprovementsCents)).Sub(acc).Sub(dec.I(sale.Sec1245Cents))
	r.set("exit_tax.adjusted_basis", figure.Money("exit_tax.adjusted_basis", adjustedBasis,
		figure.L(sale.inp("purchase_price_cents", sale.PurchasePriceCents), sale.inp("improvements_cents", sale.ImprovementsCents),
			figure.Of("accumulated_depreciation_cents", sale.AccumulatedDepreciationCents, "figure", "depreciation.accumulated"),
			figure.Of("sec1245_cents", sale.Sec1245Cents, "figure", "depreciation.sec1245")),
		"purchase + improvements - accumulated depreciation (allowed or allowable, incl. bonus)", nil, nil))
	totalGain := dec.Max(dec.Zero, amountRealized.Sub(adjustedBasis))
	var gainNotes []string
	if amountRealized.Sub(adjustedBasis).Sign() < 0 {
		gainNotes = append(gainNotes, "sale below adjusted basis: loss (Sec 1231), no exit tax; loss treatment not modeled")
	}
	r.set("exit_tax.total_gain", figure.Money("exit_tax.total_gain", totalGain,
		figure.L(figure.Fig(f("exit_tax.amount_realized")), figure.Fig(f("exit_tax.adjusted_basis"))),
		"amount_realized - adjusted_basis", gainNotes, nil))
	recognized := totalGain
	if sale.RecognizedGainCapCents != nil {
		recognized = dec.Min(totalGain, dec.I(max(0, *sale.RecognizedGainCapCents)))
		r.set("exit_tax.recognized_gain", figure.Money("exit_tax.recognized_gain", recognized,
			figure.L(figure.Fig(f("exit_tax.total_gain")), figure.Of("boot_cents", *sale.RecognizedGainCapCents, "figure", "exchange.boot")),
			"min(total_gain, boot)", []string{"1031: gain recognized only to the extent of boot"}, nil))
	}
	sec1245 := dec.Min(recognized, dec.I(sale.Sec1245Cents))
	unrec1250 := dec.Min(recognized.Sub(sec1245), acc)
	r.set("exit_tax.sec1245", figure.Money("exit_tax.sec1245", sec1245,
		figure.L(figure.Of("sec1245_cents", sale.Sec1245Cents, "figure", "depreciation.sec1245"), figure.Fig(f("exit_tax.total_gain"))),
		"min(recognized gain, bonus/cost-seg depreciation) -> ordinary income, no 25% cap", nil, nil))
	r.set("exit_tax.unrecaptured_1250", figure.Money("exit_tax.unrecaptured_1250", unrec1250,
		figure.L(figure.Fig(f("exit_tax.total_gain")),
			figure.Of("accumulated_depreciation_cents", sale.AccumulatedDepreciationCents, "figure", "depreciation.accumulated")),
		"min(recognized gain - 1245, accumulated straight-line depreciation)", nil, nil))
	ltcg := recognized.Sub(sec1245).Sub(unrec1250)
	var ltcgNotes []string
	excluded := dec.Zero
	if sale.FormerResidenceUntil != nil && sale.SaleDate != nil {
		gap := dates.Days(*sale.SaleDate, *sale.FormerResidenceUntil)
		if gap >= 0 && gap <= 3*365 {
			capv := dec.I(sec121Exclusion[hh.FilingStatus])
			excluded = dec.Min(ltcg, capv)
			ltcg = ltcg.Sub(excluded)
			ltcgNotes = append(ltcgNotes, fmt.Sprintf("Section 121: %d cents of non-depreciation gain excluded "+
				"(former residence until %s, within 2-of-5 window)", excluded.Int(), dates.ISO(*sale.FormerResidenceUntil)))
			r.Findings = append(r.Findings, jsonx.O("kind", "info", "field", "sale.former_residence_until", "severity", "warn",
				"message", "Section 121 exclusion applied to a converted residence: verify with CPA "+
					"(nonqualified use after 2008 reduces the exclusion; depreciation gain is never excluded)"))
		} else {
			ltcgNotes = append(ltcgNotes, "former residence outside the 2-of-5 window: no Section 121 exclusion")
		}
	}
	r.set("exit_tax.sec121_excluded", figure.Money("exit_tax.sec121_excluded", excluded,
		figure.L(figure.M("former_residence_until", dateVal(sale.FormerResidenceUntil)), figure.M("sale_date", dateVal(sale.SaleDate)),
			figure.M("filing_status", hh.FilingStatus)),
		"min(non-depreciation gain, 250k/500k) if within 2-of-5 window else 0", nil, nil))
	r.set("exit_tax.ltcg", figure.Money("exit_tax.ltcg", ltcg, figure.L(figure.Fig(f("exit_tax.total_gain")), figure.Fig(f("exit_tax.sec1245")),
		figure.Fig(f("exit_tax.unrecaptured_1250")), figure.Fig(f("exit_tax.sec121_excluded"))),
		"recognized gain - 1245 - 1250 - sec121 exclusion", ltcgNotes, nil))
	std := taxtables.StandardDeductionCents(hh.TaxYear, hh.FilingStatus)
	ordinaryTaxable := dec.I(hh.WagesCents).Add(dec.I(hh.OtherIncomeCents)).Sub(dec.I(std)).Sub(dec.I(hh.ReleasedSuspendedLossesCents))
	var otNotes []string
	if hh.ReleasedSuspendedLossesCents != 0 {
		otNotes = []string{"released suspended losses are an ordinary deduction in the year of a fully taxable sale"}
	}
	r.set("exit_tax.ordinary_taxable_other", figure.Money("exit_tax.ordinary_taxable_other", ordinaryTaxable,
		figure.L(hh.inp("wages_cents", hh.WagesCents), hh.inp("other_income_cents", hh.OtherIncomeCents),
			figure.Of("standard_deduction_cents", std, "manual", taxtables.Sources[taxtables.TableYear(hh.TaxYear)]),
			figure.Of("released_suspended_losses_cents", hh.ReleasedSuspendedLossesCents, "figure", "passive.released_on_sale")),
		"wages + other income - standard deduction - released suspended losses", otNotes, nil))
	st := taxtables.Stack(ordinaryTaxable.Int(), sec1245.Int(), unrec1250.Int(), ltcg.Int(), hh.TaxYear, hh.FilingStatus,
		figure.L(figure.Fig(f("exit_tax.ordinary_taxable_other"))))
	r.Stack = st
	r.set("exit_tax.fed_1245", st.Tax1245)
	r.set("exit_tax.fed_1250", st.Tax1250)
	r.set("exit_tax.fed_ltcg", st.TaxLTCG)
	for _, kc := range [][2]string{{"exit_tax.fed_1245", "exit_tax.sec1245"}, {"exit_tax.fed_1250", "exit_tax.unrecaptured_1250"},
		{"exit_tax.fed_ltcg", "exit_tax.ltcg"}} {
		fg := f(kc[0])
		fg.Notes = append(append([]string{}, st.Notes[:1]...), fg.Notes...)
		fg.Inputs = append(fg.Inputs, figure.Fig(f(kc[1])))
		fg.Status = figure.DeriveStatus(fg.Inputs, blocked)
	}
	recEx := recognized.Sub(excluded).Int()
	nii := recEx + hh.RentalNIICents
	magiWithGain := hh.MagiCents + recEx - hh.ReleasedSuspendedLossesCents
	r.set("exit_tax.niit", taxtables.NIIT(nii, magiWithGain, hh.FilingStatus, figure.L(
		figure.Of("net_investment_income_cents", nii, "figure", "exit_tax.total_gain + rental NII"),
		hh.inp("magi_cents", hh.MagiCents), figure.Of("magi_with_gain_cents", magiWithGain, "figure", "household.magi + recognized gain"),
		figure.M("filing_status", hh.FilingStatus), figure.Fig(f("exit_tax.total_gain")))))
	otherForState := hh.WagesCents + hh.OtherIncomeCents - hh.ReleasedSuspendedLossesCents
	stateFig, stateFindings := statetax.ExitTax(hh.State, recEx, otherForState, hh.FilingStatus, sale.ReplacementState)
	stateFig.Inputs = append(stateFig.Inputs, figure.Fig(f("exit_tax.total_gain")))
	stateFig.Status = figure.DeriveStatus(stateFig.Inputs, blocked)
	r.set("exit_tax.state", stateFig)
	r.Findings = append(r.Findings, stateFindings...)
	r.set("exit_tax.released_loss_benefit", ReleasedLossBenefit(hh, std))
	total := f("exit_tax.fed_1250").Dec().Add(f("exit_tax.fed_1245").Dec()).Add(f("exit_tax.fed_ltcg").Dec()).
		Add(f("exit_tax.niit").Dec()).Add(f("exit_tax.state").Dec()).Sub(f("exit_tax.released_loss_benefit").Dec())
	var tin []*figure.Input
	for _, k := range []string{"exit_tax.fed_1250", "exit_tax.fed_1245", "exit_tax.fed_ltcg", "exit_tax.niit", "exit_tax.state",
		"exit_tax.released_loss_benefit"} {
		tin = append(tin, figure.Fig(f(k)))
	}
	r.set("exit_tax.total", figure.Money("exit_tax.total", total, tin,
		"fed_1250 + fed_1245 + fed_ltcg + niit + state - released_loss_benefit", st.Notes, nil))
	r.set("exit_tax.net_proceeds", figure.Money("exit_tax.net_proceeds", f("exit_tax.net_before_tax").Dec().Sub(total),
		figure.L(figure.Fig(f("exit_tax.net_before_tax")), figure.Fig(f("exit_tax.total"))), "net_before_tax - exit_tax_total", nil, nil))
	var eff *dec.D
	if recognized.Sign() > 0 {
		e := total.Quo(recognized)
		eff = &e
	}
	r.set("exit_tax.effective_rate_on_gain", figure.Ratio("exit_tax.effective_rate_on_gain", eff,
		figure.L(figure.Fig(f("exit_tax.total")), figure.Fig(f("exit_tax.total_gain"))), "exit_tax_total / recognized gain", "rate", nil, 4))
	return r
}

// ReleasedLossBenefit is released_loss_benefit(hh, std): ordinary-income tax saved by suspended passive losses released on a
// fully taxable sale (IRC 469(g)).
//
//	benefit = [fed ordinary tax(W + O - std) + state tax(W + O)] - [same with the released loss deducted]
func ReleasedLossBenefit(hh *HouseholdTax, stdCents int64) *figure.Figure {
	rel := max64(0, hh.ReleasedSuspendedLossesCents)
	baseFed := hh.WagesCents + hh.OtherIncomeCents - stdCents
	baseState := hh.WagesCents + hh.OtherIncomeCents
	fedWithout := taxtables.OrdinaryTaxCents(max64(0, baseFed), hh.TaxYear, hh.FilingStatus)
	fedWith := taxtables.OrdinaryTaxCents(max64(0, baseFed-rel), hh.TaxYear, hh.FilingStatus)
	row := statetax.Row(hh.State)
	stSaving := dec.Zero
	if row != nil {
		stSaving = statetax.TaxOnCents(dec.I(baseState), row, hh.FilingStatus).
			Sub(statetax.TaxOnCents(dec.I(baseState-rel), row, hh.FilingStatus))
	}
	var notes []string
	if rel != 0 {
		notes = append(notes, "IRC 469(g): suspended losses released by a fully taxable disposition are deductible against wages and "+
			"other nonpassive income; this is the federal + state ordinary tax they save")
		if rel > max64(0, baseFed) {
			notes = append(notes, "released losses exceed other ordinary taxable income; the excess offsetting the gain itself is not modeled")
		}
		if row == nil {
			notes = append(notes, "state not in the table: state saving shown as 0")
		}
	}
	return figure.Money("exit_tax.released_loss_benefit", dec.I(fedWithout-fedWith).Add(stSaving),
		figure.L(hh.inp("wages_cents", hh.WagesCents), hh.inp("other_income_cents", hh.OtherIncomeCents),
			figure.Of("standard_deduction_cents", stdCents, "manual", taxtables.Sources[taxtables.TableYear(hh.TaxYear)]),
			figure.Of("released_suspended_losses_cents", rel, "figure", "passive.released_on_sale"),
			figure.M("state", hh.State), figure.M("filing_status", hh.FilingStatus)),
		"[fed_tax(W + O - std) + state_tax(W + O)] - [fed_tax(W + O - std - released) + state_tax(W + O - released)]",
		notes, nil)
}

func max64(a, b int64) int64 {
	if a > b {
		return a
	}
	return b
}

func dateVal(d *dates.Date) any {
	if d == nil {
		return nil
	}
	return *d
}
