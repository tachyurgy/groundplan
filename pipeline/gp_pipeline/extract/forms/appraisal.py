"""Appraisal summary letter: subject address, effective date, opinion of market value."""

from __future__ import annotations

from gp_pipeline.address import key as address_key
from gp_pipeline.extract.forms.kv import KV, extract_kv
from gp_pipeline.models import ExtractedField, ParsedDocument

SPECS = [
    KV(r"Effective Date of Appraisal", "appraisal.effective_date", "date", right_edge=590.0),
    KV(r"Opinion of Market Value", "appraisal.market_value", "money", right_edge=590.0),
]


def extract(doc: ParsedDocument) -> list[ExtractedField]:
    page = doc.pages[0]
    out = extract_kv(page, doc.filename, [KV(r"Subject Property:", "appraisal.property_address", "text",
                                             right_edge=590.0)], "property", None, None)
    pk = raw = None
    if out:
        raw = out[0].value
        pk = address_key(raw)
        out[0].property_key, out[0].address_raw = pk, raw
    out += extract_kv(page, doc.filename, SPECS, "property", pk, raw)
    return out
