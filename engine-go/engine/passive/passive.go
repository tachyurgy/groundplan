// Package passive ports engine/passive.py: passive activity loss rules for rental real estate (IRC 469(i)).
//
// allowance = 25,000 - 0.5 x max(0, MAGI - 100,000), floored at 0, only with active participation; MFS = 0.
// Real-estate professionals are not subject to the limit. Deductible = min(net loss, allowance); the remainder is
// suspended and carried forward. A fully taxable sale releases suspended losses; a 1031 does not.
package passive

import (
	"fmt"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/figure"
	"github.com/tachyurgy/groundplan/engine-go/jsonx"
)

var (
	allowanceMax  = dec.I(2_500_000)
	phaseoutStart = dec.I(10_000_000)
	phaseoutRate  = dec.S("0.5")
)

// Result is PassiveResult.
type Result struct {
	NetRentalCents  int64
	Allowance       *figure.Figure
	Deductible      *figure.Figure
	SuspendedNew    *figure.Figure
	CarryforwardEnd *figure.Figure
	Findings        []*jsonx.Obj
}

// SpecialAllowance is special_allowance(...).
func SpecialAllowance(magiCents int64, filingStatus string, activeParticipation, reProfessional bool, magiInput *figure.Input) *figure.Figure {
	if magiInput == nil {
		magiInput = figure.M("magi_cents", magiCents)
	}
	inputs := figure.L(magiInput, figure.M("filing_status", filingStatus), figure.M("active_participation", activeParticipation),
		figure.M("re_professional", reProfessional))
	if reProfessional {
		return figure.Money("passive.allowance", dec.Zero, inputs, "n/a: real estate professional, losses not passive",
			[]string{"real estate professional: losses are nonpassive, no 25k cap applies"}, nil)
	}
	if !activeParticipation {
		return figure.Money("passive.allowance", dec.Zero, inputs, "0 (no active participation)",
			[]string{"no active participation: the 25,000 special allowance does not apply"}, nil)
	}
	if filingStatus == "mfs" {
		return figure.Money("passive.allowance", dec.Zero, inputs, "0 (MFS)",
			[]string{"married filing separately (living together): special allowance is 0"}, nil)
	}
	reduction := phaseoutRate.Mul(dec.Max(dec.Zero, dec.I(magiCents).Sub(phaseoutStart)))
	allowance := dec.Max(dec.Zero, allowanceMax.Sub(reduction))
	var notes []string
	if reduction.Sign() > 0 {
		notes = append(notes, fmt.Sprintf("MAGI above 100,000: allowance reduced by 50%% of the excess (%d cents)", reduction.Int()))
	}
	return figure.Money("passive.allowance", allowance, inputs, "max(0, 25000 - 0.5*max(0, MAGI - 100000))", notes, nil)
}

// STRDays is one entry of str_avg_stay_days (insertion-ordered).
type STRDays struct {
	Key  string
	Days *float64
}

// Apply is apply_passive_rules(...).
func Apply(netRentalCents, priorCarryforwardCents, magiCents int64, filingStatus string, activeParticipation, reProfessional bool,
	strAvgStayDays []STRDays, magiInput *figure.Input) *Result {
	allowance := SpecialAllowance(magiCents, filingStatus, activeParticipation, reProfessional, magiInput)
	loss := max(0, -netRentalCents)
	netInput := figure.Of("net_rental_cents", netRentalCents, "figure", "cash_flow.schedule_e.line21")
	priorInput := figure.Of("prior_carryforward_cents", priorCarryforwardCents, "document", "Form 8582")
	var findings []*jsonx.Obj
	var deductibleAmt dec.D
	var formula string
	if reProfessional {
		deductibleAmt = dec.I(loss)
		formula = "loss (RE professional: fully deductible against nonpassive income)"
	} else {
		deductibleAmt = dec.Min(dec.I(loss), allowance.Dec())
		formula = "min(net rental loss, allowance)"
	}
	var deductible, suspendedNew, carry *figure.Figure
	if netRentalCents > 0 && priorCarryforwardCents > 0 {
		used := min(priorCarryforwardCents, netRentalCents)
		deductible = figure.MoneyI("passive.deductible_this_year", used, figure.L(netInput, priorInput, figure.Fig(allowance)),
			"min(prior carryforward, net passive income)", []string{"net rental income absorbs suspended losses first"}, nil)
		suspendedNew = figure.Money("passive.suspended_this_year", dec.Zero, figure.L(netInput), "0 (no loss this year)", nil, nil)
		carry = figure.MoneyI("passive.carryforward_end", priorCarryforwardCents-used, figure.L(priorInput, figure.Fig(deductible)),
			"prior carryforward - losses used against passive income", nil, nil)
	} else {
		deductible = figure.Money("passive.deductible_this_year", deductibleAmt, figure.L(netInput, figure.Fig(allowance)), formula, nil, nil)
		suspendedNew = figure.Money("passive.suspended_this_year", dec.I(loss).Sub(deductibleAmt), figure.L(netInput, figure.Fig(deductible)),
			"net rental loss - deductible this year", nil, nil)
		carry = figure.Money("passive.carryforward_end", dec.I(priorCarryforwardCents).Add(suspendedNew.Dec()),
			figure.L(priorInput, figure.Fig(suspendedNew)), "prior carryforward + suspended this year", nil, nil)
	}
	if loss != 0 && allowance.VC() == 0 && activeParticipation && !reProfessional && filingStatus != "mfs" {
		findings = append(findings, jsonx.O("kind", "info", "field", "household.magi_cents", "severity", "info",
			"message", "MAGI at or above 150,000: the 25,000 special allowance is fully phased out"))
	}
	for _, s := range strAvgStayDays {
		if s.Days != nil && *s.Days <= 7 {
			findings = append(findings, jsonx.O("kind", "unsupported_structure", "property_key", s.Key, "field", "property.property_type",
				"severity", "warn",
				"message", fmt.Sprintf("short-term rental (average stay %s days <= 7): short-term rental rules apply; not modeled", dec.PyG(*s.Days))))
		}
	}
	return &Result{netRentalCents, allowance, deductible, suspendedNew, carry, findings}
}

// ReleasedOnSale: a fully taxable sale releases suspended losses in full; a 1031 carries them forward.
func ReleasedOnSale(carryforwardCents int64, disposition string) *figure.Figure {
	inputs := figure.L(figure.Of("carryforward_cents", carryforwardCents, "document", "Form 8582"), figure.M("disposition", disposition))
	if disposition == "taxable_sale" {
		return figure.MoneyI("passive.released_on_sale", carryforwardCents, inputs,
			"carryforward (fully taxable disposition of entire interest releases all suspended losses)", nil, nil)
	}
	return figure.Money("passive.released_on_sale", dec.Zero, inputs, "0 (1031 exchange does not release suspended losses)",
		[]string{"suspended losses carry forward into the replacement property"}, nil)
}
