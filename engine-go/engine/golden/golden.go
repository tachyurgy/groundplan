// Package golden ports engine/golden.py: maps the plain-JSON `input` of a fixture case onto an engine call and
// returns the plain-JSON result whose keys are compared against `expected`. Same `fn` names as Python.
package golden

import (
	"fmt"
	"github.com/tachyurgy/groundplan/engine-go/engine/analysis"
	"strconv"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/cashflow"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/engine/depreciation"
	"github.com/tachyurgy/groundplan/engine-go/engine/exittax"
	"github.com/tachyurgy/groundplan/engine-go/engine/loans"
	"github.com/tachyurgy/groundplan/engine-go/engine/models"
	"github.com/tachyurgy/groundplan/engine-go/engine/passive"
	"github.com/tachyurgy/groundplan/engine-go/engine/statetax"
	"github.com/tachyurgy/groundplan/engine-go/engine/strategies"
	"github.com/tachyurgy/groundplan/engine-go/engine/taxtables"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// --- dict.get helpers --------------------------------------------------------------------------------------

func get(o *jsonx.Obj, k string) any { return o.MustGet(k) }

func gInt(o *jsonx.Obj, k string, def int64) int64 {
	v, ok := o.Get(k)
	if !ok || v == nil {
		return def
	}
	return AsInt(v)
}

// AsInt converts a JSON number to int64.
func AsInt(v any) int64 {
	switch x := v.(type) {
	case int64:
		return x
	case int:
		return int64(x)
	case jsonx.Float:
		return int64(x)
	case bool:
		if x {
			return 1
		}
		return 0
	case string:
		i, err := strconv.ParseInt(x, 10, 64)
		if err != nil {
			panic(err)
		}
		return i
	}
	panic(fmt.Sprintf("not an int: %T %v", v, v))
}

func gStr(o *jsonx.Obj, k, def string) string {
	if v, ok := o.Get(k); ok && v != nil {
		return v.(string)
	}
	return def
}

func gBool(o *jsonx.Obj, k string, def bool) bool {
	if v, ok := o.Get(k); ok && v != nil {
		return v.(bool)
	}
	return def
}

// AsDec is Python's D(x): strings exactly, ints exactly, floats through repr.
func AsDec(v any) dec.D {
	switch x := v.(type) {
	case string:
		return dec.S(x)
	case int64:
		return dec.I(x)
	case int:
		return dec.I(int64(x))
	case jsonx.Float:
		return dec.F(float64(x))
	case float64:
		return dec.F(x)
	case dec.D:
		return x
	}
	panic(fmt.Sprintf("not a decimal: %T", v))
}

func gDec(o *jsonx.Obj, k string) *dec.D {
	v, ok := o.Get(k)
	if !ok || v == nil {
		return nil
	}
	d := AsDec(v)
	return &d
}

func gDate(o *jsonx.Obj, k string) *dates.Date {
	v, ok := o.Get(k)
	if !ok || v == nil || v == "" {
		return nil
	}
	d := dates.MustParse(v.(string))
	return &d
}

func gIntPtr(o *jsonx.Obj, k string) *int64 {
	v, ok := o.Get(k)
	if !ok || v == nil {
		return nil
	}
	x := AsInt(v)
	return &x
}

func gObj(o *jsonx.Obj, k string) *jsonx.Obj {
	if v, ok := o.Get(k); ok && v != nil {
		return v.(*jsonx.Obj)
	}
	return jsonx.O()
}

func strsAny(ss []string) []any {
	out := make([]any, len(ss))
	for i, s := range ss {
		out[i] = s
	}
	return out
}

// --- functions ---------------------------------------------------------------------------------------------

func depreciationSchedule(i *jsonx.Obj) *jsonx.Obj {
	sched := depreciation.AnnualSchedule(gInt(i, "basis_cents", 0), *gDate(i, "placed_in_service"), gStr(i, "class", "residential"),
		gStr(i, "mode", "table"))
	var total int64
	for _, r := range sched {
		total += r.AmountCents
	}
	out := jsonx.O("years", len(sched), "first_year_cents", sched[0].AmountCents, "first_year_pct", sched[0].Pct,
		"last_year", sched[len(sched)-1].Year, "last_year_cents", sched[len(sched)-1].AmountCents, "total_cents", total)
	if len(sched) > 1 {
		out.Set("second_year_cents", sched[1].AmountCents)
	}
	if i.Has("accumulated_through") {
		out.Set("accumulated_cents", depreciation.AccumulatedThrough(sched, int(gInt(i, "accumulated_through", 0))))
	}
	if len(sched) >= 28 {
		out.Set("year28_cents", sched[27].AmountCents)
	}
	return out
}

func depreciationBasis(i *jsonx.Obj) *jsonx.Obj {
	f := depreciation.DepreciableBasis(gInt(i, "purchase_price_cents", 0), gInt(i, "improvements_cents", 0), gDec(i, "land_pct"), nil)
	bounded := false
	for _, n := range f.Notes {
		if contains(n, "bounded") {
			bounded = true
		}
	}
	return jsonx.O("basis_cents", f.ValueCents, "land_pct", fmt.Sprint(f.Inputs[2].Value), "bounded", bounded, "status", f.Status)
}

func contains(s, sub string) bool {
	for k := 0; k+len(sub) <= len(s); k++ {
		if s[k:k+len(sub)] == sub {
			return true
		}
	}
	return false
}

func ledgerOf(i *jsonx.Obj) []depreciation.LedgerRow {
	v, ok := i.Get("ledger")
	if !ok || v == nil {
		return nil
	}
	var out []depreciation.LedgerRow
	for _, r := range v.([]any) {
		out = append(out, depreciation.LedgerRowFromObj(r.(*jsonx.Obj)))
	}
	return out
}

func depreciationFull(i *jsonx.Obj) *jsonx.Obj {
	r := depreciation.Compute(gInt(i, "purchase_price_cents", 0), gInt(i, "improvements_cents", 0), gDec(i, "land_pct"),
		*gDate(i, "placed_in_service"), gStr(i, "property_type", "sfr"), int(gInt(i, "as_of_year", 0)), gStr(i, "mode", "table"),
		ledgerOf(i), gBool(i, "cost_seg_study", false), nil)
	return jsonx.O("accumulated_cents", r.Accumulated.ValueCents, "current_year_cents", r.CurrentYear.ValueCents,
		"sec1245_cents", r.Sec1245Cents, "outlier", r.Outlier)
}

// Loan builds a LoanInput from a fixture dict.
func Loan(i *jsonx.Obj) *loans.Input {
	ln := &loans.Input{LoanType: gStr(i, "loan_type", "fixed"), BalanceCents: gInt(i, "balance_cents", 0),
		BalanceAsOf: *gDate(i, "balance_as_of"), Rate: AsDec(get(i, "rate")), TermMonths: int(gInt(i, "term_months", 360)),
		IOMonths: int(gInt(i, "io_months", 0)), ArmResetDate: gDate(i, "arm_reset_date"), ArmIndexMargin: gDec(i, "arm_index_margin"),
		ArmIndex: gDec(i, "arm_index"), MonthlyPaymentCents: gIntPtr(i, "monthly_payment_cents"), MaturityDate: gDate(i, "maturity_date"),
		IsPaidOff: gBool(i, "is_paid_off", false), LienPosition: 1}
	if err := ln.Validate(); err != nil {
		panic(err)
	}
	return ln
}

// annualDebt is golden.annual_debt: the loans table's yearly row (analysis.annual_debt), incl. a back-filled year
// before the first scheduled payment.
func annualDebt(i *jsonx.Obj) *jsonx.Obj {
	var scheds []*loans.Schedule
	for _, x := range get(i, "loans").([]any) {
		scheds = append(scheds, loans.Build(Loan(x.(*jsonx.Obj))))
	}
	a, notes := analysis.AnnualDebt(scheds, int(AsInt(get(i, "year"))))
	return jsonx.O("principal_cents", a.PrincipalCents, "interest_cents", a.InterestCents, "debt_service_cents", a.DebtServiceCents,
		"balance_end_cents", a.BalanceEndCents, "backfilled", len(notes) > 0)
}

func loanSchedule(i *jsonx.Obj) *jsonx.Obj {
	s := loans.Build(Loan(i))
	var annual []any
	for _, y := range get(i, "years").([]any) {
		annual = append(annual, s.AnnualSummary(int(AsInt(y))).ToDict())
	}
	out := jsonx.O("months", len(s.Rows), "annual", annual)
	if len(s.Rows) > 0 {
		out.Set("first_payment_cents", s.Rows[0].PaymentCents)
		out.Set("last_balance_cents", s.Rows[len(s.Rows)-1].BalanceCents)
	}
	if v, ok := i.Get("rows"); ok {
		for _, idx := range v.([]any) {
			k := AsInt(idx)
			out.Set(fmt.Sprintf("row%d", k), s.Rows[k-1].ToDict())
		}
	}
	return out
}

// Ops builds YearOperations from a fixture dict.
func Ops(i *jsonx.Obj) *cashflow.YearOperations {
	o := &cashflow.YearOperations{TaxYear: int(gInt(i, "tax_year", 2025))}
	for _, k := range []string{"gross_rent_cents", "other_income_cents", "taxes_cents", "insurance_cents", "repairs_cents", "mgmt_cents",
		"utilities_cents", "hoa_cents", "other_cents", "mortgage_interest_cents", "depreciation_cents"} {
		o.Set(k, gInt(i, k, 0))
	}
	return o
}

func decOr(i *jsonx.Obj, k, def string) *dec.D {
	if d := gDec(i, k); d != nil {
		return d
	}
	d := dec.S(def)
	return &d
}

func cashFlowBridge(i *jsonx.Obj) *jsonx.Obj {
	ops := Ops(i)
	line21 := cashflow.ScheduleELine21(ops)
	ret := cashflow.CashFlowFromReturn(line21, ops.DepreciationCents, gInt(i, "principal_paid_cents", 0), gInt(i, "capital_improvements_paid_cents", 0), nil)
	noi := cashflow.NOI(ops, decOr(i, "vacancy_rate", "0"), decOr(i, "capex_reserve_rate", "0"), nil)
	net := cashflow.NetCashFlow(noi, gInt(i, "principal_paid_cents", 0), ops.MortgageInterestCents, nil)
	return jsonx.O("line21_cents", line21.ValueCents, "cash_flow_from_return_cents", ret.ValueCents, "noi_cents", noi.ValueCents,
		"net_cash_flow_cents", net.ValueCents, "delta_cents", cashflow.BridgeDelta(net, ret).ValueCents)
}

func passiveAllowance(i *jsonx.Obj) *jsonx.Obj {
	r := passive.Apply(gInt(i, "net_rental_cents", 0), gInt(i, "prior_carryforward_cents", 0), gInt(i, "magi_cents", 0),
		gStr(i, "filing_status", "mfj"), gBool(i, "active_participation", true), gBool(i, "re_professional", false), nil, nil)
	return jsonx.O("allowance_cents", r.Allowance.ValueCents, "deductible_cents", r.Deductible.ValueCents,
		"suspended_new_cents", r.SuspendedNew.ValueCents, "carryforward_end_cents", r.CarryforwardEnd.ValueCents)
}

func passiveRelease(i *jsonx.Obj) *jsonx.Obj {
	return jsonx.O("released_cents", passive.ReleasedOnSale(gInt(i, "carryforward_cents", 0), gStr(i, "disposition", "")).ValueCents)
}

func rates(ls []taxtables.Layer) []any {
	out := make([]any, len(ls))
	for k, l := range ls {
		out[k] = l.Rate
	}
	return out
}

func taxStack(i *jsonx.Obj) *jsonx.Obj {
	s := taxtables.Stack(gInt(i, "ordinary_taxable_cents", 0), gInt(i, "sec1245_cents", 0), gInt(i, "sec1250_cents", 0),
		gInt(i, "ltcg_cents", 0), int(gInt(i, "tax_year", 2025)), gStr(i, "filing_status", ""), nil)
	return jsonx.O("tax_ordinary_cents", s.TaxOrdinary.ValueCents, "tax_1245_cents", s.Tax1245.ValueCents,
		"tax_1250_cents", s.Tax1250.ValueCents, "tax_ltcg_cents", s.TaxLTCG.ValueCents, "rates_1250", rates(s.Layers1250),
		"rates_ltcg", rates(s.LayersLTCG))
}

func niit(i *jsonx.Obj) *jsonx.Obj {
	return jsonx.O("niit_cents", taxtables.NIIT(gInt(i, "nii_cents", 0), gInt(i, "magi_cents", 0), gStr(i, "filing_status", ""), nil).ValueCents)
}

func strPtr(i *jsonx.Obj, k string) *string {
	if v, ok := i.Get(k); ok && v != nil {
		s := v.(string)
		return &s
	}
	return nil
}

func stateTax(i *jsonx.Obj) *jsonx.Obj {
	f, findings := statetax.ExitTax(gStr(i, "state", ""), gInt(i, "gain_cents", 0), gInt(i, "other_income_cents", 0),
		gStr(i, "filing_status", ""), strPtr(i, "replacement_state"))
	kinds := make([]any, len(findings))
	for k, x := range findings {
		kinds[k] = x.MustGet("kind")
	}
	return jsonx.O("state_tax_cents", f.ValueCents, "status", f.Status, "finding_kinds", kinds)
}

func hhTax(i *jsonx.Obj) *exittax.HouseholdTax {
	return &exittax.HouseholdTax{FilingStatus: gStr(i, "filing_status", ""), State: gStr(i, "state", "WA"), TaxYear: int(gInt(i, "tax_year", 2025)),
		WagesCents: gInt(i, "wages_cents", 0), OtherIncomeCents: gInt(i, "other_income_cents", 0), MagiCents: gInt(i, "magi_cents", 0),
		ReleasedSuspendedLossesCents: gInt(i, "released_cents", 0), RentalNIICents: gInt(i, "rental_nii_cents", 0)}
}

func exitTax(i *jsonx.Obj) *jsonx.Obj {
	s := gObj(i, "sale")
	sale := &exittax.SaleInput{SalePriceCents: gInt(s, "sale_price_cents", 0), SellingCostRate: *decOr(s, "selling_cost_rate", "0.06"),
		LoanPayoffCents: gInt(s, "loan_payoff_cents", 0), PurchasePriceCents: gInt(s, "purchase_price_cents", 0),
		ImprovementsCents: gInt(s, "improvements_cents", 0), AccumulatedDepreciationCents: gInt(s, "accumulated_depreciation_cents", 0),
		Sec1245Cents: gInt(s, "sec1245_cents", 0), SaleDate: gDate(s, "sale_date"), FormerResidenceUntil: gDate(s, "former_residence_until"),
		RecognizedGainCapCents: gIntPtr(s, "recognized_gain_cap_cents"), Disposition: "taxable_sale"}
	r := exittax.Compute(sale, hhTax(gObj(i, "household")), nil)
	out := jsonx.O()
	for _, k := range []string{"total_gain", "unrecaptured_1250", "sec1245", "ltcg", "sec121_excluded", "fed_1250", "fed_1245", "fed_ltcg",
		"niit", "state", "released_loss_benefit", "total", "net_before_tax", "net_proceeds"} {
		out.Set(k+"_cents", r.F("exit_tax."+k).ValueCents)
	}
	out.Set("rates_1250", rates(r.Stack.Layers1250))
	out.Set("finding_count", len(r.Findings))
	return out
}

// Prop builds a PropertyModel from a fixture dict.
func Prop(i *jsonx.Obj) *models.Property {
	p := models.NewProperty()
	p.ID = gStr(i, "id", "p1")
	p.PropertyType = gStr(i, "property_type", "sfr")
	p.PurchaseDate = *gDate(i, "purchase_date")
	p.PurchasePriceCents = gInt(i, "purchase_price_cents", 0)
	p.PlacedInServiceDate = gDate(i, "placed_in_service_date")
	p.LandPct = gDec(i, "land_pct")
	p.ImprovementsCents = gInt(i, "improvements_cents", 0)
	p.CurrentValueCents = gInt(i, "current_value_cents", 0)
	p.ValueSource = gStr(i, "value_source", "confirmed")
	p.AppreciationRate = gDec(i, "appreciation_rate")
	p.RentGrowthRate = gDec(i, "rent_growth_rate")
	p.ExpenseGrowthRate = gDec(i, "expense_growth_rate")
	p.VacancyRate = gDec(i, "vacancy_rate")
	p.CapexReserveRate = gDec(i, "capex_reserve_rate")
	p.SellingCostRate = gDec(i, "selling_cost_rate")
	if v, ok := i.Get("loans"); ok {
		for _, x := range v.([]any) {
			p.Loans = append(p.Loans, Loan(x.(*jsonx.Obj)))
		}
	}
	for _, kv := range gObj(i, "years").Pairs() {
		y, _ := strconv.Atoi(kv.K)
		yo := kv.V.(*jsonx.Obj).Copy()
		yo.Set("tax_year", int64(y))
		p.AddYear(y, Ops(yo))
	}
	return p
}

func strategiesFn(i *jsonx.Obj) *jsonx.Obj {
	p := Prop(gObj(i, "property"))
	hh := gObj(i, "household")
	h := models.NewHousehold()
	h.FilingStatus = gStr(hh, "filing_status", "")
	h.State = gStr(hh, "state", "WA")
	h.TaxYear = int(gInt(hh, "tax_year", 2025))
	h.WagesCents = gInt(hh, "wages_cents", 0)
	h.OtherIncomeCents = gInt(hh, "other_income_cents", 0)
	h.MagiCents = gInt(hh, "magi_cents", 0)
	h.CarryforwardCents = gInt(hh, "carryforward_cents", 0)
	x := gObj(i, "exchange")
	a := strategies.NewAssumptions()
	a.HorizonYears = int(gInt(i, "horizon_years", 10))
	a.ReinvestRate = *decOr(i, "reinvest_rate", "0.06")
	a.Exchange = strategies.Exchange{ReplacementValueCents: gIntPtr(x, "replacement_value_cents"),
		ReplacementDebtCents: gIntPtr(x, "replacement_debt_cents"), DST: gBool(x, "dst", false),
		LoadRate: *decOr(x, "load_rate", "0.085"), DSTYield: *decOr(x, "dst_yield", "0.05"), CashTakenCents: gInt(x, "cash_taken_cents", 0)}
	r := strategies.Compare(p, h, a)
	by := map[string]*jsonx.Obj{}
	for _, pp := range r.MustGet("paths").([]any) {
		po := pp.(*jsonx.Obj)
		by[po.MustGet("path").(string)] = po.MustGet("terminal").(*jsonx.Obj)
	}
	tw := func(k string) any { return by[k].MustGet("terminal_wealth").(*jsonx.Obj).MustGet("value_cents") }
	return jsonx.O(
		"hold_terminal_wealth_cents", tw("hold"),
		"sell_terminal_wealth_cents", tw("sell"),
		"exchange_terminal_wealth_cents", tw("exchange"),
		"sell_tax_now_cents", by["sell"].MustGet("tax_paid_now_cents"),
		"sell_released_cents", by["sell"].MustGet("suspended_losses_released_cents"),
		"exchange_released_cents", by["exchange"].MustGet("suspended_losses_released_cents"),
		"boot_cents", by["exchange"].MustGet("boot_cents"), "mortgage_boot_cents", by["exchange"].MustGet("mortgage_boot_cents"),
		"tax_on_boot_cents", by["exchange"].MustGet("tax_on_boot_cents"), "gain_deferred_cents", by["exchange"].MustGet("gain_deferred_cents"),
		"dst_load_cents", by["exchange"].MustGet("dst_load_cents"),
		"cash_after_tax_cents", by["exchange"].MustGet("cash_after_tax_cents"),
		"cash_after_tax_at_horizon_cents", by["exchange"].MustGet("cash_after_tax_at_horizon_cents"),
		"replacement_value_cents", by["exchange"].MustGet("replacement_value_cents"))
}

// Functions is the dispatcher table (same names as golden.FUNCTIONS).
var Functions = map[string]func(*jsonx.Obj) *jsonx.Obj{
	"depreciation_schedule": depreciationSchedule, "depreciation_basis": depreciationBasis, "depreciation_full": depreciationFull,
	"loan_schedule": loanSchedule, "annual_debt": annualDebt, "cash_flow_bridge": cashFlowBridge, "passive_allowance": passiveAllowance,
	"passive_release": passiveRelease, "tax_stack": taxStack, "niit": niit, "state_tax": stateTax, "exit_tax": exitTax,
	"strategies": strategiesFn,
}

// RunCase runs one fixture case.
func RunCase(c *jsonx.Obj) *jsonx.Obj {
	fn := Functions[c.MustGet("fn").(string)]
	if fn == nil {
		panic("unknown fn " + c.MustGet("fn").(string))
	}
	return fn(c.MustGet("input").(*jsonx.Obj))
}

// Compare returns the diffs between expected and actual (every expected key must be equal).
func Compare(expected, actual *jsonx.Obj) []string {
	var diffs []string
	for _, kv := range expected.Pairs() {
		av, ok := actual.Get(kv.K)
		if !ok {
			diffs = append(diffs, "missing key "+kv.K)
			continue
		}
		if !jsonx.Equal(jsonx.MustDecode(jsonx.MustMarshal(kv.V)), jsonx.MustDecode(jsonx.MustMarshal(av))) {
			diffs = append(diffs, fmt.Sprintf("%s: expected %s got %s", kv.K, jsonx.MustMarshal(kv.V), jsonx.MustMarshal(av)))
		}
	}
	return diffs
}

var _ = strsAny
