"""OCR path (real tesseract), the process_document entry point, and the HTTP service."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from gp_pipeline.api import process_document
from gp_pipeline.eval import _match, _norm
from gp_pipeline.run import extract_bytes
from gp_pipeline.service import app
from tests.conftest import needs_tesseract


def _gold_doc(gold, name):
    return next(d for d in gold["documents"] if d["file"] == name)


@needs_tesseract
def test_scan_schedule_e_ocr(docs, gold):
    g = _gold_doc(gold, "2025_schedule_e.pdf")
    doc, fields, _ = extract_bytes((docs / g["scan_file"]).read_bytes(), g["scan_file"])
    assert doc.pages[0].source == "ocr" and doc.kind == "schedule_e" and doc.tax_year == 2025
    pairs = _match(g["fields"], fields)
    ok = sum(1 for gf, f in pairs if f is not None and _norm(f.value, gf["unit"]) == _norm(gf["value"], gf["unit"]))
    assert ok / len(g["fields"]) >= 0.95
    assert all(f.extractor == "ocr" and f.bbox != [0, 0, 0, 0] for f in fields)


def test_process_document_shape_and_existing_key_mapping(docs):
    data = (docs / "stmt_1_2025.pdf").read_bytes()
    existing = "1420 maple street, sacramento, ca 95838"
    r = process_document(data, "stmt_1_2025.pdf", {"property_keys": [existing], "tax_year_latest": 2025})
    assert set(r) == {"document", "extracted_fields", "findings", "properties_touched", "reconciled"}
    assert r["document"]["kind"] == "mortgage_statement" and r["document"]["bytes_retained"] is False
    assert r["properties_touched"] == [existing]
    assert r["reconciled"]["properties"][0]["key"] == existing
    assert "tax_year_latest" not in r["reconciled"]["household"]  # a statement cannot move the household's year
    assert r["reconciled"]["properties"][0]["loans"][0]["balance_cents"] > 0


@pytest.fixture(scope="module")
def svc():
    return TestClient(app)


def test_service_health_and_extract_text(svc, docs):
    h = svc.get("/health").json()
    assert h["status"] == "ok"
    with open(docs / "2025_form_1040.pdf", "rb") as fh:
        r = svc.post("/extract", files={"file": ("2025_form_1040.pdf", fh, "application/pdf")},
                     data={"household_hint": json.dumps({"state": "CA"})})
    assert r.status_code == 200
    body = r.json()
    fields = {f["field"]: f["value"] for f in body["extracted_fields"]}
    assert body["document"]["kind"] == "form_1040" and fields["form_1040.filing_status"] == "mfj"
    assert body["reconciled"]["household"]["wages_cents"] == fields["form_1040.line1a.wages"]


@needs_tesseract
def test_service_extract_scan(svc, docs):
    with open(docs / "stmt_3_2025.scan.pdf", "rb") as fh:
        r = svc.post("/extract", files={"file": ("stmt_3_2025.scan.pdf", fh, "application/pdf")})
    assert r.status_code == 200
    body = r.json()
    assert body["document"]["kind"] == "mortgage_statement"
    assert {f["extractor"] for f in body["extracted_fields"]} == {"ocr"}
    assert any(f["field"] == "mortgage.principal_balance" for f in body["extracted_fields"])


def test_service_rejects_non_pdf_and_bad_hint(svc, docs):
    assert svc.post("/extract", files={"file": ("x.txt", b"hello", "text/plain")}).status_code == 415
    with open(docs / "appraisal_1.pdf", "rb") as fh:
        assert svc.post("/extract", files={"file": ("a.pdf", fh, "application/pdf")}, data={"household_hint": "{"}).status_code == 422
