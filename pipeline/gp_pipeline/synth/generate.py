"""Render the whole Okafor-Lindqvist document set and its gold labels.

``python -m gp_pipeline.synth --out fixtures/documents`` (or ``gp-pipeline synth``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from gp_pipeline.synth import render
from gp_pipeline.synth.household import YEARS, Household, build_household
from gp_pipeline.synth.scan import DEFAULT, degrade


def _doc_plan(h: Household) -> list[tuple[str, callable]]:
    plan: list[tuple[str, callable]] = []
    for y in YEARS:
        plan.append((f"{y}_form_1040.pdf", lambda p, y=y: render.render_form_1040(h, y, p)))
        plan.append((f"{y}_schedule_e.pdf", lambda p, y=y: render.render_schedule_e(h, y, p)))
        for i, prop in enumerate(h.properties_in(y), start=1):
            plan.append((f"{y}_form_4562_{i}.pdf", lambda p, y=y, prop=prop: render.render_form_4562(h, prop, y, p)))
        plan.append((f"{y}_form_8582.pdf", lambda p, y=y: render.render_form_8582(h, y, p)))
    stmts = [("p1", "p1-first", 2025), ("p2", "p2-first", 2025), ("p3", "p3-first", 2025),
             ("p4", "p4-heloc", 2024), ("p4", "p4-first", 2022)]
    for n, (pk, lk, y) in enumerate(stmts, start=1):
        prop = h.by_key(pk)
        loan = next(lo for lo in prop.loans if lo.key == lk)
        plan.append((f"stmt_{n}_{y}.pdf",
                     lambda p, prop=prop, loan=loan, y=y: render.render_mortgage_statement(h, prop, loan, y, p)))
    plan.append(("closing_statement_1.pdf", lambda p: render.render_closing_statement(h, h.by_key("p3"), p)))
    plan.append(("appraisal_1.pdf", lambda p: render.render_appraisal(h, h.by_key("p1"), p)))
    return plan


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def household_gold(h: Household) -> dict:
    props = {}
    for p in h.properties:
        variants = sorted(set(p.address_by_year.values()) | ({p.appraisal[2]} if p.appraisal else set())
                          | {lo.statement_address for lo in p.loans})
        props[p.key] = {
            "nickname": p.nickname,
            "address": p.address.one_line(),
            "address_variants": variants,
            "property_type": p.property_type,
            "type_code": p.type_code,
            "units": p.units,
            "years_on_return": sorted(p.years),
            "purchase_date": p.purchase_date.isoformat(),
            "purchase_price_cents": p.purchase_price * 100,
            "avg_stay_nights": p.avg_stay_nights,
            "depreciation": {
                str(y): {"claimed_cents": py.expenses[18] * 100, "allowable_cents": py.depreciation_allowable * 100}
                for y, py in p.years.items()
            },
            "loans": [
                {"key": lo.key, "lender": lo.lender, "loan_type": lo.loan_type, "lien_position": lo.lien_position,
                 "is_paid_off": lo.paid_off_date is not None,
                 "arm_reset_date": lo.arm_reset.isoformat() if lo.arm_reset else None,
                 "io_end_date": lo.io_end.isoformat() if lo.io_end else None}
                for lo in p.loans
            ],
        }
    return {
        "name": h.name,
        "filing_status": h.filing_status,
        "state": h.address.state,
        "goal": h.goal,
        "magi_cents_by_year": {str(y): hy.magi * 100 for y, hy in h.years.items()},
        "agi_cents_by_year": {str(y): hy.agi * 100 for y, hy in h.years.items()},
        "suspended_loss_cents_by_year": {str(y): hy.form_8582.unallowed_total * 100 for y, hy in h.years.items()},
        "properties": props,
    }


def generate(out: Path, seed: int = 20240601, scans: bool = True, scan_params: dict | None = None,
             scan_suffix: str = ".scan.pdf", seed_out: Path | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    h = build_household(seed)
    docs = []
    for fname, fn in _doc_plan(h):
        path = out / fname
        meta = fn(str(path))
        entry = {"file": fname, "sha256": _sha(path), **meta}
        if scans:
            scan_name = fname[:-4] + scan_suffix
            degrade(path, out / scan_name, **(scan_params or DEFAULT))
            entry["scan_file"] = scan_name
        docs.append(entry)
    gold = {
        "schema": "groundplan.gold.v1",
        "seed": seed,
        "household": household_gold(h),
        "planted": h.planted,
        "documents": docs,
    }
    (out / "gold.json").write_text(json.dumps(gold, indent=2, sort_keys=True) + "\n")
    if seed_out is not None:
        from gp_pipeline.synth.seed_export import write_seed

        write_seed(seed_out, h)
    return gold


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gp-pipeline synth", description=__doc__)
    ap.add_argument("--out", default="../fixtures/documents", type=Path)
    ap.add_argument("--seed", default=20240601, type=int)
    ap.add_argument("--no-scan", action="store_true", help="skip the rasterized .scan.pdf variants")
    ap.add_argument("--seed-out", type=Path, default=None,
                    help="where to write the backend demo seed JSON (default: <out>/../seed/okafor-lindqvist.json)")
    args = ap.parse_args(argv)
    seed_out = args.seed_out or args.out.parent / "seed" / "okafor-lindqvist.json"
    gold = generate(args.out, args.seed, scans=not args.no_scan, seed_out=seed_out)
    n = sum(len(d["fields"]) for d in gold["documents"])
    print(f"wrote {len(gold['documents'])} documents ({n} gold fields) to {args.out}")
    return 0
