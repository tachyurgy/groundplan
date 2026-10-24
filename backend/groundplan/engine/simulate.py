"""Buy/sell-over-time simulation with Monte Carlo bands (POST /simulate).

Deterministic core per year (end-of-year events): value *= 1 + appreciation (+ sigma x z); rent *= 1 + rent_growth
(+ sigma x z); expenses grow at expense_growth; debt amortizes on a level annual payment; net cash flow =
rent x (1 - vacancy) - expenses - debt service, swept into a cash account that earns reinvest_rate.
Events: buy (cash pays the down payment + closing costs), sell (taxable, through the real exit-tax engine),
exchange (1031: relinquished property's equity rolls into a replacement at carryover basis, no tax unless boot),
refi (new loan at ltv x value, cash-out to the account).
Monte Carlo draws use numpy's PCG64 with an explicit seed, so a request is reproducible. The stochastic layer is
float64 (it is a distribution, not a ledger); every reported number is rounded to integer cents, and the taxes come
from the Decimal exit-tax engine.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from groundplan.engine.exit_tax import HouseholdTax, SaleInput, compute_exit_tax

RESIDENTIAL_LIFE = 27.5


@dataclass
class SimProperty:
    id: str
    value_cents: int
    debt_cents: int = 0
    rate: float = 0.065
    remaining_years: int = 30
    gross_rent_cents: int = 0
    expenses_cents: int = 0
    appreciation_rate: float = 0.035
    rent_growth: float = 0.03
    expense_growth: float = 0.03
    vacancy_rate: float = 0.05
    purchase_price_cents: int | None = None
    accumulated_depreciation_cents: int = 0
    depreciable_basis_cents: int | None = None
    selling_cost_rate: float = 0.06
    active: bool = True

    def annual_payment(self) -> float:
        if self.debt_cents <= 0 or self.remaining_years <= 0:
            return 0.0
        r = self.rate
        n = self.remaining_years
        if r == 0:
            return self.debt_cents / n
        return self.debt_cents * r / (1 - (1 + r) ** -n)


@dataclass
class SimRequest:
    start_year: int
    years: int
    properties: list[SimProperty]
    events: list[dict] = field(default_factory=list)
    reinvest_rate: float = 0.06
    starting_cash_cents: int = 0
    household: HouseholdTax = field(default_factory=HouseholdTax)
    runs: int = 0
    appr_sigma: float = 0.0
    rent_sigma: float = 0.0
    seed: int = 7


def _sell(prop: SimProperty, year: int, hh: HouseholdTax, cap: int | None = None) -> tuple[int, int]:
    """Return (net_proceeds_cents, tax_cents) through the deterministic exit-tax engine."""
    s = SaleInput(sale_price_cents=int(round(prop.value_cents)), selling_cost_rate=str(prop.selling_cost_rate),
                  loan_payoff_cents=int(round(prop.debt_cents)),
                  purchase_price_cents=int(prop.purchase_price_cents or prop.value_cents),
                  accumulated_depreciation_cents=int(prop.accumulated_depreciation_cents),
                  sale_date=date(year, 12, 31), recognized_gain_cap_cents=cap)
    h = copy.copy(hh)
    h.tax_year = year
    ex = compute_exit_tax(s, h)
    return ex.net_proceeds_cents, ex.total_cents


def _run_once(req: SimRequest, appr_shocks: np.ndarray | None, rent_shocks: np.ndarray | None) -> dict:
    props = {p.id: copy.deepcopy(p) for p in req.properties}
    for p in props.values():
        if p.purchase_price_cents is None:
            p.purchase_price_cents = p.value_cents
        if p.depreciable_basis_cents is None:
            p.depreciable_basis_cents = int(p.purchase_price_cents * 0.7)
    cash = float(req.starting_cash_cents)
    events_by_year: dict[int, list[dict]] = {}
    for e in req.events:
        events_by_year.setdefault(int(e["year"]), []).append(e)
    rows = []
    for t in range(req.years):
        yr = req.start_year + t
        cf_total = 0.0
        tax_total = 0.0
        for i, p in enumerate(sorted(props.values(), key=lambda q: q.id)):
            if not p.active:
                continue
            a_shock = appr_shocks[t, i % appr_shocks.shape[1]] if appr_shocks is not None else 0.0
            r_shock = rent_shocks[t, i % rent_shocks.shape[1]] if rent_shocks is not None else 0.0
            pay = p.annual_payment()
            interest = p.debt_cents * p.rate
            principal = min(max(0.0, pay - interest), p.debt_cents)
            cf = p.gross_rent_cents * (1 - p.vacancy_rate) - p.expenses_cents - pay
            cf_total += cf
            p.debt_cents -= principal
            p.remaining_years = max(0, p.remaining_years - 1)
            p.value_cents *= 1 + p.appreciation_rate + a_shock
            p.gross_rent_cents *= 1 + p.rent_growth + r_shock
            p.expenses_cents *= 1 + p.expense_growth
            p.accumulated_depreciation_cents = min(
                p.depreciable_basis_cents, p.accumulated_depreciation_cents + p.depreciable_basis_cents / RESIDENTIAL_LIFE)
        cash = cash * (1 + req.reinvest_rate) + cf_total
        for e in events_by_year.get(yr, []):
            kind = e.get("type")
            pid = e.get("property_id")
            if kind == "buy":
                np_ = SimProperty(id=pid or f"buy-{yr}", value_cents=int(e["value_cents"]),
                                  debt_cents=int(e.get("debt_cents", 0)), rate=float(e.get("rate", 0.065)),
                                  remaining_years=int(e.get("term_years", 30)),
                                  gross_rent_cents=int(e.get("gross_rent_cents", 0)),
                                  expenses_cents=int(e.get("expenses_cents", 0)),
                                  appreciation_rate=float(e.get("appreciation_rate", 0.035)))
                np_.purchase_price_cents = np_.value_cents
                np_.depreciable_basis_cents = int(np_.value_cents * 0.7)
                down = np_.value_cents - np_.debt_cents + np_.value_cents * float(e.get("closing_cost_rate", 0.02))
                cash -= down
                props[np_.id] = np_
            elif kind in ("sell", "exchange") and pid in props and props[pid].active:
                p = props[pid]
                if kind == "sell":
                    net, tax = _sell(p, yr, req.household)
                    cash += net
                    tax_total += tax
                    p.active = False
                else:
                    boot = int(e.get("cash_taken_cents", 0))
                    tax = _sell(p, yr, req.household, cap=boot)[1] if boot else 0
                    tax_total += tax
                    cash += boot - tax
                    realized = p.value_cents * (1 - p.selling_cost_rate)
                    repl_value = float(e.get("replacement_value_cents", realized))
                    repl = copy.deepcopy(p)
                    repl.id = e.get("replacement_id", f"{pid}-x{yr}")
                    repl.value_cents = repl_value
                    repl.debt_cents = float(e.get("replacement_debt_cents", p.debt_cents))
                    extra = repl_value - realized
                    # carryover basis: deferred gain reduces the replacement basis; depreciation history carries
                    repl.purchase_price_cents = int(p.purchase_price_cents + max(0.0, extra))
                    scale = repl_value / max(1.0, p.value_cents)
                    repl.gross_rent_cents *= scale
                    repl.expenses_cents *= scale
                    p.active = False
                    props[repl.id] = repl
            elif kind == "refi" and pid in props and props[pid].active:
                p = props[pid]
                new_debt = p.value_cents * float(e.get("ltv", 0.70))
                cash += new_debt - p.debt_cents - new_debt * float(e.get("cost_rate", 0.01))
                p.debt_cents = new_debt
                p.rate = float(e.get("rate", p.rate))
                p.remaining_years = int(e.get("term_years", 30))
        equity = sum(p.value_cents - p.debt_cents for p in props.values() if p.active)
        debt = sum(p.debt_cents for p in props.values() if p.active)
        value = sum(p.value_cents for p in props.values() if p.active)
        rows.append({"year": yr, "net_worth": equity + cash, "cash_flow": cf_total, "taxes_paid": tax_total,
                     "equity": equity, "debt": debt, "value": value, "cash": cash})
    return {"rows": rows}


def simulate(req: SimRequest) -> dict:
    base = _run_once(req, None, None)
    out = {"start_year": req.start_year, "years": req.years,
           "deterministic": [{k: (int(round(v)) if k != "year" else v) for k, v in r.items()} for r in base["rows"]],
           "bands": None, "runs": 0, "seed": req.seed}
    if req.runs and req.runs > 0:
        rng = np.random.Generator(np.random.PCG64(req.seed))
        n_props = max(1, len(req.properties) + sum(1 for e in req.events if e.get("type") in ("buy", "exchange")))
        metrics = ("net_worth", "cash_flow", "taxes_paid", "equity", "debt")
        acc = {m: np.zeros((req.runs, req.years)) for m in metrics}
        for k in range(req.runs):
            a = rng.normal(0.0, req.appr_sigma, size=(req.years, n_props)) if req.appr_sigma else None
            r = rng.normal(0.0, req.rent_sigma, size=(req.years, n_props)) if req.rent_sigma else None
            res = _run_once(req, a, r)
            for t, row in enumerate(res["rows"]):
                for m in metrics:
                    acc[m][k, t] = row[m]
        bands = []
        for t in range(req.years):
            b = {"year": req.start_year + t}
            for m in metrics:
                p10, p50, p90 = np.percentile(acc[m][:, t], [10, 50, 90])
                b[m] = {"p10": int(round(p10)), "p50": int(round(p50)), "p90": int(round(p90))}
            bands.append(b)
        out["bands"] = bands
        out["runs"] = req.runs
    return out
