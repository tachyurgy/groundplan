"""Service layer: load tenant-scoped rows, map them onto engine models (with document provenance), run the engine."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from groundplan.db import models as m
from groundplan.engine import observations as obs
from groundplan.engine.analysis import analyze_property
from groundplan.engine.cashflow import YearOperations
from groundplan.engine.figure import Input, Source, money
from groundplan.engine.loans import LoanInput
from groundplan.engine.models import DEFAULTS, HouseholdModel, PropertyModel
from groundplan.engine.narrative import generate_narrative
from groundplan.engine.observations import usd

# Schedule E line number -> engine input key
SCHED_E_LINE = {3: "gross_rent_cents", 4: "other_income_cents", 9: "insurance_cents", 11: "mgmt_cents",
                12: "mortgage_interest_cents", 14: "repairs_cents", 16: "taxes_cents", 17: "utilities_cents",
                18: "depreciation_cents", 19: "other_cents"}
FIELD_HINTS = (("rent", "gross_rent_cents"), ("interest", "mortgage_interest_cents"), ("depreciation", "depreciation_cents"),
               ("insurance", "insurance_cents"), ("repairs", "repairs_cents"), ("taxes", "taxes_cents"),
               ("utilities", "utilities_cents"), ("management", "mgmt_cents"), ("mgmt", "mgmt_cents"), ("hoa", "hoa_cents"),
               ("value", "current_value_cents"), ("purchase_price", "purchase_price_cents"))


def input_key_for_field(field: str) -> str | None:
    """Map a pipeline field name ('schedule_e.line3.rents', 'loan.balance_cents') to the engine input key."""
    mt = re.search(r"line(\d+)", field or "")
    if mt and field.startswith("schedule_e") and int(mt.group(1)) in SCHED_E_LINE:
        return SCHED_E_LINE[int(mt.group(1))]
    f = (field or "").lower()
    if "balance" in f:
        return "loan_balance"
    for hint, key in FIELD_HINTS:
        if hint in f:
            return key
    return None


def get_owned(s: Session, model, id_: str, advisor_id: str):
    return s.execute(m.scoped(model, advisor_id).where(model.id == id_)).scalar_one_or_none()


def latest_carryforward(h: m.Household) -> int:
    if not h.suspended_losses:
        return 0
    return max(h.suspended_losses, key=lambda x: x.tax_year).carryforward_cents


def household_model(h: m.Household) -> HouseholdModel:
    return HouseholdModel(filing_status=h.filing_status, state=h.state, tax_year=h.tax_year_latest,
                          wages_cents=h.wages_cents, other_income_cents=h.other_income_cents, magi_cents=h.magi_cents,
                          active_participation=h.active_participation, re_professional=h.re_professional,
                          carryforward_cents=latest_carryforward(h), net_worth_cents=h.net_worth_cents, goal=h.goal)


def _field_sources(s: Session, p: m.Property, advisor_id: str) -> dict[tuple[int, str], Input]:
    """(tax_year, input_key) -> Input pointing at the extracted field's document/page/bbox."""
    out: dict[tuple[int, str], Input] = {}
    if not p.property_key:
        return out
    rows = s.execute(
        select(m.ExtractedField, m.Document).join(m.Document, m.Document.id == m.ExtractedField.document_id)
        .where(m.ExtractedField.advisor_id == advisor_id, m.Document.advisor_id == advisor_id,
               m.Document.household_id == p.household_id, m.ExtractedField.property_key == p.property_key)
    ).all()
    for ef, doc in rows:
        key = input_key_for_field(ef.field)
        if key is None or doc.tax_year is None:
            continue
        prev = out.get((doc.tax_year, key))
        if prev is not None and doc.kind != "schedule_e":
            continue
        out[(doc.tax_year, key)] = Input(key=key, value=ef.value, source=Source(
            type="document", ref=f"{doc.filename} ({doc.kind} {doc.tax_year}) {ef.field}", page=ef.page,
            document_id=doc.id, bbox=list(ef.bbox) if ef.bbox else None))
    return out


def blocked_keys_for(p: m.Property, findings: list[m.Finding]) -> set[str]:
    keys: set[str] = set()
    for f in findings:
        if f.status != "open" or f.severity != "block" or f.property_id not in (p.id, None):
            continue
        k = input_key_for_field(f.field)
        if k == "loan_balance":
            keys |= {f"loan[{i}].balance_cents" for i in range(len(p.loans))}
        elif k:
            keys.add(k)
    return keys


def property_model(s: Session, p: m.Property, advisor_id: str, findings: list[m.Finding] | None = None) -> PropertyModel:
    srcs = _field_sources(s, p, advisor_id)
    years: dict[int, YearOperations] = {}
    rr = {r.tax_year: r for r in p.rent_rolls}
    ex = {e.tax_year: e for e in p.expense_years}
    for y in sorted(set(rr) | set(ex)):
        r, e = rr.get(y), ex.get(y)
        kw = {"gross_rent_cents": r.gross_rent_cents if r else 0, "other_income_cents": r.other_income_cents if r else 0}
        for k in ("taxes", "insurance", "repairs", "mgmt", "utilities", "hoa", "other", "mortgage_interest", "depreciation"):
            kw[f"{k}_cents"] = getattr(e, f"{k}_cents") if e else 0
        src = {}
        for k, v in kw.items():
            src[k] = srcs.get((y, k)) or Input.of(k, v, src="manual", ref=f"{y} rent roll / expense year (entered)")
        years[y] = YearOperations(tax_year=y, sources=src, **kw)
    loans = [LoanInput(loan_type=ln.loan_type, balance_cents=ln.balance_cents, balance_as_of=ln.balance_as_of, rate=ln.rate,
                       term_months=ln.term_months, io_months=ln.io_months, arm_reset_date=ln.arm_reset_date,
                       arm_index_margin=ln.arm_index_margin, monthly_payment_cents=ln.monthly_payment_cents,
                       maturity_date=ln.maturity_date, lien_position=ln.lien_position, is_paid_off=ln.is_paid_off,
                       lender=ln.lender, id=ln.id) for ln in p.loans]
    ledger = [{"tax_year": d.tax_year, "allowed_cents": d.allowed_cents, "allowable_cents": d.allowable_cents, "method": d.method}
              for d in p.depreciation_ledger]
    return PropertyModel(
        id=p.id, nickname=p.nickname, property_type=p.property_type, units=p.units,
        purchase_date=p.purchase_date or date(2015, 1, 1), purchase_price_cents=p.purchase_price_cents,
        placed_in_service_date=p.placed_in_service_date, land_pct=p.land_pct, improvements_cents=p.improvements_cents,
        cost_seg_study=p.cost_seg_study, current_value_cents=p.current_value_cents, value_source=p.value_source,
        value_as_of=p.value_as_of, appreciation_rate=p.appreciation_rate, rent_growth_rate=p.rent_growth_rate,
        expense_growth_rate=p.expense_growth_rate, vacancy_rate=p.vacancy_rate, mgmt_fee_rate=p.mgmt_fee_rate,
        capex_reserve_rate=p.capex_reserve_rate, selling_cost_rate=p.selling_cost_rate, status=p.status,
        former_residence_until=p.former_residence_until, avg_stay_days=p.avg_stay_days, loans=loans, years=years,
        ledger=ledger, blocked_keys=blocked_keys_for(p, findings or []))


def open_findings(h: m.Household) -> list[m.Finding]:
    return [f for f in h.findings if f.status == "open"]


def _obs_api(o: dict, idx: int) -> dict:
    sev = {"alert": "warn", "warn": "warn", "info": "info"}[o["severity"]]
    return {"id": f"{o['rule']}:{o.get('property_id') or 'household'}:{idx}", "severity": sev, "level": o["severity"],
            "rule": o["rule"], "message": o["message"], "property_id": o.get("property_id"), "figures": o["cites"]}


def analyze(s: Session, p: m.Property, advisor_id: str, year: int | None = None, horizon: int = 10,
            overrides: dict | None = None) -> tuple[dict, PropertyModel, HouseholdModel]:
    h = p.household
    pm = property_model(s, p, advisor_id, h.findings)
    for k, v in (overrides or {}).items():
        if v is not None and hasattr(pm, k):
            setattr(pm, k, Decimal(str(v)) if k.endswith("_rate") else v)
    hm = household_model(h)
    an = analyze_property(pm, hm, year or h.tax_year_latest, horizon)
    ctx = obs.property_context(p.nickname, an, pm, DEFAULTS["reinvest_rate"], date(an["year"] + 1, 1, 1))
    an["observations"] = [_obs_api(o, i) for i, o in enumerate(obs.evaluate(ctx, "property", p.id))]
    return an, pm, hm


def figure_status(*statuses: str) -> str:
    order = {"confirmed": 0, "estimated": 1, "blocked": 2}
    return max(statuses or ("confirmed",), key=lambda x: order[x])


def property_card(p: m.Property, an: dict, n_findings: int) -> dict:
    cf = an["cash_flow"]
    eq = an["equity"]
    ex = an["exit_tax"]
    chips = sorted({cf["net_cash_flow"]["status"], eq["equity"]["status"], ex["exit_tax_total"]["status"]})
    return {"property": property_dict(p), "value": eq["value"], "equity": eq["equity"], "net_cash_flow": cf["net_cash_flow"],
            "exit_tax": ex["exit_tax_total"], "roe": eq["roe"], "roe_rate": eq["roe_rate"], "status_chips": chips,
            "open_findings": n_findings, "dscr": cf["dscr"], "observations": an["observations"]}


def household_rollup(s: Session, h: m.Household, advisor_id: str) -> dict:
    active = [p for p in h.properties if p.status == "active"]
    analyses = []
    for p in active:
        an, pm, hm = analyze(s, p, advisor_id)
        analyses.append((p, an, pm))
    hm = household_model(h)
    return {"household": h, "analyses": analyses, "hm": hm}


def dashboard(s: Session, h: m.Household, advisor_id: str, provider=None) -> dict:
    roll = household_rollup(s, h, advisor_id)
    analyses = roll["analyses"]
    hm: HouseholdModel = roll["hm"]
    findings = open_findings(h)
    figs = []
    tot = {"value": 0, "debt": 0, "equity": 0, "net": 0, "exit": 0, "line21": 0}
    statuses: dict[str, list[str]] = {k: [] for k in tot}
    for p, an, _ in analyses:
        tot["value"] += an["equity"]["value"]["value_cents"]
        tot["debt"] += an["equity"]["total_debt"]["value_cents"]
        tot["equity"] += an["equity"]["equity"]["value_cents"]
        tot["net"] += an["cash_flow"]["net_cash_flow"]["value_cents"]
        tot["exit"] += an["exit_tax"]["exit_tax_total"]["value_cents"]
        tot["line21"] += an["_line21_cents"] or 0
        statuses["value"].append(an["equity"]["value"]["status"])
        statuses["debt"].append(an["equity"]["total_debt"]["status"])
        statuses["equity"].append(an["equity"]["equity"]["status"])
        statuses["net"].append(an["cash_flow"]["net_cash_flow"]["status"])
        statuses["exit"].append(an["exit_tax"]["exit_tax_total"]["status"])
        figs.append((p, an))

    def agg(key: str, label: str, tk: str, path: tuple[str, str], formula: str) -> dict:
        inputs = [Input(key=f"{p.nickname}.{path[1]}", value=an[path[0]][path[1]]["value_cents"],
                        source=Source(type="figure", ref=f"properties/{p.id}/{an[path[0]][path[1]]['key']}"),
                        status=an[path[0]][path[1]]["status"]) for p, an in figs]
        f = money(key, Decimal(tot[tk]), inputs or [Input.of(key, 0)], formula)
        f.status = figure_status(*statuses[tk]) if statuses[tk] else "confirmed"
        d = f.to_dict()
        d["label"] = label
        return d

    from groundplan.engine.passive import apply_passive_rules

    str_days = {p.nickname: pm.avg_stay_days for p, _, pm in analyses if pm.avg_stay_days is not None}
    pas = apply_passive_rules(tot["line21"], hm.carryforward_cents, hm.magi_cents, hm.filing_status, hm.active_participation,
                              hm.re_professional, str_days)
    metrics = {
        "total_value": agg("household.total_value", "Portfolio value", "value", ("equity", "value"), "sum of property values"),
        "total_debt": agg("household.total_debt", "Total debt", "debt", ("equity", "total_debt"), "sum of lien balances"),
        "total_equity": agg("household.total_equity", "Total equity", "equity", ("equity", "equity"), "sum of property equity"),
        "net_cash_flow": agg("household.net_cash_flow", "Net cash flow (annual)", "net", ("cash_flow", "net_cash_flow"),
                             "sum of property net cash flow"),
        "exit_tax_total": agg("household.exit_tax_total", "Exit tax if all sold today", "exit", ("exit_tax", "exit_tax_total"),
                              "sum of per-property exit tax (each stacked on the household's other income separately)"),
        "passive_allowance": {**pas.allowance.to_dict(), "label": "Rental loss allowance (8582)"},
        "suspended_losses": {**pas.carryforward_end.to_dict(), "label": "Suspended passive losses"},
        "net_rental_income": {**money("household.net_rental_income", Decimal(tot["line21"]),
                                      [Input.of(f"{p.nickname}.line21", an["_line21_cents"], src="figure") for p, an in figs] or
                                      [Input.of("line21", 0)], "sum of Schedule E line 21").to_dict(), "label": "Net rental income (Sch E)"},
    }
    observations = []
    for _p, an in figs:
        observations += an["observations"]
    hctx = {"carryforward_cents": hm.carryforward_cents, "magi_cents": hm.magi_cents, "net_rental_cents": tot["line21"],
            "allowance_cents": pas.allowance.value_cents}
    observations += [_obs_api(o, i) for i, o in enumerate(obs.evaluate(hctx, "household"))]
    order = {"alert": 0, "warn": 1, "info": 2}
    observations.sort(key=lambda o: order[o["level"]])
    cards = [property_card(p, an, sum(1 for f in findings if f.property_id == p.id)) for p, an in figs]
    facts = narrative_facts(h, figs, tot, hm, observations)
    narrative = generate_narrative(facts, provider)
    if narrative["provider"].startswith("llm"):
        narrative["provider"] = "llm"
    return {"household": household_dict(h), "metrics": metrics, "observations": observations, "properties": cards,
            "findings_open": len(findings), "narrative": narrative,
            "inactive_properties": [property_dict(p) for p in h.properties if p.status != "active"]}


def narrative_facts(h: m.Household, figs, tot: dict, hm: HouseholdModel, observations: list[dict]) -> dict:
    return {"household": {"name": h.name, "goal": h.goal}, "property_count": len(figs), "total_value": usd(tot["value"]),
            "total_debt": usd(tot["debt"]), "total_equity": usd(tot["equity"]), "net_cash_flow": usd(tot["net"]),
            "exit_tax_total": usd(tot["exit"]), "carryforward": usd(hm.carryforward_cents) if hm.carryforward_cents else None,
            "observations": [{"message": o["message"]} for o in observations if o["level"] in ("alert", "warn")]}


def summary(s: Session, h: m.Household, advisor_id: str) -> dict:
    net = 0
    eq = 0
    statuses = []
    for p in h.properties:
        if p.status != "active":
            continue
        an, _, _ = analyze(s, p, advisor_id, horizon=1)
        net += an["cash_flow"]["net_cash_flow"]["value_cents"]
        eq += an["equity"]["equity"]["value_cents"]
        statuses += [an["cash_flow"]["net_cash_flow"]["status"], an["equity"]["equity"]["status"]]
    return {"id": h.id, "name": h.name, "state": h.state, "filing_status": h.filing_status,
            "property_count": sum(1 for p in h.properties if p.status == "active"), "net_cash_flow_cents": net,
            "total_equity_cents": eq, "open_findings": len(open_findings(h)), "status": figure_status(*statuses) if statuses else "confirmed"}


def alerts(s: Session, h: m.Household, advisor_id: str, today: date | None = None) -> list[dict]:
    """Monitoring stubs computed on the fly from loans/values (roadmap: persisted + scheduled)."""
    today = today or date(h.tax_year_latest + 1, 1, 1)
    out = []
    for p in h.properties:
        if p.status != "active":
            continue
        for ln in p.loans:
            if ln.is_paid_off:
                continue
            if ln.arm_reset_date and 0 <= (ln.arm_reset_date - today).days <= 730:
                out.append(("arm_reset", p, ln.arm_reset_date, f"{p.nickname}: ARM with {ln.lender} resets {ln.arm_reset_date.isoformat()}"))
            if ln.io_months and ln.loan_type != "heloc":
                mth = ln.balance_as_of.month + ln.io_months
                end = date(ln.balance_as_of.year + (mth - 1) // 12, (mth - 1) % 12 + 1, 1)
                if 0 <= (end - today).days <= 730:
                    out.append(("io_period_ending", p, end, f"{p.nickname}: interest-only period ends {end.isoformat()}"))
            if ln.maturity_date and 0 <= (ln.maturity_date - today).days <= 1095:
                out.append(("loan_maturity", p, ln.maturity_date, f"{p.nickname}: {ln.lender} loan matures {ln.maturity_date.isoformat()}"))
        if p.value_as_of and (today - p.value_as_of).days > 365:
            out.append(("value_drift", p, today, f"{p.nickname}: value is more than a year old ({p.value_as_of.isoformat()}); refresh it"))
        an, _, _ = analyze(s, p, advisor_id, horizon=1)
        if an["_net_cents"] is not None and an["_net_cents"] < 0:
            out.append(("cash_flow_negative", p, today, f"{p.nickname}: negative cash flow {usd(an['_net_cents'])}/yr"))
        if an["_roe"] is not None and Decimal(an["_roe"]) < DEFAULTS["reinvest_rate"]:
            out.append(("roe_below_threshold", p, today, f"{p.nickname}: ROE {Decimal(an['_roe']) * 100:.1f}% below 6.0%"))
    return [{"id": f"{k}:{p.id}:{i}", "household_id": h.id, "property_id": p.id, "kind": k, "due_date": d.isoformat(),
             "message": msg, "status": "open"} for i, (k, p, d, msg) in enumerate(out)]


# ---------------------------------------------------------------- serializers


def _iso(d):
    return d.isoformat() if d else None


def _num(x):
    return None if x is None else float(x)


def household_dict(h: m.Household) -> dict:
    return {"id": h.id, "advisor_id": h.advisor_id, "name": h.name, "filing_status": h.filing_status, "state": h.state,
            "tax_year_latest": h.tax_year_latest, "wages_cents": h.wages_cents, "other_income_cents": h.other_income_cents,
            "magi_cents": h.magi_cents, "active_participation": h.active_participation, "re_professional": h.re_professional,
            "net_worth_cents": h.net_worth_cents, "goal": h.goal, "notes": h.notes,
            "suspended_losses": [{"id": x.id, "household_id": h.id, "tax_year": x.tax_year, "carryforward_cents": x.carryforward_cents}
                                 for x in sorted(h.suspended_losses, key=lambda x: x.tax_year)]}


PROPERTY_RATE_FIELDS = ("land_pct", "appreciation_rate", "rent_growth_rate", "expense_growth_rate", "vacancy_rate", "mgmt_fee_rate",
                        "capex_reserve_rate", "selling_cost_rate")


def property_dict(p: m.Property) -> dict:
    d = {"id": p.id, "household_id": p.household_id, "nickname": p.nickname, "address_line1": p.address_line1, "city": p.city,
         "state": p.state, "zip": p.zip, "property_type": p.property_type, "units": p.units, "purchase_date": _iso(p.purchase_date),
         "purchase_price_cents": p.purchase_price_cents, "placed_in_service_date": _iso(p.placed_in_service_date),
         "improvements_cents": p.improvements_cents, "cost_seg_study": p.cost_seg_study, "current_value_cents": p.current_value_cents,
         "value_source": p.value_source, "value_as_of": _iso(p.value_as_of), "status": p.status,
         "former_residence_until": _iso(p.former_residence_until), "avg_stay_days": p.avg_stay_days, "property_key": p.property_key}
    for k in PROPERTY_RATE_FIELDS:
        d[k] = _num(getattr(p, k))
    d["effective_rates"] = {k: float(DEFAULTS[k]) if getattr(p, k) is None and k in DEFAULTS else _num(getattr(p, k))
                            for k in PROPERTY_RATE_FIELDS if k != "land_pct"}
    d["effective_rates"]["land_pct"] = _num(p.land_pct) if p.land_pct is not None else 0.30
    return d


def loan_dict(ln: m.Loan) -> dict:
    return {"id": ln.id, "property_id": ln.property_id, "lender": ln.lender, "loan_type": ln.loan_type,
            "original_cents": ln.original_cents, "balance_cents": ln.balance_cents, "balance_as_of": _iso(ln.balance_as_of),
            "rate": _num(ln.rate), "term_months": ln.term_months, "io_months": ln.io_months, "arm_reset_date": _iso(ln.arm_reset_date),
            "arm_index_margin": _num(ln.arm_index_margin), "monthly_payment_cents": ln.monthly_payment_cents,
            "maturity_date": _iso(ln.maturity_date), "lien_position": ln.lien_position, "is_paid_off": ln.is_paid_off}


def finding_dict(f: m.Finding) -> dict:
    return {"id": f.id, "household_id": f.household_id, "property_id": f.property_id, "kind": f.kind, "field": f.field,
            "severity": f.severity, "message": f.message, "candidates": f.candidates or [], "status": f.status,
            "resolution": f.resolution, "key": f.key}


def document_dict(d: m.Document) -> dict:
    return {"id": d.id, "household_id": d.household_id, "kind": d.kind, "tax_year": d.tax_year, "filename": d.filename,
            "sha256": d.sha256, "page_count": d.page_count, "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            "status": d.status, "bytes_retained": False}


def field_dict(f: m.ExtractedField) -> dict:
    return {"id": f.id, "document_id": f.document_id, "entity_hint": f.entity_hint, "property_key": f.property_key, "field": f.field,
            "value": f.value, "unit": f.unit, "page": f.page, "bbox": f.bbox, "confidence": f.confidence, "extractor": f.extractor,
            "raw_text": f.raw_text}
