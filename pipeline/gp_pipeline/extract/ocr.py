"""OCR fallback: rasterize with pdftoppm, deskew, run tesseract, return words in PDF points.

* Rasterization uses pdfium (via pdfplumber) in memory at ``OCR_DPI``; the bytes never touch disk.
* Skew is estimated with a projection-profile search (the angle that makes text rows sharpest)
  and removed before OCR; bboxes are reported in the deskewed page's coordinate frame.
* Tesseract runs with ``--psm 11`` (sparse text): form pages are columns of short tokens, not
  paragraphs, and block segmentation (psm 3/6) merges neighbouring columns.
"""

from __future__ import annotations

import io
import shutil

import numpy as np
import pdfplumber
import pytesseract
from PIL import Image

from gp_pipeline.models import Page, Word

TESSERACT = shutil.which("tesseract") or "/opt/homebrew/bin/tesseract"
pytesseract.pytesseract.tesseract_cmd = TESSERACT

OCR_DPI = 300
TESS_CONFIG = "--oem 1 --psm 11 -c preserve_interword_spaces=1"


def rasterize_bytes(data: bytes, dpi: int = OCR_DPI) -> list[Image.Image]:
    """Render every page of an in-memory PDF to grayscale images (pdfium via pdfplumber; no temp files)."""
    images = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pg in pdf.pages:
            images.append(pg.to_image(resolution=dpi).original.convert("L"))
    return images


def estimate_skew(img: Image.Image, max_deg: float = 3.0, step: float = 0.1) -> float:
    """Return the rotation (degrees, PIL convention) that best straightens text rows."""
    small = img.copy()
    small.thumbnail((900, 900))
    arr = np.asarray(small, dtype=np.uint8)
    ink = (arr < 160).astype(np.uint8) * 255
    base = Image.fromarray(ink)
    best, best_score = 0.0, -1.0
    a = -max_deg
    while a <= max_deg + 1e-9:
        rot = np.asarray(base.rotate(a, resample=Image.NEAREST, fillcolor=0), dtype=np.float32)
        prof = rot.sum(axis=1)
        score = float(np.square(np.diff(prof)).sum())
        if score > best_score:
            best, best_score = a, score
        a = round(a + step, 4)
    return best


def remove_rules(img: Image.Image, hmin: int = 60, vmin: int = 80, dark_below: int = 200) -> Image.Image:
    """Whiten long horizontal/vertical dark runs (form rules and box edges) so they stop
    fragmenting the glyphs that sit on them. Runs shorter than ``hmin``/``vmin`` px are kept:
    at 300 dpi no glyph stroke in these forms is that long."""
    a = np.asarray(img).copy()
    dark = a < dark_below

    def runs(m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        d = np.diff(np.concatenate([[0], m.astype(np.int8), [0]]))
        return np.flatnonzero(d == 1), np.flatnonzero(d == -1)

    for y in np.flatnonzero(dark.sum(axis=1) >= hmin):
        s0, e0 = runs(dark[y])
        for x0, x1 in zip(s0, e0, strict=True):
            if x1 - x0 >= hmin:
                a[y, x0:x1] = 255
    for x in np.flatnonzero(dark.sum(axis=0) >= vmin):
        s0, e0 = runs(dark[:, x])
        for y0, y1 in zip(s0, e0, strict=True):
            if y1 - y0 >= vmin:
                a[y0:y1, x] = 255
    return Image.fromarray(a)


def _data_words(d: dict, dx: int = 0, dy: int = 0) -> list[dict]:
    out = []
    for i, txt in enumerate(d["text"]):
        t = (txt or "").strip()
        conf = float(d["conf"][i])
        if not t or conf < 0:
            continue
        out.append({"text": t, "x0": d["left"][i] + dx, "y0": d["top"][i] + dy,
                    "x1": d["left"][i] + d["width"][i] + dx, "y1": d["top"][i] + d["height"][i] + dy,
                    "conf": conf / 100.0})
    return out


def _refine_numbers(img: Image.Image, words: list[dict], dpi: int) -> list[dict]:
    """Second pass over numeric zones.

    Sparse-text OCR tends to drop a thousands group ("1,960" -> "960") or split it. For every
    cluster of digit-bearing words on a line, re-OCR a slightly widened crop as a single text line
    with a numeric whitelist and keep the tokens that touch the original cluster.
    """
    px = dpi / 72.0
    digit = [w for w in words if any(ch.isdigit() for ch in w["text"])]
    other = [w for w in words if w not in digit]
    digit.sort(key=lambda w: ((w["y0"] + w["y1"]) / 2, w["x0"]))
    clusters: list[list[dict]] = []
    for w in digit:
        if clusters:
            c = clusters[-1][-1]
            same_line = abs((w["y0"] + w["y1"]) / 2 - (c["y0"] + c["y1"]) / 2) < 6 * px
            if same_line and w["x0"] - c["x1"] < 9 * px:
                clusters[-1].append(w)
                continue
        clusters.append([w])
    refined: list[dict] = []
    cfg = "--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789,.()$-/%"
    for cl in clusters:
        x0 = min(w["x0"] for w in cl)
        x1 = max(w["x1"] for w in cl)
        y0 = min(w["y0"] for w in cl)
        y1 = max(w["y1"] for w in cl)
        bx0, by0 = max(0, int(x0 - 12 * px)), max(0, int(y0 - 3 * px))
        bx1, by1 = min(img.width, int(x1 + 3 * px)), min(img.height, int(y1 + 3 * px))
        crop = img.crop((bx0, by0, bx1, by1))
        d = pytesseract.image_to_data(crop, config=cfg, output_type=pytesseract.Output.DICT)
        new = [w for w in _data_words(d, bx0, by0) if w["x1"] >= x0 - 7 * px and any(ch.isdigit() for ch in w["text"])]
        old_digits = sum(ch.isdigit() for w in cl for ch in w["text"])
        new_digits = sum(ch.isdigit() for w in new for ch in w["text"])
        if new and new_digits >= old_digits:
            for w in new:
                w["refined"] = True
            refined.extend(new)
        else:
            refined.extend(cl)
    return other + refined


def ocr_image(img: Image.Image, page_no: int, page_w_pt: float, page_h_pt: float, dpi: int = OCR_DPI,
              deskew: bool = True, refine: bool = False) -> Page:
    angle = estimate_skew(img) if deskew else 0.0
    if abs(angle) >= 0.05:
        img = img.rotate(angle, resample=Image.BICUBIC, fillcolor=255)
    img = remove_rules(img)
    d = pytesseract.image_to_data(img, config=TESS_CONFIG, output_type=pytesseract.Output.DICT)
    raw = _data_words(d)
    if refine:
        raw = _refine_numbers(img, raw, dpi)
    k = 72.0 / dpi
    words = [Word(text=w["text"], x0=w["x0"] * k, top=w["y0"] * k, x1=w["x1"] * k, bottom=w["y1"] * k,
                  conf=w["conf"]) for w in raw]
    page = Page(number=page_no, width=page_w_pt, height=page_h_pt, words=words, source="ocr", skew_deg=angle)
    page._image = img
    page._dpi = dpi
    return page


def ocr_pages(data: bytes, dpi: int = OCR_DPI) -> list[Page]:
    pages = []
    for i, img in enumerate(rasterize_bytes(data, dpi), start=1):
        w_pt, h_pt = img.width * 72.0 / dpi, img.height * 72.0 / dpi
        pages.append(ocr_image(img, i, w_pt, h_pt, dpi))
    return pages
