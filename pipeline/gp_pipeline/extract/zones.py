"""Zonal reads: "give me the words inside this rectangle of this page".

For a text-layer page this is a filter over pdfplumber words. For an OCR page it re-runs
tesseract on just that crop of the deskewed raster with a page-segmentation mode suited to the
zone (``psm 4`` = a single column of variable-size text, ``psm 7`` = one text line). Full-page
sparse OCR finds the anchors (line numbers, labels); zonal OCR reads the values. On the
synthetic scans this lifts value recall substantially because full-page sparse mode drops the
leading "1," of right-aligned monospace numbers.
"""

from __future__ import annotations

import re

import pytesseract

from gp_pipeline.models import Page, Word

JUNK = re.compile(r"^[|_\-—–=~.:;'‘’\"`°«»]+$")
STRIP = "|_—–~'‘’\"`°«»"


def clean_token(t: str) -> str:
    t = t.strip().strip(STRIP)
    t = t.rstrip(".,;:") if re.search(r"\d", t) and not t.endswith(")") else t
    return t


def zone_words(page: Page, x0: float, top: float, x1: float, bottom: float, psm: int = 4,
               whitelist: str | None = None) -> list[Word]:
    if page.source == "text" or page._image is None:
        return sorted(
            [w for w in page.words if w.x0 >= x0 - 0.5 and w.x1 <= x1 + 0.5
             and (w.top + w.bottom) / 2 >= top and (w.top + w.bottom) / 2 <= bottom],
            key=lambda w: (w.top, w.x0),
        )
    key = (round(x0, 1), round(top, 1), round(x1, 1), round(bottom, 1), psm, whitelist)
    if key in page._zone_cache:
        return page._zone_cache[key]
    k = page._dpi / 72.0
    img = page._image
    bx0, by0 = max(0, int(x0 * k)), max(0, int(top * k))
    bx1, by1 = min(img.width, int(x1 * k)), min(img.height, int(bottom * k))
    crop = img.crop((bx0, by0, bx1, by1))
    cfg = f"--oem 1 --psm {psm}" + (f" -c tessedit_char_whitelist={whitelist}" if whitelist else "")
    d = pytesseract.image_to_data(crop, config=cfg, output_type=pytesseract.Output.DICT)
    out: list[Word] = []
    for i, txt in enumerate(d["text"]):
        t = clean_token(txt or "")
        conf = float(d["conf"][i])
        if not t or conf < 0 or JUNK.match(t):
            continue
        out.append(Word(text=t, x0=(d["left"][i] + bx0) / k, top=(d["top"][i] + by0) / k,
                        x1=(d["left"][i] + d["width"][i] + bx0) / k,
                        bottom=(d["top"][i] + d["height"][i] + by0) / k, conf=conf / 100.0))
    page._zone_cache[key] = out
    return out
