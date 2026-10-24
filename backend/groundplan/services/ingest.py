"""Import a ReconciledHousehold (SPEC §4.4, produced by gp_pipeline) and persist upload results.

Idempotent upsert: properties match on property_key (normalized address) then nickname; loans on lien_position;
years / ledger / suspended losses on tax_year; documents on sha256 (else filename); findings on their stable key.
Uploaded file bytes never reach this module: only sha256 + extracted fields + findings.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from groundplan.db import models as m
from groundplan.services.portfolio import input_key_for_field


def _d(x) -> date | None:
    if not x:
        return None
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def _dec(x) -> Decimal | None:
    return None if x is None else Decimal(str(x))


def _dump(x: Any) -> Any:
    if hasattr(x, "model_dump"):
        return x.model_dump(mode="json")
    if isinstance(x, list):
        return [_dump(i) for i in x]
    return x


def _set(obj, **kw) -> None:
    for k, v in kw.items():
        if v is not None:
            setattr(obj, k, v)


def import_reconciled(s: Session, h: m.Household, payload: dict) -> dict:
    payload = _dump(payload)
    aid = h.advisor_id
    stats = {"properties_created": 0, "properties_updated": 0, "loans": 0, "years": 0, "ledger": 0, "suspended_losses": 0,
             "documents": 0, "extracted_fields": 0, "findings_created": 0, "findings_updated": 0}
    hh = payload.get("household") or {}
    _set(h, filing_status=hh.get("filing_status"), state=hh.get("state"), tax_year_latest=hh.get("tax_year_latest"),
         wages_cents=hh.get("wages_cents"), other_income_cents=hh.get("other_income_cents"), magi_cents=hh.get("magi_cents"),
         active_participation=hh.get("active_participation"), re_professional=hh.get("re_professional"))
    if hh.get("goal"):
        h.goal = hh["goal"]
    if not h.name and hh.get("name"):
        h.name = hh["name"]
    by_key = {p.property_key: p for p in h.properties if p.property_key}
    by_nick = {p.nickname.lower(): p for p in h.properties}
    key_to_id: dict[str, str] = {}
    for po in payload.get("properties", []):
        p = by_key.get(po.get("key")) or by_nick.get((po.get("nickname") or "").lower())
        if p is None:
            p = m.Property(advisor_id=aid, household_id=h.id, nickname=po.get("nickname") or po.get("address_line1") or po["key"])
            s.add(p)
            h.properties.append(p)
            stats["properties_created"] += 1
        else:
            stats["properties_updated"] += 1
        land = po.get("land_pct")
        if land is None and po.get("depreciable_basis_cents") and po.get("purchase_price_cents"):
            cost = po["purchase_price_cents"] + (po.get("improvements_cents") or 0)
            land = round(1 - po["depreciable_basis_cents"] / cost, 6)
        _set(p, nickname=po.get("nickname"), address_line1=po.get("address_line1"), city=po.get("city"), state=po.get("state"),
             zip=po.get("zip"), property_type=po.get("property_type"), units=po.get("units"),
             purchase_date=_d(po.get("purchase_date")), purchase_price_cents=po.get("purchase_price_cents"),
             placed_in_service_date=_d(po.get("placed_in_service_date")), land_pct=_dec(land),
             improvements_cents=po.get("improvements_cents"), cost_seg_study=po.get("cost_seg_study"),
             current_value_cents=po.get("current_value_cents"), value_source=po.get("value_source"),
             value_as_of=_d(po.get("value_as_of")), status=po.get("status"), property_key=po.get("key"))
        if po.get("avg_stay_days") is not None:
            p.avg_stay_days = po["avg_stay_days"]
        s.flush()
        key_to_id[po["key"]] = p.id
        loans_by_pos = {ln.lien_position: ln for ln in p.loans}
        for lo in po.get("loans", []):
            ln = loans_by_pos.get(lo.get("lien_position", 1))
            if ln is None:
                ln = m.Loan(advisor_id=aid, property_id=p.id, balance_as_of=_d(lo["balance_as_of"]), rate=_dec(lo["rate"]))
                s.add(ln)
                p.loans.append(ln)
            io_months = lo.get("io_months") or 0
            if not io_months and lo.get("io_end_date"):
                end, start = _d(lo["io_end_date"]), _d(lo["balance_as_of"])
                io_months = max(0, (end.year - start.year) * 12 + end.month - start.month)
            _set(ln, lender=lo.get("lender"), loan_type=lo.get("loan_type"), original_cents=lo.get("original_cents"),
                 balance_cents=lo.get("balance_cents"), balance_as_of=_d(lo.get("balance_as_of")), rate=_dec(lo.get("rate")),
                 term_months=lo.get("term_months"), io_months=io_months, arm_reset_date=_d(lo.get("arm_reset_date")),
                 arm_index_margin=_dec(lo.get("arm_index_margin")), monthly_payment_cents=lo.get("monthly_payment_cents"),
                 maturity_date=_d(lo.get("maturity_date")), lien_position=lo.get("lien_position"), is_paid_off=lo.get("is_paid_off"))
            if not lo.get("term_months") and ln.maturity_date and ln.balance_as_of:
                ln.term_months = max(1, (ln.maturity_date.year - ln.balance_as_of.year) * 12 + ln.maturity_date.month - ln.balance_as_of.month)
            stats["loans"] += 1
        rr = {r.tax_year: r for r in p.rent_rolls}
        for ro in po.get("rent_rolls", []):
            r = rr.get(ro["tax_year"]) or m.RentRoll(advisor_id=aid, property_id=p.id, tax_year=ro["tax_year"])
            if r.id is None:
                s.add(r)
                p.rent_rolls.append(r)
            _set(r, gross_rent_cents=ro.get("gross_rent_cents"), other_income_cents=ro.get("other_income_cents"))
            stats["years"] += 1
        ex = {e.tax_year: e for e in p.expense_years}
        for eo in po.get("expense_years", []):
            e = ex.get(eo["tax_year"]) or m.ExpenseYear(advisor_id=aid, property_id=p.id, tax_year=eo["tax_year"])
            if e.id is None:
                s.add(e)
                p.expense_years.append(e)
            _set(e, **{k: eo.get(k) for k in ("taxes_cents", "insurance_cents", "repairs_cents", "mgmt_cents", "utilities_cents",
                                              "hoa_cents", "other_cents", "mortgage_interest_cents", "depreciation_cents")})
        led = {d.tax_year: d for d in p.depreciation_ledger}
        for do in po.get("depreciation_ledger", []):
            d = led.get(do["tax_year"]) or m.DepreciationLedger(advisor_id=aid, property_id=p.id, tax_year=do["tax_year"])
            if d.id is None:
                s.add(d)
                p.depreciation_ledger.append(d)
            _set(d, allowed_cents=do.get("allowed_cents"), allowable_cents=do.get("allowable_cents"), method=do.get("method"),
                 note=do.get("note"))
            stats["ledger"] += 1
    sl = {x.tax_year: x for x in h.suspended_losses}
    for so in payload.get("suspended_losses", []):
        x = sl.get(so["tax_year"]) or m.SuspendedLoss(advisor_id=aid, household_id=h.id, tax_year=so["tax_year"])
        if x.id is None:
            s.add(x)
            h.suspended_losses.append(x)
        x.carryforward_cents = so["carryforward_cents"]
        stats["suspended_losses"] += 1
    s.flush()
    doc_ids = persist_documents(s, h, payload.get("documents", []), payload.get("extracted_fields", []), stats)
    upsert_findings(s, h, payload.get("findings", []), key_to_id, doc_ids, stats)
    s.flush()
    return stats


def persist_documents(s: Session, h: m.Household, docs: list[dict], fields: list[dict], stats: dict) -> dict[str, str]:
    aid = h.advisor_id
    existing_sha = {d.sha256: d for d in h.documents}
    existing_name = {d.filename: d for d in h.documents}
    key_to_doc: dict[str, str] = {}
    for do in docs:
        sha = do.get("sha256") or hashlib.sha256(do.get("filename", "").encode()).hexdigest()
        d = existing_sha.get(sha) or existing_name.get(do.get("filename"))
        if d is None:
            d = m.Document(advisor_id=aid, household_id=h.id, filename=do.get("filename") or do.get("key"), sha256=sha)
            s.add(d)
            h.documents.append(d)
            stats["documents"] += 1
        _set(d, kind=do.get("kind"), tax_year=do.get("tax_year"), page_count=do.get("page_count"),
             status=do.get("status") or "reconciled")
        d.bytes_retained = False
        s.flush()
        key_to_doc[do.get("key") or d.filename] = d.id
        key_to_doc[d.filename] = d.id
    by_doc: dict[str, list[dict]] = {}
    for fo in fields:
        doc_id = key_to_doc.get(fo.get("document_key") or "") or fo.get("document_id")
        if doc_id:
            by_doc.setdefault(doc_id, []).append(fo)
    for doc_id, fos in by_doc.items():
        d = next(x for x in h.documents if x.id == doc_id)
        d.fields.clear()
        s.flush()
        for fo in fos:
            hint = fo.get("entity_hint") or "property"
            d.fields.append(m.ExtractedField(
                advisor_id=aid, document_id=doc_id, entity_hint=hint if hint in ("household", "property") else "property",
                property_key=fo.get("property_key"), field=fo["field"], value=fo.get("value"), unit=fo.get("unit") or "text",
                page=fo.get("page") or 1, bbox=fo.get("bbox") or [0, 0, 0, 0], confidence=fo.get("confidence") or 0,
                extractor=fo.get("extractor") or "rules", raw_text=fo.get("raw_text") or ""))
            stats["extracted_fields"] += 1
    return key_to_doc


def upsert_findings(s: Session, h: m.Household, findings: list[dict], key_to_prop: dict[str, str], key_to_doc: dict[str, str],
                    stats: dict) -> list[m.Finding]:
    aid = h.advisor_id
    existing = {f.key: f for f in h.findings if f.key}
    prop_by_key = {p.property_key: p.id for p in h.properties if p.property_key}
    out = []
    for fo in findings:
        cands = []
        for c in fo.get("candidates", []):
            c = dict(c)
            dk = c.pop("document_key", None)
            c.setdefault("document_id", key_to_doc.get(dk) if dk else c.get("document_id"))
            c.setdefault("page", None)
            cands.append(c)
        pid = key_to_prop.get(fo.get("property_key") or "") or prop_by_key.get(fo.get("property_key") or "") or fo.get("property_id")
        key = fo.get("key")
        f = existing.get(key) if key else None
        if f is None:
            f = m.Finding(advisor_id=aid, household_id=h.id, key=key, kind=fo["kind"])
            s.add(f)
            h.findings.append(f)
            stats["findings_created"] = stats.get("findings_created", 0) + 1
        else:
            stats["findings_updated"] = stats.get("findings_updated", 0) + 1
            if f.status != "open":
                # an advisor's decision is never overwritten by a re-import
                f.candidates = cands
                out.append(f)
                continue
        _set(f, property_id=pid, kind=fo.get("kind"), field=fo.get("field") or "", severity=fo.get("severity"),
             message=fo.get("message"), tax_year=fo.get("tax_year"), status=fo.get("status") or "open",
             resolution=fo.get("resolution"))
        f.candidates = cands
        out.append(f)
    s.flush()
    return out


def apply_resolution(s: Session, f: m.Finding, value: Any) -> str | None:
    """Write the advisor's chosen value back to the underlying row, so the engine runs on the resolved value."""
    if value is None or f.property_id is None:
        return None
    p = s.get(m.Property, f.property_id)
    if p is None or p.advisor_id != f.advisor_id:
        return None
    key = input_key_for_field(f.field)
    year = f.tax_year
    if key in ("gross_rent_cents", "other_income_cents") and year:
        r = next((x for x in p.rent_rolls if x.tax_year == year), None)
        if r is None:
            r = m.RentRoll(advisor_id=p.advisor_id, property_id=p.id, tax_year=year)
            s.add(r)
            p.rent_rolls.append(r)
        setattr(r, key, int(value))
        return f"rent_rolls[{year}].{key}"
    if key and key.endswith("_cents") and key not in ("current_value_cents", "purchase_price_cents") and year:
        e = next((x for x in p.expense_years if x.tax_year == year), None)
        if e is not None and hasattr(e, key):
            setattr(e, key, int(value))
            return f"expense_years[{year}].{key}"
    if key in ("current_value_cents", "purchase_price_cents"):
        setattr(p, key, int(value))
        if key == "current_value_cents":
            p.value_source = "confirmed"
        return f"property.{key}"
    return None


def resolve(s: Session, f: m.Finding, value: Any, note: str, who: str, status: str = "resolved") -> m.Finding:
    applied = apply_resolution(s, f, value) if status == "resolved" else None
    f.status = status
    f.resolution = {"value": value, "who": who, "when": datetime.now(UTC).isoformat(timespec="seconds"), "note": note,
                    "applied_to": applied}
    s.flush()
    return f
