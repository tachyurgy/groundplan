"""Turn PDF bytes into a classified :class:`ParsedDocument` (text layer first, OCR fallback)."""

from __future__ import annotations

from gp_pipeline.extract.classify import classify
from gp_pipeline.extract.ocr import ocr_pages
from gp_pipeline.extract.text import has_text_layer, sha256, text_pages
from gp_pipeline.models import ParsedDocument


def parse(data: bytes, filename: str, force_ocr: bool = False) -> ParsedDocument:
    pages = [] if force_ocr else text_pages(data)
    if force_ocr or not has_text_layer(pages):
        pages = ocr_pages(data)
    kind, year, conf = classify(pages)
    return ParsedDocument(filename=filename, sha256=sha256(data), page_count=len(pages), pages=pages, kind=kind,
                          tax_year=year, classify_confidence=conf)
