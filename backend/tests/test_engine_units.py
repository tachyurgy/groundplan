from datetime import date
from decimal import Decimal

from groundplan.engine import observations
from groundplan.engine.analysis import analyze_property
from groundplan.engine.cashflow import YearOperations
from groundplan.engine.figure import Figure, Input, cents, derive_status
from groundplan.engine.loans import LoanInput, build_schedule
from groundplan.engine.models import HouseholdModel, PropertyModel
from groundplan.engine.narrative import TemplateNarrative, generate_narrative, number_guard
from groundplan.engine.simulate import SimProperty, SimRequest, simulate
from groundplan.engine.strategies import StrategyAssumptions, compare_strategies


def test_round_half_up_once():
    assert cents(Decimal("12.5")) == 13
    assert cents(Decimal("-12.5")) == -13
    assert cents(Decimal("12.4999")) == 12


def test_status_derivation():
    assert derive_status([Input.of("a", 1, src="document")]) == "confirmed"
    assert derive_status([Input.of("a", 1, src="document"), Input.of("b", 1, src="default")]) == "estimated"
    assert derive_status([Input.of("a", 1, src="public_data")], {"a"}) == "blocked"
    child = Figure("x", 1, "blocked")
    assert derive_status([Input.figure(child)]) == "blocked"


def test_schedule_sums_to_balance():
    s = build_schedule(LoanInput("fixed", 25_000_000, date(2025, 1, 31), "0.07", term_months=240))
    assert sum(r.principal_cents for r in s.rows) == 25_000_000
    assert s.rows[-1].balance_cents == 0


def _demo_property():
    return PropertyModel(
        id="p", nickname="Test", property_type="sfr", purchase_date=date(2019, 3, 1), purchase_price_cents=50_000_000,
        land_pct="0.30", current_value_cents=65_000_000, value_source="estimated",
        loans=[LoanInput("interest_only", 40_000_000, date(2025, 12, 31), "0.06", term_months=360, io_months=12)],
        years={2025: YearOperations(2025, 3_000_000, 0, 700_000, 200_000, 300_000, 0, 0, 0, 100_000, 2_400_000, 1_272_000)})


def test_analysis_and_observations():
    p = _demo_property()
    h = HouseholdModel(magi_cents=18_000_000)
    an = analyze_property(p, h, 2025)
    assert an["cash_flow"]["net_annual"]["status"] == "estimated"  # default vacancy/capex
    ctx = observations.property_context("Test", an, p, Decimal("0.06"), date(2026, 1, 1))
    rules = {o["rule"] for o in observations.evaluate(ctx, "property")}
    assert {"cash_flow_negative", "value_estimated", "io_ending"} <= rules


def test_strategies_never_recommend_and_same_assumptions():
    r = compare_strategies(_demo_property(), HouseholdModel(), StrategyAssumptions(horizon_years=7))
    assert r["recommended"] is None
    assert all(len(p["series"]) == 7 for p in r["paths"])
    flat = str(r).lower()
    assert "recommended': none" in flat and "recommend " not in flat
    for measure in ("terminal_wealth", "cumulative_cash_flow", "tax_paid_now", "liquidity", "management_burden", "concentration"):
        assert set(r["matrix"][measure].values()) <= {"leads", "trails", "neutral"}


class _LyingLLM:
    name = "llm:fake"

    def generate(self, facts):
        return "Your portfolio is worth $9,999,999 and returns 42.0%."


class _HonestLLM:
    name = "llm:fake"

    def generate(self, facts):
        return f"The household has {facts['total_equity']} of equity."


FACTS = {"household": {"name": "H", "goal": "retire"}, "property_count": 1, "total_value": "$500,000", "total_debt": "$100,000",
         "total_equity": "$400,000", "net_cash_flow": "$12,000", "observations": [], "exit_tax_total": "$50,000"}


def test_number_guard_rejects_invented_numbers():
    assert number_guard("worth $500,000", FACTS) == []
    assert number_guard("worth $500,001", FACTS) == ["$500,001"]
    out = generate_narrative(FACTS, _LyingLLM())
    assert out["provider"] == "template"
    assert out["guard"].startswith("narrative_number_guard")
    assert "$9,999,999" not in out["text"]


def test_number_guard_passes_cited_numbers():
    out = generate_narrative(FACTS, _HonestLLM())
    assert out["provider"] == "llm:fake" and out["guard"] == "passed"


def test_template_numbers_all_come_from_facts():
    text = TemplateNarrative().generate(FACTS)
    assert number_guard(text, FACTS) == []


def test_simulate_seeded_reproducible():
    req = SimRequest(2026, 5, [SimProperty("a", 50_000_000, 20_000_000, 0.05, 25, 3_000_000, 1_000_000)],
                     events=[{"year": 2028, "type": "sell", "property_id": "a"}], runs=50, appr_sigma=0.05, seed=3)
    a, b = simulate(req), simulate(req)
    assert a["bands"] == b["bands"]
    assert a["bands"][0]["net_worth"]["p10"] <= a["bands"][0]["net_worth"]["p50"] <= a["bands"][0]["net_worth"]["p90"]
    assert a["deterministic"][2]["taxes_paid"] > 0
