"""Anchored-line extraction shared by the IRS form extractors.

A form is described as an ordered list of :class:`LineSpec` (line id, the label phrase that
starts the line, the field to emit, and the value zone). For each page we

1. group words into rows and find each line's anchor row: the label phrase (fuzzy, so OCR noise
   is tolerated) plus a bonus when the left-margin line number matches; anchors must appear in
   form order, which disambiguates repeated phrases like "Taxable amount";
2. read the value zone (a vertical strip of the template) with :func:`zone_words` and take the
   money token whose vertical centre is closest to the anchor row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from gp_pipeline.extract.layout import Row, bbox_of, clean_numeric, conf_of, group_rows, merge_money_tokens, parse_money
from gp_pipeline.extract.zones import zone_words
from gp_pipeline.models import ExtractedField, Page, Word

LABEL_X_MIN = 55.0
NUM_X_MAX = 60.0
TEXT_BASE_CONF = 0.97
OCR_BASE_CONF = 0.92


@dataclass
class LineSpec:
    line: str  # canonical id, e.g. "23b"
    phrase: str
    field: str | None = None
    zone: str | None = None
    display: str | None = None  # what is printed in the margin ("b" for 23b)


@dataclass
class Anchor:
    spec: LineSpec
    row: Row
    score: float


def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9$%]+", " ", s.lower())).strip()


def label_text(row: Row) -> str:
    return " ".join(w.text for w in row.words if w.x0 >= LABEL_X_MIN - 3)


def margin_token(row: Row) -> str:
    for w in row.words:
        if w.x1 <= NUM_X_MAX + 4:
            return w.text.strip(".:;,'‘`|").lower()
    return ""


def phrase_score(phrase: str, text: str) -> float:
    p, t = norm_text(phrase), norm_text(text)
    if not p or not t:
        return 0.0
    best = SequenceMatcher(None, p, t[: len(p)]).ratio()
    # allow a stray leading token (OCR'd checkbox, quote mark)
    tw = t.split()
    if len(tw) > 1:
        t2 = " ".join(tw[1:])
        best = max(best, SequenceMatcher(None, p, t2[: len(p)]).ratio() - 0.03)
    return best


def find_anchors(page: Page, specs: list[LineSpec], start_y: float = 0.0, accept: float = 0.72) -> dict[str, Anchor]:
    rows = [r for r in group_rows(page.words) if r.cy >= start_y]
    found: dict[str, Anchor] = {}
    i0 = 0
    for spec in specs:
        disp = (spec.display or spec.line).lower()
        best: tuple[float, int] | None = None
        for i in range(i0, min(len(rows), i0 + 14)):
            r = rows[i]
            s = phrase_score(spec.phrase, label_text(r))
            if margin_token(r) == disp:
                s += 0.12
            if best is None or s > best[0] + 1e-9:
                best = (s, i)
            if s >= 0.93:
                break
        if best and best[0] >= accept:
            found[spec.line] = Anchor(spec, rows[best[1]], round(min(best[0], 1.0), 3))
            i0 = best[1] + 1
    return found


def value_tokens(page: Page, zone: tuple[float, float], cy: float, top: float, bottom: float,
                 tol: float = 5.0, psm: int = 4) -> list[Word]:
    ws = zone_words(page, zone[0], top, zone[1], bottom, psm=psm)
    near = [w for w in ws if abs((w.top + w.bottom) / 2 - cy) <= tol]
    return merge_money_tokens(near)


def pick_money(tokens: list[Word], exclude: set[str] | None = None) -> tuple[int | None, list[Word], bool]:
    """Rightmost token that parses as money. Returns (cents, words used, corrected?)."""
    exclude = exclude or set()
    for w in sorted(tokens, key=lambda w: -w.x1):
        if w.text.lower() in exclude:
            continue
        txt, corrected = clean_numeric(w.text)
        v = parse_money(txt)
        if v is not None:
            return v, [w], corrected
    return None, [], False


def make_field(page: Page, doc_key: str, field: str, value, unit: str, words: list[Word], entity: str = "household",
               property_key: str | None = None, corrected: bool = False, address_raw: str | None = None,
               raw_text: str | None = None) -> ExtractedField:
    base = TEXT_BASE_CONF if page.source == "text" else OCR_BASE_CONF
    return ExtractedField(
        document_key=doc_key,
        entity_hint=entity,
        property_key=property_key,
        address_raw=address_raw,
        field=field,
        value=value,
        unit=unit,
        page=page.number,
        bbox=[round(v, 1) for v in bbox_of(words)] if words else [0.0, 0.0, 0.0, 0.0],
        confidence=conf_of(words, base, corrected) if words else 0.0,
        extractor="rules" if page.source == "text" else "ocr",
        raw_text=raw_text if raw_text is not None else " ".join(w.text for w in words),
    )


def zone_span(anchors: dict[str, Anchor], lines: list[str], pad: float = 9.0) -> tuple[float, float]:
    ys = [anchors[ln].row.cy for ln in lines if ln in anchors]
    if not ys:
        return 0.0, 0.0
    return min(ys) - pad, max(ys) + pad


def is_checked(page: Page, x0: float, top: float, x1: float, bottom: float) -> bool:
    """Checkbox state: an 'X' word inside the box (text layer) or ink density (raster)."""
    if page.source == "text" or page._image is None:
        return any(w.text.upper() in ("X", "[X]") and w.x0 >= x0 - 1 and w.x1 <= x1 + 1
                   and (w.top + w.bottom) / 2 >= top and (w.top + w.bottom) / 2 <= bottom for w in page.words)
    import numpy as np

    k = page._dpi / 72.0
    crop = page._image.crop((int((x0 + 1.5) * k), int((top + 1.5) * k), int((x1 - 1.5) * k), int((bottom - 1.5) * k)))
    a = np.asarray(crop)
    return a.size > 0 and float((a < 128).mean()) > 0.12
