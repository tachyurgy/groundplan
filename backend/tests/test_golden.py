"""Every case in fixtures/engine/*.json must reproduce byte-for-byte (the Go port runs the same files)."""

import json
from pathlib import Path

import pytest

from groundplan.engine.golden import compare, run_case

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "engine"
CASES = [
    pytest.param(case, id=f"{f.stem}/{case['name']}")
    for f in sorted(FIXTURES.glob("*.json")) if f.stem != "states"
    for case in json.loads(f.read_text())["cases"]
]


def test_fixture_count_covers_spec():
    names = {c.values[0]["name"] for c in CASES}
    for required in ("worked_example_a_duplex", "worked_example_b_sfr", "worked_example_c_magi_130k",
                     "worked_example_c_magi_140k", "worked_example_c_magi_150k", "worked_example_d_table",
                     "worked_example_d_simple", "residential_year28_remainder_jan", "niit_exactly_at_threshold",
                     "1031_full_mortgage_boot", "1031_partial_mortgage_boot_plus_cash", "dst_load_reduces_working_equity",
                     "section_121_converted_residence", "stack_low_income_1250_under_25pct"):
        assert required in names
    assert sum(1 for n in names if n.startswith("residential_27_5_")) == 12


@pytest.mark.parametrize("case", CASES)
def test_golden_case(case):
    assert compare(case["expected"], run_case(case)) == []
