#!/usr/bin/env python3
"""Upload-flow parity between two Groundplan backends (sibling of parity.py; standard library only).

    python3 scripts/parity_upload.py https://gp-python-api.levelbrook.com https://gp-go-api.levelbrook.com

For each of fixtures/documents/2025_schedule_e.pdf (text layer) and 2025_schedule_e.scan.pdf (OCR), on a fresh
workspace per backend: dashboard -> upload -> dashboard (Maple blocked by the rent conflict) -> resolve the blocking
finding with the document's value -> dashboard + Maple analysis (confirmed, provenance = the upload) -> re-upload the
same file (no new property, the decided conflict does not reopen, no duplicate document). Every response is diffed
after normalising ids/timestamps (parity.norm), and the flow's invariants are asserted on each side. Exit 1 on any
difference or failed invariant.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parity import Backend, diff, norm  # noqa: E402

DOCS = Path(__file__).resolve().parents[1] / "fixtures" / "documents"


def upload(be: Backend, path: str, filename: str, data: bytes):
    import urllib.error
    import urllib.request

    boundary = "gp" + uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            "Content-Type: application/pdf\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(be.base + "/api/v1" + path, data=body, method="POST", headers={
        "X-Workspace-Id": be.ws, "Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "groundplan-parity/1"})
    try:
        with urllib.request.urlopen(req, timeout=be.timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def maple_card(dash) -> dict:
    return next(c for c in dash["properties"] if c["property"]["nickname"] == "Maple duplex")


def flow(be: Backend, fname: str, log) -> list:
    """Run the flow on one backend; returns the list of (step, status, json) and appends invariant failures to log."""
    data = (DOCS / fname).read_bytes()
    steps = []

    def step(name, status, body):
        steps.append((name, status, body))
        return body

    def check(cond, msg):
        if not cond:
            log.append(f"{be.base} {fname}: {msg}")

    _, hh, _ = be.call("GET", "/households")
    hid = hh[0]["id"]
    s, dash, _ = be.call("GET", f"/households/{hid}/dashboard")
    step("dashboard before", s, dash)
    check(maple_card(dash)["net_cash_flow"]["status"] == "confirmed", "Maple not confirmed before the upload")
    s, up = upload(be, f"/households/{hid}/documents", fname, data)
    step("upload", s, up)
    check(s == 201, f"upload HTTP {s}: {up}")
    if s != 201:
        return steps
    check(up.get("import") == {"properties_created": 0, "properties_updated": 3, "conflicts_raised": 1}, f"import counts {up.get('import')}")
    block = [f for f in up["findings"] if f["severity"] == "block"]
    check(len(block) == 1 and block[0]["field"] == "schedule_e.line3.rents", f"blocking findings {[(f['field']) for f in block]}")
    s, dash, _ = be.call("GET", f"/households/{hid}/dashboard")
    step("dashboard after upload", s, dash)
    maple = maple_card(dash)
    check(maple["net_cash_flow"]["status"] == "blocked" and len(dash["properties"]) == 4, "Maple not blocked after upload")
    s, fs, _ = be.call("GET", f"/households/{hid}/findings?status=open")
    step("open findings after upload", s, fs)
    if block:
        doc_value = next(c["value"] for c in block[0]["candidates"] if c["source"].startswith("uploaded document"))
        s, res, _ = be.call("POST", f"/findings/{block[0]['id']}/resolve", {"value": doc_value, "note": "the return is right"})
        step("resolve", s, res)
        check(s == 200 and res["status"] == "resolved", f"resolve HTTP {s}")
        s, dash, _ = be.call("GET", f"/households/{hid}/dashboard")
        step("dashboard after resolve", s, dash)
        check(maple_card(dash)["net_cash_flow"]["status"] == "confirmed", "Maple not confirmed after resolve")
        pid = maple["property"]["id"]
        s, an, _ = be.call("GET", f"/properties/{pid}/analysis")
        step("maple analysis after resolve", s, an)
        check(an["cash_flow"]["gross_rent"]["value_cents"] == doc_value, "resolved value not written back")
        check(an["cash_flow"]["gross_rent"]["inputs"][0]["source"]["type"] == "document", "rent provenance is not the document")
        s, st, _ = be.call("GET", f"/properties/{pid}/strategies")
        step("maple strategies after resolve", s, st)
    s, up2 = upload(be, f"/households/{hid}/documents", fname, data)
    step("re-upload", s, up2)
    check(s == 201 and up2.get("import", {}).get("properties_created") == 0, "re-upload created a property")
    check(not [f for f in up2.get("findings", []) if f["severity"] == "block" and f["status"] == "open"], "decided conflict reopened")
    s, docs, _ = be.call("GET", f"/households/{hid}/documents")
    step("documents after re-upload", s, docs)
    check(len(docs) == 1, f"{len(docs)} documents after re-upload (want 1)")
    s, fs, _ = be.call("GET", f"/households/{hid}/findings")
    step("all findings at the end", s, fs)
    s, dash, _ = be.call("GET", f"/households/{hid}/dashboard")
    step("dashboard at the end", s, dash)
    return steps


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base_a")
    ap.add_argument("base_b")
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)
    failures: list[str] = []
    rows = []
    for fname in ("2025_schedule_e.pdf", "2025_schedule_e.scan.pdf"):
        A, B = Backend(args.base_a, args.timeout), Backend(args.base_b, args.timeout)
        sa, sb = flow(A, fname, failures), flow(B, fname, failures)
        ida, idb = {}, {}
        for (name, sta, ja), (_, stb, jb) in zip(sa, sb, strict=False):
            d = diff(norm(ja, ida), norm(jb, idb))
            if sta != stb:
                d.insert(0, f"HTTP {sta} != {stb}")
            rows.append((f"{fname}: {name}", "PASS" if not d else "FAIL", d))
        if len(sa) != len(sb):
            rows.append((f"{fname}: step count", "FAIL", [f"{len(sa)} != {len(sb)}"]))
    for name, verdict, d in rows:
        print(f"{name:<60}{verdict}  {d[0] if d else ''}")
        if args.verbose:
            for line in d[1:15]:
                print("      ", line)
    for f in failures:
        print("INVARIANT FAILED:", f)
    ok = sum(1 for r in rows if r[1] == "PASS")
    print(f"\n{ok}/{len(rows)} upload-flow checks passed, {len(failures)} invariant failures")
    return 0 if ok == len(rows) and not failures else 1


if __name__ == "__main__":
    sys.exit(main())
