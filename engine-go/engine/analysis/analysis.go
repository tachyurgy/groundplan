// Package analysis ports engine/analysis.py: compose the engine modules into the per-property analysis (pure).
// The output shape matches web/src/api/types.ts PropertyAnalysis (minus property and observations). Python's
// private "_..." keys are fields on Result instead of members of the JSON object.
package analysis

import (
	"fmt"
	"strings"

	"github.com/cockroachdb/apd/v3"
	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/cashflow"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/engine/depreciation"
	"github.com/tachyurgy/groundplan/engine-go/engine/equity"
	"github.com/tachyurgy/groundplan/engine-go/engine/exittax"
	"github.com/tachyurgy/groundplan/engine-go/engine/figure"
	"github.com/tachyurgy/groundplan/engine-go/engine/loans"
	"github.com/tachyurgy/groundplan/engine-go/engine/models"
	"github.com/tachyurgy/groundplan/engine-go/engine/taxtables"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

var methodForClass = map[string]string{"residential": "sl_27_5", "nonresidential": "sl_39", "land": "sl_27_5"}

// LoanSchedules builds one schedule per lien.
func LoanSchedules(p *models.Property) []*loans.Schedule {
	out := make([]*loans.Schedule, len(p.Loans))
	for i, ln := range p.Loans {
		out[i] = loans.Build(ln)
	}
	return out
}

func lenderOr(s *loans.Schedule, fallback string) string {
	if s.Loan.Lender != "" {
		return s.Loan.Lender
	}
	return fallback
}

// AnnualDebt is annual_debt(scheds, year): combined annual debt with the before-statement back-fill.
func AnnualDebt(scheds []*loans.Schedule, year int) (loans.Annual, []string) {
	out := loans.CombinedAnnual(scheds, year)
	var notes []string
	for _, s := range scheds {
		if len(s.Rows) == 0 {
			continue
		}
		anyYear := false
		for _, r := range s.Rows {
			if r.Year == year {
				anyYear = true
				break
			}
		}
		if anyYear || year >= s.Rows[0].Year {
			continue
		}
		first := s.Rows
		if len(first) > 12 {
			first = first[:12]
		}
		for _, r := range first {
			out.PrincipalCents += r.PrincipalCents
			out.InterestCents += r.InterestCents
			out.DebtServiceCents += r.PaymentCents
		}
		out.BalanceEndCents += s.Loan.BalanceCents
		notes = append(notes, fmt.Sprintf("%s: %d debt service taken from the first 12 months after the %s statement",
			lenderOr(s, "loan"), year, dates.ISO(s.Loan.BalanceAsOf)))
	}
	return out, notes
}

// LoanAnnualFor is the per-loan AnnualDebt.
func LoanAnnualFor(s *loans.Schedule, year int) loans.Annual {
	a, _ := AnnualDebt([]*loans.Schedule{s}, year)
	return a
}

// OpsForYear returns the actual year if on file, else the latest earlier year projected forward.
func OpsForYear(p *models.Property, year int) (*cashflow.YearOperations, *int) {
	if o, ok := p.Years[year]; ok {
		return o, nil
	}
	base := 0
	found := false
	for y := range p.Years {
		if y < year && (!found || y > base) {
			base, found = y, true
		}
	}
	if !found {
		return nil, nil
	}
	rg, _ := models.RateOrDefault(p.RentGrowthRate, "rent_growth_rate")
	eg, _ := models.RateOrDefault(p.ExpenseGrowthRate, "expense_growth_rate")
	return cashflow.ProjectOperations(p.Years[base], year-base, &rg, &eg), &base
}

// HouseholdTax builds the exit-tax household.
func HouseholdTax(h *models.Household, released, rentalNII int64, taxYear int) *exittax.HouseholdTax {
	ty := taxYear
	if ty == 0 {
		ty = h.TaxYear
	}
	return &exittax.HouseholdTax{FilingStatus: h.FilingStatus, State: h.State, TaxYear: ty, WagesCents: h.WagesCents,
		OtherIncomeCents: h.OtherIncomeCents, MagiCents: h.MagiCents, ReleasedSuspendedLossesCents: released, RentalNIICents: rentalNII}
}

// DepreciationFor is depreciation_for(p, year, mode).
func DepreciationFor(p *models.Property, year int, mode string) *depreciation.Result {
	return depreciation.Compute(p.PurchasePriceCents, p.ImprovementsCents, p.LandPct, p.InService(), p.PropertyType, year, mode,
		p.Ledger, p.CostSegStudy, map[string]*figure.Input{"purchase_price_cents": figure.Of("purchase_price_cents", p.PurchasePriceCents,
			"manual", "purchase price (closing statement / manual)")})
}

// ValueInput is the provenance of the current value.
func ValueInput(p *models.Property) *figure.Input {
	src := "public_data"
	if p.ValueSource == "confirmed" {
		src = "manual"
	}
	asOf := "unknown"
	if p.ValueAsOf != nil {
		asOf = dates.ISO(*p.ValueAsOf)
	}
	return figure.Of("current_value_cents", p.CurrentValueCents, src, fmt.Sprintf("%s value as of %s", p.ValueSource, asOf))
}

// RateNum is _rate_num: float(Decimal(str(x))) or None.
func RateNum(x *dec.D) any {
	if x == nil {
		return nil
	}
	return jsonx.Float(x.Float64())
}

// Result is the analysis dict plus the private "_" keys.
type Result struct {
	Out           *jsonx.Obj
	Figs          map[string]*figure.Figure
	FigOrder      []string
	Year          int
	NetCents      *int64
	NOICents      *int64
	Line21Cents   *int64
	DSCR          *string
	EquityCents   *int64
	ROE           *string
	ExitTaxCents  int64
	DepOutlier    bool
	Balances      []int64
	AnnualDebt    loans.Annual
	Concentration *string
	LandBounded   bool
	Findings      []*jsonx.Obj
}

func objs(xs []*jsonx.Obj) []any {
	out := make([]any, len(xs))
	for i, x := range xs {
		out[i] = x
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

func sum(xs []int64) int64 {
	var t int64
	for _, x := range xs {
		t += x
	}
	return t
}

// AnalyzeProperty is analyze_property(p, h, year, horizon, carryforward_release, mode).
func AnalyzeProperty(p *models.Property, h *models.Household, year, horizon int, carryforwardRelease int64, mode string) *Result {
	if year == 0 {
		year = h.TaxYear
	}
	if mode == "" {
		mode = "table"
	}
	res := &Result{Figs: map[string]*figure.Figure{}, Year: year}
	reg := func(f *figure.Figure) *figure.Figure {
		if _, ok := res.Figs[f.Key]; !ok {
			res.FigOrder = append(res.FigOrder, f.Key)
		}
		res.Figs[f.Key] = f
		return f
	}
	var notes []string
	scheds := LoanSchedules(p)
	annual, debtNotes := AnnualDebt(scheds, year)
	notes = append(notes, debtNotes...)
	ops, projectedFrom := OpsForYear(p, year)
	if projectedFrom != nil && *projectedFrom != 0 {
		notes = append(notes, fmt.Sprintf("no operating data for %d: projected from %d", year, *projectedFrom))
	}
	vac, vacSrc := models.RateOrDefault(p.VacancyRate, "vacancy_rate")
	capex, capexSrc := models.RateOrDefault(p.CapexReserveRate, "capex_reserve_rate")
	blocked := p.BlockedKeys
	vacIn := figure.Of("vacancy_rate", vac, vacSrc)
	capexIn := figure.Of("capex_reserve_rate", capex, capexSrc)

	// ---------------- cash flow ----------------
	if ops == nil {
		ops = &cashflow.YearOperations{TaxYear: year}
		notes = append(notes, fmt.Sprintf("no operating data on file for %d or earlier", year))
	}
	rentIn := ops.Inp("gross_rent_cents", ops.GrossRentCents)
	grossRent := reg(figure.MoneyI("cash_flow.gross_rent", ops.GrossRentCents, figure.L(rentIn), "Schedule E line 3 rents received", nil, blocked))
	vacancyLoss := reg(figure.Money("cash_flow.vacancy_loss", dec.I(ops.GrossRentCents).Mul(vac), figure.L(figure.Fig(grossRent), vacIn),
		"gross_rent * vacancy_rate", nil, nil))
	otherIncome := reg(figure.MoneyI("cash_flow.other_income", ops.OtherIncomeCents,
		figure.L(ops.Inp("other_income_cents", ops.OtherIncomeCents)), "other rental income", nil, nil))
	var expInputs []*figure.Input
	for _, k := range cashflow.ExpenseLines {
		expInputs = append(expInputs, ops.Inp(k+"_cents", ops.Get(k+"_cents")))
	}
	opex := reg(figure.MoneyI("cash_flow.operating_expenses", ops.ExpensesTotal(), expInputs,
		"taxes + insurance + repairs + mgmt + utilities + hoa + other (excludes interest and depreciation)", nil, blocked))
	capexRes := reg(figure.Money("cash_flow.capex_reserve", dec.I(ops.GrossRentCents).Mul(capex), figure.L(figure.Fig(grossRent), capexIn),
		"gross_rent * capex_reserve_rate", nil, nil))
	noiVal := grossRent.Dec().Sub(vacancyLoss.Dec()).Add(otherIncome.Dec()).Sub(opex.Dec()).Sub(capexRes.Dec())
	noiFig := reg(figure.Money("cash_flow.noi", noiVal, figure.L(figure.Fig(grossRent), figure.Fig(vacancyLoss), figure.Fig(otherIncome),
		figure.Fig(opex), figure.Fig(capexRes)), "gross_rent - vacancy_loss + other_income - operating_expenses - capex_reserve", nil, blocked))
	var loanInputs []*figure.Input
	for i, s := range scheds {
		loanInputs = append(loanInputs, figure.Of(fmt.Sprintf("loan[%d].debt_service_cents", i), LoanAnnualFor(s, year).DebtServiceCents,
			"figure", fmt.Sprintf("loans.schedule[%s]", lenderOr(s, fmt.Sprint(i)))))
	}
	if len(loanInputs) == 0 {
		loanInputs = figure.L(figure.M("debt_service_cents", int64(0)))
	}
	debtService := reg(figure.MoneyI("cash_flow.debt_service", annual.DebtServiceCents, loanInputs,
		"sum over liens of (principal + interest) paid in the year", debtNotes, nil))
	net := reg(figure.Money("cash_flow.net_annual", noiFig.Dec().Sub(debtService.Dec()), figure.L(figure.Fig(noiFig), figure.Fig(debtService)),
		"NOI - debt service (principal + interest)", nil, blocked))
	res.NetCents = net.ValueCents
	line21 := reg(cashflow.ScheduleELine21(ops))
	depLine := reg(figure.MoneyI("cash_flow.schedule_e.line18_depreciation", ops.DepreciationCents,
		figure.L(ops.Inp("depreciation_cents", ops.DepreciationCents)), "Schedule E line 18 depreciation", nil, nil))
	principal := reg(figure.MoneyI("cash_flow.principal_paid", annual.PrincipalCents,
		figure.L(figure.Of("principal_cents", annual.PrincipalCents, "figure", "loans.schedule")),
		"sum of principal paid on all liens in the year", debtNotes, nil))
	capimpC := p.CapitalImprovementsPaid[year]
	capimp := reg(figure.MoneyI("cash_flow.capital_improvements_paid", capimpC, figure.L(figure.M("capital_improvements_paid_cents", capimpC)),
		"capital improvements paid in cash (Form 4562 additions)", nil, nil))
	fromRet := reg(figure.Money("cash_flow.from_return", line21.Dec().Add(depLine.Dec()).Sub(principal.Dec()).Sub(capimp.Dec()),
		figure.L(figure.Fig(line21), figure.Fig(depLine), figure.Fig(principal), figure.Fig(capimp)),
		"line21 + line18_depreciation - principal_paid - capital_improvements_paid",
		[]string{"interest is already inside line 21 and is never subtracted twice"}, nil))
	delta := reg(cashflow.BridgeDelta(net, fromRet))
	rg, _ := models.RateOrDefault(p.RentGrowthRate, "rent_growth_rate")
	eg, _ := models.RateOrDefault(p.ExpenseGrowthRate, "expense_growth_rate")
	var projection []any
	for t := 1; t <= horizon; t++ {
		o := cashflow.ProjectOperations(ops, t, &rg, &eg)
		a, _ := AnnualDebt(scheds, year+t)
		n := cashflow.NOI(o, &vac, &capex, nil)
		projection = append(projection, jsonx.O("year", year+t, "noi_cents", n.ValueCents, "debt_service_cents", a.DebtServiceCents,
			"net_cash_flow_cents", n.VC()-a.DebtServiceCents))
	}
	if projection == nil {
		projection = []any{}
	}
	dscr := reg(loans.DSCR(noiFig.VC(), annual.DebtServiceCents, figure.L(figure.Fig(noiFig), figure.Fig(debtService))))
	var pf any
	if projectedFrom != nil {
		pf = int64(*projectedFrom)
	}
	cf := jsonx.O("gross_rent", grossRent.ToDict(), "vacancy_loss", vacancyLoss.ToDict(), "other_income", otherIncome.ToDict(),
		"operating_expenses", opex.ToDict(), "capex_reserve", capexRes.ToDict(), "noi", noiFig.ToDict(),
		"debt_service", debtService.ToDict(), "net_cash_flow", net.ToDict(), "dscr", dscr.ToDict(),
		"projection", projection, "projected_from_year", pf,
		"schedule_e_bridge", jsonx.O("line21", line21.ToDict(), "line18_depreciation", depLine.ToDict(),
			"principal_paid", principal.ToDict(), "capital_improvements_paid", capimp.ToDict(),
			"cash_flow_from_return", fromRet.ToDict(), "delta_vs_engine", delta.ToDict()))

	// ---------------- equity ----------------
	asOf := dates.New(year, 12, 31)
	balances := make([]int64, len(scheds))
	for i, s := range scheds {
		if len(s.Rows) > 0 && s.Rows[0].Year <= year {
			balances[i] = s.BalanceAt(asOf)
		} else if s.Loan.IsPaidOff {
			balances[i] = 0
		} else {
			balances[i] = s.Loan.BalanceCents
		}
	}
	vin := ValueInput(p)
	valueFig := reg(figure.MoneyI("equity.value", p.CurrentValueCents, figure.L(vin), "current value", nil, blocked))
	var debtInputs []*figure.Input
	for i, s := range scheds {
		debtInputs = append(debtInputs, figure.Of(fmt.Sprintf("loan[%d].balance_cents", i), balances[i], "figure",
			fmt.Sprintf("loans.schedule[%s]", lenderOr(s, fmt.Sprint(i)))))
	}
	if len(debtInputs) == 0 {
		debtInputs = figure.L(figure.M("balance_cents", int64(0)))
	}
	debtFig := reg(figure.MoneyI("equity.total_debt", sum(balances), debtInputs,
		fmt.Sprintf("sum of lien balances at %s (paid-off liens = 0)", dates.ISO(asOf)), nil, blocked))
	eq := reg(figure.Money("equity.net", valueFig.Dec().Sub(debtFig.Dec()), figure.L(figure.Fig(valueFig), figure.Fig(debtFig)),
		"current_value - sum(loan balances)", nil, blocked))
	lend := reg(equity.Lendable(p.CurrentValueCents, balances, vin))
	appr, apprSrc := models.RateOrDefault(p.AppreciationRate, "appreciation_rate")
	var beginBalances int64
	for _, s := range scheds {
		beginBalances += s.BalanceAt(dates.New(year-1, 12, 31))
	}
	valueBegin := dec.I(p.CurrentValueCents).Quo(dec.One.Add(appr)).Int()
	eqBegin := valueBegin - beginBalances
	apprFig := reg(equity.AppreciationThisYear(valueBegin, &appr, apprSrc))
	numer := dec.I(derefOr(res.NetCents)).Add(principal.Dec()).Add(apprFig.Dec())
	var roeRate *dec.D
	if eqBegin > 0 {
		r := numer.Quo(dec.I(eqBegin))
		roeRate = &r
	}
	var roeNotes []string
	if eqBegin <= 0 {
		roeNotes = []string{"equity at start of year is not positive: ROE undefined"}
	}
	roeFig := reg(figure.Money("equity.roe", numer, figure.L(figure.Fig(net), figure.Fig(principal), figure.Fig(apprFig),
		figure.Of("equity_begin_cents", eqBegin, "figure", "equity.net (begin of year)")),
		"numerator = net_cash_flow + principal_paydown + appreciation_this_year; roe_rate = numerator / equity_begin_of_year", roeNotes, nil))
	var conc *figure.Figure
	if h.NetWorthCents != nil && *h.NetWorthCents != 0 {
		conc = equity.Concentration(p.CurrentValueCents, h.NetWorthCents)
	}
	var roeRateOut, concOut, concRate any
	if roeRate != nil {
		q := roeRate.Quantize(6, apd.RoundHalfEven)
		roeRateOut = RateNum(&q)
	}
	if conc != nil {
		concOut = conc.ToDict()
		if conc.Value != nil {
			v := dec.S(*conc.Value)
			concRate = RateNum(&v)
		}
	}
	eqOut := jsonx.O("value", valueFig.ToDict(), "total_debt", debtFig.ToDict(), "equity", eq.ToDict(), "lendable_equity", lend.ToDict(),
		"roe", roeFig.ToDict(), "roe_rate", roeRateOut, "concentration", concOut, "concentration_rate", concRate,
		"appreciation_this_year", apprFig.ToDict())

	// ---------------- appreciation ----------------
	cagr := equity.CAGR(p.PurchasePriceCents, p.CurrentValueCents, p.PurchaseDate, asOf)
	var projRows []any
	for n := 0; n <= horizon; n++ {
		v := equity.ProjectedValue(p.CurrentValueCents, &appr, n, vin, apprSrc).VC()
		var d int64
		for _, s := range scheds {
			if len(s.Rows) > 0 && s.Rows[0].Year <= year+n {
				d += s.BalanceAt(dates.New(year+n, 12, 31))
			} else if !s.Loan.IsPaidOff {
				d += s.Loan.BalanceCents
			}
		}
		projRows = append(projRows, jsonx.O("year", year+n, "value_cents", v, "equity_cents", v-d, "debt_cents", d))
	}
	projH := reg(equity.ProjectedValue(p.CurrentValueCents, &appr, horizon, vin, apprSrc))
	var cagrNum any
	if cagr.Value != nil {
		v := dec.S(*cagr.Value)
		cagrNum = RateNum(&v)
	}
	appreciation := jsonx.O("rate", RateNum(&appr), "rate_source", apprSrc, "cagr_since_purchase", cagrNum, "cagr", cagr.ToDict(),
		"projected", projRows, "projected_value_horizon", projH.ToDict())

	// ---------------- depreciation ----------------
	dep := DepreciationFor(p, year, mode)
	pclass := depreciation.PropertyClass(p.PropertyType)
	method := methodForClass[pclass]
	if p.CostSegStudy {
		method = "cost_seg"
	}
	reg(dep.Basis)
	reg(dep.Accumulated)
	reg(dep.CurrentYear)
	sched := make([]any, len(dep.Schedule))
	for i, r := range dep.Schedule {
		sched[i] = jsonx.O("year", r.Year, "amount_cents", r.AmountCents, "method", method, "pct", jsonx.Float(dec.S(r.Pct).Float64()))
	}
	landBounded := false
	for _, n := range dep.Basis.Notes {
		if strings.Contains(n, "bounded") {
			landBounded = true
		}
	}
	depOut := jsonx.O("schedule", sched, "accumulated_cents", dep.Accumulated.ValueCents, "accumulated", dep.Accumulated.ToDict(),
		"depreciable_basis", dep.Basis.ToDict(), "annual", dep.CurrentYear.ToDict(), "method", method, "mode", mode,
		"property_class", pclass, "land_pct_bounded", landBounded, "sec1245_cents", dep.Sec1245Cents, "outlier", dep.Outlier,
		"notes", strs(dep.Notes), "accumulated_through_year", year-1)

	// ---------------- exit tax: sale at start of year+1 at current value ----------------
	depSale := DepreciationFor(p, year+1, mode)
	sc, scSrc := models.RateOrDefault(p.SellingCostRate, "selling_cost_rate")
	saleDate := dates.New(year+1, 1, 15)
	sale := &exittax.SaleInput{SalePriceCents: p.CurrentValueCents, SellingCostRate: sc, LoanPayoffCents: sum(balances),
		PurchasePriceCents: p.PurchasePriceCents, ImprovementsCents: p.ImprovementsCents,
		AccumulatedDepreciationCents: depSale.Accumulated.VC() - depSale.Sec1245Cents, Sec1245Cents: depSale.Sec1245Cents,
		SaleDate: &saleDate, FormerResidenceUntil: p.FormerResidenceUntil, Disposition: "taxable_sale",
		Sources: map[string]*figure.Input{"sale_price_cents": vin}}
	ex := exittax.Compute(sale, HouseholdTax(h, carryforwardRelease, 0, year+1), blocked)
	if scSrc != "default" {
		sel := ex.F("exit_tax.selling_costs")
		sel.Inputs[1].Source.Type = "manual"
		sel.Status = figure.DeriveStatus(sel.Inputs, blocked)
	}
	for _, k := range ex.Order {
		reg(ex.Figures[k])
	}
	xf := ex.F
	salePrice := reg(figure.MoneyI("exit_tax.sale_price", p.CurrentValueCents, figure.L(vin), "assumed sale price = current value", nil, blocked))
	payoffs := reg(figure.MoneyI("exit_tax.loan_payoffs", sum(balances), figure.L(figure.Fig(debtFig)), "sum of lien balances at sale", nil, nil))
	exitOut := jsonx.O("sale_price", salePrice.ToDict(), "selling_costs", xf("exit_tax.selling_costs").ToDict(), "loan_payoffs", payoffs.ToDict())
	for _, k := range []string{"net_before_tax", "adjusted_basis", "total_gain", "unrecaptured_1250", "sec1245", "ltcg", "fed_1250",
		"fed_1245", "fed_ltcg", "niit", "state", "net_proceeds", "sec121_excluded", "ordinary_taxable_other", "amount_realized",
		"effective_rate_on_gain"} {
		exitOut.Set(k, xf("exit_tax."+k).ToDict())
	}
	stackNotes := append(append([]string{}, ex.Stack.Notes...),
		"Order: ordinary income (wages + other - standard deduction - released suspended losses) fills the brackets first; "+
			"Sec 1245 recapture stacks next at full ordinary rates; unrecaptured Sec 1250 gain stacks on top at min(bracket, 25%); "+
			"the remaining long-term gain lands last at 0/15/20% by where it falls.")
	exitOut.Set("exit_tax_total", xf("exit_tax.total").ToDict())
	exitOut.Set("stacking_notes", strs(stackNotes))
	exitOut.Set("layers_1250", layers(ex.Stack.Layers1250))
	exitOut.Set("layers_ltcg", layers(ex.Stack.LayersLTCG))
	exitOut.Set("findings", objs(ex.Findings))
	exitOut.Set("sale_assumed_on", dates.ISO(saleDate))
	exitOut.Set("suspended_losses_released_cents", carryforwardRelease)

	// ---------------- loans ----------------
	var loansOut []any
	for i, ln := range p.Loans {
		s := scheds[i]
		var rows []any
		for y := year; y <= year+horizon; y++ {
			a := LoanAnnualFor(s, y)
			var yrRows []loans.MonthRow
			for _, r := range s.Rows {
				if r.Year == y {
					yrRows = append(yrRows, r)
				}
			}
			var marker any
			balloon := false
			for _, r := range yrRows {
				if r.Phase == "balloon_due" {
					balloon = true
				}
			}
			switch {
			case balloon:
				marker = "balloon"
			case ln.ArmResetDate != nil && ln.ArmResetDate.Year() == y:
				marker = "arm_reset"
			case len(yrRows) > 0 && (yrRows[len(yrRows)-1].Phase == "interest_only" || yrRows[len(yrRows)-1].Phase == "heloc"):
				marker = "io"
			case ln.MaturityDate != nil && ln.MaturityDate.Year() == y:
				marker = "maturity"
			}
			var rate any
			if len(yrRows) > 0 {
				rate = jsonx.Float(dec.S(yrRows[len(yrRows)-1].Rate).Float64())
			} else {
				r := ln.Rate
				rate = RateNum(&r)
			}
			rows = append(rows, jsonx.O("year", y, "principal_cents", a.PrincipalCents, "interest_cents", a.InterestCents,
				"debt_service_cents", a.DebtServiceCents, "balance_end_cents", a.BalanceEndCents, "rate", rate, "marker", marker))
		}
		la := LoanAnnualFor(s, year)
		lref := lenderOr(s, fmt.Sprint(i))
		ads := figure.MoneyI(fmt.Sprintf("loans[%d].annual_debt_service", i), la.DebtServiceCents,
			figure.L(figure.Of("schedule", fmt.Sprintf("%d monthly rows", len(s.Rows)), "figure", fmt.Sprintf("loans.schedule[%s]", lref)),
				figure.M("rate", ln.Rate), figure.Of("balance_cents", ln.BalanceCents, "document", "mortgage statement")),
			"sum of the monthly payments falling in the year", s.Notes, nil)
		bal := figure.MoneyI(fmt.Sprintf("loans[%d].balance_at_year_end", i), balances[i],
			figure.L(figure.Of("balance_cents", ln.BalanceCents, "document", fmt.Sprintf("statement %s", dates.ISO(ln.BalanceAsOf)))),
			fmt.Sprintf("amortized balance at %s", dates.ISO(asOf)), nil, nil)
		ldscr := loans.DSCR(noiFig.VC(), annual.DebtServiceCents, figure.L(figure.Fig(noiFig), figure.Fig(debtService)))
		months := make([]any, len(s.Rows))
		for k, r := range s.Rows {
			months[k] = r.ToDict()
		}
		var lid any
		if ln.ID != nil {
			lid = *ln.ID
		}
		if rows == nil {
			rows = []any{}
		}
		loansOut = append(loansOut, jsonx.O("loan_id", lid, "annual", rows, "dscr", ldscr.ToDict(), "annual_debt_service", ads.ToDict(),
			"balance_at_year_end", bal.ToDict(), "months", months, "months_total", len(s.Rows), "notes", strs(s.Notes)))
	}
	if loansOut == nil {
		loansOut = []any{}
	}

	res.Out = jsonx.O("property_id", p.ID, "year", year, "horizon", horizon, "notes", strs(notes),
		"cash_flow", cf, "equity", eqOut, "appreciation", appreciation, "depreciation", depOut, "exit_tax", exitOut, "loans", loansOut)
	res.NOICents = noiFig.ValueCents
	res.Line21Cents = line21.ValueCents
	res.DSCR = dscr.Value
	res.EquityCents = eq.ValueCents
	if roeRate != nil {
		s := roeRate.String()
		res.ROE = &s
	}
	res.ExitTaxCents = ex.TotalCents()
	res.DepOutlier = dep.Outlier
	res.Balances = balances
	res.AnnualDebt = annual
	if conc != nil {
		res.Concentration = conc.Value
	}
	res.LandBounded = landBounded
	res.Findings = ex.Findings
	return res
}

func layers(ls []taxtables.Layer) []any { return taxtables.LayersDicts(ls) }

func derefOr(x *int64) int64 {
	if x == nil {
		return 0
	}
	return *x
}
