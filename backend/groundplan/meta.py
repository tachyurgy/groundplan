"""Build/runtime facts for GET /api/v1/meta (SPEC §8.2)."""

from __future__ import annotations

import platform
import subprocess
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from groundplan import __version__
from groundplan.config import get_settings

STARTED_AT = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@lru_cache(maxsize=1)
def git_sha() -> str:
    sha = get_settings().git_sha.strip()
    if sha:
        return sha[:12]
    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=Path(__file__).parent, capture_output=True,
                             text=True, timeout=2)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return __version__


def runtime() -> str:
    return f"{platform.python_implementation()} {platform.python_version()}"
