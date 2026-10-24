"""Lazy bridge to the document pipeline (Agent B's gp_pipeline). The API works without it installed.

Expected entry point (any of these, first found wins):
    gp_pipeline.api.process_document(data: bytes, filename: str, context: dict) -> dict | pydantic model
    gp_pipeline.process_document(...)
returning {"document": {...DocumentOut}, "extracted_fields": [...], "findings": [...],
           "reconciled": optional ReconciledHousehold-shaped dict}.
The bytes are passed in memory and never written to disk or the DB by this process.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable


class PipelineUnavailable(Exception):
    pass


def load_processor() -> Callable:
    try:
        importlib.import_module("gp_pipeline")
    except ImportError as e:
        raise PipelineUnavailable("the gp_pipeline package is not installed in this environment") from e
    for mod_name in ("gp_pipeline.api", "gp_pipeline"):
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        fn = getattr(mod, "process_document", None)
        if callable(fn):
            return fn
    raise PipelineUnavailable("gp_pipeline is installed but exposes no process_document(data, filename, context) entry point")
