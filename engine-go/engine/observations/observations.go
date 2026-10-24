// Package observations ports engine/observations.py: deterministic observation rules. The whole rule list lives
// in Rules so it is reviewable in one place; every number in a message comes from the context.
package observations

import (
	"fmt"
	"sort"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/engine/models"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

// USD is usd(c): "-$1,234" style whole dollars (float division and %.0f exactly like Python).
func USD(c *int64) string {
	if c == nil {
		return "n/a"
	}
	v := *c
	sign := ""
	if v < 0 {
		sign = "-"
		v = -v
	}
	return sign + "$" + dec.Commas(dec.PyFixed(float64(v)/100, 0))
}

// USDi is USD for a plain integer.
func USDi(c int64) string { return USD(&c) }

// Pct is pct(x): "n/a" or Decimal(str(x)) * 100 formatted .1f + "%".
func Pct(x *string) string {
	if x == nil {
		return "n/a"
	}
	return dec.S(*x).Mul(dec.I(100)).Fixed(1) + "%"
}

// Ctx is the flat context dict the rules read (nil pointers = Python None / missing keys).
type Ctx struct {
	Name              string
	NetCashFlowCents  *int64
	DSCR              *string
	ROE               *string
	ReinvestRate      string
	EquityCents       int64
	ExitTaxCents      int64
	IOEndMonths       *int
	ARMResetMonths    *int
	MaturityMonths    *int
	LandPctBounded    bool
	DepOutlier        bool
	ValueSource       string
	ValueCents        int64
	Concentration     *string
	AvgStayDays       *float64
	CarryforwardCents int64
	MagiCents         int64
	NetRentalCents    int64
	AllowanceCents    *int64
}

// Rule is one observation rule.
type Rule struct {
	ID       string
	Scope    string
	Severity string
	When     func(c *Ctx) bool
	Message  func(c *Ctx) string
	Cites    []string
}

func within(m *int, limit int) bool { return m != nil && 0 <= *m && *m <= limit }

// Rules is the reviewable rule table (same order as Python's RULES).
var Rules = []Rule{
	{"cash_flow_negative", "property", "alert", func(c *Ctx) bool { return c.NetCashFlowCents != nil && *c.NetCashFlowCents < 0 },
		func(c *Ctx) string {
			return fmt.Sprintf("%s runs negative cash flow of %s a year after debt service.", c.Name, USD(c.NetCashFlowCents))
		}, []string{"cash_flow.net_annual"}},
	{"dscr_low", "property", "warn", func(c *Ctx) bool { return c.DSCR != nil && dec.S(*c.DSCR).Lt(dec.S("1.2")) },
		func(c *Ctx) string {
			return fmt.Sprintf("%s covers its debt service %sx, below the 1.20x lenders look for.", c.Name, dec.S(*c.DSCR).Fixed(2))
		}, []string{"loans.dscr"}},
	{"roe_below_reinvest", "property", "warn", func(c *Ctx) bool { return c.ROE != nil && dec.S(*c.ROE).Lt(dec.S(c.ReinvestRate)) },
		func(c *Ctx) string {
			rr := c.ReinvestRate
			return fmt.Sprintf("%s returns %s on its equity, below the %s reinvestment assumption.", c.Name, Pct(c.ROE), Pct(&rr))
		}, []string{"equity.roe"}},
	{"recapture_heavy", "property", "warn", func(c *Ctx) bool {
		return c.EquityCents > 0 && dec.I(c.ExitTaxCents).Gt(dec.S("0.15").Mul(dec.I(c.EquityCents)))
	}, func(c *Ctx) string {
		return fmt.Sprintf("Selling %s today would cost %s in tax, more than 15%% of its %s equity.", c.Name, USDi(c.ExitTaxCents), USDi(c.EquityCents))
	}, []string{"exit_tax.total", "equity.net"}},
	{"io_ending", "property", "alert", func(c *Ctx) bool { return within(c.IOEndMonths, 24) },
		func(c *Ctx) string {
			return fmt.Sprintf("The interest-only period on %s ends in %d months; payments step up to amortizing.", c.Name, *c.IOEndMonths)
		}, []string{"loans.schedule"}},
	{"arm_reset", "property", "alert", func(c *Ctx) bool { return within(c.ARMResetMonths, 24) },
		func(c *Ctx) string {
			return fmt.Sprintf("The ARM on %s resets in %d months.", c.Name, *c.ARMResetMonths)
		}, []string{"loans.schedule"}},
	{"loan_maturity", "property", "warn", func(c *Ctx) bool { return within(c.MaturityMonths, 36) },
		func(c *Ctx) string {
			return fmt.Sprintf("A loan on %s matures in %d months.", c.Name, *c.MaturityMonths)
		}, []string{"loans.schedule"}},
	{"land_pct_bounded", "property", "info", func(c *Ctx) bool { return c.LandPctBounded },
		func(c *Ctx) string {
			return fmt.Sprintf("The land share for %s was outside 20-60%% and was bounded; confirm with the assessor split.", c.Name)
		}, []string{"depreciation.depreciable_basis"}},
	{"depreciation_gap", "property", "warn", func(c *Ctx) bool { return c.DepOutlier },
		func(c *Ctx) string {
			return fmt.Sprintf("Depreciation claimed on the return for %s differs from the allowable amount by more than 5%%; recapture still uses allowable.", c.Name)
		}, []string{"depreciation.accumulated"}},
	{"value_estimated", "property", "info", func(c *Ctx) bool { return c.ValueSource == "estimated" },
		func(c *Ctx) string {
			return fmt.Sprintf("The value of %s (%s) is an estimate, not an appraisal.", c.Name, USDi(c.ValueCents))
		}, []string{"equity.value"}},
	{"concentration_high", "property", "warn", func(c *Ctx) bool { return c.Concentration != nil && dec.S(*c.Concentration).Gt(dec.S("0.40")) },
		func(c *Ctx) string {
			return fmt.Sprintf("%s is %s of household net worth.", c.Name, Pct(c.Concentration))
		}, []string{"equity.concentration"}},
	{"str_flagged", "property", "warn", func(c *Ctx) bool { return c.AvgStayDays != nil && *c.AvgStayDays <= 7 },
		func(c *Ctx) string {
			return fmt.Sprintf("%s is a short-term rental (average stay %s nights): short-term rental rules apply and are not modeled.",
				c.Name, dec.PyG(*c.AvgStayDays))
		}, []string{"passive.allowance"}},
	{"suspended_losses", "household", "info", func(c *Ctx) bool { return c.CarryforwardCents > 0 },
		func(c *Ctx) string {
			return fmt.Sprintf("The household carries %s of suspended passive losses; a fully taxable sale would release them, a 1031 would not.",
				USDi(c.CarryforwardCents))
		}, []string{"passive.carryforward_end"}},
	{"magi_phaseout", "household", "info", func(c *Ctx) bool { return c.MagiCents > 10_000_000 && c.NetRentalCents < 0 },
		func(c *Ctx) string {
			return fmt.Sprintf("MAGI of %s reduces the $25,000 rental loss allowance to %s.", USDi(c.MagiCents), USD(c.AllowanceCents))
		}, []string{"passive.allowance"}},
}

func monthsUntil(d, today dates.Date) int {
	return (d.Year()-today.Year())*12 + (int(d.Month()) - int(today.Month()))
}

func minp(cur *int, v int) *int {
	if cur == nil || v < *cur {
		return &v
	}
	return cur
}

// AnalysisFacts is what property_context reads from the analysis' private keys.
type AnalysisFacts struct {
	NetCents      *int64
	DSCR          *string
	ROE           *string
	EquityCents   *int64
	ExitTaxCents  int64
	LandBounded   bool
	DepOutlier    bool
	Concentration *string
}

// PropertyContext is property_context(name, an, p, reinvest_rate, today).
func PropertyContext(name string, an AnalysisFacts, p *models.Property, reinvestRate dec.D, today dates.Date) *Ctx {
	var ioEnd, arm, mat *int
	for _, ln := range p.Loans {
		if ln.IsPaidOff {
			continue
		}
		if ln.IOMonths != 0 && ln.LoanType != "heloc" {
			y, m := ln.BalanceAsOf.Year(), int(ln.BalanceAsOf.Month())+ln.IOMonths
			end := dates.New(y+floorDiv(m-1, 12), floorMod(m-1, 12)+1, 1)
			ioEnd = minp(ioEnd, monthsUntil(end, today))
		}
		if ln.ArmResetDate != nil {
			arm = minp(arm, monthsUntil(*ln.ArmResetDate, today))
		}
		if ln.MaturityDate != nil {
			mat = minp(mat, monthsUntil(*ln.MaturityDate, today))
		}
	}
	var eq int64
	if an.EquityCents != nil {
		eq = *an.EquityCents
	}
	return &Ctx{Name: name, NetCashFlowCents: an.NetCents, DSCR: an.DSCR, ROE: an.ROE, ReinvestRate: reinvestRate.String(),
		EquityCents: eq, ExitTaxCents: an.ExitTaxCents, IOEndMonths: ioEnd, ARMResetMonths: arm, MaturityMonths: mat,
		LandPctBounded: an.LandBounded, DepOutlier: an.DepOutlier, ValueSource: p.ValueSource, ValueCents: p.CurrentValueCents,
		Concentration: an.Concentration, AvgStayDays: p.AvgStayDays}
}

func floorDiv(a, b int) int {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}

func floorMod(a, b int) int { return a - floorDiv(a, b)*b }

var sevOrder = map[string]int{"alert": 0, "warn": 1, "info": 2}

// Evaluate runs every rule of a scope; panics inside a predicate count as "no hit" like Python's except clause.
func Evaluate(c *Ctx, scope string, propertyID *string) []*jsonx.Obj {
	var out []*jsonx.Obj
	for _, r := range Rules {
		if r.Scope != scope {
			continue
		}
		if safeWhen(r, c) {
			var pid any
			if propertyID != nil {
				pid = *propertyID
			}
			cites := make([]any, len(r.Cites))
			for i, x := range r.Cites {
				cites[i] = x
			}
			out = append(out, jsonx.O("rule", r.ID, "severity", r.Severity, "message", r.Message(c), "cites", cites, "property_id", pid))
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		return sevOrder[out[i].MustGet("severity").(string)] < sevOrder[out[j].MustGet("severity").(string)]
	})
	return out
}

func safeWhen(r Rule, c *Ctx) (hit bool) {
	defer func() {
		if recover() != nil {
			hit = false
		}
	}()
	return r.When(c)
}

// RuleTable is rule_table().
func RuleTable() []any {
	out := make([]any, len(Rules))
	for i, r := range Rules {
		cites := make([]any, len(r.Cites))
		for k, x := range r.Cites {
			cites[k] = x
		}
		out[i] = jsonx.O("id", r.ID, "scope", r.Scope, "severity", r.Severity, "cites", cites)
	}
	return out
}
