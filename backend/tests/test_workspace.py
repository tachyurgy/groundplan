"""SPEC §8.1/§8.2: no-login workspaces, provisioning + seeding, isolation, guards, reset, sweep, meta, CORS."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from groundplan.config import get_settings
from groundplan.db import models as m
from groundplan.services import workspace as ws

API = "/api/v1"


def _wid() -> str:
    return str(uuid.uuid4())


def _ip() -> str:
    return f"198.51.100.{uuid.uuid4().int % 250}-{uuid.uuid4().hex[:6]}"


def _h(wid: str, ip: str | None = None) -> dict:
    return {"X-Workspace-Id": wid, "X-Forwarded-For": ip or _ip()}


@pytest.fixture()
def settings():
    st = get_settings()
    saved = st.model_dump()
    yield st
    for k, v in saved.items():
        setattr(st, k, v)


def test_missing_and_invalid_workspace_is_400(client):
    from fastapi.testclient import TestClient

    from groundplan.api import app

    bare = TestClient(app)
    for hdr in ({}, {"X-Workspace-Id": "not-a-uuid"}, {"X-Workspace-Id": ""}):
        r = bare.get(f"{API}/households", headers=hdr)
        assert r.status_code == 400, hdr
        assert r.headers["content-type"].startswith("application/problem+json")
        assert r.json()["type"].startswith("https://groundplan.dev/problems/workspace-")
    # these three need no workspace
    assert bare.get(f"{API}/health").status_code == 200
    assert bare.get(f"{API}/meta").status_code == 200
    assert bare.get(f"{API}/eval/latest").status_code in (200, 404)


def test_meta_shape(client):
    r = client.get(f"{API}/meta", headers={"X-Workspace-Id": ""}).json()
    assert r["backend"] == "python" and r["engine"] in ("python", "go")
    assert r["runtime"].startswith("CPython 3.") and r["db"].startswith("postgres ")
    assert set(r) == {"backend", "version", "engine", "runtime", "started_at", "db"}
    datetime.fromisoformat(r["started_at"].replace("Z", "+00:00"))


def test_first_request_provisions_and_seeds(client):
    wid = _wid()
    rows = client.get(f"{API}/households", headers=_h(wid)).json()
    assert [r["name"] for r in rows] == ["Okafor-Lindqvist household"] and rows[0]["property_count"] == 4
    info = client.get(f"{API}/workspace", headers=_h(wid)).json()
    assert info["id"] == wid and info["households"] == 1 and info["documents"] == 0 and info["created_at"]
    # canonicalised: upper-case form of the same UUID is the same workspace
    assert len(client.get(f"{API}/households", headers=_h(wid.upper())).json()) == 1


def test_two_workspace_isolation(client):
    a, b = _wid(), _wid()
    ha = client.get(f"{API}/households", headers=_h(a)).json()[0]["id"]
    hb = client.get(f"{API}/households", headers=_h(b)).json()[0]["id"]
    assert ha != hb
    # a mutation in A is invisible in B
    assert client.patch(f"{API}/households/{ha}", json={"name": "A only"}, headers=_h(a)).status_code == 200
    assert client.get(f"{API}/households", headers=_h(b)).json()[0]["name"] == "Okafor-Lindqvist household"
    # B cannot read or write A's rows
    pa = client.get(f"{API}/households/{ha}", headers=_h(a)).json()["properties"][0]["id"]
    for url in (f"/households/{ha}", f"/households/{ha}/dashboard", f"/properties/{pa}", f"/properties/{pa}/analysis"):
        assert client.get(API + url, headers=_h(b)).status_code == 404, url
    assert client.delete(f"{API}/households/{ha}", headers=_h(b)).status_code == 404
    assert client.get(f"{API}/households/{ha}", headers=_h(a)).json()["name"] == "A only"


def test_concurrent_first_requests_seed_exactly_once(db_session_factory):
    wid, ip = _wid(), _ip()
    n = 8
    barrier = threading.Barrier(n)
    results, errors = [], []

    def go():
        s = db_session_factory()
        try:
            barrier.wait()
            results.append(ws.ensure(s, wid, ip).created)
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        finally:
            s.close()

    threads = [threading.Thread(target=go) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert results.count(True) == 1 and len(results) == n
    with db_session_factory() as s:
        assert s.execute(select(func.count()).select_from(m.Household).where(m.Household.advisor_id == wid)).scalar_one() == 1
        # the losers rolled back their provisioning-counter bump: one new workspace counted once
        assert s.execute(text("SELECT count FROM workspace_provisions WHERE ip = :ip"), {"ip": ip}).scalar_one() == 1


def test_concurrent_first_requests_through_the_api(client):
    wid, ip = _wid(), _ip()
    codes: list[int] = []
    barrier = threading.Barrier(5)

    def go():
        barrier.wait()
        codes.append(client.get(f"{API}/households", headers=_h(wid, ip)).status_code)

    threads = [threading.Thread(target=go) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes == [200] * 5
    assert len(client.get(f"{API}/households", headers=_h(wid, ip)).json()) == 1


def test_per_ip_daily_workspace_limit(client, settings):
    settings.max_workspaces_per_ip_per_day = 3
    ip = _ip()
    for _ in range(3):
        assert client.get(f"{API}/workspace", headers=_h(_wid(), ip)).status_code == 200
    r = client.get(f"{API}/workspace", headers=_h(_wid(), ip))
    assert r.status_code == 429 and r.json()["type"].endswith("workspace-rate-limit")
    # CF-Connecting-IP wins over X-Forwarded-For
    r = client.get(f"{API}/workspace", headers={"X-Workspace-Id": _wid(), "CF-Connecting-IP": ip, "X-Forwarded-For": _ip()})
    assert r.status_code == 429
    # existing workspaces from that IP keep working; another IP is unaffected
    assert client.get(f"{API}/workspace", headers=_h(_wid(), _ip())).status_code == 200


def test_household_limit(client, settings):
    settings.max_households_per_workspace = 2
    wid = _wid()
    body = {"name": "Extra", "filing_status": "single", "state": "WA"}
    assert client.post(f"{API}/households", json=body, headers=_h(wid)).status_code == 201
    r = client.post(f"{API}/households", json=body, headers=_h(wid))
    assert r.status_code == 429 and r.json()["type"].endswith("household-limit")


def test_document_limit_and_upload_size(client, settings):
    wid = _wid()
    hid = client.get(f"{API}/households", headers=_h(wid)).json()[0]["id"]
    settings.max_upload_mb = 1
    big = b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10)
    r = client.post(f"{API}/households/{hid}/documents", files={"file": ("big.pdf", big, "application/pdf")}, headers=_h(wid))
    assert r.status_code == 413
    settings.max_body_mb = 1
    r = client.post(f"{API}/households/{hid}/documents", files={"file": ("big.pdf", big * 2, "application/pdf")}, headers=_h(wid))
    assert r.status_code == 413 and r.json()["type"].endswith("body-too-large")
    settings.max_documents_per_workspace = 0
    r = client.post(f"{API}/households/{hid}/documents", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}, headers=_h(wid))
    assert r.status_code == 429 and r.json()["type"].endswith("document-limit")


def test_reset_reseeds(client):
    wid = _wid()
    hid = client.get(f"{API}/households", headers=_h(wid)).json()[0]["id"]
    client.patch(f"{API}/households/{hid}", json={"name": "changed"}, headers=_h(wid))
    client.post(f"{API}/households", json={"name": "Second", "filing_status": "single", "state": "WA"}, headers=_h(wid))
    assert client.get(f"{API}/workspace", headers=_h(wid)).json()["households"] == 2
    r = client.post(f"{API}/workspace/reset", headers=_h(wid)).json()
    assert r["id"] == wid and r["households"] == 1 and r["documents"] == 0
    rows = client.get(f"{API}/households", headers=_h(wid)).json()
    assert [x["name"] for x in rows] == ["Okafor-Lindqvist household"] and rows[0]["id"] != hid
    assert rows[0]["open_findings"] == 4


def test_idle_sweep(client, db_session_factory):
    old, fresh = _wid(), _wid()
    client.get(f"{API}/workspace", headers=_h(old))
    client.get(f"{API}/workspace", headers=_h(fresh))
    with db_session_factory() as s:
        s.execute(text("UPDATE advisors SET last_seen_at = :t WHERE id = :id"),
                  {"t": datetime.now(UTC) - timedelta(days=15), "id": old})
        s.commit()
        assert ws.sweep(s) >= 1
        assert s.get(m.Advisor, old) is None and s.get(m.Advisor, fresh) is not None
        assert s.execute(select(func.count()).select_from(m.Household).where(m.Household.advisor_id == old)).scalar_one() == 0
    # coming back after the sweep just gets a fresh seeded workspace
    assert len(client.get(f"{API}/households", headers=_h(old)).json()) == 1


def test_last_seen_is_touched(client, db_session_factory):
    wid = _wid()
    client.get(f"{API}/workspace", headers=_h(wid))
    with db_session_factory() as s:
        s.execute(text("UPDATE advisors SET last_seen_at = now() - interval '3 days' WHERE id = :id"), {"id": wid})
        s.commit()
    client.get(f"{API}/workspace", headers=_h(wid))
    with db_session_factory() as s:
        seen = s.execute(select(m.Advisor.last_seen_at).where(m.Advisor.id == wid)).scalar_one()
        assert seen > datetime.now(UTC) - timedelta(minutes=1)


@pytest.mark.parametrize("origin,allowed", [
    ("https://gp-python.levelbrook.com", True), ("https://gp-go.levelbrook.com", True), ("http://localhost:5173", True),
    ("http://localhost:4173", True), ("https://abc123.gp-python.pages.dev", True), ("https://feat-x.gp-go.pages.dev", True),
    ("https://evil.example.com", False), ("https://gp-python.pages.dev.evil.com", False),
])
def test_cors(client, origin, allowed):
    r = client.options(f"{API}/households", headers={"Origin": origin, "Access-Control-Request-Method": "GET",
                                                     "Access-Control-Request-Headers": "x-workspace-id,content-type"})
    assert (r.headers.get("access-control-allow-origin") == origin) is allowed
    if allowed:
        assert "x-workspace-id" in r.headers["access-control-allow-headers"].lower()
