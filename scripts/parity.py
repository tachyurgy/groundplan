#!/usr/bin/env python3
"""Parity check between two Groundplan backends (SPEC §8.3). Standard library only.

    python3 scripts/parity.py https://gp-python-api.levelbrook.com https://gp-go-api.levelbrook.com
    python3 scripts/parity.py http://localhost:8000 http://localhost:8080 --verbose

A fresh random workspace is created on each side (so both start from the seeded demo household). Then every GET for
the household and its properties is walked (dashboard, analysis with and without overrides, figure trees, strategies at
several horizons / assumption overrides, fact sheets json/csv/emoney/rightcapital/mgp, findings, alerts, documents,
scenarios, deterministic simulate, workspace), the same mutations are applied to both (PATCH property assumptions,
resolve the blocking finding, PUT a tax year) and the affected GETs are walked again. JSON is diffed after normalising
ids, UUIDs and timestamps. Cents must be byte-identical. Monte Carlo (sigma > 0) is compared for shape only: numpy's
PCG64 and Go's PRNG differ. `/meta` is compared for shape only (it names the backend). Exit 1 on any difference.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
import uuid

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?")
IGNORE_KEYS = {"id", "created_at", "updated_at", "uploaded_at", "generated_at", "started_at", "last_seen_at", "when", "version"}
SHAPE_ONLY = {"meta", "simulate_mc"}


class Backend:
    def __init__(self, base: str, timeout: float):
        self.base = base.rstrip("/")
        self.ws = str(uuid.uuid4())
        self.timeout = timeout

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, object, str]:
        url = self.base + (path if path.startswith("/engine") else "/api/v1" + path)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "X-Workspace-Id": self.ws, "Content-Type": "application/json", "Accept": "application/json, text/csv",
            "User-Agent": "groundplan-parity/1"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw, status, ctype = r.read(), r.status, r.headers.get("content-type", "")
        except urllib.error.HTTPError as e:
            raw, status, ctype = e.read(), e.code, e.headers.get("content-type", "")
        if "json" in ctype:
            return status, json.loads(raw or b"null"), ctype
        return status, raw.decode("utf-8", "replace"), ctype


def norm(x, idmap: dict):
    """Replace ids/UUIDs by stable placeholders (first-seen order per side) and timestamps by <ts>."""
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            if k in IGNORE_KEYS and not isinstance(v, dict | list):
                out[k] = "<ignored>"
            else:
                out[k] = norm(v, idmap)
        return out
    if isinstance(x, list):
        return [norm(v, idmap) for v in x]
    if isinstance(x, str):
        s = UUID_RE.sub(lambda m: idmap.setdefault(m.group(0).lower(), f"<uuid{len(idmap)}>"), x)
        return TS_RE.sub("<ts>", s)
    return x


def diff(a, b, path="$", out=None, limit=50):
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(a.keys() | b.keys()):
            if k not in a:
                out.append(f"{path}.{k}: only in B")
            elif k not in b:
                out.append(f"{path}.{k}: only in A")
            else:
                diff(a[k], b[k], f"{path}.{k}", out, limit)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            diff(x, y, f"{path}[{i}]", out, limit)
    elif type(a) is not type(b) and not (isinstance(a, int | float) and isinstance(b, int | float) and not isinstance(a, bool)):
        out.append(f"{path}: {type(a).__name__} {a!r:.60} != {type(b).__name__} {b!r:.60}")
    elif a != b:
        out.append(f"{path}: {a!r:.60} != {b!r:.60}")
    return out


def shape(x):
    if isinstance(x, dict):
        return {k: shape(v) for k, v in x.items()}
    if isinstance(x, list):
        return [shape(x[0])] if x else []
    return type(x).__name__ if not isinstance(x, int | float) or isinstance(x, bool) else "number"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base_a")
    ap.add_argument("base_b")
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)
    A, B = Backend(args.base_a, args.timeout), Backend(args.base_b, args.timeout)
    ida, idb = {}, {}
    rows: list[tuple[str, str, int, str]] = []

    def both(name, method, path_a, path_b=None, body=None, mode="exact"):
        sa, ja, _ = A.call(method, path_a, body)
        sb, jb, _ = B.call(method, path_b or path_a, body)
        if mode == "shape":
            d = diff(shape(ja), shape(jb))
        else:
            d = diff(norm(ja, ida), norm(jb, idb))
        if sa != sb:
            d.insert(0, f"HTTP {sa} != {sb}")
        rows.append((name, "PASS" if not d else "FAIL", len(d), (f"[{sa}] " if sa >= 300 else "") + (d[0] if d else "")))
        if args.verbose and d:
            for line in d[:15]:
                print(f"    {name}: {line}")
        return ja, jb

    both("meta", "GET", "/meta", mode="shape")
    both("health", "GET", "/health", mode="shape")
    ha, hb = both("households", "GET", "/households")
    if not (isinstance(ha, list) and ha and isinstance(hb, list) and hb):
        print("cannot continue: no seeded household on one side", file=sys.stderr)
        _print(rows)
        return 1
    hid_a, hid_b = ha[0]["id"], hb[0]["id"]
    both("workspace", "GET", "/workspace")
    hh_a, hh_b = both("household", "GET", f"/households/{hid_a}", f"/households/{hid_b}")
    pa = {p["nickname"]: p["id"] for p in hh_a.get("properties", [])}
    pb = {p["nickname"]: p["id"] for p in hh_b.get("properties", [])}
    pairs = [(n, pa[n], pb[n]) for n in sorted(pa) if n in pb]
    if set(pa) != set(pb):
        rows.append(("property set", "FAIL", 1, f"{sorted(pa)} != {sorted(pb)}"))

    def household_walk(tag=""):
        for sub in ("dashboard", "alerts", "findings", "findings?status=open", "documents"):
            both(f"{tag}household/{sub}", "GET", f"/households/{hid_a}/{sub}", f"/households/{hid_b}/{sub}")

    STRAT = [("h10", "horizon=10"), ("h5", "horizon=5"), ("h20", "horizon=20"),
             ("dst", "dst=true&load_rate=0.085&dst_yield=0.05&replacement_debt_cents=0&cash_taken_cents=1000000"),
             ("assumptions", "appreciation_rate=0.05&rent_growth=0.02&expense_growth=0.04&reinvest_rate=0.07&horizon=12")]

    def property_walk(tag=""):
        for n, a, b in pairs:
            short = n.lower().replace(" ", "_")
            both(f"{tag}{short}/property", "GET", f"/properties/{a}", f"/properties/{b}")
            both(f"{tag}{short}/analysis", "GET", f"/properties/{a}/analysis", f"/properties/{b}/analysis")
            q = "?current_value_cents=70000000&arm_index=0.06&vacancy_rate=0.08&horizon=15"
            both(f"{tag}{short}/analysis+overrides", "GET", f"/properties/{a}/analysis{q}", f"/properties/{b}/analysis{q}")
            for key in ("exit_tax.total", "cash_flow.net_annual", "equity.net", "equity.roe", "depreciation.accumulated", "cash_flow.bridge_delta"):
                both(f"{tag}{short}/figure/{key}", "GET", f"/properties/{a}/figure/{key}", f"/properties/{b}/figure/{key}")
            for label, qs in STRAT:
                both(f"{tag}{short}/strategies[{label}]", "GET", f"/properties/{a}/strategies?{qs}", f"/properties/{b}/strategies?{qs}")
            for fmt in ("json", "csv", "emoney", "rightcapital", "mgp"):
                both(f"{tag}{short}/factsheet.{fmt}", "GET", f"/properties/{a}/factsheet?format={fmt}",
                     f"/properties/{b}/factsheet?format={fmt}")
            both(f"{tag}{short}/scenarios", "GET", f"/properties/{a}/scenarios", f"/properties/{b}/scenarios")

    household_walk()
    property_walk()
    both("rules", "GET", "/rules")
    sim = {"household_id": None, "start_year": 2026, "years": 8,
           "events": [{"year": 2029, "type": "sell", "property_ref": "Oak condo"}],
           "monte_carlo": {"runs": 0, "appr_sigma": 0, "rent_sigma": 0}}
    sa_, ja_, _ = A.call("POST", "/simulate", {**sim, "household_id": hid_a})
    sb_, jb_, _ = B.call("POST", "/simulate", {**sim, "household_id": hid_b})
    d = diff(norm(ja_, ida), norm(jb_, idb))
    if sa_ != sb_:
        d.insert(0, f"HTTP {sa_} != {sb_}")
    rows.append(("simulate (sigma=0)", "PASS" if not d else "FAIL", len(d), d[0] if d else ""))
    mc = {**sim, "monte_carlo": {"runs": 200, "appr_sigma": 0.04, "rent_sigma": 0.03, "seed": 7}}
    sa_, ja_, _ = A.call("POST", "/simulate", {**mc, "household_id": hid_a})
    sb_, jb_, _ = B.call("POST", "/simulate", {**mc, "household_id": hid_b})
    d = diff(shape(ja_), shape(jb_))
    if sa_ != sb_:
        d.insert(0, f"HTTP {sa_} != {sb_}")
    rows.append(("simulate (monte carlo, shape)", "PASS" if not d else "FAIL", len(d), d[0] if d else ""))

    # ---- mutations, identical on both sides
    if pairs:
        n, a, b = next(((n, a, b) for n, a, b in pairs if n == "Maple duplex"), pairs[0])
        both("PATCH property assumptions", "PATCH", f"/properties/{a}", f"/properties/{b}",
             body={"appreciation_rate": 0.045, "rent_growth_rate": 0.025, "vacancy_rate": 0.06})
        both("PUT year 2025", "PUT", f"/properties/{a}/years/2025", f"/properties/{b}/years/2025",
             body={"gross_rent_cents": 5_100_000, "repairs_cents": 360_000, "mortgage_interest_cents": 686_000})
    fa = A.call("GET", f"/households/{hid_a}/findings?status=open")[1]
    fb = B.call("GET", f"/households/{hid_b}/findings?status=open")[1]
    blk_a = next((f for f in fa if f.get("severity") == "block"), None) if isinstance(fa, list) else None
    blk_b = next((f for f in fb if f.get("severity") == "block"), None) if isinstance(fb, list) else None
    if blk_a and blk_b:
        val = blk_a["candidates"][-1]["value"]
        both("POST resolve blocking finding", "POST", f"/findings/{blk_a['id']}/resolve", f"/findings/{blk_b['id']}/resolve",
             body={"value": val, "note": "parity check"})
    else:
        rows.append(("POST resolve blocking finding", "FAIL" if bool(blk_a) != bool(blk_b) else "SKIP", 0,
                     "no blocking finding on one side"))
    household_walk("after/")
    property_walk("after/")
    both("after/workspace", "GET", "/workspace")
    return _print(rows)


def _print(rows) -> int:
    w = max(len(r[0]) for r in rows)
    fails = [r for r in rows if r[1] == "FAIL"]
    for name, st, n, first in rows:
        print(f"{name:<{w}}  {st:<4}  {n:>3}  {first[:110]}")
    print(f"\n{len(rows) - len(fails)}/{len(rows)} checks passed" + (f", {len(fails)} FAILED" if fails else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
