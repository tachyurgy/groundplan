"""Text-layer variant end to end: extraction, entity resolution, reconciliation, planted findings."""

from __future__ import annotations

from gp_pipeline.eval import eval_variant
from gp_pipeline.finance import res_27_5_allowable_cents
from gp_pipeline.run import run_files


def test_eval_text_variant(docs, gold):
    files = {d["file"]: docs / d["file"] for d in gold["documents"]}
    r = eval_variant(docs, gold, "text", files)
    assert r["classification"]["kind_accuracy"] == 1.0
    assert r["overall"]["recall"] >= 0.99 and r["overall"]["precision"] >= 0.99
    assert r["entity_resolution"]["accuracy"] == 1.0 and r["entity_resolution"]["resolved_properties"] == 4
    assert all(p["found"] for p in r["entity_resolution"]["planted"])
    assert r["findings"]["found"] == r["findings"]["planted"] == 5
    assert r["findings"]["unplanted_non_info"] == 0


def test_reconciled_household_maps_onto_the_domain_model(docs):
    rec = run_files(sorted(p for p in docs.glob("*.pdf") if ".scan" not in p.name))
    h = rec.household
    assert h.filing_status == "mfj" and h.state == "CA" and h.tax_year_latest == 2025 and h.magi_cents > 0
    by = {p.property_type: p for p in rec.properties}
    assert set(by) == {"multifamily", "vacation_str", "sfr"}
    duplex = by["multifamily"]
    assert duplex.years_seen == [2023, 2024, 2025] and len(duplex.address_variants) >= 3
    assert duplex.value_source == "confirmed" and duplex.current_value_cents  # appraisal
    elm = next(p for p in rec.properties if p.key.startswith("2875 elm"))
    assert elm.purchase_price_cents and elm.loans[0].loan_type == "arm" and elm.loans[0].arm_reset_date
    led = {x.tax_year: x for x in elm.depreciation_ledger}
    assert led[2024].allowable_cents == res_27_5_allowable_cents(elm.depreciable_basis_cents, __import__("datetime").date(2024, 7, 1), 2024)
    assert led[2024].allowed_cents < led[2024].allowable_cents
    oak = next(p for p in rec.properties if p.key.startswith("915 oak"))
    assert {lo.loan_type for lo in oak.loans} == {"fixed", "heloc"} and any(lo.is_paid_off for lo in oak.loans)
    assert {s.tax_year: s.carryforward_cents for s in rec.suspended_losses}[2025] > 0
    assert {f.kind for f in rec.findings} >= {"unsupported_structure", "missing", "outlier", "conflict"}
    # never averaged: the conflict carries both candidates
    c = next(f for f in rec.findings if f.kind == "conflict")
    assert len(c.candidates) >= 2 and len({x.value for x in c.candidates}) >= 2
