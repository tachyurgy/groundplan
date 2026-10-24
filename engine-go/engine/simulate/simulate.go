// Package simulate ports engine/simulate.py: buy/sell-over-time simulation with Monte Carlo bands.
//
// The deterministic core is float64 exactly like Python (a distribution, not a ledger) and reproduces Python's
// numbers bit-for-bit: every product that feeds an addition is wrapped in float64() so the Go compiler cannot fuse
// it into an FMA on arm64, and x**n uses a correctly rounded power (what glibc's pow returns). Taxes on sells and
// exchanges come from the decimal exit-tax engine. Monte Carlo draws use Go's math/rand/v2 PCG seeded from the
// request seed: reproducible, but NOT the same stream as numpy's PCG64, so stochastic bands differ from Python's
// (documented); with sigma = 0 every run equals the deterministic path and the bands match exactly.
package simulate

import (
	"fmt"
	"math"
	"math/big"
	"math/rand/v2"
	"sort"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/engine/exittax"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

const residentialLife = 27.5

// Property is SimProperty. HasPurchase/HasBasis model Python's None.
type Property struct {
	ID                           string
	ValueCents                   float64
	DebtCents                    float64
	Rate                         float64
	RemainingYears               int
	GrossRentCents               float64
	ExpensesCents                float64
	AppreciationRate             float64
	RentGrowth                   float64
	ExpenseGrowth                float64
	VacancyRate                  float64
	PurchasePriceCents           *float64
	AccumulatedDepreciationCents float64
	DepreciableBasisCents        *float64
	SellingCostRate              float64
	Active                       bool
}

// NewProperty returns the dataclass defaults.
func NewProperty(id string, value float64) *Property {
	return &Property{ID: id, ValueCents: value, Rate: 0.065, RemainingYears: 30, AppreciationRate: 0.035, RentGrowth: 0.03,
		ExpenseGrowth: 0.03, VacancyRate: 0.05, SellingCostRate: 0.06, Active: true}
}

func (p *Property) clone() *Property {
	c := *p
	if p.PurchasePriceCents != nil {
		v := *p.PurchasePriceCents
		c.PurchasePriceCents = &v
	}
	if p.DepreciableBasisCents != nil {
		v := *p.DepreciableBasisCents
		c.DepreciableBasisCents = &v
	}
	return &c
}

// PowInt is a correctly rounded x**n for integer n (glibc pow is correctly rounded for these arguments).
func PowInt(x float64, n int) float64 {
	if n == 0 {
		return 1
	}
	prec := uint(64*absInt(n) + 128)
	bx := new(big.Float).SetPrec(prec).SetFloat64(x)
	r := new(big.Float).SetPrec(prec).SetFloat64(1)
	for i := 0; i < absInt(n); i++ {
		r.Mul(r, bx)
	}
	if n < 0 {
		one := new(big.Float).SetPrec(prec).SetFloat64(1)
		r = new(big.Float).SetPrec(prec).Quo(one, r)
	}
	f, _ := r.Float64()
	return f
}

func absInt(n int) int {
	if n < 0 {
		return -n
	}
	return n
}

// AnnualPayment is SimProperty.annual_payment().
func (p *Property) AnnualPayment() float64 {
	if p.DebtCents <= 0 || p.RemainingYears <= 0 {
		return 0.0
	}
	r := p.Rate
	n := p.RemainingYears
	if r == 0 {
		return p.DebtCents / float64(n)
	}
	return float64(p.DebtCents*r) / (1 - PowInt(1+r, -n))
}

// Request is SimRequest.
type Request struct {
	StartYear         int
	Years             int
	Properties        []*Property
	Events            []*jsonx.Obj
	ReinvestRate      float64
	StartingCashCents float64
	Household         exittax.HouseholdTax
	Runs              int
	ApprSigma         float64
	RentSigma         float64
	Seed              int64
}

func pyInt(f float64) int64 { return int64(f) } // int(float): truncation toward zero

func sell(p *Property, year int, hh exittax.HouseholdTax, capv *int64) (int64, int64) {
	purchase := p.ValueCents
	if p.PurchasePriceCents != nil && *p.PurchasePriceCents != 0 {
		purchase = *p.PurchasePriceCents
	}
	sd := dates.New(year, 12, 31)
	s := &exittax.SaleInput{SalePriceCents: dec.PyRound(p.ValueCents), SellingCostRate: dec.S(dec.PyFloatRepr(p.SellingCostRate)),
		LoanPayoffCents: dec.PyRound(p.DebtCents), PurchasePriceCents: pyInt(purchase),
		AccumulatedDepreciationCents: pyInt(p.AccumulatedDepreciationCents), SaleDate: &sd, RecognizedGainCapCents: capv,
		Disposition: "taxable_sale"}
	h := hh
	h.TaxYear = year
	ex := exittax.Compute(s, &h, nil)
	return ex.NetProceedsCents(), ex.TotalCents()
}

// Row is one simulated year.
type Row struct {
	Year                                                               int
	NetWorth, CashFlow, TaxesPaid, Equity, Debt, Value, Cash, CumTaxes float64
}

// ordered property map (Python dict semantics).
type propMap struct {
	order []string
	m     map[string]*Property
}

func (pm *propMap) set(p *Property) {
	if _, ok := pm.m[p.ID]; !ok {
		pm.order = append(pm.order, p.ID)
	}
	pm.m[p.ID] = p
}

func (pm *propMap) values() []*Property {
	out := make([]*Property, 0, len(pm.order))
	for _, k := range pm.order {
		out = append(out, pm.m[k])
	}
	return out
}

// event helpers (dict.get with defaults, Python int()/float() conversions)
func evNum(e *jsonx.Obj, k string, def float64) float64 {
	v, ok := e.Get(k)
	if !ok {
		return def
	}
	return toFloat(v, def)
}

func toFloat(v any, def float64) float64 {
	switch x := v.(type) {
	case int64:
		return float64(x)
	case int:
		return float64(x)
	case jsonx.Float:
		return float64(x)
	case float64:
		return x
	case bool:
		if x {
			return 1
		}
		return 0
	case string:
		d, err := dec.Parse(x)
		if err != nil {
			panic(fmt.Errorf("could not convert string to float: %q", x))
		}
		return d.Float64()
	case nil:
		panic(fmt.Errorf("float() argument must be a string or a real number, not 'NoneType'"))
	}
	return def
}

func evInt(e *jsonx.Obj, k string, def int64) int64 {
	v, ok := e.Get(k)
	if !ok {
		return def
	}
	switch x := v.(type) {
	case int64:
		return x
	case jsonx.Float:
		return int64(x)
	case string:
		d, err := dec.Parse(x)
		if err != nil {
			panic(fmt.Errorf("invalid literal for int(): %q", x))
		}
		return d.Int()
	}
	return int64(toFloat(v, float64(def)))
}

func evStr(e *jsonx.Obj, k string) (string, bool) {
	v, ok := e.Get(k)
	if !ok || v == nil {
		return "", false
	}
	if s, ok := v.(string); ok {
		return s, true
	}
	return fmt.Sprint(v), true
}

func runOnce(req *Request, apprShocks, rentShocks [][]float64) []Row {
	props := &propMap{m: map[string]*Property{}}
	for _, p := range req.Properties {
		props.set(p.clone())
	}
	for _, p := range props.values() {
		if p.PurchasePriceCents == nil {
			v := p.ValueCents
			p.PurchasePriceCents = &v
		}
		if p.DepreciableBasisCents == nil {
			v := float64(pyInt(*p.PurchasePriceCents * 0.7))
			p.DepreciableBasisCents = &v
		}
	}
	cash := req.StartingCashCents
	eventsByYear := map[int][]*jsonx.Obj{}
	for _, e := range req.Events {
		y := int(evInt(e, "year", 0))
		eventsByYear[y] = append(eventsByYear[y], e)
	}
	var rows []Row
	cumTax := 0.0
	for t := 0; t < req.Years; t++ {
		yr := req.StartYear + t
		cfTotal := 0.0
		taxTotal := 0.0
		sorted := props.values()
		sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].ID < sorted[j].ID })
		for i, p := range sorted {
			if !p.Active {
				continue
			}
			aShock, rShock := 0.0, 0.0
			if apprShocks != nil {
				aShock = apprShocks[t][i%len(apprShocks[t])]
			}
			if rentShocks != nil {
				rShock = rentShocks[t][i%len(rentShocks[t])]
			}
			pay := p.AnnualPayment()
			interest := p.DebtCents * p.Rate
			principal := 0.0
			if d := pay - interest; d > 0.0 {
				principal = d
			}
			if p.DebtCents < principal {
				principal = p.DebtCents
			}
			cf := float64(p.GrossRentCents*(1-p.VacancyRate)) - p.ExpensesCents - pay
			cfTotal += cf
			p.DebtCents -= principal
			p.RemainingYears = max(0, p.RemainingYears-1)
			p.ValueCents *= 1 + p.AppreciationRate + aShock
			p.GrossRentCents *= 1 + p.RentGrowth + rShock
			p.ExpensesCents *= 1 + p.ExpenseGrowth
			next := p.AccumulatedDepreciationCents + *p.DepreciableBasisCents/residentialLife
			if next < *p.DepreciableBasisCents {
				p.AccumulatedDepreciationCents = next
			} else {
				p.AccumulatedDepreciationCents = *p.DepreciableBasisCents
			}
		}
		cash = float64(cash*(1+req.ReinvestRate)) + cfTotal
		for _, e := range eventsByYear[yr] {
			kind, _ := evStr(e, "type")
			pid, hasPid := evStr(e, "property_id")
			switch {
			case kind == "buy":
				id := pid
				if !hasPid || pid == "" {
					id = fmt.Sprintf("buy-%d", yr)
				}
				np := NewProperty(id, float64(evInt(e, "value_cents", 0)))
				np.DebtCents = float64(evInt(e, "debt_cents", 0))
				np.Rate = evNum(e, "rate", 0.065)
				np.RemainingYears = int(evInt(e, "term_years", 30))
				np.GrossRentCents = float64(evInt(e, "gross_rent_cents", 0))
				np.ExpensesCents = float64(evInt(e, "expenses_cents", 0))
				np.AppreciationRate = evNum(e, "appreciation_rate", 0.035)
				pp := np.ValueCents
				np.PurchasePriceCents = &pp
				db := float64(pyInt(np.ValueCents * 0.7))
				np.DepreciableBasisCents = &db
				down := (np.ValueCents - np.DebtCents) + float64(np.ValueCents*evNum(e, "closing_cost_rate", 0.02))
				cash -= down
				props.set(np)
			case (kind == "sell" || kind == "exchange") && hasPid && props.m[pid] != nil && props.m[pid].Active:
				p := props.m[pid]
				if kind == "sell" {
					net, tax := sell(p, yr, req.Household, nil)
					cash += float64(net)
					taxTotal += float64(tax)
					p.Active = false
				} else {
					boot := evInt(e, "cash_taken_cents", 0)
					var tax int64
					if boot != 0 {
						b := boot
						_, tax = sell(p, yr, req.Household, &b)
					}
					taxTotal += float64(tax)
					cash += float64(boot - tax)
					realized := p.ValueCents * (1 - p.SellingCostRate)
					replValue := evNum(e, "replacement_value_cents", realized)
					repl := p.clone()
					if rid, ok := evStr(e, "replacement_id"); ok {
						repl.ID = rid
					} else {
						repl.ID = fmt.Sprintf("%s-x%d", pid, yr)
					}
					repl.ValueCents = replValue
					repl.DebtCents = evNum(e, "replacement_debt_cents", p.DebtCents)
					extra := replValue - realized
					bump := 0.0 // Python max(0.0, extra)
					if extra > 0.0 {
						bump = extra
					}
					pp := float64(pyInt(*p.PurchasePriceCents + bump))
					repl.PurchasePriceCents = &pp
					den := p.ValueCents
					if !(den > 1.0) {
						den = 1.0
					}
					scale := replValue / den
					repl.GrossRentCents *= scale
					repl.ExpensesCents *= scale
					p.Active = false
					props.set(repl)
				}
			case kind == "refi" && hasPid && props.m[pid] != nil && props.m[pid].Active:
				p := props.m[pid]
				newDebt := p.ValueCents * evNum(e, "ltv", 0.70)
				cash += (newDebt - p.DebtCents) - float64(newDebt*evNum(e, "cost_rate", 0.01))
				p.DebtCents = newDebt
				p.Rate = evNum(e, "rate", p.Rate)
				p.RemainingYears = int(evInt(e, "term_years", 30))
			}
		}
		cumTax += taxTotal
		equity, debt, value := 0.0, 0.0, 0.0
		for _, p := range props.values() {
			if p.Active {
				equity += p.ValueCents - p.DebtCents
			}
		}
		for _, p := range props.values() {
			if p.Active {
				debt += p.DebtCents
			}
		}
		for _, p := range props.values() {
			if p.Active {
				value += p.ValueCents
			}
		}
		rows = append(rows, Row{yr, equity + cash, cfTotal, taxTotal, equity, debt, value, cash, cumTax})
	}
	return rows
}

// Band is p10/p50/p90.
type Band struct{ P10, P50, P90 int64 }

// ToDict renders a band.
func (b Band) ToDict() *jsonx.Obj { return jsonx.O("p10", b.P10, "p50", b.P50, "p90", b.P90) }

// IntRow is a deterministic row rounded to integer cents (Python int(round(v))).
type IntRow struct {
	Year                                                               int
	NetWorth, CashFlow, TaxesPaid, Equity, Debt, Value, Cash, CumTaxes int64
}

// Result is the simulate() output.
type Result struct {
	StartYear     int
	Years         int
	Deterministic []IntRow
	Bands         []map[string]Band // nil when runs == 0
	Runs          int
	Seed          int64
}

var metrics = []string{"net_worth", "cash_flow", "taxes_paid", "equity", "debt", "cum_taxes"}

func metric(r Row, m string) float64 {
	switch m {
	case "net_worth":
		return r.NetWorth
	case "cash_flow":
		return r.CashFlow
	case "taxes_paid":
		return r.TaxesPaid
	case "equity":
		return r.Equity
	case "debt":
		return r.Debt
	}
	return r.CumTaxes
}

// Simulate is simulate(req).
func Simulate(req *Request) *Result {
	base := runOnce(req, nil, nil)
	out := &Result{StartYear: req.StartYear, Years: req.Years, Seed: req.Seed}
	for _, r := range base {
		out.Deterministic = append(out.Deterministic, IntRow{r.Year, dec.PyRound(r.NetWorth), dec.PyRound(r.CashFlow), dec.PyRound(r.TaxesPaid),
			dec.PyRound(r.Equity), dec.PyRound(r.Debt), dec.PyRound(r.Value), dec.PyRound(r.Cash), dec.PyRound(r.CumTaxes)})
	}
	if req.Runs > 0 {
		rng := rand.New(rand.NewPCG(uint64(req.Seed), 0x9e3779b97f4a7c15))
		nProps := len(req.Properties)
		for _, e := range req.Events {
			if k, _ := evStr(e, "type"); k == "buy" || k == "exchange" {
				nProps++
			}
		}
		nProps = max(1, nProps)
		acc := map[string][][]float64{}
		for _, m := range metrics {
			acc[m] = make([][]float64, req.Years)
			for t := range acc[m] {
				acc[m][t] = make([]float64, req.Runs)
			}
		}
		draw := func(sigma float64) [][]float64 {
			if sigma == 0 {
				return nil
			}
			out := make([][]float64, req.Years)
			for t := range out {
				out[t] = make([]float64, nProps)
				for j := range out[t] {
					out[t][j] = rng.NormFloat64() * sigma
				}
			}
			return out
		}
		for k := 0; k < req.Runs; k++ {
			a := draw(req.ApprSigma)
			r := draw(req.RentSigma)
			res := runOnce(req, a, r)
			for t, row := range res {
				for _, m := range metrics {
					acc[m][t][k] = metric(row, m)
				}
			}
		}
		for t := 0; t < req.Years; t++ {
			b := map[string]Band{}
			for _, m := range metrics {
				xs := append([]float64(nil), acc[m][t]...)
				sort.Float64s(xs)
				b[m] = Band{dec.PyRound(percentile(xs, 10)), dec.PyRound(percentile(xs, 50)), dec.PyRound(percentile(xs, 90))}
			}
			out.Bands = append(out.Bands, b)
		}
		out.Runs = req.Runs
	}
	return out
}

// percentile is numpy.percentile(..., method="linear") on a sorted slice, including numpy's lerp form.
func percentile(sorted []float64, q float64) float64 {
	n := len(sorted)
	if n == 1 {
		return sorted[0]
	}
	idx := q / 100 * float64(n-1)
	lo := int(math.Floor(idx))
	hi := min(lo+1, n-1)
	t := idx - float64(lo)
	a, b := sorted[lo], sorted[hi]
	d := b - a
	if t >= 0.5 {
		return b - float64(d*(1-t))
	}
	return a + float64(d*t)
}
