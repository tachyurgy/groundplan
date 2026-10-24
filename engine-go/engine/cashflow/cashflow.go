// Package cashflow ports engine/cashflow.py: NOI, net cash flow and the Schedule E -> cash-flow bridge.
//
// NOI = gross_rent x (1 - vacancy) + other_income - (taxes + insurance + repairs + mgmt + utilities + hoa + other)
//
//   - gross_rent x capex_reserve_rate
//
// net_cash_flow = NOI - debt service; cash_flow_from_return = line21 + line18 - principal - capital improvements.
package cashflow

import (
	"fmt"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/figure"
)

// ExpenseLines in Schedule E order.
var ExpenseLines = []string{"taxes", "insurance", "repairs", "mgmt", "utilities", "hoa", "other"}

// YearOperations is one year of rents and expenses.
type YearOperations struct {
	TaxYear               int
	GrossRentCents        int64
	OtherIncomeCents      int64
	TaxesCents            int64
	InsuranceCents        int64
	RepairsCents          int64
	MgmtCents             int64
	UtilitiesCents        int64
	HoaCents              int64
	OtherCents            int64
	MortgageInterestCents int64
	DepreciationCents     int64
	Sources               map[string]*figure.Input
}

// Get returns a field by its Python name (e.g. "taxes_cents").
func (o *YearOperations) Get(key string) int64 {
	switch key {
	case "gross_rent_cents":
		return o.GrossRentCents
	case "other_income_cents":
		return o.OtherIncomeCents
	case "taxes_cents":
		return o.TaxesCents
	case "insurance_cents":
		return o.InsuranceCents
	case "repairs_cents":
		return o.RepairsCents
	case "mgmt_cents":
		return o.MgmtCents
	case "utilities_cents":
		return o.UtilitiesCents
	case "hoa_cents":
		return o.HoaCents
	case "other_cents":
		return o.OtherCents
	case "mortgage_interest_cents":
		return o.MortgageInterestCents
	case "depreciation_cents":
		return o.DepreciationCents
	}
	panic("unknown operations key " + key)
}

// Set assigns a field by its Python name.
func (o *YearOperations) Set(key string, v int64) {
	switch key {
	case "gross_rent_cents":
		o.GrossRentCents = v
	case "other_income_cents":
		o.OtherIncomeCents = v
	case "taxes_cents":
		o.TaxesCents = v
	case "insurance_cents":
		o.InsuranceCents = v
	case "repairs_cents":
		o.RepairsCents = v
	case "mgmt_cents":
		o.MgmtCents = v
	case "utilities_cents":
		o.UtilitiesCents = v
	case "hoa_cents":
		o.HoaCents = v
	case "other_cents":
		o.OtherCents = v
	case "mortgage_interest_cents":
		o.MortgageInterestCents = v
	case "depreciation_cents":
		o.DepreciationCents = v
	default:
		panic("unknown operations key " + key)
	}
}

// Inp is YearOperations.inp(key, value): the per-field provenance override or a manual input.
func (o *YearOperations) Inp(key string, value int64) *figure.Input {
	if in := o.Sources[key]; in != nil {
		return in
	}
	return figure.M(key, value)
}

// ExpensesTotal sums the seven operating expense lines.
func (o *YearOperations) ExpensesTotal() int64 {
	var t int64
	for _, k := range ExpenseLines {
		t += o.Get(k + "_cents")
	}
	return t
}

// optD is Python's D(x or 0): None and any zero (falsy Decimal) become the integer 0.
func optD(x *dec.D) dec.D {
	if x == nil || x.IsZero() {
		return dec.Zero
	}
	return *x
}

// OrZero is exported for the other engine packages.
func OrZero(x *dec.D) dec.D { return optD(x) }

func srcFor(x *dec.D) string {
	if x == nil {
		return "default"
	}
	return "manual"
}

// NOI is noi(ops, vacancy_rate, capex_reserve_rate, blocked).
func NOI(ops *YearOperations, vacancyRate, capexReserveRate *dec.D, blocked figure.KeySet) *figure.Figure {
	vac := optD(vacancyRate)
	capexRate := optD(capexReserveRate)
	rent := dec.I(ops.GrossRentCents)
	effective := rent.Mul(dec.One.Sub(vac))
	capex := rent.Mul(capexRate)
	total := effective.Add(dec.I(ops.OtherIncomeCents)).Sub(dec.I(ops.ExpensesTotal())).Sub(capex)
	inputs := figure.L(ops.Inp("gross_rent_cents", ops.GrossRentCents), ops.Inp("other_income_cents", ops.OtherIncomeCents))
	for _, k := range ExpenseLines {
		inputs = append(inputs, ops.Inp(k+"_cents", ops.Get(k+"_cents")))
	}
	inputs = append(inputs, figure.Of("vacancy_rate", vac, srcFor(vacancyRate)), figure.Of("capex_reserve_rate", capexRate, srcFor(capexReserveRate)))
	return figure.Money("cash_flow.noi", total, inputs,
		"gross_rent*(1-vacancy) + other_income - (taxes+insurance+repairs+mgmt+utilities+hoa+other) - gross_rent*capex_reserve_rate",
		nil, blocked)
}

// NetCashFlow is net_cash_flow(noi, principal, interest).
func NetCashFlow(noiFig *figure.Figure, principalCents, interestCents int64, loanInputs []*figure.Input) *figure.Figure {
	inputs := figure.L(figure.Fig(noiFig), figure.Of("principal_paid_cents", principalCents, "figure", "loans.schedule"),
		figure.Of("interest_paid_cents", interestCents, "figure", "loans.schedule"))
	inputs = append(inputs, loanInputs...)
	return figure.Money("cash_flow.net_annual", noiFig.Dec().Sub(dec.I(principalCents)).Sub(dec.I(interestCents)), inputs,
		"NOI - (principal + interest)", nil, nil)
}

// ScheduleELine21 = rents + other income - expenses - mortgage interest - depreciation.
func ScheduleELine21(ops *YearOperations) *figure.Figure {
	total := dec.I(ops.GrossRentCents).Add(dec.I(ops.OtherIncomeCents)).Sub(dec.I(ops.ExpensesTotal())).
		Sub(dec.I(ops.MortgageInterestCents)).Sub(dec.I(ops.DepreciationCents))
	inputs := figure.L(ops.Inp("gross_rent_cents", ops.GrossRentCents), ops.Inp("other_income_cents", ops.OtherIncomeCents))
	for _, k := range ExpenseLines {
		inputs = append(inputs, ops.Inp(k+"_cents", ops.Get(k+"_cents")))
	}
	inputs = append(inputs, ops.Inp("mortgage_interest_cents", ops.MortgageInterestCents), ops.Inp("depreciation_cents", ops.DepreciationCents))
	return figure.Money("cash_flow.schedule_e.line21", total, inputs,
		"line3 rents + line4 royalties/other - lines 5..19 expenses (incl. line12 interest, line18 depreciation)", nil, nil)
}

// CashFlowFromReturn is cash_flow_from_return(...).
func CashFlowFromReturn(line21 *figure.Figure, depreciationCents, principalPaidCents, capitalImprovementsPaidCents int64,
	extra []*figure.Input) *figure.Figure {
	inputs := figure.L(figure.Fig(line21), figure.Of("line18_depreciation_cents", depreciationCents, "document", "Schedule E line 18"),
		figure.Of("principal_paid_cents", principalPaidCents, "figure", "loans.schedule"),
		figure.M("capital_improvements_paid_cents", capitalImprovementsPaidCents))
	inputs = append(inputs, extra...)
	v := line21.Dec().Add(dec.I(depreciationCents)).Sub(dec.I(principalPaidCents)).Sub(dec.I(capitalImprovementsPaidCents))
	return figure.Money("cash_flow.from_return", v, inputs, "line21 + line18_depreciation - principal_paid - capital_improvements_paid",
		[]string{"interest is inside line 21 already and is not subtracted again"}, nil)
}

// BridgeDelta is bridge_delta(engine_cf, return_cf).
func BridgeDelta(engineCF, returnCF *figure.Figure) *figure.Figure {
	delta := engineCF.Dec().Sub(returnCF.Dec())
	var notes []string
	if !delta.IsZero() {
		notes = append(notes, "delta = vacancy/capex reserve assumptions and any expense lines the return books differently")
	}
	return figure.Money("cash_flow.bridge_delta", delta, figure.L(figure.Fig(engineCF), figure.Fig(returnCF)),
		"cash_flow.net_annual - cash_flow.from_return", notes, nil)
}

// ProjectOperations grows rent/other income by rent_growth and every expense line by expense_growth.
func ProjectOperations(base *YearOperations, yearsAhead int, rentGrowth, expenseGrowth *dec.D) *YearOperations {
	rg := dec.One.Add(optD(rentGrowth)).PowInt(yearsAhead)
	eg := dec.One.Add(optD(expenseGrowth)).PowInt(yearsAhead)
	o := &YearOperations{
		TaxYear:               base.TaxYear + yearsAhead,
		GrossRentCents:        dec.I(base.GrossRentCents).Mul(rg).Cents(),
		OtherIncomeCents:      dec.I(base.OtherIncomeCents).Mul(rg).Cents(),
		MortgageInterestCents: 0,
		DepreciationCents:     base.DepreciationCents,
	}
	for _, k := range ExpenseLines {
		o.Set(k+"_cents", dec.I(base.Get(k+"_cents")).Mul(eg).Cents())
	}
	ref := fmt.Sprintf("projection(+%dy)", yearsAhead)
	o.Sources = map[string]*figure.Input{}
	for _, k := range projectedKeys {
		o.Sources[k] = figure.Of(k, o.Get(k), "figure", ref)
	}
	return o
}

// projectedKeys is the kw dict order in project_operations (only *_cents keys get a source).
var projectedKeys = []string{"gross_rent_cents", "other_income_cents", "mortgage_interest_cents", "depreciation_cents",
	"taxes_cents", "insurance_cents", "repairs_cents", "mgmt_cents", "utilities_cents", "hoa_cents", "other_cents"}
