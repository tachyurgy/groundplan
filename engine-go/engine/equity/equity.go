// Package equity ports engine/equity.py: equity, lendable equity, ROE, CAGR, projected value, concentration.
package equity

import (
	"fmt"

	"github.com/tachyurgy/groundplan/engine-go/dec"
	"github.com/tachyurgy/groundplan/engine-go/engine/cashflow"
	"github.com/tachyurgy/groundplan/engine-go/engine/dates"
	"github.com/tachyurgy/groundplan/engine-go/engine/figure"
)

// LTVLendable is the lendable-equity LTV.
var LTVLendable = dec.S("0.70")

func balanceInputs(balances []int64) []*figure.Input {
	var out []*figure.Input
	for i, b := range balances {
		out = append(out, figure.Of(fmt.Sprintf("loan[%d].balance_cents", i), b, "figure", "loans.schedule"))
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

// Equity is equity(value, balances).
func Equity(valueCents int64, balances []int64, valueInput *figure.Input, blocked figure.KeySet) *figure.Figure {
	if valueInput == nil {
		valueInput = figure.M("current_value_cents", valueCents)
	}
	inputs := figure.Ins(figure.L(valueInput), balanceInputs(balances))
	return figure.Money("equity.net", dec.I(valueCents).Sub(dec.I(sum(balances))), inputs, "current_value - sum(loan balances)", nil, blocked)
}

// Lendable is lendable_equity(value, balances, value_input).
func Lendable(valueCents int64, balances []int64, valueInput *figure.Input) *figure.Figure {
	if valueInput == nil {
		valueInput = figure.M("current_value_cents", valueCents)
	}
	ltv := LTVLendable
	inputs := figure.Ins(figure.L(valueInput, figure.Of("max_ltv", ltv, "default")), balanceInputs(balances))
	v := dec.Max(dec.Zero, dec.I(valueCents).Mul(ltv).Sub(dec.I(sum(balances))))
	return figure.Money("equity.lendable", v, inputs, "max(0, value*0.70 - sum(balances))", nil, nil)
}

// AppreciationThisYear is appreciation_this_year(value_begin, rate, src).
func AppreciationThisYear(valueBeginCents int64, rate *dec.D, rateSrc string) *figure.Figure {
	r := cashflow.OrZero(rate)
	return figure.Money("equity.appreciation_this_year", dec.I(valueBeginCents).Mul(r),
		figure.L(figure.Of("value_begin_cents", valueBeginCents, "figure", "equity.value"), figure.Of("appreciation_rate", r, rateSrc)),
		"value_begin * appreciation_rate", nil, nil)
}

// ProjectedValue is projected_value(value, rate, years, value_input, src).
func ProjectedValue(valueCents int64, rate *dec.D, years int, valueInput *figure.Input, rateSrc string) *figure.Figure {
	r := cashflow.OrZero(rate)
	if valueInput == nil {
		valueInput = figure.M("current_value_cents", valueCents)
	}
	return figure.Money(fmt.Sprintf("equity.projected_value[%d]", years), dec.I(valueCents).Mul(dec.One.Add(r).PowInt(years)),
		figure.L(valueInput, figure.Of("appreciation_rate", r, rateSrc), figure.M("years", int64(years))),
		"value * (1 + appreciation_rate)^n", nil, nil)
}

// CAGR is cagr(purchase_price, value, purchase_date, as_of).
func CAGR(purchasePriceCents, valueCents int64, purchaseDate, asOf dates.Date) *figure.Figure {
	years := dec.I(int64(dates.Days(asOf, purchaseDate))).Quo(dec.S("365.25"))
	var val *dec.D
	var notes []string
	if years.Sign() <= 0 || purchasePriceCents <= 0 {
		notes = append(notes, "cannot compute CAGR without a positive holding period and purchase price")
	} else {
		ratio := dec.I(valueCents).Quo(dec.I(purchasePriceCents))
		v := ratio.Pow(dec.One.Quo(years)).Sub(dec.One)
		val = &v
	}
	return figure.Ratio("equity.cagr", val, figure.L(figure.M("purchase_price_cents", purchasePriceCents),
		figure.M("current_value_cents", valueCents), figure.M("purchase_date", purchaseDate), figure.M("as_of", asOf)),
		"(value / purchase_price)^(1/years) - 1", "rate", notes, 6)
}

// Concentration is property value / household net worth.
func Concentration(valueCents int64, netWorthCents *int64) *figure.Figure {
	var val *dec.D
	var notes []string
	if netWorthCents != nil && *netWorthCents != 0 {
		v := dec.I(valueCents).Quo(dec.I(*netWorthCents))
		val = &v
	} else {
		notes = []string{"household net worth not provided"}
	}
	var nw any
	if netWorthCents != nil {
		nw = *netWorthCents
	}
	return figure.Ratio("equity.concentration", val, figure.L(figure.M("current_value_cents", valueCents),
		figure.M("household_net_worth_cents", nw)), "property value / household net worth", "ratio", notes, 6)
}
