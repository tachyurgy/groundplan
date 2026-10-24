"""Cash flow per property per year, plus the Schedule E -> cash-flow bridge.

NOI = gross_rent x (1 - vacancy) + other_income - (taxes + insurance + repairs + mgmt + utilities + hoa + other)
      - capex_reserve                       (capex_reserve = gross_rent x capex_reserve_rate)
net_cash_flow = NOI - debt_service (principal + interest)
Schedule E bridge: cash_flow_from_return = line21 + line18_depreciation - principal_paid - capital_improvements_paid
(interest is already inside line 21, so it is never subtracted twice).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from groundplan.engine.figure import D, Figure, Input, money

EXPENSE_LINES = ("taxes", "insurance", "repairs", "mgmt", "utilities", "hoa", "other")


@dataclass
class YearOperations:
    tax_year: int
    gross_rent_cents: int
    other_income_cents: int = 0
    taxes_cents: int = 0
    insurance_cents: int = 0
    repairs_cents: int = 0
    mgmt_cents: int = 0
    utilities_cents: int = 0
    hoa_cents: int = 0
    other_cents: int = 0
    mortgage_interest_cents: int = 0
    depreciation_cents: int = 0
    sources: dict[str, Input] = field(default_factory=dict)  # per-field provenance overrides

    def inp(self, key: str, value, src: str = "manual") -> Input:
        return self.sources.get(key) or Input.of(key, value, src=src)

    def expenses_total(self) -> int:
        return sum(getattr(self, f"{k}_cents") for k in EXPENSE_LINES)


def noi(ops: YearOperations, vacancy_rate, capex_reserve_rate, blocked: set[str] | None = None) -> Figure:
    vac = D(vacancy_rate or 0)
    capex_rate = D(capex_reserve_rate or 0)
    rent = Decimal(ops.gross_rent_cents)
    effective_rent = rent * (Decimal(1) - vac)
    capex = rent * capex_rate
    total = effective_rent + Decimal(ops.other_income_cents) - Decimal(ops.expenses_total()) - capex
    inputs = [ops.inp("gross_rent_cents", ops.gross_rent_cents), ops.inp("other_income_cents", ops.other_income_cents)]
    inputs += [ops.inp(f"{k}_cents", getattr(ops, f"{k}_cents")) for k in EXPENSE_LINES]
    inputs += [
        Input.of("vacancy_rate", vac, src="default" if vacancy_rate is None else "manual"),
        Input.of("capex_reserve_rate", capex_rate, src="default" if capex_reserve_rate is None else "manual"),
    ]
    return money(
        "cash_flow.noi", total, inputs,
        "gross_rent*(1-vacancy) + other_income - (taxes+insurance+repairs+mgmt+utilities+hoa+other) - gross_rent*capex_reserve_rate",
        blocked_keys=blocked,
    )


def net_cash_flow(noi_fig: Figure, principal_cents: int, interest_cents: int, loan_inputs: list[Input] | None = None) -> Figure:
    inputs = [Input.figure(noi_fig), Input.of("principal_paid_cents", principal_cents, src="figure", ref="loans.schedule"),
              Input.of("interest_paid_cents", interest_cents, src="figure", ref="loans.schedule")]
    if loan_inputs:
        inputs += loan_inputs
    return money("cash_flow.net_annual", noi_fig.dec - Decimal(principal_cents) - Decimal(interest_cents), inputs,
                 "NOI - (principal + interest)")


def schedule_e_line21(ops: YearOperations) -> Figure:
    """Schedule E line 21 = rents + other income - expenses - mortgage interest - depreciation (line 20 total)."""
    total = (Decimal(ops.gross_rent_cents) + Decimal(ops.other_income_cents) - Decimal(ops.expenses_total())
             - Decimal(ops.mortgage_interest_cents) - Decimal(ops.depreciation_cents))
    inputs = [ops.inp("gross_rent_cents", ops.gross_rent_cents), ops.inp("other_income_cents", ops.other_income_cents)]
    inputs += [ops.inp(f"{k}_cents", getattr(ops, f"{k}_cents")) for k in EXPENSE_LINES]
    inputs += [ops.inp("mortgage_interest_cents", ops.mortgage_interest_cents),
               ops.inp("depreciation_cents", ops.depreciation_cents)]
    return money("cash_flow.schedule_e.line21", total, inputs,
                 "line3 rents + line4 royalties/other - lines 5..19 expenses (incl. line12 interest, line18 depreciation)")


def cash_flow_from_return(line21: Figure, depreciation_cents: int, principal_paid_cents: int,
                         capital_improvements_paid_cents: int = 0, extra_inputs: list[Input] | None = None) -> Figure:
    inputs = [Input.figure(line21), Input.of("line18_depreciation_cents", depreciation_cents, src="document", ref="Schedule E line 18"),
              Input.of("principal_paid_cents", principal_paid_cents, src="figure", ref="loans.schedule"),
              Input.of("capital_improvements_paid_cents", capital_improvements_paid_cents)]
    if extra_inputs:
        inputs += extra_inputs
    return money("cash_flow.from_return", line21.dec + Decimal(depreciation_cents) - Decimal(principal_paid_cents)
                 - Decimal(capital_improvements_paid_cents), inputs,
                 "line21 + line18_depreciation - principal_paid - capital_improvements_paid",
                 ["interest is inside line 21 already and is not subtracted again"])


def bridge_delta(engine_cf: Figure, return_cf: Figure) -> Figure:
    delta = engine_cf.dec - return_cf.dec
    notes = []
    if delta != 0:
        notes.append("delta = vacancy/capex reserve assumptions and any expense lines the return books differently")
    return money("cash_flow.bridge_delta", delta, [Input.figure(engine_cf), Input.figure(return_cf)],
                 "cash_flow.net_annual - cash_flow.from_return", notes)


def project_operations(base: YearOperations, years_ahead: int, rent_growth, expense_growth) -> YearOperations:
    """Grow rent/other income by rent_growth and every expense line by expense_growth for `years_ahead` years.

    Growth is applied as an exact Decimal power and rounded per line, so projected years are reproducible.
    """
    rg = (Decimal(1) + D(rent_growth or 0)) ** years_ahead
    eg = (Decimal(1) + D(expense_growth or 0)) ** years_ahead
    from groundplan.engine.figure import cents as _c
    kw = {
        "tax_year": base.tax_year + years_ahead,
        "gross_rent_cents": _c(Decimal(base.gross_rent_cents) * rg),
        "other_income_cents": _c(Decimal(base.other_income_cents) * rg),
        "mortgage_interest_cents": 0,
        "depreciation_cents": base.depreciation_cents,
    }
    for k in EXPENSE_LINES:
        kw[f"{k}_cents"] = _c(Decimal(getattr(base, f"{k}_cents")) * eg)
    src = {k: Input.of(k, v, src="figure", ref=f"projection(+{years_ahead}y)") for k, v in kw.items() if k.endswith("_cents")}
    return YearOperations(sources=src, **kw)
