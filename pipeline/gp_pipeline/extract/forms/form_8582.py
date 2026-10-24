"""Form 8582: Parts I-III lines and the Worksheet 5 allocation of unallowed (suspended) losses."""

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
from gp_pipeline.extract.layout import group_rows
from gp_pipeline.models import ExtractedField, ParsedDocument

ZONES = {"M": (397.0, 482.0), "R": (497.0, 590.0)}
SPECS = [
    LineSpec("1a", "Activities with net income (enter the amount from Worksheet 1", "line1a.net_income", "M"),
    LineSpec("1b", "Activities with net loss (enter the amount from Worksheet 1", "line1b.net_loss", "M", "b"),
    LineSpec("1c", "Prior years' unallowed losses (enter the amount from Worksheet 1", "line1c.prior_unallowed",
             "M", "c"),
    LineSpec("1d", "Combine lines 1a, 1b, and 1c", "line1d.combined", "R", "d"),
    LineSpec("2a", "Activities with net income (enter the amount from Worksheet 3", None, "M"),
    LineSpec("2b", "Activities with net loss (enter the amount from Worksheet 3", None, "M", "b"),
    LineSpec("2c", "Prior years' unallowed losses (enter the amount from Worksheet 3", None, "M", "c"),
    LineSpec("2d", "Combine lines 2a, 2b, and 2c", None, "R", "d"),
    LineSpec("3", "Combine lines 1d and 2d", "line3.combined", "R"),
    LineSpec("4", "Enter the smaller of the loss on line 1d or the loss on line 3", "line4.loss", "R"),
    LineSpec("5", "Enter $150,000. If married filing separately", "line5.threshold", "M"),
    LineSpec("6", "Enter modified adjusted gross income", "line6.magi", "M"),
    LineSpec("7", "Subtract line 6 from line 5", "line7.excess", "M"),
    LineSpec("8", "Multiply line 7 by 50%", "line8.allowance", "R"),
    LineSpec("9", "Enter the smaller of line 4 or line 8", "line9.special_allowance", "R"),
    LineSpec("10", "Add the income, if any, on lines 1a and 2a", "line10.passive_income", "R"),
    LineSpec("11", "Total losses allowed from all passive activities", "line11.total_allowed", "R"),
]


def extract(doc: ParsedDocument) -> list[ExtractedField]:
    out: list[ExtractedField] = []
    page = doc.pages[0]
    anchors = find_anchors(page, SPECS)
    spans = {z: zone_span(anchors, [s.line for s in SPECS if s.zone == z]) for z in ZONES}
    for ln, anc in anchors.items():
        if not anc.spec.field:
            continue
        top, bottom = spans[anc.spec.zone]
        v, ws, corr = pick_money(value_tokens(page, ZONES[anc.spec.zone], anc.row.cy, top, bottom),
                                 exclude={ln, anc.spec.display or ln})
        if v is not None:
            out.append(make_field(page, doc.filename, f"form_8582.{anc.spec.field}", v, "cents", ws, corrected=corr))
    if len(doc.pages) > 1:
        out += _worksheet5(doc)
    return out


def _worksheet5(doc: ParsedDocument) -> list[ExtractedField]:
    page = doc.pages[1]
    ws5 = find_anchors(page, [LineSpec("ws5", "Worksheet 5 - Allocation of Unallowed Losses")], accept=0.6)
    out: list[ExtractedField] = []
    if "ws5" not in ws5:
        return out
    y0 = ws5["ws5"].row.cy
    rows = [r for r in group_rows(page.words) if r.cy > y0 + 12]
    if not rows:
        return out
    top, bottom = rows[0].cy - 8, rows[-1].cy + 8
    for r in rows:
        text = r.text()
        if re.match(r"^\W*Total\b", text) and "Enter" not in text:
            v, ws, corr = pick_money(value_tokens(page, ZONES["R"], r.cy, top, bottom))
            if v is not None:
                out.append(make_field(page, doc.filename, "form_8582.unallowed_loss_total", v, "cents", ws,
                                      corrected=corr))
            break
        if "Schedule" in text and "Rental" in text:
            name_ws = [w for w in r.words if w.x1 < 256]
            name = " ".join(w.text for w in name_ws)
            name = re.sub(r"^\s*Rental\s*[-–—]?\s*", "", name, flags=re.I)
            v, ws, corr = pick_money(value_tokens(page, ZONES["R"], r.cy, top, bottom))
            if v is not None and name:
                out.append(make_field(page, doc.filename, "form_8582.ws5.unallowed_loss", v, "cents", ws, "property",
                                      address_key(name), corr, name))
    return out
