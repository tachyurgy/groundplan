from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import Response

from groundplan.api.deps import Ctx
from groundplan.api.problems import Problem
from groundplan.api.schemas import HouseholdIn, HouseholdPatch
from groundplan.db import models as m
from groundplan.services import ingest
from groundplan.services import portfolio as svc
from groundplan.services import report as report_svc

router = APIRouter(tags=["households"])


@router.get("/households", summary="List households (HouseholdSummary[])")
def list_households(c: Ctx = Depends()):
    rows = c.s.execute(m.scoped(m.Household, c.aid).order_by(m.Household.name)).scalars().all()
    return [svc.summary(c.s, h, c.aid) for h in rows]


@router.post("/households", status_code=201)
def create_household(body: HouseholdIn, c: Ctx = Depends()):
    from groundplan.config import get_settings
    from groundplan.services import workspace as ws

    cap = get_settings().max_households_per_workspace
    if ws.counts(c.s, c.aid)[0] >= cap:
        raise Problem(429, "Household limit reached", f"a workspace holds at most {cap} households; delete one or reset "
                      "the workspace", "https://groundplan.dev/problems/household-limit")
    h = m.Household(advisor_id=c.aid, **body.model_dump())
    c.s.add(h)
    c.s.commit()
    return svc.household_dict(h)


@router.get("/households/{household_id}")
def get_household(household_id: str, c: Ctx = Depends()):
    h = c.household(household_id)
    d = svc.household_dict(h)
    d["properties"] = [svc.property_dict(p) for p in h.properties]
    return d


@router.patch("/households/{household_id}")
def patch_household(household_id: str, body: HouseholdPatch, c: Ctx = Depends()):
    h = c.household(household_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(h, k, v)
    c.s.commit()
    return svc.household_dict(h)


@router.delete("/households/{household_id}", status_code=204)
def delete_household(household_id: str, c: Ctx = Depends()):
    c.s.delete(c.household(household_id))
    c.s.commit()
    return Response(status_code=204)


@router.get("/households/{household_id}/dashboard")
def household_dashboard(household_id: str, c: Ctx = Depends()):
    return svc.dashboard(c.s, c.household(household_id), c.aid)


@router.get("/households/{household_id}/alerts")
def household_alerts(household_id: str, c: Ctx = Depends()):
    return svc.alerts(c.s, c.household(household_id), c.aid)


@router.get("/households/{household_id}/findings")
def household_findings(household_id: str, status: str | None = Query(None, pattern="^(open|resolved|dismissed)$"),
                       c: Ctx = Depends()):
    h = c.household(household_id)
    q = m.scoped(m.Finding, c.aid).where(m.Finding.household_id == h.id).order_by(m.Finding.created_at)
    if status:
        q = q.where(m.Finding.status == status)
    order = {"block": 0, "warn": 1, "info": 2}
    rows = sorted(c.s.execute(q).scalars().all(), key=lambda f: order.get(f.severity, 3))
    return [svc.finding_dict(f) for f in rows]


@router.post("/households/{household_id}/import-reconciled", summary="Upsert a ReconciledHousehold (SPEC §4.4) from gp_pipeline")
def import_reconciled(household_id: str, payload: dict = Body(..., description="ReconciledHousehold JSON"), c: Ctx = Depends()):
    h = c.household(household_id)
    if "household" not in payload or "properties" not in payload:
        raise Problem(422, "Not a ReconciledHousehold", "payload must carry `household` and `properties`")
    stats = ingest.import_reconciled(c.s, h, payload)
    c.s.commit()
    return {"household_id": h.id, "stats": stats, "properties": [svc.property_dict(p) for p in h.properties],
            "findings_open": len(svc.open_findings(h))}


@router.get("/households/{household_id}/report.pdf", response_class=Response,
            responses={200: {"content": {"application/pdf": {}}}})
def household_report(household_id: str, c: Ctx = Depends()):
    h = c.household(household_id)
    dash = svc.dashboard(c.s, h, c.aid)
    analyses = []
    for p in h.properties:
        if p.status == "active":
            an, _, _ = svc.analyze(c.s, p, c.aid)
            analyses.append((svc.property_dict(p), an))
    adv = c.s.get(m.Advisor, c.aid)
    pdf = report_svc.render(dash, analyses, {"firm_name": adv.firm_name if adv else ""})
    safe = "".join(ch if ch.isalnum() else "-" for ch in h.name).strip("-").lower()
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{safe}-report.pdf"',
                                                                "Cache-Control": "no-store"})
