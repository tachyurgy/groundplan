"""Pipeline orchestration: bytes -> ParsedDocument -> ExtractedFields -> entity resolution -> reconciliation.

Nothing here writes the document bytes anywhere: PDFs are parsed from memory and dropped.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from gp_pipeline.extract.document import parse
from gp_pipeline.extract.llm import Extractor, default_extractor
from gp_pipeline.models import ExtractedField, Finding, ParsedDocument, ReconciledHousehold


def extract_bytes(data: bytes, filename: str, force_ocr: bool = False,
                  extractor: Extractor | None = None) -> tuple[ParsedDocument, list[ExtractedField], list[Finding]]:
    doc = parse(data, filename, force_ocr=force_ocr)
    res = (extractor or default_extractor()).extract(doc)
    for f in res.fields:
        f.document_kind = doc.kind
        f.tax_year = doc.tax_year
    # pages hold the raster for OCR'd docs; drop it so nothing derived from the bytes outlives the call
    for p in doc.pages:
        p._image = None
        p._zone_cache.clear()
    return doc, res.fields, res.findings


def run_files(paths: Iterable[Path | str], force_ocr: bool = False, household_hint: dict | None = None) -> ReconciledHousehold:
    docs: list[ParsedDocument] = []
    fields: list[ExtractedField] = []
    findings: list[Finding] = []
    for p in paths:
        p = Path(p)
        d, fs, fd = extract_bytes(p.read_bytes(), p.name, force_ocr=force_ocr)
        docs.append(d)
        fields += fs
        findings += fd
    return run_parsed(docs, fields, findings, household_hint)


def run_parsed(docs: list[ParsedDocument], fields: list[ExtractedField], findings: list[Finding] | None = None,
               household_hint: dict | None = None) -> ReconciledHousehold:
    from gp_pipeline import reconcile, resolve

    matches, _ = resolve.resolve(fields)
    resolve.apply(fields, matches)
    return reconcile.reconcile(docs, fields, matches, extra_findings=findings or [], household_hint=household_hint)
