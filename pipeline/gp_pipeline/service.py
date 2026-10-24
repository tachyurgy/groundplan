"""``gp-pipeline`` HTTP service (SPEC §8): the document pipeline as an internal container both API backends call.

    POST /extract   multipart ``file`` (PDF), optional form field ``household_hint`` (JSON: property_keys, state,
                    tax_year_latest) -> the gp_pipeline.api.process_document result
    GET  /health    {status, version, tesseract}

No public route (it sits on the docker network only), no database, no disk writes: the upload is read into memory,
processed and dropped. ``uvicorn gp_pipeline.service:app --port 8090``.
"""

from __future__ import annotations

import json
import logging
import os
import time

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from gp_pipeline import __version__
from gp_pipeline.api import process_document

log = logging.getLogger("gp_pipeline.service")
MAX_BYTES = int(float(os.environ.get("GP_MAX_UPLOAD_MB", "15")) * 1024 * 1024)

app = FastAPI(title="gp-pipeline", version=__version__,
              description="Internal document-extraction service for Groundplan. Bytes are processed in memory and dropped.")


def _tesseract_version() -> str | None:
    try:
        import pytesseract

        return str(pytesseract.get_tesseract_version())
    except Exception:  # noqa: BLE001
        return None


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__, "tesseract": _tesseract_version()}


@app.post("/extract")
async def extract(file: UploadFile = File(...), household_hint: str | None = Form(None)):
    data = await file.read(MAX_BYTES + 1)
    await file.close()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"max {MAX_BYTES // (1024 * 1024)} MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "not a PDF")
    try:
        ctx = json.loads(household_hint) if household_hint else {}
    except json.JSONDecodeError as e:
        raise HTTPException(422, "household_hint must be JSON") from e
    t0 = time.time()
    try:
        result = await run_in_threadpool(process_document, data, file.filename or "upload.pdf", ctx)
    except Exception as e:  # noqa: BLE001 - a malformed PDF is the client's problem, not a crash
        log.exception("extract_failed filename=%s", file.filename)
        raise HTTPException(422, f"could not read this PDF: {type(e).__name__}") from e
    finally:
        del data
    log.info("extract filename=%s kind=%s fields=%d seconds=%.1f", file.filename, result["document"]["kind"],
             len(result["extracted_fields"]), time.time() - t0)
    return result
