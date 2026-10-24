"""Form-type and tax-year classification from page text (text layer or OCR).

Ordered anchor rules: the first rule whose required anchors all appear wins. Schedule E is tested
before Form 1040 because its header also says "(Form 1040)". Confidence is the fraction of the
rule's supporting anchors found, so a noisy OCR page that only matches the minimum scores lower.
"""

from __future__ import annotations

import re

from gp_pipeline.models import DocumentKind, Page

RULES: list[tuple[DocumentKind, list[str], list[str]]] = [
    # kind, required (all), supporting (any count)
    ("schedule_e", [r"supplemental\s+income", r"schedule\s*e"], [r"rental\s+real\s+estate", r"properties",
                                                                   r"fair\s+rental"]),
    ("form_8582", [r"passive\s+activity\s+loss"], [r"form\s*8582", r"special\s+allowance", r"worksheet"]),
    ("form_4562", [r"depreciation\s+and\s+amortization"], [r"form\s*4562", r"macrs", r"recovery\s+period"]),
    ("form_1040", [r"individual\s+income\s+tax\s+return"], [r"form\s*1040", r"filing\s+status",
                                                              r"adjusted\s+gross\s+income"]),
    ("closing_statement", [r"settlement\s+statement"], [r"contract\s+sales\s+price", r"closing\s+costs",
                                                         r"settlement\s+date"]),
    ("appraisal", [r"apprais"], [r"market\s+value", r"effective\s+date", r"uspap"]),
    ("mortgage_statement", [r"loan\s+number"], [r"principal\s+balance", r"mortgage", r"line\s+of\s+credit",
                                                r"paid.in.full", r"lien\s+position"]),
]

YEAR_RE = re.compile(r"\b(20[12]\d)\b")


def classify(pages: list[Page]) -> tuple[DocumentKind, int | None, float]:
    if not pages:
        return "other", None, 0.0
    text = " ".join(w.text for w in pages[0].words)
    low = text.lower()
    for kind, req, sup in RULES:
        if all(re.search(r, low) for r in req):
            found = sum(bool(re.search(r, low)) for r in sup)
            conf = round(0.6 + 0.4 * found / max(1, len(sup)), 3)
            return kind, tax_year(kind, pages), conf
    return "other", tax_year("other", pages), 0.2


def tax_year(kind: DocumentKind, pages: list[Page]) -> int | None:
    p = pages[0]
    if kind in ("schedule_e", "form_1040", "form_4562", "form_8582"):
        # the big year printed in the header (largest token that is a year, top 12% of the page)
        cands = [w for w in p.words if w.top < p.height * 0.12 and YEAR_RE.fullmatch(w.text.strip())]
        if cands:
            big = max(cands, key=lambda w: w.bottom - w.top)
            return int(big.text)
    text = " ".join(w.text for w in p.words)
    if kind == "mortgage_statement":
        m = re.search(r"Year-to-Date\s*\((20\d\d)\)", text) or re.search(r"as of \d\d/\d\d/(20\d\d)", text)
        if m:
            return int(m.group(1))
    if kind == "closing_statement":
        m = re.search(r"Settlement Date:?\s*\d\d/\d\d/(20\d\d)", text)
        if m:
            return int(m.group(1))
    if kind == "appraisal":
        m = re.search(r"Effective Date of Appraisal:?\s*\d\d/\d\d/(20\d\d)", text)
        if m:
            return int(m.group(1))
    years = [int(y) for y in YEAR_RE.findall(text)]
    return max(set(years), key=years.count) if years else None
