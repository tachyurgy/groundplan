from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends

from groundplan.api.deps import Ctx
from groundplan.api.problems import Problem
from groundplan.api.schemas import SimulateIn
from groundplan.db import models as m
from groundplan.engine.exit_tax import HouseholdTax
from groundplan.engine.observations import rule_table
from groundplan.engine.simulate import SimProperty, SimRequest, simulate
from groundplan.services import portfolio as svc

router = APIRouter(tags=["system"])
EVAL_PATH = Path(__file__).resolve().parents[4] / "fixtures" / "documents" / "eval-latest.json"


@router.get("/eval/latest", summary="Last pipeline eval summary (fixtures/documents/eval-latest.json)")
def eval_latest():
    if not EVAL_PATH.exists():
        raise Problem(404, "No eval yet", "run `make pipeline-eval` to produce fixtures/documents/eval-latest.json")
    return json.loads(EVAL_PATH.read_text())


@router.get("/rules", summary="The observation rule table (reviewable in one place)")
def rules():
    return rule_table()


def _band(x: int) -> dict:
    return {"p10": x, "p50": x, "p90": x}


@router.post("/simulate", summary="Buy/sell-over-time simulation with Monte Carlo percentile bands")
def run_simulation(body: SimulateIn, c: Ctx = Depends()):
    a = body.assumptions
    props: list[SimProperty] = []
    hh = HouseholdTax(filing_status=a.filing_status, state=a.state, wages_cents=a.wages_cents,
                      other_income_cents=a.other_income_cents, magi_cents=a.magi_cents)
    if body.household_id:
        h = c.household(body.household_id)
        hh = HouseholdTax(filing_status=h.filing_status, state=h.state, wages_cents=h.wages_cents,
                          other_income_cents=h.other_income_cents, magi_cents=h.magi_cents)
        if not body.properties:
            for p in h.properties:
                if p.status != "active":
                    continue
                an, pm, _ = svc.analyze(c.s, p, c.aid, horizon=1)
                active = [ln for ln in pm.loans if not ln.is_paid_off]
                props.append(SimProperty(
                    id=p.nickname, value_cents=p.current_value_cents, debt_cents=sum(an["_balances"]),
                    rate=float(active[0].rate) if active else 0.0, remaining_years=30,
                    gross_rent_cents=an["cash_flow"]["gross_rent"]["value_cents"],
                    expenses_cents=an["cash_flow"]["operating_expenses"]["value_cents"] + an["cash_flow"]["capex_reserve"]["value_cents"],
                    appreciation_rate=float(pm.appreciation_rate or a.appreciation_rate), rent_growth=a.rent_growth,
                    expense_growth=a.expense_growth, vacancy_rate=float(pm.vacancy_rate if pm.vacancy_rate is not None else a.vacancy_rate),
                    purchase_price_cents=p.purchase_price_cents + p.improvements_cents,
                    accumulated_depreciation_cents=an["depreciation"]["accumulated_cents"] or 0,
                    depreciable_basis_cents=an["depreciation"]["depreciable_basis"]["value_cents"]))
    for i, sp in enumerate(body.properties):
        vac = a.vacancy_rate
        rent = sp.gross_rent_cents
        exp = sp.expenses_cents or 0
        if rent is None:
            rent = int(round(((sp.noi_cents or int(sp.current_value_cents * a.cap_rate)) + exp) / (1 - vac)))
        basis = sp.purchase_price_cents or sp.current_value_cents
        props.append(SimProperty(id=sp.id or sp.nickname or f"p{i + 1}", value_cents=sp.current_value_cents, debt_cents=sp.debt_cents,
                                 rate=sp.rate, remaining_years=sp.remaining_years, gross_rent_cents=rent, expenses_cents=exp,
                                 appreciation_rate=a.appreciation_rate, rent_growth=a.rent_growth, expense_growth=a.expense_growth,
                                 vacancy_rate=vac, purchase_price_cents=basis,
                                 accumulated_depreciation_cents=sp.accumulated_depreciation_cents or 0,
                                 depreciable_basis_cents=int(basis * (1 - (sp.land_pct if sp.land_pct is not None else 0.30)))))
    ids = {p.id for p in props}
    events = []
    for e in body.events:
        d = e.model_dump(exclude_none=True)
        ref = d.get("property_id") or d.get("property_ref")
        d["property_id"] = ref if ref in ids or e.type == "buy" else ref
        if e.type == "buy":
            d.setdefault("value_cents", d.get("amount_cents") or 0)
            d.setdefault("gross_rent_cents", int(d["value_cents"] * a.cap_rate / (1 - a.vacancy_rate)))
            ids.add(ref or f"buy-{e.year}")
        if e.type == "exchange" and d.get("amount_cents"):
            d.setdefault("replacement_value_cents", d["amount_cents"])
        if e.type == "exchange" and d.get("debt_cents") is not None:
            d.setdefault("replacement_debt_cents", d["debt_cents"])
        if e.type == "refi" and d.get("debt_cents"):
            pv = next((p.value_cents for p in props if p.id == ref), None)
            if pv:
                d.setdefault("ltv", d["debt_cents"] / pv)
        events.append(d)
    mc = body.monte_carlo
    req = SimRequest(start_year=body.start_year, years=body.years, properties=props, events=events, reinvest_rate=a.reinvest_rate,
                     starting_cash_cents=a.starting_cash_cents, household=hh, runs=mc.runs, appr_sigma=mc.appr_sigma,
                     rent_sigma=mc.rent_sigma, seed=mc.seed)
    res = simulate(req)
    det = res["deterministic"]
    bands = res["bands"]
    series = []
    for t, row in enumerate(det):
        b = bands[t] if bands else None
        series.append({
            "year": row["year"],
            "net_worth": b["net_worth"] if b else _band(row["net_worth"]),
            "cash_flow": b["cash_flow"] if b else _band(row["cash_flow"]),
            "taxes_paid": b["taxes_paid"] if b else _band(row["taxes_paid"]),
            "equity_cents": b["equity"]["p50"] if b else row["equity"],
            "debt_cents": b["debt"]["p50"] if b else row["debt"],
            "cash_cents": row["cash"], "value_cents": row["value"],
            "deterministic": {k: row[k] for k in ("net_worth", "cash_flow", "taxes_paid", "equity", "debt")},
            "events": [e.model_dump(exclude_none=True) for e in body.events if e.year == row["year"]],
        })
    last = bands[-1] if bands else None
    return {"series": series, "runs": res["runs"], "seed": res["seed"],
            "terminal": {"net_worth": last["net_worth"] if last else _band(det[-1]["net_worth"]),
                         "cumulative_taxes": last["cum_taxes"] if last else _band(det[-1]["cum_taxes"])},
            "properties": [p.id for p in props],
            "notes": ["Monte Carlo draws are seeded (PCG64) and reproducible; taxes on sells/exchanges come from the deterministic "
                      "exit-tax engine; cash flows are pre-income-tax and swept to a cash account at the reinvest rate."]}


__all__ = ["router", "m"]
