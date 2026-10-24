// Package service ports backend/groundplan/services: map tenant rows onto engine models (with document
// provenance), run the engine, and shape the API dicts exactly like services/portfolio.py.
package service

import (
	"context"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/analysis"
	"github.com/tachyurgy/groundplan/engine-go/engine/cashflow"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/engine/depreciation"
	"github.com/tachyurgy/groundplan/engine-go/engine/figure"
	"github.com/tachyurgy/groundplan/engine-go/engine/loans"
	"github.com/tachyurgy/groundplan/engine-go/engine/models"
	"github.com/tachyurgy/groundplan/engine-go/engine/narrative"
	"github.com/tachyurgy/groundplan/engine-go/engine/observations"
	"github.com/tachyurgy/groundplan/engine-go/engine/passive"
	"github.com/tachyurgy/groundplan/engine-go/internal/store"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// InvalidInput is the Go stand-in for the ValueError / ArithmeticError the Python routes turn into 422.
type InvalidInput struct{ Msg string }

func (e *InvalidInput) Error() string { return e.Msg }

var schedELine = map[int]string{3: "gross_rent_cents", 4: "other_income_cents", 9: "insurance_cents", 11: "mgmt_cents",
	12: "mortgage_interest_cents", 14: "repairs_cents", 16: "taxes_cents", 17: "utilities_cents", 18: "depreciation_cents", 19: "other_cents"}

var fieldHints = [][2]string{{"rent", "gross_rent_cents"}, {"interest", "mortgage_interest_cents"}, {"depreciation", "depreciation_cents"},
	{"insurance", "insurance_cents"}, {"repairs", "repairs_cents"}, {"taxes", "taxes_cents"}, {"utilities", "utilities_cents"},
	{"management", "mgmt_cents"}, {"mgmt", "mgmt_cents"}, {"hoa", "hoa_cents"}, {"value", "current_value_cents"},
	{"purchase_price", "purchase_price_cents"}}

var lineRE = regexp.MustCompile(`line(\d+)`)

// InputKeyForField maps a pipeline field name onto the engine input key ("" = none).
func InputKeyForField(field string) string {
	if m := lineRE.FindStringSubmatch(field); m != nil && strings.HasPrefix(field, "schedule_e") {
		n, _ := strconv.Atoi(m[1])
		if k, ok := schedELine[n]; ok {
			return k
		}
	}
	f := strings.ToLower(field)
	if strings.Contains(f, "balance") {
		return "loan_balance"
	}
	for _, h := range fieldHints {
		if strings.Contains(f, h[0]) {
			return h[1]
		}
	}
	return ""
}

// LatestCarryforward is the carryforward of the latest suspended-loss year.
func LatestCarryforward(h *store.Household) int64 {
	if len(h.SuspendedLosses) == 0 {
		return 0
	}
	best := h.SuspendedLosses[0]
	for _, x := range h.SuspendedLosses[1:] {
		if x.TaxYear > best.TaxYear {
			best = x
		}
	}
	return best.CarryforwardCents
}

// HouseholdModel maps a household row.
func HouseholdModel(h *store.Household) *models.Household {
	return &models.Household{FilingStatus: h.FilingStatus, State: h.State, TaxYear: h.TaxYearLatest, WagesCents: h.WagesCents,
		OtherIncomeCents: h.OtherIncomeCents, MagiCents: h.MagiCents, ActiveParticipation: h.ActiveParticipation,
		REProfessional: h.REProfessional, CarryforwardCents: LatestCarryforward(h), NetWorthCents: h.NetWorthCents, Goal: h.Goal}
}

type ykey struct {
	year int
	key  string
}

func (svc *Service) fieldSources(ctx context.Context, p *store.Property, aid string) (map[ykey]*figure.Input, error) {
	out := map[ykey]*figure.Input{}
	if p.PropertyKey == nil || *p.PropertyKey == "" {
		return out, nil
	}
	rows, err := store.FieldSources(ctx, svc.Q(ctx), aid, p.HouseholdID, *p.PropertyKey)
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		key := InputKeyForField(r.Field.Field)
		if key == "" || r.Doc.TaxYear == nil {
			continue
		}
		k := ykey{*r.Doc.TaxYear, key}
		if prev := out[k]; prev != nil && r.Doc.Kind != "schedule_e" {
			continue
		}
		ref := fmt.Sprintf("%s (%s %d) %s", r.Doc.Filename, r.Doc.Kind, *r.Doc.TaxYear, r.Field.Field)
		page := r.Field.Page
		did := r.Doc.ID
		var bbox []any
		if b, ok := r.Field.BBox.([]any); ok && len(b) > 0 {
			bbox = b
		}
		out[k] = &figure.Input{Key: key, Value: r.Field.Value, Source: figure.Source{Type: "document", Ref: &ref, Page: &page,
			DocumentID: &did, BBox: bbox}}
	}
	return out, nil
}

// BlockedKeysFor is blocked_keys_for(p, findings).
func BlockedKeysFor(p *store.Property, findings []*store.Finding) figure.KeySet {
	keys := figure.KeySet{}
	for _, f := range findings {
		if f.Status != "open" || f.Severity != "block" || !(f.PropertyID == nil || *f.PropertyID == p.ID) {
			continue
		}
		k := InputKeyForField(f.Field)
		if k == "loan_balance" {
			for i := range p.Loans {
				keys[fmt.Sprintf("loan[%d].balance_cents", i)] = true
			}
		} else if k != "" {
			keys[k] = true
		}
	}
	return keys
}

// PropertyModel maps a property row (with sources and blocked keys).
func (svc *Service) PropertyModel(ctx context.Context, p *store.Property, aid string, findings []*store.Finding) (*models.Property, error) {
	srcs, err := svc.fieldSources(ctx, p, aid)
	if err != nil {
		return nil, err
	}
	pm := models.NewProperty()
	rr := map[int]*store.RentRoll{}
	ex := map[int]*store.ExpenseYear{}
	yset := map[int]bool{}
	for _, r := range p.RentRolls {
		rr[r.TaxYear] = r
		yset[r.TaxYear] = true
	}
	for _, e := range p.ExpenseYears {
		ex[e.TaxYear] = e
		yset[e.TaxYear] = true
	}
	var years []int
	for y := range yset {
		years = append(years, y)
	}
	sort.Ints(years)
	for _, y := range years {
		o := &cashflow.YearOperations{TaxYear: y, Sources: map[string]*figure.Input{}}
		if r := rr[y]; r != nil {
			o.GrossRentCents, o.OtherIncomeCents = r.GrossRentCents, r.OtherIncomeCents
		}
		if e := ex[y]; e != nil {
			for _, k := range store.ExpenseKeys {
				o.Set(k, e.Cents[k])
			}
		}
		for _, k := range append([]string{"gross_rent_cents", "other_income_cents"}, store.ExpenseKeys...) {
			if s := srcs[ykey{y, k}]; s != nil {
				o.Sources[k] = s
			} else {
				o.Sources[k] = figure.Of(k, o.Get(k), "manual", fmt.Sprintf("%d rent roll / expense year (entered)", y))
			}
		}
		pm.AddYear(y, o)
	}
	for _, ln := range p.Loans {
		id := ln.ID
		pm.Loans = append(pm.Loans, &loans.Input{LoanType: ln.LoanType, BalanceCents: ln.BalanceCents, BalanceAsOf: ln.BalanceAsOf,
			Rate: ln.Rate, TermMonths: ln.TermMonths, IOMonths: ln.IOMonths, ArmResetDate: ln.ArmResetDate, ArmIndexMargin: ln.ArmIndexMargin,
			MonthlyPaymentCents: ln.MonthlyPaymentCents, MaturityDate: ln.MaturityDate, LienPosition: ln.LienPosition, IsPaidOff: ln.IsPaidOff,
			Lender: ln.Lender, ID: &id})
	}
	for _, d := range p.Ledger {
		allowed := d.AllowedCents
		pm.Ledger = append(pm.Ledger, depreciation.NewLedgerRow(d.TaxYear, &allowed, d.AllowableCents, d.Method))
	}
	pm.ID, pm.Nickname, pm.PropertyType, pm.Units = p.ID, p.Nickname, p.PropertyType, p.Units
	if p.PurchaseDate != nil {
		pm.PurchaseDate = *p.PurchaseDate
	} else {
		pm.PurchaseDate = dates.New(2015, 1, 1)
	}
	pm.PurchasePriceCents, pm.PlacedInServiceDate, pm.LandPct, pm.ImprovementsCents = p.PurchasePriceCents, p.PlacedInServiceDate, p.LandPct, p.ImprovementsCents
	pm.CostSegStudy, pm.CurrentValueCents, pm.ValueSource, pm.ValueAsOf = p.CostSegStudy, p.CurrentValueCents, p.ValueSource, p.ValueAsOf
	pm.AppreciationRate, pm.RentGrowthRate, pm.ExpenseGrowthRate = p.AppreciationRate, p.RentGrowthRate, p.ExpenseGrowthRate
	pm.VacancyRate, pm.MgmtFeeRate, pm.CapexReserveRate, pm.SellingCostRate = p.VacancyRate, p.MgmtFeeRate, p.CapexReserveRate, p.SellingCostRate
	pm.Status, pm.FormerResidenceUntil, pm.AvgStayDays = p.Status, p.FormerResidenceUntil, p.AvgStayDays
	pm.BlockedKeys = BlockedKeysFor(p, findings)
	return pm, nil
}

// OpenFindings filters open findings.
func OpenFindings(h *store.Household) []*store.Finding {
	var out []*store.Finding
	for _, f := range h.Findings {
		if f.Status == "open" {
			out = append(out, f)
		}
	}
	return SortFindings(h, out)
}

var severityRank = map[string]int{"block": 0, "warn": 1, "info": 2}

// SortFindings is sort_findings(h, findings): the one findings order on both stacks, severity rank (block, warn, info),
// property nickname (no property first), kind, key, field, id; byte order, matching store.FindingsOrderBy (COLLATE "C").
func SortFindings(h *store.Household, fs []*store.Finding) []*store.Finding {
	nick := map[string]string{}
	for _, p := range h.Properties {
		nick[p.ID] = p.Nickname
	}
	type k struct {
		rank    int
		hasProp bool
		nick    string
		kind    string
		key     string
		field   string
		id      string
	}
	keyOf := func(f *store.Finding) k {
		r, ok := severityRank[f.Severity]
		if !ok {
			r = 3
		}
		x := k{rank: r, kind: f.Kind, field: f.Field, id: f.ID}
		if f.PropertyID != nil {
			x.nick, x.hasProp = nick[*f.PropertyID]
		}
		if f.Key != nil {
			x.key = *f.Key
		}
		return x
	}
	out := append([]*store.Finding{}, fs...)
	sort.SliceStable(out, func(i, j int) bool {
		a, b := keyOf(out[i]), keyOf(out[j])
		switch {
		case a.rank != b.rank:
			return a.rank < b.rank
		case a.hasProp != b.hasProp:
			return !a.hasProp
		case a.nick != b.nick:
			return a.nick < b.nick
		case a.kind != b.kind:
			return a.kind < b.kind
		case a.key != b.key:
			return a.key < b.key
		case a.field != b.field:
			return a.field < b.field
		}
		return a.id < b.id
	})
	return out
}

func obsAPI(o *jsonx.Obj, idx int) *jsonx.Obj {
	sevMap := map[string]string{"alert": "warn", "warn": "warn", "info": "info"}
	sev := o.MustGet("severity").(string)
	pid := o.MustGet("property_id")
	pidS := "household"
	if pid != nil {
		pidS = pid.(string)
	}
	return jsonx.O("id", fmt.Sprintf("%s:%s:%d", o.MustGet("rule"), pidS, idx), "severity", sevMap[sev], "level", sev,
		"rule", o.MustGet("rule"), "message", o.MustGet("message"), "property_id", pid, "figures", o.MustGet("cites"))
}

// AnalysisOverrides are the what-if query params of /analysis.
var AnalysisOverrides = []string{"appreciation_rate", "rent_growth_rate", "expense_growth_rate", "vacancy_rate", "capex_reserve_rate",
	"selling_cost_rate", "land_pct", "current_value_cents", "arm_index"}

// Override is one (key, value) query override in the Python dict order.
type Override struct{ K, V string }

func parseDecimal(v string) (dec.D, error) {
	d, err := dec.Parse(v)
	if err != nil {
		return d, &InvalidInput{Msg: err.Error()}
	}
	return d, nil
}

// PyInt is Python int(str): optional sign, digits, underscores, surrounding whitespace.
func PyInt(v string) (int64, error) {
	s := strings.ReplaceAll(strings.TrimSpace(v), "_", "")
	i, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return 0, &InvalidInput{Msg: fmt.Sprintf("invalid literal for int() with base 10: %s", pyRepr(v))}
	}
	return i, nil
}

func pyRepr(s string) string { return "'" + strings.ReplaceAll(s, "'", `\'`) + "'" }

// ApplyOverrides is apply_overrides(pm, overrides).
func ApplyOverrides(pm *models.Property, ov []Override) ([]string, error) {
	var applied []string
	for _, o := range ov {
		if o.V == "" {
			continue
		}
		switch o.K {
		case "arm_index":
			d, err := parseDecimal(o.V)
			if err != nil {
				return nil, err
			}
			for _, ln := range pm.Loans {
				if ln.LoanType == "arm" {
					x := d
					ln.ArmIndex = &x
				}
			}
			applied = append(applied, o.K)
		case "current_value_cents":
			i, err := PyInt(o.V)
			if err != nil {
				return nil, err
			}
			pm.CurrentValueCents = i
			pm.ValueSource = "confirmed"
			applied = append(applied, o.K)
		default:
			d, err := parseDecimal(o.V)
			if err != nil {
				return nil, err
			}
			x := &d
			switch o.K {
			case "appreciation_rate":
				pm.AppreciationRate = x
			case "rent_growth_rate":
				pm.RentGrowthRate = x
			case "expense_growth_rate":
				pm.ExpenseGrowthRate = x
			case "vacancy_rate":
				pm.VacancyRate = x
			case "capex_reserve_rate":
				pm.CapexReserveRate = x
			case "selling_cost_rate":
				pm.SellingCostRate = x
			case "land_pct":
				pm.LandPct = x
			default:
				continue
			}
			applied = append(applied, o.K)
		}
	}
	return applied, nil
}

// Analyzed is the (an, pm, hm) triple returned by services.portfolio.analyze.
type Analyzed struct {
	R            *analysis.Result
	PM           *models.Property
	HM           *models.Household
	Observations []any
}

// Out is the public analysis dict (Python's dict minus the private keys, plus overrides_applied/observations).
func (a *Analyzed) Out() *jsonx.Obj { return a.R.Out }

// Analyze is services.portfolio.analyze(s, p, advisor_id, year, horizon, overrides).
func (svc *Service) Analyze(ctx context.Context, p *store.Property, aid string, year, horizon int, ov []Override) (an *Analyzed, err error) {
	defer recoverArith(&err)
	h := p.Household
	pm, err := svc.PropertyModel(ctx, p, aid, h.Findings)
	if err != nil {
		return nil, err
	}
	applied, err := ApplyOverrides(pm, ov)
	if err != nil {
		return nil, err
	}
	hm := HouseholdModel(h)
	if year == 0 {
		year = h.TaxYearLatest
	}
	r := analysis.AnalyzeProperty(pm, hm, year, horizon, 0, "table")
	ap := make([]any, len(applied))
	for i, x := range applied {
		ap[i] = x
	}
	r.Out.Set("overrides_applied", ap)
	pid := p.ID
	octx := observations.PropertyContext(p.Nickname, observations.AnalysisFacts{NetCents: r.NetCents, DSCR: r.DSCR, ROE: r.ROE,
		EquityCents: r.EquityCents, ExitTaxCents: r.ExitTaxCents, LandBounded: r.LandBounded, DepOutlier: r.DepOutlier,
		Concentration: r.Concentration}, pm, models.Defaults["reinvest_rate"], dates.New(r.Year+1, 1, 1))
	var obs []any
	for i, o := range observations.Evaluate(octx, "property", &pid) {
		obs = append(obs, obsAPI(o, i))
	}
	if obs == nil {
		obs = []any{}
	}
	r.Out.Set("observations", obs)
	return &Analyzed{R: r, PM: pm, HM: hm, Observations: obs}, nil
}

func figureStatus(ss ...string) string { return figure.WorstOf(ss...) }

func obj(v any, path ...string) *jsonx.Obj {
	o := v.(*jsonx.Obj)
	for _, k := range path {
		o = o.MustGet(k).(*jsonx.Obj)
	}
	return o
}

func vc(o *jsonx.Obj) int64 {
	switch x := o.MustGet("value_cents").(type) {
	case *int64:
		if x == nil {
			return 0
		}
		return *x
	case int64:
		return x
	}
	return 0
}

func st(o *jsonx.Obj) string { return o.MustGet("status").(string) }

// PropertyCard is property_card(p, an, n_findings).
func PropertyCard(p *store.Property, an *Analyzed, nFindings int) *jsonx.Obj {
	out := an.Out()
	cf, eq, ex := obj(out, "cash_flow"), obj(out, "equity"), obj(out, "exit_tax")
	set := map[string]bool{st(obj(cf, "net_cash_flow")): true, st(obj(eq, "equity")): true, st(obj(ex, "exit_tax_total")): true}
	var chips []string
	for k := range set {
		chips = append(chips, k)
	}
	sort.Strings(chips)
	ch := make([]any, len(chips))
	for i, c := range chips {
		ch[i] = c
	}
	return jsonx.O("property", PropertyDict(p), "value", eq.MustGet("value"), "equity", eq.MustGet("equity"),
		"net_cash_flow", cf.MustGet("net_cash_flow"), "exit_tax", ex.MustGet("exit_tax_total"), "roe", eq.MustGet("roe"),
		"roe_rate", eq.MustGet("roe_rate"), "status_chips", ch, "open_findings", nFindings, "dscr", cf.MustGet("dscr"),
		"observations", out.MustGet("observations"))
}

type propAn struct {
	p  *store.Property
	an *Analyzed
}

// Dashboard is services.portfolio.dashboard(s, h, advisor_id).
func (svc *Service) Dashboard(ctx context.Context, h *store.Household, aid string) (*jsonx.Obj, []propAn, error) {
	var figs []propAn
	for _, p := range h.Properties {
		if p.Status != "active" {
			continue
		}
		an, err := svc.Analyze(ctx, p, aid, 0, 10, nil)
		if err != nil {
			return nil, nil, err
		}
		figs = append(figs, propAn{p, an})
	}
	hm := HouseholdModel(h)
	findings := OpenFindings(h)
	tot := map[string]int64{}
	statuses := map[string][]string{}
	for _, pa := range figs {
		out := pa.an.Out()
		eq, cf, ex := obj(out, "equity"), obj(out, "cash_flow"), obj(out, "exit_tax")
		tot["value"] += vc(obj(eq, "value"))
		tot["debt"] += vc(obj(eq, "total_debt"))
		tot["equity"] += vc(obj(eq, "equity"))
		tot["net"] += vc(obj(cf, "net_cash_flow"))
		tot["exit"] += vc(obj(ex, "exit_tax_total"))
		if pa.an.R.Line21Cents != nil {
			tot["line21"] += *pa.an.R.Line21Cents
		}
		statuses["value"] = append(statuses["value"], st(obj(eq, "value")))
		statuses["debt"] = append(statuses["debt"], st(obj(eq, "total_debt")))
		statuses["equity"] = append(statuses["equity"], st(obj(eq, "equity")))
		statuses["net"] = append(statuses["net"], st(obj(cf, "net_cash_flow")))
		statuses["exit"] = append(statuses["exit"], st(obj(ex, "exit_tax_total")))
	}
	agg := func(key, label, tk, p0, p1, formula string) *jsonx.Obj {
		var inputs []*figure.Input
		for _, pa := range figs {
			fo := obj(pa.an.Out(), p0, p1)
			ref := fmt.Sprintf("properties/%s/%s", pa.p.ID, fo.MustGet("key"))
			s := st(fo)
			inputs = append(inputs, &figure.Input{Key: pa.p.Nickname + "." + p1, Value: vc(fo), Source: figure.Source{Type: "figure", Ref: &ref}, Status: &s})
		}
		if len(inputs) == 0 {
			inputs = figure.L(figure.M(key, int64(0)))
		}
		f := figure.MoneyI(key, tot[tk], inputs, formula, nil, nil)
		if len(statuses[tk]) > 0 {
			f.Status = figureStatus(statuses[tk]...)
		} else {
			f.Status = "confirmed"
		}
		d := f.ToDict()
		d.Set("label", label)
		return d
	}
	var strDays []passive.STRDays
	for _, pa := range figs {
		if pa.an.PM.AvgStayDays != nil {
			strDays = append(strDays, passive.STRDays{Key: pa.p.Nickname, Days: pa.an.PM.AvgStayDays})
		}
	}
	pas := passive.Apply(tot["line21"], hm.CarryforwardCents, hm.MagiCents, hm.FilingStatus, hm.ActiveParticipation, hm.REProfessional, strDays, nil)
	var nriInputs []*figure.Input
	for _, pa := range figs {
		nriInputs = append(nriInputs, figure.Of(pa.p.Nickname+".line21", pa.an.R.Line21Cents, "figure"))
	}
	if len(nriInputs) == 0 {
		nriInputs = figure.L(figure.M("line21", int64(0)))
	}
	metrics := jsonx.O(
		"total_value", agg("household.total_value", "Portfolio value", "value", "equity", "value", "sum of property values"),
		"total_debt", agg("household.total_debt", "Total debt", "debt", "equity", "total_debt", "sum of lien balances"),
		"total_equity", agg("household.total_equity", "Total equity", "equity", "equity", "equity", "sum of property equity"),
		"net_cash_flow", agg("household.net_cash_flow", "Net cash flow (annual)", "net", "cash_flow", "net_cash_flow", "sum of property net cash flow"),
		"exit_tax_total", agg("household.exit_tax_total", "Exit tax if all sold today", "exit", "exit_tax", "exit_tax_total",
			"sum of per-property exit tax (each stacked on the household's other income separately)"),
		"passive_allowance", pas.Allowance.ToDict().Set("label", "Rental loss allowance (8582)"),
		"suspended_losses", pas.CarryforwardEnd.ToDict().Set("label", "Suspended passive losses"),
		"net_rental_income", figure.MoneyI("household.net_rental_income", tot["line21"], nriInputs, "sum of Schedule E line 21", nil, nil).
			ToDict().Set("label", "Net rental income (Sch E)"),
	)
	var obsList []*jsonx.Obj
	for _, pa := range figs {
		for _, o := range pa.an.Observations {
			obsList = append(obsList, o.(*jsonx.Obj))
		}
	}
	allow := pas.Allowance.ValueCents
	hctx := &observations.Ctx{CarryforwardCents: hm.CarryforwardCents, MagiCents: hm.MagiCents, NetRentalCents: tot["line21"], AllowanceCents: allow}
	for i, o := range observations.Evaluate(hctx, "household", nil) {
		obsList = append(obsList, obsAPI(o, i))
	}
	order := map[string]int{"alert": 0, "warn": 1, "info": 2}
	sort.SliceStable(obsList, func(i, j int) bool {
		return order[obsList[i].MustGet("level").(string)] < order[obsList[j].MustGet("level").(string)]
	})
	var cards []any
	for _, pa := range figs {
		n := 0
		for _, f := range findings {
			if f.PropertyID != nil && *f.PropertyID == pa.p.ID {
				n++
			}
		}
		cards = append(cards, PropertyCard(pa.p, pa.an, n))
	}
	if cards == nil {
		cards = []any{}
	}
	facts := &narrative.Facts{HouseholdName: h.Name, Goal: h.Goal, PropertyCount: len(figs), TotalValue: observations.USDi(tot["value"]),
		TotalDebt: observations.USDi(tot["debt"]), TotalEquity: observations.USDi(tot["equity"]), NetCashFlow: observations.USDi(tot["net"]),
		ExitTaxTotal: observations.USDi(tot["exit"])}
	if hm.CarryforwardCents != 0 {
		c := observations.USDi(hm.CarryforwardCents)
		facts.Carryforward = &c
	}
	obsAny := make([]any, len(obsList))
	for i, o := range obsList {
		obsAny[i] = o
		if lv := o.MustGet("level").(string); lv == "alert" || lv == "warn" {
			facts.Observations = append(facts.Observations, o.MustGet("message").(string))
		}
	}
	var inactive []any
	for _, p := range h.Properties {
		if p.Status != "active" {
			inactive = append(inactive, PropertyDict(p))
		}
	}
	if inactive == nil {
		inactive = []any{}
	}
	out := jsonx.O("household", HouseholdDict(h), "metrics", metrics, "observations", obsAny, "properties", cards,
		"findings_open", len(findings), "narrative", narrative.Generate(facts), "inactive_properties", inactive)
	return out, figs, nil
}

// Summary is services.portfolio.summary(s, h, advisor_id).
func (svc *Service) Summary(ctx context.Context, h *store.Household, aid string) (*jsonx.Obj, error) {
	var net, eq int64
	var statuses []string
	count := 0
	for _, p := range h.Properties {
		if p.Status != "active" {
			continue
		}
		count++
		an, err := svc.Analyze(ctx, p, aid, 0, 1, nil)
		if err != nil {
			return nil, err
		}
		out := an.Out()
		ncf, e := obj(out, "cash_flow", "net_cash_flow"), obj(out, "equity", "equity")
		net += vc(ncf)
		eq += vc(e)
		statuses = append(statuses, st(ncf), st(e))
	}
	status := "confirmed"
	if len(statuses) > 0 {
		status = figureStatus(statuses...)
	}
	return jsonx.O("id", h.ID, "name", h.Name, "state", h.State, "filing_status", h.FilingStatus, "property_count", count,
		"net_cash_flow_cents", net, "total_equity_cents", eq, "open_findings", len(OpenFindings(h)), "status", status), nil
}

// Alerts is services.portfolio.alerts(s, h, advisor_id).
func (svc *Service) Alerts(ctx context.Context, h *store.Household, aid string) ([]any, error) {
	today := dates.New(h.TaxYearLatest+1, 1, 1)
	type al struct {
		kind string
		p    *store.Property
		d    dates.Date
		msg  string
	}
	var out []al
	for _, p := range h.Properties {
		if p.Status != "active" {
			continue
		}
		for _, ln := range p.Loans {
			if ln.IsPaidOff {
				continue
			}
			if ln.ArmResetDate != nil {
				if d := dates.Days(*ln.ArmResetDate, today); 0 <= d && d <= 730 {
					out = append(out, al{"arm_reset", p, *ln.ArmResetDate, fmt.Sprintf("%s: ARM with %s resets %s", p.Nickname, ln.Lender, dates.ISO(*ln.ArmResetDate))})
				}
			}
			if ln.IOMonths != 0 && ln.LoanType != "heloc" {
				mth := int(ln.BalanceAsOf.Month()) + ln.IOMonths
				end := dates.New(ln.BalanceAsOf.Year()+floorDiv(mth-1, 12), floorMod(mth-1, 12)+1, 1)
				if d := dates.Days(end, today); 0 <= d && d <= 730 {
					out = append(out, al{"io_period_ending", p, end, fmt.Sprintf("%s: interest-only period ends %s", p.Nickname, dates.ISO(end))})
				}
			}
			if ln.MaturityDate != nil {
				if d := dates.Days(*ln.MaturityDate, today); 0 <= d && d <= 1095 {
					out = append(out, al{"loan_maturity", p, *ln.MaturityDate, fmt.Sprintf("%s: %s loan matures %s", p.Nickname, ln.Lender, dates.ISO(*ln.MaturityDate))})
				}
			}
		}
		if p.ValueAsOf != nil && dates.Days(today, *p.ValueAsOf) > 365 {
			out = append(out, al{"value_drift", p, today, fmt.Sprintf("%s: value is more than a year old (%s); refresh it", p.Nickname, dates.ISO(*p.ValueAsOf))})
		}
		an, err := svc.Analyze(ctx, p, aid, 0, 1, nil)
		if err != nil {
			return nil, err
		}
		if an.R.NetCents != nil && *an.R.NetCents < 0 {
			out = append(out, al{"cash_flow_negative", p, today, fmt.Sprintf("%s: negative cash flow %s/yr", p.Nickname, observations.USD(an.R.NetCents))})
		}
		if an.R.ROE != nil && dec.S(*an.R.ROE).Lt(models.Defaults["reinvest_rate"]) {
			out = append(out, al{"roe_below_threshold", p, today, fmt.Sprintf("%s: ROE %s%% below 6.0%%", p.Nickname, dec.S(*an.R.ROE).Mul(dec.I(100)).Fixed(1))})
		}
	}
	res := make([]any, len(out))
	for i, a := range out {
		res[i] = jsonx.O("id", fmt.Sprintf("%s:%s:%d", a.kind, a.p.ID, i), "household_id", h.ID, "property_id", a.p.ID, "kind", a.kind,
			"due_date", dates.ISO(a.d), "message", a.msg, "status", "open")
	}
	return res, nil
}

func floorDiv(a, b int) int {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}

func floorMod(a, b int) int { return a - floorDiv(a, b)*b }

// --- serializers -------------------------------------------------------------------------------------------

func isoDate(d *time.Time) any {
	if d == nil {
		return nil
	}
	return dates.ISO(*d)
}

func num(x *dec.D) any {
	if x == nil {
		return nil
	}
	return jsonx.Float(x.Float64())
}

// HouseholdDict is household_dict(h).
func HouseholdDict(h *store.Household) *jsonx.Obj {
	sl := append([]*store.SuspendedLoss{}, h.SuspendedLosses...)
	sort.SliceStable(sl, func(i, j int) bool { return sl[i].TaxYear < sl[j].TaxYear })
	sls := make([]any, len(sl))
	for i, x := range sl {
		sls[i] = jsonx.O("id", x.ID, "household_id", h.ID, "tax_year", x.TaxYear, "carryforward_cents", x.CarryforwardCents)
	}
	return jsonx.O("id", h.ID, "advisor_id", h.AdvisorID, "name", h.Name, "filing_status", h.FilingStatus, "state", h.State,
		"tax_year_latest", h.TaxYearLatest, "wages_cents", h.WagesCents, "other_income_cents", h.OtherIncomeCents,
		"magi_cents", h.MagiCents, "active_participation", h.ActiveParticipation, "re_professional", h.REProfessional,
		"net_worth_cents", h.NetWorthCents, "goal", h.Goal, "notes", h.Notes, "suspended_losses", sls)
}

// PropertyRateFields in model order.
var PropertyRateFields = []string{"land_pct", "appreciation_rate", "rent_growth_rate", "expense_growth_rate", "vacancy_rate",
	"mgmt_fee_rate", "capex_reserve_rate", "selling_cost_rate"}

// PropertyDict is property_dict(p).
func PropertyDict(p *store.Property) *jsonx.Obj {
	var stay any
	if p.AvgStayDays != nil {
		stay = jsonx.Float(*p.AvgStayDays)
	}
	d := jsonx.O("id", p.ID, "household_id", p.HouseholdID, "nickname", p.Nickname, "address_line1", p.AddressLine1, "city", p.City,
		"state", p.State, "zip", p.Zip, "property_type", p.PropertyType, "units", p.Units, "purchase_date", isoDate(p.PurchaseDate),
		"purchase_price_cents", p.PurchasePriceCents, "placed_in_service_date", isoDate(p.PlacedInServiceDate),
		"improvements_cents", p.ImprovementsCents, "cost_seg_study", p.CostSegStudy, "current_value_cents", p.CurrentValueCents,
		"value_source", p.ValueSource, "value_as_of", isoDate(p.ValueAsOf), "status", p.Status,
		"former_residence_until", isoDate(p.FormerResidenceUntil), "avg_stay_days", stay, "property_key", p.PropertyKey)
	for _, k := range PropertyRateFields {
		d.Set(k, num(p.Rate(k)))
	}
	eff := jsonx.O()
	for _, k := range PropertyRateFields {
		if k == "land_pct" {
			continue
		}
		if def, ok := models.Defaults[k]; ok && p.Rate(k) == nil {
			eff.Set(k, jsonx.Float(def.Float64()))
		} else {
			eff.Set(k, num(p.Rate(k)))
		}
	}
	if p.LandPct != nil {
		eff.Set("land_pct", num(p.LandPct))
	} else {
		eff.Set("land_pct", jsonx.Float(0.30))
	}
	d.Set("effective_rates", eff)
	return d
}

// LoanDict is loan_dict(ln).
func LoanDict(ln *store.Loan) *jsonx.Obj {
	r := ln.Rate
	return jsonx.O("id", ln.ID, "property_id", ln.PropertyID, "lender", ln.Lender, "loan_type", ln.LoanType,
		"original_cents", ln.OriginalCents, "balance_cents", ln.BalanceCents, "balance_as_of", dates.ISO(ln.BalanceAsOf),
		"rate", num(&r), "term_months", ln.TermMonths, "io_months", ln.IOMonths, "arm_reset_date", isoDate(ln.ArmResetDate),
		"arm_index_margin", num(ln.ArmIndexMargin), "monthly_payment_cents", ln.MonthlyPaymentCents,
		"maturity_date", isoDate(ln.MaturityDate), "lien_position", ln.LienPosition, "is_paid_off", ln.IsPaidOff)
}

// FindingDict is finding_dict(f).
func FindingDict(f *store.Finding) *jsonx.Obj {
	cands := f.Candidates
	if cands == nil {
		cands = []any{}
	}
	return jsonx.O("id", f.ID, "household_id", f.HouseholdID, "property_id", f.PropertyID, "kind", f.Kind, "field", f.Field,
		"severity", f.Severity, "message", f.Message, "candidates", cands, "status", f.Status, "resolution", f.Resolution, "key", f.Key)
}

// DocumentDict is document_dict(d).
func (svc *Service) DocumentDict(d *store.Document) *jsonx.Obj {
	return jsonx.O("id", d.ID, "household_id", d.HouseholdID, "kind", d.Kind, "tax_year", d.TaxYear, "filename", d.Filename,
		"sha256", d.Sha256, "page_count", d.PageCount, "uploaded_at", svc.PyISO(d.UploadedAt), "status", d.Status, "bytes_retained", false)
}

// FieldDict is field_dict(f).
func FieldDict(f *store.Field) *jsonx.Obj {
	return jsonx.O("id", f.ID, "document_id", f.DocumentID, "entity_hint", f.EntityHint, "property_key", f.PropertyKey, "field", f.Field,
		"value", f.Value, "unit", f.Unit, "page", f.Page, "bbox", f.BBox, "confidence", jsonx.Float(f.Confidence), "extractor", f.Extractor,
		"raw_text", f.RawText)
}

// PyISO renders a timestamp like Python's datetime.isoformat() in the DB session time zone.
func (svc *Service) PyISO(t time.Time) string {
	t = t.In(svc.Store.TZ)
	s := t.Format("2006-01-02T15:04:05")
	if us := t.Nanosecond() / 1000; us != 0 {
		s += fmt.Sprintf(".%06d", us)
	}
	return s + t.Format("-07:00")
}
