from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "fixtures" / "documents"
HAS_TESSERACT = shutil.which("tesseract") is not None or Path("/opt/homebrew/bin/tesseract").exists()
needs_tesseract = pytest.mark.skipif(not HAS_TESSERACT, reason="tesseract not installed")


@pytest.fixture(scope="session")
def docs() -> Path:
    if not (DOCS / "gold.json").exists():
        pytest.skip("fixtures/documents missing: run `make synth`")
    return DOCS


@pytest.fixture(scope="session")
def gold(docs) -> dict:
    return json.loads((docs / "gold.json").read_text())
