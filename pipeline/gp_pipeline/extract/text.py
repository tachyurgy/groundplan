"""Text-layer word extraction with coordinates (pdfplumber). Bytes in, pages out; nothing touches disk."""

from __future__ import annotations

import hashlib
import io

import pdfplumber

from gp_pipeline.models import Page, Word

MIN_WORDS_FOR_TEXT_LAYER = 8


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text_pages(data: bytes) -> list[Page]:
    pages: list[Page] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for i, pg in enumerate(pdf.pages, start=1):
            words = [
                Word(text=w["text"], x0=w["x0"], top=w["top"], x1=w["x1"], bottom=w["bottom"], conf=1.0)
                for w in pg.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5)
            ]
            pages.append(Page(number=i, width=float(pg.width), height=float(pg.height), words=words, source="text"))
    return pages


def has_text_layer(pages: list[Page]) -> bool:
    return bool(pages) and all(len(p.words) >= MIN_WORDS_FOR_TEXT_LAYER for p in pages)
