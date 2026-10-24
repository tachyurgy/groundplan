"""ALTA settlement statement (buyer side): price, closing costs, loan, settlement date, and
whether a land/improvement allocation is present at all (it usually is not)."""

from __future__ import annotations

import re

from gp_pipeline.address import key as address_key
from gp_pipeline.extract.forms.base import make_field
from gp_pipeline.extract.forms.kv import KV, extract_kv
from gp_pipeline.models import ExtractedField, ParsedDocument

DEBIT = (430.0, 504.0)
CREDIT = (506.0, 590.0)

SPECS = [
    KV(r"Settlement Date", "closing.settlement_date", "date", right_edge=590.0),
    KV(r"Contract Sales Price", "closing.contract_sales_price", "money", min_x=DEBIT[0], right_edge=DEBIT[1]),
    KV(r"Assumption of Existing Loan|New Loan Amount|Loan Amount", "closing.loan_amount", "money",
       min_x=CREDIT[0], right_edge=CREDIT[1]),
    KV(r"Total Closing Costs", "closing.total_closing_costs", "money", min_x=DEBIT[0], right_edge=DEBIT[1]),
]


def extract(doc: ParsedDocument) -> list[ExtractedField]:
    page = doc.pages[0]
    out: list[ExtractedField] = []
    addr = extract_kv(page, doc.filename, [KV(r"^Property:", "closing.property_address", "text",
                                              right_edge=590.0)], "property", None, None)
    pk = raw = None
    if addr:
        raw = addr[0].value
        pk = address_key(raw)
        addr[0].property_key, addr[0].address_raw = pk, raw
        out += addr
    out += extract_kv(page, doc.filename, SPECS, "property", pk, raw)
    text = " ".join(w.text for p in doc.pages for w in p.words)
    has_alloc = bool(re.search(r"\bland\b.{0,40}(allocation|improvement|building)|allocation of (the )?purchase price",
                               text, re.I))
    out.append(make_field(page, doc.filename, "closing.land_allocation_present", has_alloc, "bool", [], "property",
                          pk, address_raw=raw, raw_text="(document-level check)"))
    out[-1].confidence = 0.9
    return out
