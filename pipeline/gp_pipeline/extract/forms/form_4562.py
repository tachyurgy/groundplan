"""Form 4562 (one per rental activity): activity address, Part III MACRS lines 17 and 19h, Part IV line 22."""

from __future__ import annotations

import re

from gp_pipeline.address import key as address_key
from gp_pipeline.extract.forms.base import LineSpec, find_anchors, make_field, pick_money, value_tokens
from gp_pipeline.extract.zones import zone_words
from gp_pipeline.models import ExtractedField, ParsedDocument

R = (497.0, 590.0)
BASIS = (262.0, 352.0)
PIS = (170.0, 245.0)

SPECS = [
    LineSpec("17", "MACRS deductions for assets placed in service in tax years beginning before"),
    LineSpec("19h", "Residential rental property", display="h"),
    LineSpec("22", "Total. Add amounts from line 12, lines 14 through 17"),
]


def extract(doc: ParsedDocument) -> list[ExtractedField]:
    page = doc.pages[0]
    out: list[ExtractedField] = []
    act = find_anchors(page, [LineSpec("act", "Name(s) shown on return Business or activity to which this form")],
                       accept=0.55, label_x_min=0)
    pk = raw = None
    if "act" in act:
        cy = act["act"].row.cy
        ws = zone_words(page, 246.0, cy + 4, 496.0, cy + 15, psm=7)
        text = " ".join(w.text for w in ws)
        text = re.sub(r"^\s*RENTAL\s*[-–—]?\s*", "", text, flags=re.I).strip()
        if text:
            pk, raw = address_key(text), text
            out.append(make_field(page, doc.filename, "form_4562.activity", text, "text", ws, "property", pk,
                                  address_raw=text))
    anchors = find_anchors(page, SPECS)
    ys = [a.row.cy for a in anchors.values()]
    top, bottom = (min(ys) - 9, max(ys) + 9) if ys else (0, 0)
    for ln, fname in (("17", "line17.prior_macrs"), ("22", "line22.total")):
        if ln in anchors:
            v, ws, corr = pick_money(value_tokens(page, R, anchors[ln].row.cy, top, bottom), exclude={ln})
            if v is not None:
                out.append(make_field(page, doc.filename, f"form_4562.{fname}", v, "cents", ws, "property", pk, corr,
                                      raw))
    if "19h" in anchors:
        cy = anchors["19h"].row.cy
        v, ws, corr = pick_money(value_tokens(page, R, cy, top, bottom))
        if v is not None:
            out.append(make_field(page, doc.filename, "form_4562.line19h.deduction", v, "cents", ws, "property", pk,
                                  corr, raw))
            b, bws, bcorr = pick_money(value_tokens(page, BASIS, cy, cy - 7, cy + 7, psm=7))
            if b is not None:
                out.append(make_field(page, doc.filename, "form_4562.line19h.basis", b, "cents", bws, "property", pk,
                                      bcorr, raw))
            dws = zone_words(page, PIS[0], cy - 7, PIS[1], cy + 7, psm=7, whitelist="0123456789/")
            for w in dws:
                m = re.fullmatch(r"(\d{1,2})/(\d{4})", w.text)
                if m:
                    out.append(make_field(page, doc.filename, "form_4562.line19h.placed_in_service",
                                          f"{m.group(2)}-{int(m.group(1)):02d}", "text", [w], "property", pk,
                                          address_raw=raw))
                    break
    return out
