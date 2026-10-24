"""The one entry point both API backends use (in-process or through the ``gp-pipeline`` HTTP service).

``process_document(data, filename, context) -> dict`` returns exactly the shape of SPEC §3
``POST /households/{id}/documents`` minus database ids, plus ``reconciled`` (a single-document ReconciledHousehold the
backend can upsert with its import-reconciled logic)::

    {"document": DocumentOut, "extracted_fields": [ExtractedField], "findings": [Finding],
     "properties_touched": [property_key], "reconciled": ReconciledHousehold}

``context`` (all optional): ``property_keys`` (the household's existing normalized addresses: a printed address that
matches one at >= 0.85 is filed under that key, so a new statement lands on the existing property), ``state``,
``name``, ``tax_year_latest``. The bytes are parsed in memory and dropped; nothing is written anywhere.
"""

from __future__ import annotations

from typing import Any

from gp_pipeline.address import normalize, similarity
from gp_pipeline.resolve import THRESHOLD
from gp_pipeline.run import extract_bytes, run_parsed

# household facts a single document cannot establish; never sent, so an upload cannot reset them
NOT_FROM_ONE_DOCUMENT = ("active_participation", "re_professional", "goal", "notes", "name")


def _map_to_existing(fields, existing: list[str]) -> None:
    if not existing:
        return
    parsed = [(k, normalize(k)) for k in existing if k]
    cache: dict[str, str] = {}
    for f in fields:
        if not f.property_key:
            continue
        if f.property_key not in cache:
            mine = normalize(f.address_raw or f.property_key)
            best = max(((similarity(mine, p), k) for k, p in parsed), default=(0.0, None))
            cache[f.property_key] = best[1] if best[0] >= THRESHOLD else f.property_key
        f.property_key = cache[f.property_key]


def _strip_unobserved(po: dict) -> None:
    """Drop PropertyOut fields one document did not actually show (model defaults), so the importer cannot use them
    to overwrite what the household already knows (a statement does not know the property type, a return does not
    know the market value, nothing here knows about capital improvements or a cost-seg study)."""
    for k in [k for k, v in po.items() if v is None]:
        po.pop(k)
    if not po.get("years_seen"):
        po.pop("property_type", None)
        po.pop("units", None)
    if "current_value_cents" not in po:
        po.pop("value_source", None)
    for k in ("improvements_cents", "cost_seg_study", "status"):
        po.pop(k, None)


def process_document(data: bytes, filename: str, context: dict | None = None) -> dict[str, Any]:
    ctx = context or {}
    doc, fields, extra = extract_bytes(data, filename)
    del data
    rec = run_parsed([doc], fields, extra, household_hint={"state": ctx.get("state")})
    _map_to_existing(rec.extracted_fields, ctx.get("property_keys") or [])
    for p in rec.properties:  # keep the reconciled view consistent with the remapped field keys
        mapped = next((f.property_key for f in rec.extracted_fields
                       if f.address_raw and f.address_raw in p.address_variants), p.key)
        if mapped != p.key:
            for fd in rec.findings:
                if fd.property_key == p.key:
                    fd.property_key = mapped
            p.key = mapped
    out = rec.model_dump(mode="json")
    out["household"] = {k: v for k, v in out["household"].items() if v is not None and k not in NOT_FROM_ONE_DOCUMENT}
    out["household"]["name"] = ""  # the importer only sets a name on an unnamed household
    ty, known = out["household"].get("tax_year_latest"), ctx.get("tax_year_latest")
    if ty is not None and (doc.kind != "form_1040" or (known is not None and ty < known)):
        out["household"].pop("tax_year_latest")  # an older return must not roll the household back a year
    for po in out["properties"]:
        _strip_unobserved(po)
    document = out["documents"][0] | {"status": "extracted"}
    return {
        "document": document,
        "extracted_fields": out["extracted_fields"],
        "findings": out["findings"],
        "properties_touched": sorted({f["property_key"] for f in out["extracted_fields"] if f.get("property_key")}),
        "reconciled": out,
    }
