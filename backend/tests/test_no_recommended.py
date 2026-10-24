"""SPEC §8.3: no key named `recommended` anywhere in any response. Walks every GET (and the simulate POST) for the
seeded demo household and its properties in a fresh workspace."""

from __future__ import annotations

import json
import uuid

API = "/api/v1"


def _keys(x, path="$"):
    if isinstance(x, dict):
        for k, v in x.items():
            yield f"{path}.{k}", k
            yield from _keys(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _keys(v, f"{path}[{i}]")


def test_no_recommended_key_anywhere(client):
    hdr = {"X-Workspace-Id": str(uuid.uuid4()), "X-Forwarded-For": f"203.0.113.{uuid.uuid4().int % 200}"}
    get = lambda url, **p: client.get(API + url, headers=hdr, params=p)  # noqa: E731
    hid = get("/households").json()[0]["id"]
    urls = ["/households", f"/households/{hid}", f"/households/{hid}/dashboard", f"/households/{hid}/alerts",
            f"/households/{hid}/findings", f"/households/{hid}/documents", "/workspace", "/meta", "/health", "/rules"]
    bodies = []
    pids = [p["id"] for p in get(f"/households/{hid}").json()["properties"]]
    for pid in pids:
        urls += [f"/properties/{pid}", f"/properties/{pid}/analysis", f"/properties/{pid}/scenarios",
                 f"/properties/{pid}/figure/exit_tax.total", f"/properties/{pid}/figure/cash_flow.net_annual"]
        for fmt in ("json", "emoney", "rightcapital", "mgp"):
            urls.append(f"/properties/{pid}/factsheet?format={fmt}")
        for horizon in (5, 10, 20):
            bodies.append(get(f"/properties/{pid}/strategies", horizon=horizon).json())
        bodies.append(get(f"/properties/{pid}/strategies", dst="true", replacement_debt_cents=0, cash_taken_cents=500_000).json())
    for u in urls:
        r = client.get(API + u, headers=hdr)
        assert r.status_code in (200, 404), (u, r.status_code)
        bodies.append(r.json())
    sim = client.post(f"{API}/simulate", headers=hdr, json={"household_id": hid, "years": 5,
                                                            "monte_carlo": {"runs": 50, "appr_sigma": 0.05, "rent_sigma": 0.03}})
    assert sim.status_code == 200
    bodies.append(sim.json())
    offenders = [p for b in bodies for p, k in _keys(b) if k == "recommended"]
    assert offenders == []
    assert "recommended" not in json.dumps(bodies)
