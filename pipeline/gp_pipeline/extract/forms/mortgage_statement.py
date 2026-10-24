"""Mortgage / HELOC statements and paid-in-full letters (one loan per document)."""

from __future__ import annotations

from gp_pipeline.address import key as address_key
from gp_pipeline.extract.forms.base import make_field
from gp_pipeline.extract.forms.kv import KV, extract_kv
from gp_pipeline.extract.layout import group_rows
from gp_pipeline.models import ExtractedField, ParsedDocument

SPECS = [
    KV(r"Statement Date", "mortgage.statement_date", "date"),
    KV(r"Loan Number", "mortgage.loan_number", "text"),
    KV(r"Original Principal Balance", "mortgage.original_amount", "money"),
    KV(r"Credit Limit", "mortgage.credit_limit", "money"),
    KV(r"Origination Date", "mortgage.origination_date", "date"),
    KV(r"Outstanding Principal Balance", "mortgage.principal_balance", "money"),
    KV(r"(Interest Rate|Annual Percentage Rate)", "mortgage.interest_rate", "rate"),
    KV(r"Loan Type", "mortgage.loan_type_text", "text"),
    KV(r"Lien Position", "mortgage.lien_position", "lien"),
    KV(r"Original Term", "mortgage.term_months", "int"),
    KV(r"Maturity Date", "mortgage.maturity_date", "date"),
    KV(r"Next Rate Change Date", "mortgage.next_rate_change_date", "date"),
    KV(r"Index\s*/\s*Margin", "mortgage.index_margin", "rate", last=True),
    KV(r"(Interest-Only Period|Draw Period.*) Ends", "mortgage.io_period_end", "date"),
    KV(r"Payoff Date", "mortgage.payoff_date", "date"),
    KV(r"Loan Status", "mortgage.paid_in_full", "bool"),
    KV(r"(Regular Monthly Payment|Minimum Payment Due)", "mortgage.monthly_payment", "money"),
    KV(r"Principal Paid Year-to-Date", "mortgage.principal_paid_ytd", "money"),
    KV(r"Interest Paid Year-to-Date", "mortgage.interest_paid_ytd", "money"),
]


def extract(doc: ParsedDocument) -> list[ExtractedField]:
    page = doc.pages[0]
    out: list[ExtractedField] = []
    addr = extract_kv(page, doc.filename, [KV(r"Property Address", "mortgage.property_address", "text", below=True,
                                              right_edge=page.width - 20)], "loan", None, None)
    pk = raw = None
    if addr:
        raw = addr[0].value
        pk = address_key(raw)
        addr[0].property_key, addr[0].address_raw = pk, raw
        out += addr
    rows = group_rows(page.words)
    if rows:
        top = [w for w in rows[0].words if w.x0 < 330]
        if top:
            out.append(make_field(page, doc.filename, "mortgage.lender", " ".join(w.text for w in top), "text", top,
                                  "loan", pk, address_raw=raw))
    out += extract_kv(page, doc.filename, SPECS, "loan", pk, raw)
    # the index/margin row holds the margin as "+ 2.75%"; a rate parse picks the last % token
    return out
