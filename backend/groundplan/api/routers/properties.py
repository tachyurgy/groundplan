from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse, Response

from groundplan.api.deps import Ctx, owned
from groundplan.api.problems import Problem
from groundplan.api.schemas import LoanIn, LoanPatch, PropertyIn, PropertyPatch, ScenarioIn, YearIn
from groundplan.db import models as m
from groundplan.services import factsheet
from groundplan.services import portfolio as svc

router = APIRouter(tags=["properties"])
RATE_FIELDS = set(svc.PROPERTY_RATE_FIELDS)


def _set_prop(p: m.Property, data: dict) -> None:
    for k, v in data.items():
        setattr(p, k, Decimal(str(v)) if (k in RATE_FIELDS and v is not None) else v)


@router.post("/households/{household_id}/properties", status_code=201)
def create_property(household_id: str, body: PropertyIn, c: Ctx = Depends()):
    h = c.household(household_id)
    p = m.Property(advisor_id=c.aid, household_id=h.id)
    _set_prop(p, body.model_dump())
    c.s.add(p)
    c.s.commit()
    return svc.property_dict(p)


@router.get("/properties/{property_id}")
def get_property(property_id: str, c: Ctx = Depends()):
    p = c.property(property_id)
    d = svc.property_dict(p)
    d["loans"] = [svc.loan_dict(ln) for ln in p.loans]
    d["years"] = _years(p)
    return d


def _years(p: m.Property) -> list[dict]:
    rr = {r.tax_year: r for r in p.rent_rolls}
    ex = {e.tax_year: e for e in p.expense_years}
    led = {d.tax_year: d for d in p.depreciation_ledger}
    out = []
    for y in sorted(set(rr) | set(ex) | set(led)):
        r, e, d = rr.get(y), ex.get(y), led.get(y)
        row = {"tax_year": y, "gross_rent_cents": r.gross_rent_cents if r else 0, "other_income_cents": r.other_income_cents if r else 0}
        for k in ("taxes", "insurance", "repairs", "mgmt", "utilities", "hoa", "other", "mortgage_interest", "depreciation"):
            row[f"{k}_cents"] = getattr(e, f"{k}_cents") if e else 0
        row["depreciation_ledger"] = ({"id": d.id, "allowed_cents": d.allowed_cents, "allowable_cents": d.allowable_cents,
                                       "method": d.method, "note": d.note} if d else None)
        out.append(row)
    return out


@router.patch("/properties/{property_id}")
def patch_property(property_id: str, body: PropertyPatch, c: Ctx = Depends()):
    p = c.property(property_id)
    _set_prop(p, body.model_dump(exclude_unset=True))
    c.s.commit()
    return svc.property_dict(p)


@router.delete("/properties/{property_id}", status_code=204)
def delete_property(property_id: str, c: Ctx = Depends()):
    c.s.delete(c.property(property_id))
    c.s.commit()
    return Response(status_code=204)


def _analysis_params(request: Request) -> dict:
    qp = request.query_params
    return {k: qp.get(k) for k in svc.ANALYSIS_OVERRIDES if qp.get(k) not in (None, "")}


def _analysis(c: Ctx, property_id: str, request: Request, year: int | None, horizon: int):
    p = c.property(property_id)
    try:
        return p, svc.analyze(c.s, p, c.aid, year, horizon, _analysis_params(request))
    except (ValueError, ArithmeticError) as e:
        raise Problem(422, "Invalid assumption override", str(e)) from e


def _strip_private(an: dict) -> dict:
    return {k: v for k, v in an.items() if not k.startswith("_")}


@router.get("/properties/{property_id}/analysis",
            description="Overrides as query params: " + ", ".join(svc.ANALYSIS_OVERRIDES))
def property_analysis(property_id: str, request: Request, response: Response, year: int | None = Query(None, ge=1990, le=2100),
                      horizon: int = Query(10, ge=1, le=40), c: Ctx = Depends()):
    p, (an, _, _) = _analysis(c, property_id, request, year, horizon)
    response.headers["X-Engine"] = an.get("_engine", "python")
    out = _strip_private(an)
    out["property"] = svc.property_dict(p)
    loans = {ln.id: svc.loan_dict(ln) for ln in p.loans}
    for row in out["loans"]:
        row["loan"] = loans.get(row["loan_id"])
    out["findings"] = [svc.finding_dict(f) for f in svc.sort_findings(p.household, p.household.findings)
                       if f.property_id == p.id and f.status == "open"]
    return out


@router.get("/properties/{property_id}/figure/{key:path}", summary="One Figure with its full inputs tree (traceability drawer)")
def property_figure(property_id: str, key: str, request: Request, year: int | None = Query(None), horizon: int = Query(10, ge=1, le=40),
                    depth: int = Query(12, ge=0, le=40), c: Ctx = Depends()):
    _, (an, _, _) = _analysis(c, property_id, request, year, horizon)
    figs = an["_figs"]
    fig = figs.get(key)
    if fig is None:
        for f in list(figs.values()):
            fig = next((x for x in f.walk() if x.key == key), None)
            if fig:
                break
    if fig is None:
        raise Problem(404, "Figure not found", f"no figure {key!r}; known keys: {', '.join(sorted(figs))}")
    d = fig.to_dict(depth)
    d["year"] = an["year"]
    return d


@router.get("/properties/{property_id}/strategies",
            description="Overrides as query params: " + ", ".join(svc.STRATEGY_OVERRIDES))
def property_strategies(property_id: str, request: Request, response: Response, horizon: int = Query(10, ge=1, le=40),
                        c: Ctx = Depends()):
    p = c.property(property_id)
    params = {k: request.query_params.get(k) for k in svc.STRATEGY_OVERRIDES}
    try:
        r = svc.strategies(c.s, p, c.aid, horizon, params)
        response.headers["X-Engine"] = r.pop("_engine", "python")
        return r
    except (ValueError, ArithmeticError) as e:
        raise Problem(422, "Invalid strategy assumption", str(e)) from e


@router.post("/properties/{property_id}/loans", status_code=201)
def create_loan(property_id: str, body: LoanIn, c: Ctx = Depends()):
    p = c.property(property_id)
    data = body.model_dump()
    data["rate"] = Decimal(str(data["rate"]))
    if data.get("arm_index_margin") is not None:
        data["arm_index_margin"] = Decimal(str(data["arm_index_margin"]))
    ln = m.Loan(advisor_id=c.aid, property_id=p.id, **data)
    c.s.add(ln)
    c.s.commit()
    return svc.loan_dict(ln)


@router.patch("/loans/{loan_id}")
def patch_loan(loan_id: str, body: LoanPatch, c: Ctx = Depends()):
    ln = owned(c.s, m.Loan, loan_id, c.aid, "Loan")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(ln, k, Decimal(str(v)) if k in ("rate", "arm_index_margin") and v is not None else v)
    c.s.commit()
    return svc.loan_dict(ln)


@router.delete("/loans/{loan_id}", status_code=204)
def delete_loan(loan_id: str, c: Ctx = Depends()):
    c.s.delete(owned(c.s, m.Loan, loan_id, c.aid, "Loan"))
    c.s.commit()
    return Response(status_code=204)


@router.put("/properties/{property_id}/years/{tax_year}", summary="Upsert RentRoll + ExpenseYear (+ DepreciationLedger) for a year")
def put_year(property_id: str, tax_year: int, body: YearIn, c: Ctx = Depends()):
    p = c.property(property_id)
    data = body.model_dump()
    led = data.pop("depreciation")
    r = next((x for x in p.rent_rolls if x.tax_year == tax_year), None)
    if r is None:
        r = m.RentRoll(advisor_id=c.aid, property_id=p.id, tax_year=tax_year)
        c.s.add(r)
        p.rent_rolls.append(r)
    r.gross_rent_cents, r.other_income_cents = data.pop("gross_rent_cents"), data.pop("other_income_cents")
    e = next((x for x in p.expense_years if x.tax_year == tax_year), None)
    if e is None:
        e = m.ExpenseYear(advisor_id=c.aid, property_id=p.id, tax_year=tax_year)
        c.s.add(e)
        p.expense_years.append(e)
    for k, v in data.items():
        setattr(e, k, v)
    if led is not None:
        d = next((x for x in p.depreciation_ledger if x.tax_year == tax_year), None)
        if d is None:
            d = m.DepreciationLedger(advisor_id=c.aid, property_id=p.id, tax_year=tax_year)
            c.s.add(d)
            p.depreciation_ledger.append(d)
        for k in ("allowed_cents", "allowable_cents", "method", "note"):
            if k in led:
                setattr(d, k, led[k])
    c.s.commit()
    return next(y for y in _years(p) if y["tax_year"] == tax_year)


@router.post("/properties/{property_id}/scenarios", status_code=201)
def create_scenario(property_id: str, body: ScenarioIn, c: Ctx = Depends()):
    p = c.property(property_id)
    params = {k: v for k, v in body.assumptions.items() if k in svc.STRATEGY_OVERRIDES}
    ex = body.assumptions.get("exchange") or {}
    params.update({k: v for k, v in ex.items() if k in svc.STRATEGY_OVERRIDES})
    results = svc.strategies(c.s, p, c.aid, body.horizon_years, params)
    sc = m.Scenario(advisor_id=c.aid, property_id=p.id, name=body.name, horizon_years=body.horizon_years,
                    assumptions=body.assumptions, results=results)
    c.s.add(sc)
    c.s.commit()
    return _scenario_dict(sc)


@router.get("/properties/{property_id}/scenarios")
def list_scenarios(property_id: str, c: Ctx = Depends()):
    p = c.property(property_id)
    return [_scenario_dict(sc, results=False) for sc in p.scenarios]


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str, c: Ctx = Depends()):
    return _scenario_dict(owned(c.s, m.Scenario, scenario_id, c.aid, "Scenario"))


def _scenario_dict(sc: m.Scenario, results: bool = True) -> dict:
    return {"id": sc.id, "property_id": sc.property_id, "name": sc.name, "horizon_years": sc.horizon_years,
            "assumptions": sc.assumptions, "results": sc.results if results else None,
            "created_at": sc.created_at.isoformat() if sc.created_at else None}


@router.get("/properties/{property_id}/factsheet", summary="Fact Sheet mapping (best-effort) for eMoney / RightCapital / MoneyGuidePro")
def property_factsheet(property_id: str, format: str = Query("json", pattern="^(emoney|rightcapital|mgp|json|csv)$"),
                       c: Ctx = Depends()):
    p = c.property(property_id)
    an, _, _ = svc.analyze(c.s, p, c.aid, horizon=1)
    sheet = factsheet.build(svc.property_dict(p), an, [svc.loan_dict(ln) for ln in p.loans], format)
    if format == "csv":
        return PlainTextResponse(factsheet.to_csv(sheet), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{p.nickname.replace(" ", "-").lower()}-factsheet.csv"'})
    return sheet
