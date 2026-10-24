"""Label -> value extraction for free-form documents (statements, settlement sheets, letters).

A :class:`KV` names a label regex, the field, the value type, and how far right the value may
sit. For each row whose text matches the label, the value is read from the strip between the
label's right edge and the box edge (zonal OCR on scans), or from the row below when the layout
puts the value under its label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from gp_pipeline.extract.forms.base import make_field
from gp_pipeline.extract.layout import (
    clean_numeric,
    group_rows,
    merge_money_tokens,
    parse_date,
    parse_money,
    parse_rate,
)
from gp_pipeline.extract.zones import zone_words
from gp_pipeline.models import ExtractedField, Page, Word


@dataclass
class KV:
    label: str  # regex matched against the row text (case-insensitive)
    field: str
    vtype: str  # money | date | rate | int | text | lien | bool | month_count
    below: bool = False  # value printed on the next line, under the label
    right_edge: float | None = None  # box edge; default = 304 for left-box labels else page edge
    min_x: float | None = None  # explicit value strip start (e.g. a debit/credit column)
    last: bool = False  # take the right-most matching token (credit column) instead of the first


def _row_label_end(row_words: list[Word], label: str) -> tuple[float, float] | None:
    """Return (label_x0, label_x1) for the first run of words whose joined text matches ``label``."""
    rx = re.compile(label, re.I)
    for i in range(len(row_words)):
        acc = ""
        for j in range(i, min(len(row_words), i + 12)):
            acc = (acc + " " + row_words[j].text).strip()
            if rx.match(acc):
                return row_words[i].x0, row_words[j].x1
    return None


def _parse(vtype: str, ws: list[Word]) -> tuple[object | None, list[Word], bool]:
    if vtype == "text":
        txt = " ".join(w.text for w in ws).strip(" :")
        return (txt or None), ws, False
    if vtype == "money":
        cands = merge_money_tokens(ws)
        for w in cands:
            t, corr = clean_numeric(w.text)
            if "$" in t or "." in t or "," in t:
                v = parse_money(t)
                if v is not None:
                    return v, [w], corr
        for w in cands:
            t, corr = clean_numeric(w.text)
            v = parse_money(t)
            if v is not None:
                return v, [w], corr
        return None, [], False
    for w in ws:
        t, corr = clean_numeric(w.text)
        if vtype == "date":
            v = parse_date(t)
        elif vtype == "rate":
            v = parse_rate(t)
        elif vtype == "int":
            v = int(t) if re.fullmatch(r"\d{1,4}", t) else None
        elif vtype == "lien":
            m = re.fullmatch(r"([1-4])(st|nd|rd|th)", re.sub(r"^[il|]", "1", t.lower()))
            v = int(m.group(1)) if m else None
        elif vtype == "bool":
            v = True if re.search(r"PAID", " ".join(x.text for x in ws), re.I) else None
        else:
            v = None
        if v is not None:
            return v, [w], corr
    return None, [], False


def extract_kv(page: Page, doc_key: str, specs: list[KV], entity: str, property_key: str | None,
               address_raw: str | None, prefix_seen: set[str] | None = None) -> list[ExtractedField]:
    out: list[ExtractedField] = []
    rows = group_rows(page.words)
    seen = prefix_seen if prefix_seen is not None else set()
    for spec in specs:
        if spec.field in seen:
            continue
        for ri, r in enumerate(rows):
            hit = _row_label_end(r.words, spec.label)
            if not hit:
                continue
            lx0, lx1 = hit
            edge = spec.right_edge or (304.0 if lx0 < 310 else page.width - 20)
            if spec.below:
                nxt = rows[ri + 1] if ri + 1 < len(rows) else None
                if nxt is None:
                    continue
                cy = nxt.cy
                ws = zone_words(page, lx0 - 3, cy - 6.5, edge, cy + 6.0, psm=7)
            else:
                cy = r.cy
                x0 = spec.min_x if spec.min_x is not None else lx1 + 2
                ws = zone_words(page, x0, cy - 6.5, edge, cy + 6.0, psm=7)
            if page.source == "text" or not ws:
                pool = nxt.words if spec.below else r.words
                ws = [w for w in pool if w.x0 >= (lx0 - 3 if spec.below else (spec.min_x or lx1 + 1)) and w.x1 <= edge + 1]
            if spec.last:
                ws = sorted(ws, key=lambda w: -w.x1)
            v, used, corr = _parse(spec.vtype, ws)
            if v is None:
                continue
            out.append(make_field(page, doc_key, spec.field, v, "cents" if spec.vtype == "money" else
                                  {"date": "date", "rate": "rate", "text": "text", "bool": "bool"}.get(spec.vtype, "int"),
                                  used, entity, property_key, corr, address_raw))
            seen.add(spec.field)
            break
    return out
