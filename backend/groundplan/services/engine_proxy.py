"""GP_ENGINE=go: forward engine computation to the Go port (the strangler-pattern migration, SPEC §6/§8).

The Python API keeps the DB, tenancy, provenance and presentation; only the pure engine call crosses the wire
(`groundplan.engine.wire`). Every forwarded call falls back to the in-process Python engine on any error (connect,
timeout, non-200, bad JSON) and logs `engine_go_fallback`; after a failure the Go engine is skipped for
`BREAKER_SECONDS` so a dead service costs one timeout, not one per request. When both results exist (analysis), money
figures are compared and any difference is logged as `engine_go_diff` (shadow comparison while serving Go's answer).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from groundplan.config import get_settings
from groundplan.engine import wire

log = logging.getLogger("groundplan.engine_proxy")
BREAKER_SECONDS = 30.0
_open_until = [0.0]


def enabled() -> bool:
    return get_settings().engine == "go" and time.monotonic() >= _open_until[0]


def _post(path: str, body: dict) -> dict | None:
    import httpx

    st = get_settings()
    url = st.engine_go_url.rstrip("/") + path
    t0 = time.monotonic()
    try:
        r = httpx.post(url, json=body, timeout=httpx.Timeout(st.engine_go_timeout_s, connect=1.0))
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        out = r.json()
        log.info("engine_go_ok path=%s ms=%d", path, (time.monotonic() - t0) * 1000)
        return out
    except Exception as e:  # noqa: BLE001 - any failure means: use the Python engine
        _open_until[0] = time.monotonic() + BREAKER_SECONDS
        log.warning("engine_go_fallback path=%s url=%s error=%s: %s", path, url, type(e).__name__, str(e)[:200])
        return None


def analyze(pm, hm, year: int | None, horizon: int) -> dict | None:
    return _post("/engine/analyze", {"wire": wire.WIRE_VERSION, "property": wire.encode(pm), "household": wire.encode(hm),
                                     "year": year, "horizon": horizon})


def strategies(pm, hm, assumptions) -> dict | None:
    return _post("/engine/strategies", {"wire": wire.WIRE_VERSION, "property": wire.encode(pm), "household": wire.encode(hm),
                                        "assumptions": wire.encode(assumptions)})


def cents_diff(a: Any, b: Any, path: str = "$", out: list | None = None) -> list[str]:
    """Paths where two JSON trees disagree on a *_cents / value_cents integer."""
    out = [] if out is None else out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a.keys() & b.keys():
            if k.endswith("cents") and isinstance(a[k], int) and a[k] != b[k]:
                out.append(f"{path}.{k}")
            else:
                cents_diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            cents_diff(x, y, f"{path}[{i}]", out)
    return out
