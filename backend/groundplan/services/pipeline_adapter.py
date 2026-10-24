"""Bridge to the document pipeline, two modes (SPEC §8):

* ``GP_PIPELINE_URL`` set (production: ``http://gp-pipeline:8090``): POST the bytes to ``{url}/extract`` as multipart.
  The bytes travel over the private docker network only and are not written anywhere on either side.
* unset (local dev): import ``gp_pipeline.api.process_document`` in-process (gp_pipeline is a uv path dependency).

Both return ``{"document", "extracted_fields", "findings", "properties_touched", "reconciled"}``.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable

from groundplan.config import get_settings


class PipelineUnavailable(Exception):
    pass


class PipelineRejected(Exception):
    """The pipeline service answered 4xx (not a PDF, unreadable, too large)."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def _remote(url: str, timeout: float) -> Callable:
    import httpx

    def process(data: bytes, filename: str, context: dict) -> dict:
        try:
            r = httpx.post(f"{url.rstrip('/')}/extract", files={"file": (filename, data, "application/pdf")},
                           data={"household_hint": json.dumps(context)}, timeout=timeout)
        except httpx.HTTPError as e:
            raise PipelineUnavailable(f"the pipeline service at {url} is unreachable ({type(e).__name__})") from e
        if 400 <= r.status_code < 500:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise PipelineRejected(r.status_code, str(detail))
        if r.status_code >= 500:
            raise PipelineUnavailable(f"the pipeline service returned {r.status_code}")
        return r.json()

    return process


def load_processor() -> Callable:
    st = get_settings()
    if st.pipeline_url:
        return _remote(st.pipeline_url, st.pipeline_timeout_s)
    try:
        mod = importlib.import_module("gp_pipeline.api")
    except ImportError as e:
        raise PipelineUnavailable("the gp_pipeline package is not installed in this environment and GP_PIPELINE_URL "
                                  "is not set") from e
    fn = getattr(mod, "process_document", None)
    if not callable(fn):
        raise PipelineUnavailable("gp_pipeline is installed but exposes no process_document(data, filename, context)")
    return fn


def mode() -> str:
    return "http" if get_settings().pipeline_url else "in-process"
