"""Document upload through the API, both pipeline modes (SPEC §8): in-process gp_pipeline and the gp-pipeline HTTP
service (a real uvicorn on a free port). Real tesseract for the .scan.pdf. The bytes are never persisted."""

from __future__ import annotations

import shutil
import socket
import threading
import time
import uuid
from pathlib import Path

import pytest

from groundplan.config import get_settings

API = "/api/v1"
DOCS = Path(__file__).resolve().parents[2] / "fixtures" / "documents"
needs_docs = pytest.mark.skipif(not (DOCS / "gold.json").exists(), reason="run `make synth` first")
needs_tesseract = pytest.mark.skipif(not (shutil.which("tesseract") or Path("/opt/homebrew/bin/tesseract").exists()),
                                     reason="tesseract not installed")


def _ws(client):
    hdr = {"X-Workspace-Id": str(uuid.uuid4()), "X-Forwarded-For": f"192.0.2.{uuid.uuid4().int % 250}"}
    hid = client.get(f"{API}/households", headers=hdr).json()[0]["id"]
    return hdr, hid


def _upload(client, hdr, hid, name):
    with open(DOCS / name, "rb") as fh:
        return client.post(f"{API}/households/{hid}/documents", files={"file": (name, fh, "application/pdf")}, headers=hdr)


@pytest.fixture()
def pipeline_url():
    st = get_settings()
    saved = st.pipeline_url
    yield st
    st.pipeline_url = saved


@pytest.fixture(scope="module")
def pipeline_service():
    import uvicorn
    from gp_pipeline.service import app

    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(timeout=5)


def _check_schedule_e(client, hdr, hid, r):
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["document"]["kind"] == "schedule_e" and body["document"]["tax_year"] == 2025
    assert body["document"]["bytes_retained"] is False and len(body["document"]["sha256"]) == 64
    fields = body["extracted_fields"]
    assert len(fields) > 40 and all(f["page"] == 1 and len(f["bbox"]) == 4 for f in fields)
    assert len(body["properties_touched"]) == 3
    assert any(f["kind"] == "unsupported_structure" for f in body["findings"])  # the Tahoe type-3 column
    # the household still analyses after the import, and the document is listed with its fields
    assert client.get(f"{API}/households/{hid}/dashboard", headers=hdr).status_code == 200
    docs = client.get(f"{API}/households/{hid}/documents", headers=hdr).json()
    assert [d["filename"] for d in docs] == ["2025_schedule_e.pdf"] and docs[0]["field_count"] == len(fields)
    one = client.get(f"{API}/documents/{body['document']['id']}", headers=hdr).json()
    assert len(one["fields"]) == len(fields)
    assert client.get(f"{API}/workspace", headers=hdr).json()["documents"] == 1
    return body


@needs_docs
def test_upload_text_pdf_in_process(client, pipeline_url):
    pipeline_url.pipeline_url = ""
    hdr, hid = _ws(client)
    body = _check_schedule_e(client, hdr, hid, _upload(client, hdr, hid, "2025_schedule_e.pdf"))
    assert {f["extractor"] for f in body["extracted_fields"]} == {"rules"}
    # idempotent on sha256: a re-upload updates, it does not duplicate
    _upload(client, hdr, hid, "2025_schedule_e.pdf")
    assert len(client.get(f"{API}/households/{hid}/documents", headers=hdr).json()) == 1


@needs_docs
@needs_tesseract
def test_upload_scan_pdf_in_process(client, pipeline_url):
    pipeline_url.pipeline_url = ""
    hdr, hid = _ws(client)
    r = _upload(client, hdr, hid, "stmt_3_2025.scan.pdf")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["document"]["kind"] == "mortgage_statement"
    vals = {f["field"]: f["value"] for f in body["extracted_fields"]}
    assert {f["extractor"] for f in body["extracted_fields"]} == {"ocr"}
    assert vals["mortgage.principal_balance"] == 45_750_000 and abs(vals["mortgage.interest_rate"] - 0.05875) < 1e-9
    assert client.get(f"{API}/households/{hid}/dashboard", headers=hdr).status_code == 200


@needs_docs
def test_upload_text_pdf_via_http_service(client, pipeline_url, pipeline_service):
    pipeline_url.pipeline_url = pipeline_service
    hdr, hid = _ws(client)
    _check_schedule_e(client, hdr, hid, _upload(client, hdr, hid, "2025_schedule_e.pdf"))


@needs_docs
@needs_tesseract
def test_upload_scan_pdf_via_http_service(client, pipeline_url, pipeline_service):
    pipeline_url.pipeline_url = pipeline_service
    hdr, hid = _ws(client)
    r = _upload(client, hdr, hid, "2025_schedule_e.scan.pdf")
    assert r.status_code == 201, r.text
    body = r.json()
    assert {f["extractor"] for f in body["extracted_fields"]} == {"ocr"} and len(body["properties_touched"]) == 3
    rents = sorted(f["value"] for f in body["extracted_fields"] if f["field"] == "schedule_e.line3.rents")
    assert len(rents) == 3 and all(v > 1_000_000 for v in rents)


def test_upload_not_a_pdf_and_service_down(client, pipeline_url, pipeline_service):
    hdr, hid = _ws(client)
    pipeline_url.pipeline_url = pipeline_service
    r = client.post(f"{API}/households/{hid}/documents", files={"file": ("x.pdf", b"hello", "application/pdf")}, headers=hdr)
    assert r.status_code == 422 and r.json()["type"].endswith("document-rejected")
    pipeline_url.pipeline_url = "http://127.0.0.1:9"  # nothing listens on the discard port
    r = client.post(f"{API}/households/{hid}/documents", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}, headers=hdr)
    assert r.status_code == 503 and r.json()["bytes_retained"] is False
    pipeline_url.pipeline_url = ""
    r = client.post(f"{API}/households/{hid}/documents", files={"file": ("x.pdf", b"%PDF-1.4 junk", "application/pdf")}, headers=hdr)
    assert r.status_code == 422
    assert client.get(f"{API}/workspace", headers=hdr).json()["documents"] == 0
