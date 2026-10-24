package api

import (
	"fmt"
	"net/http"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/exittax"
	"github.com/tachyurgy/groundplan/engine-go/engine/simulate"
	"github.com/tachyurgy/groundplan/engine-go/internal/service"
	"github.com/tachyurgy/groundplan/engine-go/internal/store"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// Port of routers/misc.py run_simulation (POST /simulate).

type simIn struct {
	startYear, years int
	householdID      *string
	props            []*parsed
	events           []*parsed
	a                *parsed
	mc               *parsed
}

func parseSimulate(v any) (*simIn, []any) {
	top := schema{fields: []spec{
		{name: "start_year", k: kInt, def: int64(2026)},
		{name: "years", k: kInt, def: int64(10), ge: f(1), le: f(40)},
		{name: "household_id", k: kStr, nullable: true},
		{name: "properties", k: kAny},
		{name: "events", k: kAny},
		{name: "assumptions", k: kAny},
		{name: "monte_carlo", k: kAny},
	}}
	b, errs := top.parse(v, []any{"body"})
	if b == nil {
		return nil, errs
	}
	out := &simIn{startYear: int(b.i64("start_year")), years: int(b.i64("years")), householdID: b.strp("household_id")}
	list := func(name string, sc schema) []*parsed {
		raw := b.vals[name]
		if raw == nil {
			if b.has(name) {
				errs = append(errs, verr([]any{"body", name}, "Input should be a valid list", "list_type"))
			}
			return nil
		}
		arr, ok := raw.([]any)
		if !ok {
			errs = append(errs, verr([]any{"body", name}, "Input should be a valid list", "list_type"))
			return nil
		}
		var res []*parsed
		for i, x := range arr {
			p, e := sc.parse(x, []any{"body", name, i})
			errs = append(errs, e...)
			if p != nil {
				res = append(res, p)
			}
		}
		return res
	}
	out.props = list("properties", simPropertyIn)
	out.events = list("events", simEvent)
	sub := func(name string, sc schema) *parsed {
		raw := b.vals[name]
		if raw == nil {
			if b.has(name) {
				errs = append(errs, verr([]any{"body", name}, "Input should be a valid dictionary or object to extract fields from", "model_attributes_type"))
			}
			raw = jsonx.O()
		}
		p, e := sc.parse(raw, []any{"body", name})
		errs = append(errs, e...)
		return p
	}
	out.a = sub("assumptions", simAssumptions)
	out.mc = sub("monte_carlo", monteCarlo)
	return out, errs
}

// dumpEvent is SimEvent.model_dump(exclude_none=True): declared fields first, then extras in input order.
func dumpEvent(e *parsed) *jsonx.Obj {
	d := jsonx.O()
	for _, k := range e.order {
		v := e.vals[k]
		if v == nil {
			continue
		}
		if fv, ok := v.(float64); ok {
			v = jsonx.Float(fv)
		}
		d.Set(k, v)
	}
	for _, kv := range e.extra.Pairs() {
		if kv.V != nil {
			d.Set(kv.K, kv.V)
		}
	}
	return d
}

func band(x int64) *jsonx.Obj { return jsonx.O("p10", x, "p50", x, "p90", x) }

func (s *Server) simulate(w http.ResponseWriter, r *http.Request) (any, error) {
	v, p := readJSON(r, true)
	if p != nil {
		return nil, p
	}
	in, errs := parseSimulate(v)
	if len(errs) > 0 {
		return nil, validationProblem(errs)
	}
	a := in.a
	hh := exittax.NewHouseholdTax()
	hh.FilingStatus, hh.State = a.str("filing_status"), a.str("state")
	hh.WagesCents, hh.OtherIncomeCents, hh.MagiCents = a.i64("wages_cents"), a.i64("other_income_cents"), a.i64("magi_cents")
	var props []*simulate.Property
	if in.householdID != nil && *in.householdID != "" {
		h, err := s.household(r, *in.householdID)
		if err != nil {
			return nil, err
		}
		hh = exittax.NewHouseholdTax()
		hh.FilingStatus, hh.State, hh.WagesCents, hh.OtherIncomeCents, hh.MagiCents = h.FilingStatus, h.State, h.WagesCents, h.OtherIncomeCents, h.MagiCents
		if len(in.props) == 0 {
			for _, pr := range h.Properties {
				if pr.Status != "active" {
					continue
				}
				an, err := s.Svc.Analyze(r.Context(), pr, h.AdvisorID, 0, 1, nil)
				if err != nil {
					return nil, err
				}
				var debt int64
				for _, b := range an.R.Balances {
					debt += b
				}
				rate := 0.0
				for _, ln := range an.PM.Loans {
					if !ln.IsPaidOff {
						rate = ln.Rate.Float64()
						break
					}
				}
				out := an.Out()
				cf := out.MustGet("cash_flow").(*jsonx.Obj)
				gross := fvc(cf.MustGet("gross_rent"))
				exp := fvc(cf.MustGet("operating_expenses")) + fvc(cf.MustGet("capex_reserve"))
				appr := a.fl("appreciation_rate")
				if an.PM.AppreciationRate != nil && !an.PM.AppreciationRate.IsZero() {
					appr = an.PM.AppreciationRate.Float64()
				}
				vac := a.fl("vacancy_rate")
				if an.PM.VacancyRate != nil {
					vac = an.PM.VacancyRate.Float64()
				}
				dep := out.MustGet("depreciation").(*jsonx.Obj)
				pp := float64(pr.PurchasePriceCents + pr.ImprovementsCents)
				db := float64(fvc(dep.MustGet("depreciable_basis")))
				sp := simulate.NewProperty(pr.Nickname, float64(pr.CurrentValueCents))
				sp.DebtCents, sp.Rate, sp.RemainingYears = float64(debt), rate, 30
				sp.GrossRentCents, sp.ExpensesCents = float64(gross), float64(exp)
				sp.AppreciationRate, sp.RentGrowth, sp.ExpenseGrowth, sp.VacancyRate = appr, a.fl("rent_growth"), a.fl("expense_growth"), vac
				sp.PurchasePriceCents = &pp
				sp.AccumulatedDepreciationCents = float64(fvc(dep.MustGet("accumulated")))
				sp.DepreciableBasisCents = &db
				props = append(props, sp)
			}
		}
	}
	for i, sp := range in.props {
		vac := a.fl("vacancy_rate")
		exp := sp.i64("expenses_cents")
		var rent int64
		if x := sp.i64p("gross_rent_cents"); x != nil {
			rent = *x
		} else {
			noi := sp.i64("noi_cents")
			if noi == 0 {
				noi = int64(float64(sp.i64("current_value_cents")) * a.fl("cap_rate"))
			}
			rent = dec.PyRound(float64(noi+exp) / (1 - vac))
		}
		basis := sp.i64("purchase_price_cents")
		if basis == 0 {
			basis = sp.i64("current_value_cents")
		}
		id := sp.str("id")
		if id == "" {
			id = sp.str("nickname")
		}
		if id == "" {
			id = fmt.Sprintf("p%d", i+1)
		}
		land := 0.30
		if lp := sp.flp("land_pct"); lp != nil {
			land = *lp
		}
		bf := float64(basis)
		dbv := float64(int64(bf * (1 - land)))
		x := simulate.NewProperty(id, float64(sp.i64("current_value_cents")))
		x.DebtCents, x.Rate, x.RemainingYears = float64(sp.i64("debt_cents")), sp.fl("rate"), int(sp.i64("remaining_years"))
		x.GrossRentCents, x.ExpensesCents = float64(rent), float64(exp)
		x.AppreciationRate, x.RentGrowth, x.ExpenseGrowth, x.VacancyRate = a.fl("appreciation_rate"), a.fl("rent_growth"), a.fl("expense_growth"), vac
		x.PurchasePriceCents = &bf
		x.AccumulatedDepreciationCents = float64(sp.i64("accumulated_depreciation_cents"))
		x.DepreciableBasisCents = &dbv
		props = append(props, x)
	}
	ids := map[string]bool{}
	for _, p := range props {
		ids[p.ID] = true
	}
	var events []*jsonx.Obj
	for _, e := range in.events {
		d := dumpEvent(e)
		ref := d.MustGet("property_id")
		if !truthyJSON(ref) {
			ref = d.MustGet("property_ref")
		}
		d.Set("property_id", ref)
		typ := e.str("type")
		if typ == "buy" {
			if !d.Has("value_cents") {
				amt := d.MustGet("amount_cents")
				if !truthyJSON(amt) {
					amt = int64(0)
				}
				d.Set("value_cents", amt)
			}
			if !d.Has("gross_rent_cents") {
				d.Set("gross_rent_cents", int64(jsonNum(d.MustGet("value_cents"))*a.fl("cap_rate")/(1-a.fl("vacancy_rate"))))
			}
			if rs, ok := ref.(string); ok && rs != "" {
				ids[rs] = true
			} else {
				ids[fmt.Sprintf("buy-%d", e.i64("year"))] = true
			}
		}
		if typ == "exchange" && truthyJSON(d.MustGet("amount_cents")) && !d.Has("replacement_value_cents") {
			d.Set("replacement_value_cents", d.MustGet("amount_cents"))
		}
		if typ == "exchange" && d.Has("debt_cents") && d.MustGet("debt_cents") != nil && !d.Has("replacement_debt_cents") {
			d.Set("replacement_debt_cents", d.MustGet("debt_cents"))
		}
		if typ == "refi" && truthyJSON(d.MustGet("debt_cents")) {
			var pv float64
			found := false
			for _, p := range props {
				if rs, ok := ref.(string); ok && p.ID == rs {
					pv, found = p.ValueCents, true
					break
				}
			}
			if found && pv != 0 && !d.Has("ltv") {
				d.Set("ltv", jsonx.Float(jsonNum(d.MustGet("debt_cents"))/pv))
			}
		}
		events = append(events, d)
	}
	mc := in.mc
	req := &simulate.Request{StartYear: in.startYear, Years: in.years, Properties: props, Events: events, ReinvestRate: a.fl("reinvest_rate"),
		StartingCashCents: float64(a.i64("starting_cash_cents")), Household: hh, Runs: int(mc.i64("runs")), ApprSigma: mc.fl("appr_sigma"),
		RentSigma: mc.fl("rent_sigma"), Seed: mc.i64("seed")}
	res, err := runSim(req)
	if err != nil {
		return nil, err
	}
	var series []any
	for t, row := range res.Deterministic {
		var b map[string]simulate.Band
		if res.Bands != nil {
			b = res.Bands[t]
		}
		pick := func(m string, x int64) *jsonx.Obj {
			if b != nil {
				return b[m].ToDict()
			}
			return band(x)
		}
		eq, debt := row.Equity, row.Debt
		if b != nil {
			eq, debt = b["equity"].P50, b["debt"].P50
		}
		var evs []any
		for _, e := range in.events {
			if int(e.i64("year")) == row.Year {
				evs = append(evs, dumpEvent(e))
			}
		}
		if evs == nil {
			evs = []any{}
		}
		series = append(series, jsonx.O("year", row.Year, "net_worth", pick("net_worth", row.NetWorth), "cash_flow", pick("cash_flow", row.CashFlow),
			"taxes_paid", pick("taxes_paid", row.TaxesPaid), "equity_cents", eq, "debt_cents", debt, "cash_cents", row.Cash,
			"value_cents", row.Value, "deterministic", jsonx.O("net_worth", row.NetWorth, "cash_flow", row.CashFlow,
				"taxes_paid", row.TaxesPaid, "equity", row.Equity, "debt", row.Debt), "events", evs))
	}
	last := res.Deterministic[len(res.Deterministic)-1]
	term := jsonx.O("net_worth", band(last.NetWorth), "cumulative_taxes", band(last.CumTaxes))
	if res.Bands != nil {
		lb := res.Bands[len(res.Bands)-1]
		term = jsonx.O("net_worth", lb["net_worth"].ToDict(), "cumulative_taxes", lb["cum_taxes"].ToDict())
	}
	return jsonx.O("series", series, "runs", res.Runs, "seed", res.Seed, "terminal", term,
		"properties", anyList(props, func(p *simulate.Property) any { return p.ID }),
		"notes", []any{"Monte Carlo draws are seeded (PCG64) and reproducible; taxes on sells/exchanges come from the deterministic " +
			"exit-tax engine; cash flows are pre-income-tax and swept to a cash account at the reinvest rate."}), nil
}

func runSim(req *simulate.Request) (res *simulate.Result, err error) {
	defer func() {
		if r := recover(); r != nil {
			if e, ok := r.(error); ok {
				err = &service.InvalidInput{Msg: e.Error()}
				return
			}
			panic(r)
		}
	}()
	return simulate.Simulate(req), nil
}

func fvc(v any) int64 {
	o, ok := v.(*jsonx.Obj)
	if !ok {
		return 0
	}
	switch x := o.MustGet("value_cents").(type) {
	case *int64:
		if x != nil {
			return *x
		}
	case int64:
		return x
	}
	return 0
}

func truthyJSON(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case string:
		return x != ""
	case int64:
		return x != 0
	case jsonx.Float:
		return x != 0
	case bool:
		return x
	}
	return true
}

func jsonNum(v any) float64 {
	switch x := v.(type) {
	case int64:
		return float64(x)
	case jsonx.Float:
		return float64(x)
	}
	return 0
}

var _ = store.ErrNotFound
