"""Equity, lendable equity, ROE, CAGR, projected value, concentration."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from groundplan.engine.figure import D, Figure, Input, money, ratio

LTV_LENDABLE = Decimal("0.70")


def equity(value_cents: int, balances_cents: list[int], value_input: Input | None = None,
           blocked: set[str] | None = None) -> Figure:
    inputs = [value_input or Input.of("current_value_cents", value_cents)]
    inputs += [Input.of(f"loan[{i}].balance_cents", b, src="figure", ref="loans.schedule") for i, b in enumerate(balances_cents)]
    return money("equity.net", Decimal(value_cents) - Decimal(sum(balances_cents)), inputs,
                 "current_value - sum(loan balances)", blocked_keys=blocked)


def lendable_equity(value_cents: int, balances_cents: list[int], value_input: Input | None = None, ltv=LTV_LENDABLE) -> Figure:
    inputs = [value_input or Input.of("current_value_cents", value_cents), Input.of("max_ltv", D(ltv), src="default")]
    inputs += [Input.of(f"loan[{i}].balance_cents", b, src="figure", ref="loans.schedule") for i, b in enumerate(balances_cents)]
    v = max(Decimal(0), Decimal(value_cents) * D(ltv) - Decimal(sum(balances_cents)))
    return money("equity.lendable", v, inputs, "max(0, value*0.70 - sum(balances))")


def roe(net_cash_flow_cents: int, principal_paydown_cents: int, appreciation_cents: int, equity_begin_cents: int,
        inputs: list[Input] | None = None) -> Figure:
    val = None if equity_begin_cents <= 0 else (
        Decimal(net_cash_flow_cents + principal_paydown_cents + appreciation_cents) / Decimal(equity_begin_cents))
    return ratio("equity.roe", val, inputs or [
        Input.of("net_cash_flow_cents", net_cash_flow_cents, src="figure", ref="cash_flow.net_annual"),
        Input.of("principal_paydown_cents", principal_paydown_cents, src="figure", ref="loans.schedule"),
        Input.of("appreciation_cents", appreciation_cents, src="figure", ref="equity.appreciation_this_year"),
        Input.of("equity_begin_cents", equity_begin_cents, src="figure", ref="equity.net")],
        "(net_cash_flow + principal_paydown + appreciation_this_year) / equity_begin_of_year",
        notes=[] if equity_begin_cents > 0 else ["equity at start of year is not positive: ROE undefined"])


def appreciation_this_year(value_begin_cents: int, appreciation_rate, rate_src: str = "default") -> Figure:
    r = D(appreciation_rate or 0)
    return money("equity.appreciation_this_year", Decimal(value_begin_cents) * r,
                 [Input.of("value_begin_cents", value_begin_cents, src="figure", ref="equity.value"),
                  Input.of("appreciation_rate", r, src=rate_src)], "value_begin * appreciation_rate")


def projected_value(value_cents: int, appreciation_rate, years: int, value_input: Input | None = None,
                    rate_src: str = "default") -> Figure:
    r = D(appreciation_rate or 0)
    return money(f"equity.projected_value[{years}]", Decimal(value_cents) * (Decimal(1) + r) ** years,
                 [value_input or Input.of("current_value_cents", value_cents), Input.of("appreciation_rate", r, src=rate_src),
                  Input.of("years", years)], "value * (1 + appreciation_rate)^n")


def cagr(purchase_price_cents: int, value_cents: int, purchase_date: date, as_of: date) -> Figure:
    years = Decimal((as_of - purchase_date).days) / Decimal("365.25")
    val = None
    notes: list[str] = []
    if years <= 0 or purchase_price_cents <= 0:
        notes.append("cannot compute CAGR without a positive holding period and purchase price")
    else:
        ratio_v = Decimal(value_cents) / Decimal(purchase_price_cents)
        # Decimal ** Decimal works for positive base
        val = ratio_v ** (Decimal(1) / years) - Decimal(1)
    return ratio("equity.cagr", val, [Input.of("purchase_price_cents", purchase_price_cents),
                                      Input.of("current_value_cents", value_cents), Input.of("purchase_date", purchase_date),
                                      Input.of("as_of", as_of)], "(value / purchase_price)^(1/years) - 1", notes=notes)


def concentration(value_cents: int, household_net_worth_cents: int | None) -> Figure:
    val = None if not household_net_worth_cents else Decimal(value_cents) / Decimal(household_net_worth_cents)
    return ratio("equity.concentration", val, [Input.of("current_value_cents", value_cents),
                                               Input.of("household_net_worth_cents", household_net_worth_cents)],
                 "property value / household net worth", unit="ratio",
                 notes=[] if household_net_worth_cents else ["household net worth not provided"])
