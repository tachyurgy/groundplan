"""GP_ENGINE=go (strangler migration): the API forwards pure engine calls over the wire API and falls back to Python.
The "Go" engine here is this app's own reference /engine endpoints on a real uvicorn, so the test proves the wire format
is lossless (identical JSON) and that the fallback works when the engine is down."""

from __future__ import annotations

import logging
import socket
import threading
import time
import uuid

import pytest

from groundplan.config import get_settings
from groundplan.services import engine_proxy

API = "/api/v1"


@pytest.fixture(scope="module")
def engine_server(db_session_factory):
    import uvicorn

    from groundplan.api import create_app

    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning", lifespan="off"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(timeout=5)


@pytest.fixture()
def engine_go():
    st = get_settings()
    saved = (st.engine, st.engine_go_url)
    engine_proxy._open_until[0] = 0.0
    yield st
    st.engine, st.engine_go_url = saved
    engine_proxy._open_until[0] = 0.0


def _props(client, hdr):
    hid = client.get(f"{API}/households", headers=hdr).json()[0]["id"]
    return [p["id"] for p in client.get(f"{API}/households/{hid}", headers=hdr).json()["properties"]]


def test_forwarded_results_are_identical(client, engine_go, engine_server, caplog):
    hdr = {"X-Workspace-Id": str(uuid.uuid4())}
    pids = _props(client, hdr)
    calls = [("analysis", {}), ("analysis", {"current_value_cents": 70_000_000, "arm_index": "0.06"}),
             ("strategies", {"horizon": 7}), ("strategies", {"dst": "true", "replacement_debt_cents": 0, "cash_taken_cents": 500_000})]
    for pid in pids:
        for path, params in calls:
            engine_go.engine = "python"
            a = client.get(f"{API}/properties/{pid}/{path}", params=params, headers=hdr)
            engine_go.engine, engine_go.engine_go_url = "go", engine_server
            with caplog.at_level(logging.INFO, logger="groundplan.engine_proxy"):
                b = client.get(f"{API}/properties/{pid}/{path}", params=params, headers=hdr)
            assert a.headers["x-engine"] == "python" and b.headers["x-engine"] == "go", (pid, path)
            assert a.json() == b.json(), (pid, path)
    assert "engine_go_ok" in caplog.text and "engine_go_diff" not in caplog.text
    engine_go.engine = "python"


def test_falls_back_to_python_when_go_is_down(client, engine_go, caplog):
    hdr = {"X-Workspace-Id": str(uuid.uuid4())}
    pid = _props(client, hdr)[0]
    engine_go.engine = "python"
    ref = client.get(f"{API}/properties/{pid}/strategies", headers=hdr).json()
    engine_go.engine, engine_go.engine_go_url = "go", "http://127.0.0.1:9"
    with caplog.at_level(logging.WARNING, logger="groundplan.engine_proxy"):
        r = client.get(f"{API}/properties/{pid}/strategies", headers=hdr)
    assert r.status_code == 200 and r.headers["x-engine"] == "python" and r.json() == ref
    assert "engine_go_fallback" in caplog.text
    assert client.get(f"{API}/meta").json()["engine"] == "go"
    # breaker open: the next call does not even try
    assert engine_proxy.enabled() is False


def test_engine_wire_endpoints_reject_garbage(client):
    assert client.post("/engine/analyze", json={"property": {"nope": 1}}).status_code == 422
    assert client.post("/engine/strategies", json={}).status_code == 422
