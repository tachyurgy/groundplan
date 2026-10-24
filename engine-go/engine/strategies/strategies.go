// Package strategies ports engine/strategies.py: Hold vs Sell-now vs 1031 (incl. DST) over the same horizon on
// IDENTICAL assumptions, a leads/trails/neutral matrix per measure, and per-path caveats. There is no
// "recommended" field anywhere: no path is ever labelled as the advised choice.
package strategies

import (
	"fmt"
	"strings"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/analysis"
	"github.com/tachyurgy/groundplan/engine-go/engine/cashflow"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/engine/depreciation"
	"github.com/tachyurgy/groundplan/engine-go/engine/exittax"
	"github.com/tachyurgy/groundplan/engine-go/engine/figure"
	"github.com/tachyurgy/groundplan/engine-go/engine/loans"
	"github.com/tachyurgy/groundplan/engine-go/engine/models"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// Conventions is the text Python derives from its module docstring.
const Conventions = "- t = 0 is \"today\" (start of `start_year`); year t ends Dec 31 of start_year + t - 1.\n" +
	"- Cash flows are pre-income-tax; only disposition taxes are modeled. Every cash flow is reinvested at\n" +
	"  reinvest_rate (end-of-year contributions).\n" +
	"- Terminal wealth = what the household would hold if everything were liquidated at the horizon, net of selling\n" +
	"  costs, loan payoffs and the exit tax due then. For the 1031 path the deferred liability is shown as its own\n" +
	"  line, never netted silently.\n" +
	"- No path is ever labelled as the advised choice, and there is no such field: the comparison is a leads/trails/neutral matrix per measure."

var neutralBand = dec.S("0.01")

// Exchange is ExchangeAssumptions.
type Exchange struct {
	ReplacementValueCents *int64
	ReplacementDebtCents  *int64
	DST                   bool
	LoadRate              dec.D
	DSTYield              dec.D
	CashTakenCents        int64
	ReplacementState      *string
}

// Assumptions is StrategyAssumptions.
type Assumptions struct {
	HorizonYears     int
	AppreciationRate *dec.D
	RentGrowth       *dec.D
	ExpenseGrowth    *dec.D
	ReinvestRate     dec.D
	StartYear        int
	Exchange         Exchange
}

// NewAssumptions returns the dataclass defaults.
func NewAssumptions() Assumptions {
	return Assumptions{HorizonYears: 10, ReinvestRate: models.Defaults["reinvest_rate"],
		Exchange: Exchange{LoadRate: models.Defaults["dst_load_rate"], DSTYield: models.Defaults["dst_yield"]}}
}

func row(year int, cf, equity, value, debt, deferred, wealth int64) *jsonx.Obj {
	return jsonx.O("year", year, "cash_flow_cents", cf, "equity_cents", equity, "value_cents", value, "debt_cents", debt,
		"cumulative_tax_deferred_cents", deferred, "wealth_cents", wealth)
}

func grow(amount, rate dec.D, n int) dec.D { return amount.Mul(dec.One.Add(rate).PowInt(n)) }

func pick(a, b *dec.D) *dec.D {
	if a != nil {
		return a
	}
	return b
}

func ints(o *jsonx.Obj, k string) int64 {
	switch v := o.MustGet(k).(type) {
	case int64:
		return v
	case int:
		return int64(v)
	case *int64:
		if v != nil {
			return *v
		}
	}
	return 0
}

func strs(ss []string) []any {
	out := make([]any, len(ss))
	for i, s := range ss {
		out[i] = s
	}
	return out
}

// Compare is compare_strategies(p, h, a). The returned object has the same keys and order as Python's dict.
func Compare(p *models.Property, h *models.Household, a Assumptions) *jsonx.Obj {
	start := a.StartYear
	if start == 0 {
		start = h.TaxYear + 1
	}
	n := max(1, a.HorizonYears)
	appr, apprSrc := models.RateOrDefault(pick(a.AppreciationRate, p.AppreciationRate), "appreciation_rate")
	rg, _ := models.RateOrDefault(pick(a.RentGrowth, p.RentGrowthRate), "rent_growth_rate")
	eg, _ := models.RateOrDefault(pick(a.ExpenseGrowth, p.ExpenseGrowthRate), "expense_growth_rate")
	vac, _ := models.RateOrDefault(p.VacancyRate, "vacancy_rate")
	capex, _ := models.RateOrDefault(p.CapexReserveRate, "capex_reserve_rate")
	sc, _ := models.RateOrDefault(p.SellingCostRate, "selling_cost_rate")
	rr := a.ReinvestRate
	shared := jsonx.O("horizon_years", n, "start_year", start, "appreciation_rate", appr.String(), "appreciation_source", apprSrc,
		"rent_growth", rg.String(), "expense_growth", eg.String(), "reinvest_rate", rr.String(), "selling_cost_rate", sc.String(),
		"vacancy_rate", vac.String(), "capex_reserve_rate", capex.String())
	scheds := analysis.LoanSchedules(p)
	today := dates.New(start-1, 12, 31)
	debtNow := loans.TotalBalanceAt(scheds, today)
	valueNow := dec.I(p.CurrentValueCents)
	baseOps, _ := analysis.OpsForYear(p, start-1)
	carry := h.CarryforwardCents
	vsrc := "public_data"
	if p.ValueSource == "confirmed" {
		vsrc = "manual"
	}
	valueIn := figure.Of("current_value_cents", p.CurrentValueCents, vsrc)
	assumptionInputs := figure.L(valueIn, figure.Of("appreciation_rate", appr, apprSrc), figure.M("reinvest_rate", rr),
		figure.M("horizon_years", int64(n)))

	type override struct {
		purchase, improvements, acc, sec1245 int64
	}
	saleAt := func(valueCents, debtCents int64, throughYear int, released int64, taxYear int, capv *int64, bo *override) *exittax.Result {
		dep := analysis.DepreciationFor(p, throughYear+1, "table")
		acc := dep.Accumulated.VC() - dep.Sec1245Cents
		sd := dates.New(throughYear+1, 1, 15)
		s := &exittax.SaleInput{SalePriceCents: valueCents, SellingCostRate: sc, LoanPayoffCents: debtCents,
			PurchasePriceCents: p.PurchasePriceCents, ImprovementsCents: p.ImprovementsCents, AccumulatedDepreciationCents: acc,
			Sec1245Cents: dep.Sec1245Cents, SaleDate: &sd, FormerResidenceUntil: p.FormerResidenceUntil,
			RecognizedGainCapCents: capv, ReplacementState: a.Exchange.ReplacementState, Disposition: "taxable_sale"}
		if bo != nil {
			s.PurchasePriceCents, s.ImprovementsCents, s.AccumulatedDepreciationCents, s.Sec1245Cents = bo.purchase, bo.improvements, bo.acc, bo.sec1245
			s.FormerResidenceUntil = nil
		}
		return exittax.Compute(s, analysis.HouseholdTax(h, released, 0, taxYear), p.BlockedKeys)
	}

	// ---------------- HOLD ----------------
	var holdSeries []*jsonx.Obj
	reinvested := dec.Zero
	var cumCF int64
	var holdExit *exittax.Result
	for t := 1; t <= n; t++ {
		yr := start + t - 1
		var noiC int64
		if baseOps != nil {
			o := cashflow.ProjectOperations(baseOps, t, &rg, &eg)
			noiC = cashflow.NOI(o, &vac, &capex, nil).VC()
		}
		ann := loans.CombinedAnnual(scheds, yr)
		cf := noiC - ann.DebtServiceCents - ann.BalloonCents
		cumCF += cf
		reinvested = reinvested.Mul(dec.One.Add(rr)).Add(dec.I(cf))
		valueT := grow(valueNow, appr, t).Cents()
		debtT := loans.TotalBalanceAt(scheds, dates.New(yr, 12, 31))
		ex := saleAt(valueT, debtT, yr, carry, yr+1, nil, nil)
		holdExit = ex
		wealth := ex.NetProceedsCents() + reinvested.Cents()
		holdSeries = append(holdSeries, row(yr, cf, valueT-debtT, valueT, debtT, ex.TotalCents(), wealth))
	}
	last := holdSeries[len(holdSeries)-1]
	holdTerminal := ints(last, "wealth_cents")
	hold := jsonx.O("path", "hold", "label", "Hold", "series", holdSeries,
		"terminal", jsonx.O(
			"terminal_wealth", figure.MoneyI("strategy.hold.terminal_wealth", holdTerminal,
				figure.Ins(assumptionInputs, figure.L(figure.Fig(holdExit.F("exit_tax.net_proceeds")))),
				"net proceeds if sold at horizon (equity - selling costs - exit tax) + cash flows reinvested", nil, nil).ToDict(),
			"ending_equity_cents", ints(last, "equity_cents"),
			"exit_tax_at_horizon_cents", holdExit.TotalCents(),
			"cumulative_cash_flow_cents", cumCF,
			"reinvested_cash_flow_cents", reinvested.Cents(),
			"tax_paid_now_cents", int64(0),
			"suspended_losses_released_cents", int64(0)),
		"caveats", strs([]string{"Concentration: the household stays exposed to this one property and market.",
			"The deferred exit tax grows every year as depreciation accumulates and the property appreciates.",
			"Assumes the property keeps being managed (tenants, repairs, capital reserves).",
			"Cash flows are pre-income-tax and assumed reinvested at the reinvest rate."}))

	// ---------------- SELL NOW ----------------
	sellEx := saleAt(valueNow.Int(), debtNow, start-1, carry, start, nil, nil)
	proceeds := dec.I(sellEx.NetProceedsCents())
	var sellSeries []*jsonx.Obj
	for t := 1; t <= n; t++ {
		sellSeries = append(sellSeries, row(start+t-1, 0, 0, 0, 0, 0, grow(proceeds, rr, t).Cents()))
	}
	sellLast := ints(sellSeries[len(sellSeries)-1], "wealth_cents")
	carryCaveat := "No suspended passive losses to release."
	if carry != 0 {
		carryCaveat = fmt.Sprintf("Suspended passive losses (%d cents) are released and reduce the tax.", carry)
	}
	sell := jsonx.O("path", "sell", "label", "Sell now (taxable)", "series", sellSeries,
		"terminal", jsonx.O(
			"terminal_wealth", figure.MoneyI("strategy.sell.terminal_wealth", sellLast,
				figure.Ins(assumptionInputs, figure.L(figure.Fig(sellEx.F("exit_tax.net_proceeds")))),
				"net proceeds today x (1 + reinvest_rate)^horizon", nil, nil).ToDict(),
			"net_proceeds_today_cents", sellEx.NetProceedsCents(),
			"exit_tax_today_cents", sellEx.TotalCents(),
			"cumulative_cash_flow_cents", int64(0),
			"tax_paid_now_cents", sellEx.TotalCents(),
			"suspended_losses_released_cents", carry,
			"exit_tax", sellEx.ToDict()),
		"caveats", strs([]string{"The full exit tax is paid now.",
			"Terminal wealth depends on actually earning the reinvest rate on the proceeds.", carryCaveat}))

	// ---------------- 1031 / DST ----------------
	x := a.Exchange
	amountRealized := sellEx.F("exit_tax.amount_realized").VC()
	netBefore := sellEx.F("exit_tax.net_before_tax").VC()
	totalGain := sellEx.F("exit_tax.total_gain").VC()
	oldAdjBasis := sellEx.F("exit_tax.adjusted_basis").VC()
	replValue := amountRealized
	if x.ReplacementValueCents != nil {
		replValue = *x.ReplacementValueCents
	}
	replDebt := debtNow
	replDebtSrc := "default"
	if x.ReplacementDebtCents != nil {
		replDebt = *x.ReplacementDebtCents
		replDebtSrc = "manual"
	}
	mortgageBoot := max(0, debtNow-replDebt)
	boot := x.CashTakenCents + mortgageBoot
	var bootNotes []string
	if mortgageBoot != 0 {
		bootNotes = []string{fmt.Sprintf("mortgage boot %d cents", mortgageBoot)}
	}
	bootFig := figure.MoneyI("exchange.boot", boot, figure.L(figure.M("cash_taken_cents", x.CashTakenCents),
		figure.Of("old_debt_paid_off_cents", debtNow, "figure", "loans.schedule"), figure.Of("replacement_debt_cents", replDebt, replDebtSrc)),
		"cash_taken + max(0, old_debt_paid_off - replacement_debt)", bootNotes, nil)
	var bootEx *exittax.Result
	if boot > 0 {
		b := boot
		bootEx = saleAt(valueNow.Int(), debtNow, start-1, 0, start, &b, nil)
	}
	var bootTax int64
	if bootEx != nil {
		bootTax = bootEx.TotalCents()
	}
	recognized := min(boot, totalGain)
	deferredGain := totalGain - recognized
	exchangeEquity := netBefore - x.CashTakenCents
	findings := append([]*jsonx.Obj{}, sellEx.Findings...)
	if bootEx != nil {
		var add []*jsonx.Obj
		for _, f := range bootEx.Findings {
			if !containsObj(findings, f) {
				add = append(add, f)
			}
		}
		findings = append(findings, add...)
	}
	replBasis := replValue - deferredGain
	carryoverPart := oldAdjBasis
	newBasisPart := max(0, replBasis-carryoverPart)
	lp, _, _ := depreciation.BoundedLandPct(p.LandPct)
	newDepBasis := dec.I(newBasisPart).Mul(dec.One.Sub(lp)).Cents()
	oldSched := depreciation.AnnualSchedule(depreciation.DepreciableBasis(p.PurchasePriceCents, p.ImprovementsCents, p.LandPct, nil).VC(),
		p.InService(), depreciation.PropertyClass(p.PropertyType), "table")
	newSched := depreciation.AnnualSchedule(newDepBasis, dates.New(start, 1, 15), "residential", "table")
	depBefore := sellEx.F("exit_tax.unrecaptured_1250").VC()
	old1245 := sellEx.F("exit_tax.sec1245").VC()
	load := dec.Zero
	if x.DST {
		load = x.LoadRate
	}
	dstY := x.DSTYield
	loadCost := dec.I(exchangeEquity).Mul(load).Cents()
	workingValue := dec.I(replValue - loadCost)
	var replRate dec.D
	if x.DST {
		replRate = dec.S("0.05")
	} else {
		var ws []dec.D
		for _, ln := range p.Loans {
			if !ln.IsPaidOff {
				ws = append(ws, ln.Rate)
			}
		}
		if len(ws) > 0 {
			replRate = dec.I(0).Add(dec.Sum(ws...)).Quo(dec.I(int64(len(ws))))
		} else {
			replRate = dec.S("0.065")
		}
	}
	var replLoan *loans.Input
	if x.DST {
		replLoan = &loans.Input{LoanType: "interest_only", BalanceCents: replDebt, BalanceAsOf: today, Rate: replRate, TermMonths: n * 12,
			IOMonths: n * 12, LienPosition: 1}
	} else {
		replLoan = &loans.Input{LoanType: "fixed", BalanceCents: replDebt, BalanceAsOf: today, Rate: replRate, TermMonths: 360, LienPosition: 1}
	}
	var replSched *loans.Schedule
	if replDebt > 0 {
		replSched = loans.Build(replLoan)
	}
	var baseNOI int64
	if baseOps != nil {
		baseNOI = cashflow.NOI(baseOps, &vac, &capex, nil).VC()
	}
	capRate := dec.Zero
	if !valueNow.IsZero() {
		capRate = dec.I(baseNOI).Quo(valueNow)
	}
	var xSeries []*jsonx.Obj
	reinv := dec.Zero
	var cum int64
	var xExit *exittax.Result
	for t := 1; t <= n; t++ {
		yr := start + t - 1
		var cf int64
		if x.DST {
			cf = dec.I(exchangeEquity - loadCost).Mul(dstY).Cents()
		} else {
			noiT := workingValue.Mul(capRate).Mul(dec.One.Add(rg).PowInt(t - 1)).Cents()
			var ds int64
			if replSched != nil {
				ds = replSched.DebtServiceInYear(yr)
			}
			cf = noiT - ds
		}
		cum += cf
		reinv = reinv.Mul(dec.One.Add(rr)).Add(dec.I(cf))
		valueT := grow(workingValue, appr, t).Cents()
		var debtT int64
		if replSched != nil {
			debtT = replSched.BalanceAt(dates.New(yr, 12, 31))
		}
		var accNew, accOldCont int64
		for _, r := range newSched {
			if r.Year <= yr {
				accNew += r.AmountCents
			}
		}
		for _, r := range oldSched {
			if start <= r.Year && r.Year <= yr {
				accOldCont += r.AmountCents
			}
		}
		accTotal := depBefore + accOldCont + accNew
		ex := saleAt(valueT, debtT, yr, carry, yr+1, nil, &override{replBasis + depBefore + old1245, 0, accTotal, old1245})
		xExit = ex
		wealth := ex.NetProceedsCents() + reinv.Cents()
		xSeries = append(xSeries, row(yr, cf, valueT-debtT, valueT, debtT, ex.TotalCents(), wealth))
	}
	label := "1031 exchange (direct replacement)"
	if x.DST {
		label = "1031 exchange into a DST"
	}
	xCaveats := []string{"Deferred, not forgiven: the deferred liability is shown at the horizon and grows with depreciation.",
		"Suspended passive losses are NOT released by an exchange; they carry into the replacement.",
		"45-day identification and 180-day closing deadlines; a qualified intermediary is required."}
	if x.DST {
		xCaveats = append(xCaveats, "DST interests are illiquid (typically 5-10 year hold, no secondary market).",
			"No control: the sponsor makes every property decision.",
			"Sponsor risk and fees: the load reduces working equity on day one.",
			"Distributions are not guaranteed.")
	} else {
		xCaveats = append(xCaveats, "A direct replacement keeps the management burden and concentration.")
	}
	if x.CashTakenCents != 0 && bootTax > x.CashTakenCents {
		xCaveats = append(xCaveats, "Tax on boot exceeds the cash taken out; the difference must come from other funds.")
	}
	var bootExOut any
	if bootEx != nil {
		bootExOut = bootEx.ToDict()
	}
	xLast := ints(xSeries[len(xSeries)-1], "wealth_cents")
	exch := jsonx.O("path", "exchange", "label", label, "dst", x.DST, "series", xSeries,
		"terminal", jsonx.O(
			"terminal_wealth", figure.MoneyI("strategy.exchange.terminal_wealth", xLast,
				figure.Ins(assumptionInputs, figure.L(figure.Fig(bootFig), figure.Fig(xExit.F("exit_tax.net_proceeds")))),
				"replacement liquidated at horizon net of selling costs, debt and the deferred tax + distributions reinvested",
				[]string{"the deferred liability is subtracted explicitly (deferred_liability_at_horizon_cents)"}, nil).ToDict(),
			"boot", bootFig.ToDict(),
			"boot_cents", boot, "mortgage_boot_cents", mortgageBoot, "cash_taken_cents", x.CashTakenCents,
			"tax_on_boot_cents", bootTax, "tax_paid_now_cents", bootTax,
			"gain_recognized_cents", recognized, "gain_deferred_cents", deferredGain,
			"replacement_value_cents", replValue, "replacement_debt_cents", replDebt,
			"replacement_basis_cents", replBasis, "exchange_equity_cents", exchangeEquity,
			"dst_load_cents", loadCost, "deferred_liability_at_horizon_cents", xExit.TotalCents(),
			"cumulative_cash_flow_cents", cum, "suspended_losses_released_cents", int64(0),
			"suspended_losses_carried_cents", carry,
			"exit_tax_on_boot", bootExOut),
		"caveats", strs(xCaveats))
	paths := []*jsonx.Obj{hold, sell, exch}
	matrix := leadsTrails(paths)
	fo := make([]any, len(findings))
	for i, f := range findings {
		fo[i] = f
	}
	pa := make([]any, len(paths))
	for i, pp := range paths {
		pa[i] = pp
	}
	return jsonx.O("property_id", p.ID, "assumptions", shared, "paths", pa, "matrix", matrix, "findings", fo, "conventions", Conventions)
}

func containsObj(list []*jsonx.Obj, f *jsonx.Obj) bool {
	fb := string(jsonx.MustMarshal(f))
	for _, x := range list {
		if string(jsonx.MustMarshal(x)) == fb {
			return true
		}
	}
	return false
}

type kvInt struct {
	k string
	v int64
}

func rank(values []kvInt, higherIsBetter bool) *jsonx.Obj {
	best, worst := values[0].v, values[0].v
	for _, x := range values[1:] {
		if higherIsBetter {
			best, worst = max(best, x.v), min(worst, x.v)
		} else {
			best, worst = min(best, x.v), max(worst, x.v)
		}
	}
	scale := max(abs(best), abs(worst), 1)
	out := jsonx.O()
	for _, x := range values {
		switch {
		case dec.I(best - worst).Abs().Quo(dec.I(scale)).Le(neutralBand):
			out.Set(x.k, "neutral")
		case x.v == best:
			out.Set(x.k, "leads")
		case x.v == worst:
			out.Set(x.k, "trails")
		default:
			out.Set(x.k, "neutral")
		}
	}
	return out
}

func abs(x int64) int64 {
	if x < 0 {
		return -x
	}
	return x
}

func leadsTrails(paths []*jsonx.Obj) *jsonx.Obj {
	var tw, ccf, tpn []kvInt
	dst := false
	for _, pp := range paths {
		k := pp.MustGet("path").(string)
		t := pp.MustGet("terminal").(*jsonx.Obj)
		tw = append(tw, kvInt{k, ints(t.MustGet("terminal_wealth").(*jsonx.Obj), "value_cents")})
		ccf = append(ccf, kvInt{k, ints(t, "cumulative_cash_flow_cents")})
		tpn = append(tpn, kvInt{k, ints(t, "tax_paid_now_cents")})
		if k == "exchange" {
			if v, ok := pp.Get("dst"); ok {
				dst, _ = v.(bool)
			}
		}
	}
	mb, conc := "trails", "trails"
	if dst {
		mb, conc = "leads", "neutral"
	}
	m := jsonx.O(
		"terminal_wealth", rank(tw, true),
		"cumulative_cash_flow", rank(ccf, true),
		"tax_paid_now", rank(tpn, false),
		"liquidity", jsonx.O("hold", "neutral", "sell", "leads", "exchange", "trails"),
		"management_burden", jsonx.O("hold", "trails", "sell", "leads", "exchange", mb),
		"concentration", jsonx.O("hold", "trails", "sell", "leads", "exchange", conc))
	m.Set("_explain", jsonx.O(
		"terminal_wealth", "higher terminal after-tax wealth leads",
		"cumulative_cash_flow", "more cash received over the horizon leads",
		"tax_paid_now", "less tax due at decision time leads",
		"liquidity", "cash in hand leads; a held property is neutral; an exchange (esp. DST) locks capital up",
		"management_burden", "no landlord duties leads (sell, DST); hands-on ownership trails",
		"concentration", "diversified proceeds lead; one property trails; a DST is diversified across a sponsor portfolio",
		"note", "a measure is neutral when all three paths are within 1% of each other; there is no overall winner"))
	return m
}

func f(key string, cents int64, formula string, notes []string, status string) *jsonx.Obj {
	fig := figure.MoneyI(key, cents, figure.L(figure.Of(key, cents, "figure", "strategies")), formula, notes, nil)
	if status != "" {
		fig.Status = status
	}
	return fig.ToDict()
}

// Present adds the Figure-shaped fields the web client renders (types.ts StrategyComparison).
func Present(r *jsonx.Obj, baseStatus string, baseReason *string) *jsonx.Obj {
	a := r.MustGet("assumptions").(*jsonx.Obj)
	paths := r.MustGet("paths").([]any)
	for _, pv := range paths {
		pth := pv.(*jsonx.Obj)
		t := pth.MustGet("terminal").(*jsonx.Obj)
		tw := t.MustGet("terminal_wealth").(*jsonx.Obj)
		st := tw.MustGet("status").(string)
		nw := figure.Worst(st, baseStatus)
		if nw != st {
			tw.Set("status", nw)
			ref := "property analysis"
			if baseReason != nil {
				ref = *baseReason
			}
			ins := append(tw.MustGet("inputs").([]any), jsonx.O("key", "base_analysis.status", "value", baseStatus, "status", baseStatus,
				"source", jsonx.O("type", "figure", "ref", ref, "page", nil)))
			tw.Set("inputs", ins)
		}
		if b, ok := t.Get("boot"); ok && b != nil {
			bo := b.(*jsonx.Obj)
			bo.Set("status", figure.Worst(bo.MustGet("status").(string), baseStatus))
		}
	}
	for _, pv := range paths {
		pth := pv.(*jsonx.Obj)
		t := pth.MustGet("terminal").(*jsonx.Obj)
		st := t.MustGet("terminal_wealth").(*jsonx.Obj).MustGet("status").(string)
		key := pth.MustGet("path").(string)
		t.Set("cumulative_cash_flow", f("strategy."+key+".cumulative_cash_flow", ints(t, "cumulative_cash_flow_cents"),
			"sum of yearly net cash flow over the horizon", nil, st))
		t.Set("tax_paid_now", f("strategy."+key+".tax_paid_now", ints(t, "tax_paid_now_cents"), "tax due at decision time", nil, st))
		switch key {
		case "hold":
			t.Set("deferred_liability", f("strategy.hold.deferred_liability", ints(t, "exit_tax_at_horizon_cents"),
				"exit tax if sold at the horizon (grows with depreciation and appreciation)", nil, st))
			t.Set("ending_equity", f("strategy.hold.ending_equity", ints(t, "ending_equity_cents"), "value - debt at horizon", nil, st))
		case "sell":
			t.Set("deferred_liability", f("strategy.sell.deferred_liability", 0, "nothing deferred: tax paid now", nil, st))
			t.Set("ending_equity", f("strategy.sell.ending_equity", 0, "no property held", nil, st))
			rrp := dec.S(a.MustGet("reinvest_rate").(string)).Mul(dec.I(100)).Fixed(1)
			pth.Set("proceeds_use", []any{
				jsonx.O("label", "Net proceeds after tax, today", "value", f("strategy.sell.net_proceeds", ints(t, "net_proceeds_today_cents"),
					"net before tax - exit tax", nil, st)),
				jsonx.O("label", "Exit tax paid now", "value", f("strategy.sell.exit_tax", ints(t, "exit_tax_today_cents"),
					"fed_1250 + fed_1245 + fed_ltcg + niit + state", nil, st)),
				jsonx.O("label", fmt.Sprintf("Proceeds invested at %s%% for %v years", rrp, a.MustGet("horizon_years")),
					"value", t.MustGet("terminal_wealth")),
			})
		default:
			t.Set("deferred_liability", f("strategy.exchange.deferred_liability", ints(t, "deferred_liability_at_horizon_cents"),
				"tax due if the replacement is sold at the horizon (carryover basis)", []string{"shown explicitly and subtracted from terminal wealth"}, st))
			series := pth.MustGet("series").([]*jsonx.Obj)
			lastRow := series[len(series)-1]
			t.Set("ending_equity", f("strategy.exchange.ending_equity", ints(lastRow, "equity_cents"), "replacement value - debt at horizon", nil, st))
			pth.Set("boot", jsonx.O(
				"cash_boot", f("exchange.cash_boot", ints(t, "cash_taken_cents"), "cash taken out of the exchange", nil, st),
				"mortgage_boot", f("exchange.mortgage_boot", ints(t, "mortgage_boot_cents"), "max(0, old debt paid off - replacement debt)", nil, st),
				"total_boot", t.MustGet("boot"),
				"gain_recognized", f("exchange.gain_recognized", ints(t, "gain_recognized_cents"), "min(boot, total gain)", nil, st),
				"tax_on_boot", f("exchange.tax_on_boot", ints(t, "tax_on_boot_cents"), "boot taxed through the same exit-tax stack", nil, st)))
			pu := []any{
				jsonx.O("label", "Equity rolled into the replacement", "value", f("exchange.equity_rolled", ints(t, "exchange_equity_cents"),
					"net before tax - cash taken", nil, st)),
				jsonx.O("label", "Gain deferred (carried into the replacement basis)", "value", f("exchange.gain_deferred",
					ints(t, "gain_deferred_cents"), "total gain - gain recognized", nil, st)),
			}
			if d, _ := pth.MustGet("dst").(bool); d {
				pu = append(pu, jsonx.O("label", "DST load (fees and sponsor costs)", "value", f("exchange.dst_load", ints(t, "dst_load_cents"),
					"exchange equity x load_rate", nil, st)))
			}
			pth.Set("proceeds_use", pu)
		}
	}
	r.Set("base_status", baseStatus)
	r.Set("horizon_years", a.MustGet("horizon_years"))
	cav := jsonx.O()
	for _, pv := range paths {
		pth := pv.(*jsonx.Obj)
		cav.Set(pth.MustGet("path").(string), pth.MustGet("caveats"))
	}
	r.Set("caveats", cav)
	matrix := r.MustGet("matrix").(*jsonx.Obj)
	r.Set("matrix_explain", matrix.Delete("_explain"))
	return r
}

var _ = strings.TrimSpace
