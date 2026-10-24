package api

import (
	"fmt"
	"net/http"
	"strconv"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/analysis"
	"github.com/tachyurgy/groundplan/engine-go/engine/cashflow"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/engine/depreciation"
	"github.com/tachyurgy/groundplan/engine-go/engine/figure"
	"github.com/tachyurgy/groundplan/engine-go/engine/golden"
	"github.com/tachyurgy/groundplan/engine-go/engine/models"
	"github.com/tachyurgy/groundplan/engine-go/engine/strategies"
	"github.com/tachyurgy/groundplan/engine-go/internal/service"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// Internal engine endpoints (SPEC §6): the Python API can forward pure engine math here behind GP_ENGINE=go.
//
//	POST /engine/analyze     {"property": PropertyModel, "household": HouseholdModel, "year"?, "horizon"?: 10,
//	                          "carryforward_release"?: 0, "mode"?: "table"}
//	                         -> the public analysis dict (backend/groundplan/engine/wire.py); with "private": true
//	                            {"analysis": ..., "private": {...the "_" keys}} for debugging
//	POST /engine/strategies  {"property", "household", "assumptions": StrategyAssumptions (+ "exchange": {...}),
//	                          "present"?: {"base_status", "base_reason"}} -> compare_strategies(...) [then present(...)]
//
// The wire format is backend/groundplan/engine/wire.py (Decimals as strings, years keyed by "2025", Inputs as
// {key, value, source}); Python serves the same two endpoints as the reference implementation.
//
// Model JSON uses the Python dataclass field names (engine/models.py, loans.LoanInput, cashflow.YearOperations);
// rates and other decimals may be strings (exact) or numbers (Decimal(repr(float))).

func decAny(v any) *dec.D {
	if v == nil {
		return nil
	}
	d := golden.AsDec(v)
	return &d
}

func gS(o *jsonx.Obj, k, def string) string {
	if v, ok := o.Get(k); ok && v != nil {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return def
}

func gI(o *jsonx.Obj, k string, def int64) int64 {
	if v, ok := o.Get(k); ok && v != nil {
		return golden.AsInt(v)
	}
	return def
}

func gB(o *jsonx.Obj, k string, def bool) bool {
	if v, ok := o.Get(k); ok && v != nil {
		if b, ok := v.(bool); ok {
			return b
		}
	}
	return def
}

func gD(o *jsonx.Obj, k string) *dates.Date {
	v, ok := o.Get(k)
	if !ok || v == nil || v == "" {
		return nil
	}
	d := dates.MustParse(v.(string))
	return &d
}

func gIP(o *jsonx.Obj, k string) *int64 {
	if v, ok := o.Get(k); ok && v != nil {
		x := golden.AsInt(v)
		return &x
	}
	return nil
}

func gDec(o *jsonx.Obj, k string) *dec.D { return decAny(o.MustGet(k)) }

func householdFromJSON(o *jsonx.Obj) *models.Household {
	h := models.NewHousehold()
	h.FilingStatus, h.State = gS(o, "filing_status", "mfj"), gS(o, "state", "CA")
	h.TaxYear = int(gI(o, "tax_year", 2025))
	h.WagesCents, h.OtherIncomeCents, h.MagiCents = gI(o, "wages_cents", 0), gI(o, "other_income_cents", 0), gI(o, "magi_cents", 0)
	h.ActiveParticipation, h.REProfessional = gB(o, "active_participation", true), gB(o, "re_professional", false)
	h.CarryforwardCents = gI(o, "carryforward_cents", 0)
	h.NetWorthCents = gIP(o, "net_worth_cents")
	h.Goal = gS(o, "goal", "")
	return h
}

func propertyFromJSON(o *jsonx.Obj) *models.Property {
	p := models.NewProperty()
	p.ID, p.Nickname, p.PropertyType = gS(o, "id", "p1"), gS(o, "nickname", ""), gS(o, "property_type", "sfr")
	p.Units = int(gI(o, "units", 1))
	if d := gD(o, "purchase_date"); d != nil {
		p.PurchaseDate = *d
	}
	p.PurchasePriceCents = gI(o, "purchase_price_cents", 0)
	p.PlacedInServiceDate = gD(o, "placed_in_service_date")
	p.LandPct = gDec(o, "land_pct")
	p.ImprovementsCents = gI(o, "improvements_cents", 0)
	p.CostSegStudy = gB(o, "cost_seg_study", false)
	p.CurrentValueCents = gI(o, "current_value_cents", 0)
	p.ValueSource = gS(o, "value_source", "estimated")
	p.ValueAsOf = gD(o, "value_as_of")
	p.AppreciationRate, p.RentGrowthRate, p.ExpenseGrowthRate = gDec(o, "appreciation_rate"), gDec(o, "rent_growth_rate"), gDec(o, "expense_growth_rate")
	p.VacancyRate, p.MgmtFeeRate, p.CapexReserveRate = gDec(o, "vacancy_rate"), gDec(o, "mgmt_fee_rate"), gDec(o, "capex_reserve_rate")
	p.SellingCostRate = gDec(o, "selling_cost_rate")
	p.Status = gS(o, "status", "active")
	p.FormerResidenceUntil = gD(o, "former_residence_until")
	if v, ok := o.Get("avg_stay_days"); ok && v != nil {
		f := jsonNum(v)
		p.AvgStayDays = &f
	}
	for _, lo := range objList(o.MustGet("loans")) {
		ln := golden.Loan(lo)
		ln.LienPosition = int(gI(lo, "lien_position", 1))
		ln.Lender = gS(lo, "lender", "")
		if id, ok := lo.Get("id"); ok && id != nil {
			s := fmt.Sprint(id)
			ln.ID = &s
		}
		p.Loans = append(p.Loans, ln)
	}
	if ys, ok := o.MustGet("years").(*jsonx.Obj); ok && ys != nil {
		for _, kv := range ys.Pairs() {
			y, err := strconv.Atoi(kv.K)
			if err != nil {
				panic(&service.InvalidInput{Msg: "years keys must be tax years"})
			}
			yo := kv.V.(*jsonx.Obj).Copy()
			yo.Set("tax_year", int64(y))
			ops := golden.Ops(yo)
			if src, ok := yo.MustGet("sources").(*jsonx.Obj); ok && src != nil {
				ops.Sources = map[string]*figure.Input{}
				for _, sk := range src.Pairs() {
					ops.Sources[sk.K] = inputFromJSON(sk.V.(*jsonx.Obj))
				}
			}
			p.AddYear(y, ops)
		}
	}
	for _, lr := range objList(o.MustGet("ledger")) {
		p.Ledger = append(p.Ledger, depreciation.LedgerRowFromObj(lr))
	}
	if ci, ok := o.MustGet("capital_improvements_paid").(*jsonx.Obj); ok && ci != nil {
		for _, kv := range ci.Pairs() {
			y, _ := strconv.Atoi(kv.K)
			p.CapitalImprovementsPaid[y] = golden.AsInt(kv.V)
		}
	}
	if bk, ok := o.MustGet("blocked_keys").([]any); ok {
		for _, k := range bk {
			if s, ok := k.(string); ok {
				p.BlockedKeys[s] = true
			}
		}
	}
	return p
}

var _ = cashflow.ExpenseLines

func engineBody(r *http.Request) (*jsonx.Obj, error) {
	v, p := readJSON(r, true)
	if p != nil {
		return nil, p
	}
	o, ok := v.(*jsonx.Obj)
	if !ok || !o.Has("property") || !o.Has("household") {
		return nil, NewProblem(422, "Invalid engine input", "body must carry `property` and `household`")
	}
	return o, nil
}

func engineCall[T any](fn func() T) (out T, err error) {
	defer func() {
		if r := recover(); r != nil {
			switch e := r.(type) {
			case *service.InvalidInput:
				err = e
			case *dec.ArithmeticError:
				err = &service.InvalidInput{Msg: e.Msg}
			case error:
				err = &service.InvalidInput{Msg: e.Error()}
			default:
				err = &service.InvalidInput{Msg: fmt.Sprint(e)}
			}
		}
	}()
	return fn(), nil
}

func (s *Server) engineAnalyze(w http.ResponseWriter, r *http.Request) (any, error) {
	o, err := engineBody(r)
	if err != nil {
		return nil, err
	}
	return engineCall(func() *jsonx.Obj {
		p := propertyFromJSON(o.MustGet("property").(*jsonx.Obj))
		h := householdFromJSON(o.MustGet("household").(*jsonx.Obj))
		horizon := int(gI(o, "horizon", 0))
		if horizon == 0 {
			horizon = 10
		}
		res := analysis.AnalyzeProperty(p, h, int(gI(o, "year", 0)), horizon, gI(o, "carryforward_release", 0), gS(o, "mode", "table"))
		if gB(o, "private", false) {
			var bal []any
			for _, b := range res.Balances {
				bal = append(bal, b)
			}
			if bal == nil {
				bal = []any{}
			}
			priv := jsonx.O("net_cents", res.NetCents, "noi_cents", res.NOICents, "line21_cents", res.Line21Cents, "dscr", res.DSCR,
				"equity_cents", res.EquityCents, "roe", res.ROE, "exit_tax_cents", res.ExitTaxCents, "dep_outlier", res.DepOutlier,
				"balances", bal, "annual_debt", res.AnnualDebt.ToDict(), "concentration", res.Concentration, "land_bounded", res.LandBounded,
				"findings", anyList(res.Findings, func(x *jsonx.Obj) any { return x }),
				"figure_keys", anyList(res.FigOrder, func(x string) any { return x }))
			return jsonx.O("analysis", res.Out, "private", priv)
		}
		return res.Out
	})
}

func (s *Server) engineStrategies(w http.ResponseWriter, r *http.Request) (any, error) {
	o, err := engineBody(r)
	if err != nil {
		return nil, err
	}
	return engineCall(func() *jsonx.Obj {
		p := propertyFromJSON(o.MustGet("property").(*jsonx.Obj))
		h := householdFromJSON(o.MustGet("household").(*jsonx.Obj))
		ao, _ := o.MustGet("assumptions").(*jsonx.Obj)
		if ao == nil {
			ao = jsonx.O()
		}
		a := strategies.NewAssumptions()
		a.HorizonYears = int(gI(ao, "horizon_years", 10))
		a.AppreciationRate, a.RentGrowth, a.ExpenseGrowth = gDec(ao, "appreciation_rate"), gDec(ao, "rent_growth"), gDec(ao, "expense_growth")
		if d := gDec(ao, "reinvest_rate"); d != nil {
			a.ReinvestRate = *d
		}
		a.StartYear = int(gI(ao, "start_year", 0))
		if x, ok := ao.MustGet("exchange").(*jsonx.Obj); ok && x != nil {
			a.Exchange.ReplacementValueCents, a.Exchange.ReplacementDebtCents = gIP(x, "replacement_value_cents"), gIP(x, "replacement_debt_cents")
			a.Exchange.DST = gB(x, "dst", false)
			if d := gDec(x, "load_rate"); d != nil {
				a.Exchange.LoadRate = *d
			}
			if d := gDec(x, "dst_yield"); d != nil {
				a.Exchange.DSTYield = *d
			}
			a.Exchange.CashTakenCents = gI(x, "cash_taken_cents", 0)
			if st := gS(x, "replacement_state", ""); st != "" {
				a.Exchange.ReplacementState = &st
			}
		}
		res := strategies.Compare(p, h, a)
		if pr, ok := o.MustGet("present").(*jsonx.Obj); ok && pr != nil {
			var reason *string
			if v, ok := pr.Get("base_reason"); ok && v != nil {
				s := fmt.Sprint(v)
				reason = &s
			}
			res = strategies.Present(res, gS(pr, "base_status", "confirmed"), reason)
		}
		return res
	})
}

// inputFromJSON decodes a wire Input {key, value, source: {type, ref, page, document_id, bbox}, label}.
func inputFromJSON(o *jsonx.Obj) *figure.Input {
	in := &figure.Input{Key: gS(o, "key", ""), Value: o.MustGet("value"), Label: gS(o, "label", "")}
	src := o.MustGet("source").(*jsonx.Obj)
	if src == nil {
		src = jsonx.O()
	}
	in.Source.Type = gS(src, "type", "manual")
	if v, ok := src.Get("ref"); ok && v != nil {
		r := fmt.Sprint(v)
		in.Source.Ref = &r
	}
	if v, ok := src.Get("page"); ok && v != nil {
		pg := int(golden.AsInt(v))
		in.Source.Page = &pg
	}
	if v, ok := src.Get("document_id"); ok && v != nil {
		d := fmt.Sprint(v)
		in.Source.DocumentID = &d
	}
	if v, ok := src.MustGet("bbox").([]any); ok && len(v) > 0 {
		in.Source.BBox = v
	}
	return in
}
