"""Schedule E (Form 1040) Part I: per-property columns A/B/C plus the 23a-26 totals.

Template zones (PDF points on a 612x792 page) mirror the form's three property columns. Every
page of Part I is processed the same way; lines 23a-26 are only read where present (first page).
Arithmetic self-checks (line 20 = sum of 5-19, line 21 = 3 + 4 - 20) lower the confidence of
the fields involved when they fail, which is how OCR digit errors surface downstream.
"""

from __future__ import annotations

import re

from gp_pipeline.address import key as address_key
from gp_pipeline.extract.forms.base import (
    LineSpec,
    find_anchors,
    make_field,
    pick_money,
    value_tokens,
    zone_span,
)
from gp_pipeline.extract.layout import clean_numeric, group_rows
from gp_pipeline.extract.zones import zone_words
from gp_pipeline.models import ExtractedField, Page, ParsedDocument

COLS = {"A": (333.0, 420.0), "B": (418.0, 503.0), "C": (502.0, 590.0)}
TOTAL_ZONES = {"inner": (418.0, 503.0), "outer": (502.0, 590.0)}

PROPERTY_LINES = [
    LineSpec("3", "Rents received", "line3.rents"),
    LineSpec("4", "Royalties received", "line4.royalties"),
    LineSpec("5", "Advertising", "line5.advertising"),
    LineSpec("6", "Auto and travel", "line6.auto_travel"),
    LineSpec("7", "Cleaning and maintenance", "line7.cleaning_maintenance"),
    LineSpec("8", "Commissions", "line8.commissions"),
    LineSpec("9", "Insurance", "line9.insurance"),
    LineSpec("10", "Legal and other professional fees", "line10.legal_professional"),
    LineSpec("11", "Management fees", "line11.management_fees"),
    LineSpec("12", "Mortgage interest paid to banks", "line12.mortgage_interest"),
    LineSpec("13", "Other interest", "line13.other_interest"),
    LineSpec("14", "Repairs", "line14.repairs"),
    LineSpec("15", "Supplies", "line15.supplies"),
    LineSpec("16", "Taxes", "line16.taxes"),
    LineSpec("17", "Utilities", "line17.utilities"),
    LineSpec("18", "Depreciation expense or depletion", "line18.depreciation"),
    LineSpec("19", "Other (list)", "line19.other"),
    LineSpec("20", "Total expenses. Add lines 5 through 19", "line20.total_expenses"),
    LineSpec("21", "Subtract line 20 from line 3", "line21.income_or_loss"),
    LineSpec("22", "Deductible rental real estate loss after limitation", "line22.deductible_loss"),
]
TOTAL_LINES = [
    LineSpec("23a", "Total of all amounts reported on line 3 for all rental properties", "line23a.total_rents",
             "inner"),
    LineSpec("23b", "Total of all amounts reported on line 4 for all royalty properties", "line23b.total_royalties",
             "inner", display="b"),
    LineSpec("23c", "Total of all amounts reported on line 12 for all properties",
             "line23c.total_mortgage_interest", "inner", display="c"),
    LineSpec("23d", "Total of all amounts reported on line 18 for all properties", "line23d.total_depreciation",
             "inner", display="d"),
    LineSpec("23e", "Total of all amounts reported on line 20 for all properties", "line23e.total_expenses",
             "inner", display="e"),
    LineSpec("24", "Income. Add positive amounts shown on line 21", "line24.income", "outer"),
    LineSpec("25", "Losses. Add royalty losses from line 21 and rental real estate losses", "line25.losses",
             "outer"),
    LineSpec("26", "Total rental real estate and royalty income or (loss)", "line26.total", "outer"),
]
HEADER_LINES = [
    LineSpec("1a", "Physical address of each property", None),
    LineSpec("1b", "Type of Property", None),
    LineSpec("tp", "Type of Property:", None, display="-"),
]
EXPENSE_LINES = [str(n) for n in range(5, 20)]


def _addresses(page: Page, y_1a: float, y_1b: float) -> list[tuple[str, list]]:
    """Address rows between the 1a and 1b anchors, top to bottom (= columns A, B, C)."""
    out = []
    band_rows = [r for r in group_rows([w for w in page.words if y_1a + 5 < (w.top + w.bottom) / 2 < y_1b - 4])]
    for r in band_rows:
        ws = [w for w in r.words if w.x0 >= 56]
        if not ws or not any(ch.isdigit() for ch in "".join(w.text for w in ws)):
            continue
        if page.source == "ocr":
            line = zone_words(page, 58.0, r.cy - 7, 590.0, r.cy + 6, psm=7)
            if line:
                ws = line
        text = " ".join(w.text for w in ws)
        out.append((text, ws))
    return out[:3]


def _type_and_days(page: Page, y_1b: float) -> list[dict]:
    """Line 1b (type code) and line 2 (fair rental / personal-use days) for rows A, B, C.

    Single-digit cells are the hardest thing on the page for OCR, so each cell is read on its own
    (one text line, digits only) at the template row offset below the 1b anchor.
    """
    zones = {"type": (92.0, 136.0), "fair": (392.0, 466.0), "personal": (476.0, 538.0)}
    out = []
    for i in range(3):
        cy = y_1b + 32.5 + 13 * i
        rec: dict = {}
        for name, (x0, x1) in zones.items():
            ws = zone_words(page, x0, cy - 6.5, x1, cy + 6.0, psm=7, whitelist="0123456789")
            ws = [w for w in ws if re.fullmatch(r"\d{1,3}", clean_numeric(w.text)[0])]
            if ws:
                w = ws[-1]
                txt, corr = clean_numeric(w.text)
                rec[name] = (int(txt), w, corr)
        out.append(rec)
    return out


def extract(doc: ParsedDocument) -> list[ExtractedField]:
    fields: list[ExtractedField] = []
    for page in doc.pages:
        fields.extend(_extract_page(doc, page))
    return fields


def _extract_page(doc: ParsedDocument, page: Page) -> list[ExtractedField]:
    out: list[ExtractedField] = []
    hdr = find_anchors(page, HEADER_LINES)
    lines = find_anchors(page, PROPERTY_LINES, start_y=hdr["tp"].row.cy if "tp" in hdr else 0.0)
    if not lines:
        return out
    letters = ["A", "B", "C"]
    addrs: list[tuple[str, list]] = []
    if "1a" in hdr and "1b" in hdr:
        addrs = _addresses(page, hdr["1a"].row.cy, hdr["1b"].row.cy)
    col_prop: dict[str, tuple[str, str]] = {}
    for i, (text, ws) in enumerate(addrs):
        L = letters[i]
        pk = address_key(text)
        col_prop[L] = (pk, text)
        out.append(make_field(page, doc.filename, "schedule_e.line1a.address", text, "text", ws, "property", pk,
                              address_raw=text))
    if "1b" in hdr:
        for i, rec in enumerate(_type_and_days(page, hdr["1b"].row.cy)):
            L = letters[i]
            if L not in col_prop:
                continue
            pk, raw = col_prop[L]
            for name, fname in (("type", "schedule_e.line1b.type"), ("fair", "schedule_e.line2.fair_rental_days"),
                                ("personal", "schedule_e.line2.personal_use_days")):
                if name in rec:
                    v, w, corr = rec[name]
                    out.append(make_field(page, doc.filename, fname, v, "int", [w], "property", pk, corr, raw))

    top, bottom = zone_span(lines, [s.line for s in PROPERTY_LINES])
    col_values: dict[str, dict[str, ExtractedField]] = {L: {} for L in letters}
    for L, zone in COLS.items():
        if L not in col_prop:
            continue
        pk, raw = col_prop[L]
        for ln, anc in lines.items():
            toks = value_tokens(page, zone, anc.row.cy, top, bottom)
            v, ws, corr = pick_money(toks, exclude={ln})
            if v is None:
                continue
            f = make_field(page, doc.filename, f"schedule_e.{anc.spec.field}", v, "cents", ws, "property", pk, corr,
                           raw)
            col_values[L][ln] = f
            out.append(f)
    _arith_checks(col_values)

    totals = find_anchors(page, TOTAL_LINES, start_y=lines[max(lines, key=lambda k: lines[k].row.cy)].row.cy)
    if totals:
        t_top, t_bottom = zone_span(totals, [s.line for s in TOTAL_LINES])
        for ln, anc in totals.items():
            zone = TOTAL_ZONES[anc.spec.zone or "outer"]
            toks = value_tokens(page, zone, anc.row.cy, t_top, t_bottom)
            v, ws, corr = pick_money(toks, exclude={ln, anc.spec.display or ""})
            if v is None:
                continue
            out.append(make_field(page, doc.filename, f"schedule_e.{anc.spec.field}", v, "cents", ws, "household",
                                  None, corr))
    return out


def _arith_checks(col_values: dict[str, dict[str, ExtractedField]]) -> None:
    for vals in col_values.values():
        if not vals:
            continue
        exp = sum(vals[k].value for k in EXPENSE_LINES if k in vals)
        if "20" in vals and vals["20"].value != exp:
            for k in [*EXPENSE_LINES, "20"]:
                if k in vals:
                    vals[k].confidence = round(vals[k].confidence * 0.6, 3)
        if "21" in vals and "3" in vals and "20" in vals:
            if vals["3"].value + (vals["4"].value if "4" in vals else 0) - vals["20"].value != vals["21"].value:
                for k in ("3", "20", "21"):
                    vals[k].confidence = round(vals[k].confidence * 0.6, 3)
