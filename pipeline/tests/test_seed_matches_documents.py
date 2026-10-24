"""The backend demo seed (fixtures/seed/okafor-lindqvist.json) and the synthetic documents describe the same household:
the pipeline's reconciled output must land on the seed's property keys with the same numbers, except the one planted
Maple 2025 rent-roll gap that the demo turns into a blocking conflict."""

from __future__ import annotations

import json

from gp_pipeline.run import run_files
from gp_pipeline.synth.seed_export import MAPLE_RENT_ROLL_SHORTFALL, build_seed

SEED_COLS = ("taxes_cents", "insurance_cents", "repairs_cents", "mgmt_cents", "utilities_cents", "hoa_cents", "other_cents",
             "mortgage_interest_cents", "depreciation_cents")


def test_committed_seed_is_current(docs):
    committed = json.loads((docs.parent / "seed" / "okafor-lindqvist.json").read_text())
    assert committed == json.loads(json.dumps(build_seed())), "run `make synth` to regenerate fixtures/seed"


def test_documents_reconcile_onto_the_seed(docs):
    seed = build_seed()
    rec = run_files(sorted(p for p in docs.glob("*.pdf") if ".scan" not in p.name))
    by_key = {p.key: p for p in rec.properties}
    assert {p["property_key"] for p in seed["properties"]} == set(by_key)
    gaps = []
    for sp in seed["properties"]:
        rp = by_key[sp["property_key"]]
        assert sp["property_type"] == rp.property_type
        for se, re_ in zip(sp["expense_years"], sorted(rp.expense_years, key=lambda e: e.tax_year), strict=True):
            assert se["tax_year"] == re_.tax_year
            assert {c: se[c] for c in SEED_COLS} == {c: getattr(re_, c) for c in SEED_COLS}, (sp["nickname"], se["tax_year"])
        for sr, rr in zip(sp["rent_rolls"], sorted(rp.rent_rolls, key=lambda r: r.tax_year), strict=True):
            if sr["gross_rent_cents"] != rr.gross_rent_cents:
                gaps.append((sp["nickname"], sr["tax_year"], rr.gross_rent_cents - sr["gross_rent_cents"]))
        for sl, rl in zip(sp["loans"], rp.loans, strict=True):
            assert sl["lien_position"] == rl.lien_position and sl["loan_type"] == rl.loan_type
            if sl["balance_as_of"] == rl.balance_as_of:
                assert sl["balance_cents"] == rl.balance_cents
    assert gaps == [("Maple duplex", 2025, MAPLE_RENT_ROLL_SHORTFALL * 100)]
    hh = seed["household"]
    assert (hh["wages_cents"], hh["magi_cents"], hh["filing_status"]) == (rec.household.wages_cents, rec.household.magi_cents, "mfj")
    assert {s["tax_year"]: s["carryforward_cents"] for s in seed["suspended_losses"] if s["carryforward_cents"]} == \
        {s.tax_year: s.carryforward_cents for s in rec.suspended_losses}
    # the seed's findings carry the pipeline's stable keys, so a re-upload updates instead of duplicating
    rec_keys = {f.key for f in rec.findings}
    for f in seed["findings"]:
        if not f["key"].startswith("address_variants:"):
            assert f["key"] in rec_keys, f["key"]
