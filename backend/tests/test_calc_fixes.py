"""Regression tests for three calculation bugs (loans back-fill balance, 1031 cash boot, released-loss benefit).

Expected values are worked out by hand in the comments; the engine must reproduce them to the cent.
"""

from datetime import date

from groundplan.engine.analysis import annual_debt
from groundplan.engine.exit_tax import HouseholdTax, SaleInput, compute_exit_tax
from groundplan.engine.golden import _prop
from groundplan.engine.loans import LoanInput, build_schedule
from groundplan.engine.models import HouseholdModel
from groundplan.engine.strategies import ExchangeAssumptions, StrategyAssumptions, compare_strategies

# ------------------------------------------------------------------ bug 1: loans table back-fill year


def test_backfill_year_balance_is_statement_balance_not_doubled():
    # Statement says 185,000.00 owed on 2025-12-31; the schedule starts Jan 2026, so 2025 is a back-filled year.
    # The 2025 year-end balance IS the statement balance: 18,500,000 cents (the bug added it twice: 37,000,000).
    s = build_schedule(LoanInput("fixed", 18_500_000, date(2025, 12, 31), "0.0375", term_months=196))
    a, notes = annual_debt([s], 2025)
    assert a["balance_end_cents"] == 18_500_000
    assert notes  # the back-fill is still noted


def test_backfill_two_loans_sum_once():
    # two back-filled liens: 185,000 + 40,000 = 225,000.00 -> 22,500,000 cents
    s1 = build_schedule(LoanInput("fixed", 18_500_000, date(2025, 12, 31), "0.0375", term_months=196))
    s2 = build_schedule(LoanInput("fixed", 4_000_000, date(2025, 12, 31), "0.07", term_months=120))
    a, _ = annual_debt([s1, s2], 2025)
    assert a["balance_end_cents"] == 22_500_000


# ------------------------------------------------------------------ bug 3: released suspended losses


def _wa_sale() -> SaleInput:
    return SaleInput(sale_price_cents=100_000_000, purchase_price_cents=50_000_000, accumulated_depreciation_cents=15_000_000)


def test_released_loss_benefit_22pct_bracket_wa():
    # MFJ 2025, wages 200,000, std deduction 31,500 -> ordinary taxable 168,500 without the release, 154,300 with it.
    # Both inside the 22% bracket (96,950..206,700): federal saving = 14,200 x 22% = 3,124.00. WA has no income tax.
    hh = HouseholdTax(filing_status="mfj", state="WA", tax_year=2025, wages_cents=20_000_000, magi_cents=20_000_000,
                      released_suspended_losses_cents=1_420_000)
    r = compute_exit_tax(_wa_sale(), hh)
    assert r.figures["exit_tax.released_loss_benefit"].value_cents == 312_400
    no_rel = compute_exit_tax(_wa_sale(), HouseholdTax(filing_status="mfj", state="WA", tax_year=2025,
                                                       wages_cents=20_000_000, magi_cents=20_000_000))
    assert no_rel.figures["exit_tax.released_loss_benefit"].value_cents == 0
    f = r.figures
    components = sum(f[k].value_cents for k in ("exit_tax.fed_1250", "exit_tax.fed_1245", "exit_tax.fed_ltcg",
                                                 "exit_tax.niit", "exit_tax.state"))
    assert r.total_cents == components - 312_400
    assert f["exit_tax.released_loss_benefit"].notes  # explains IRC 469(g)


def test_released_loss_benefit_crosses_bracket():
    # MFJ 2025, wages 131,500 -> taxable 100,000 without the release, 85,800 with it.
    # 100,000 -> 96,950 at 22% = 3,050 x 0.22 = 671.00; 96,950 -> 85,800 at 12% = 11,150 x 0.12 = 1,338.00 -> 2,009.00
    hh = HouseholdTax(filing_status="mfj", state="WA", tax_year=2025, wages_cents=13_150_000, magi_cents=13_150_000,
                      released_suspended_losses_cents=1_420_000)
    assert compute_exit_tax(_wa_sale(), hh).figures["exit_tax.released_loss_benefit"].value_cents == 200_900


def test_released_loss_benefit_ca_magi_above_phaseout():
    # MAGI 186,000 (>150k: the 25k allowance is fully phased out, which is WHY the 14,200 was suspended).
    # Federal: 172,000 - 31,500 = 140,500 vs 126,300, both 22% -> 3,124.00.
    # CA (no state std deduction in the table): 172,000 vs 157,800, both in the 9.3% band (141,212..721,318)
    #   -> 14,200 x 0.093 = 1,320.60.  Total 4,444.60.
    hh = HouseholdTax(filing_status="mfj", state="CA", tax_year=2025, wages_cents=16_000_000, other_income_cents=1_200_000,
                      magi_cents=18_600_000, released_suspended_losses_cents=1_420_000)
    sale = SaleInput(sale_price_cents=78_000_000, loan_payoff_cents=18_500_000, purchase_price_cents=31_000_000,
                     improvements_cents=2_000_000, accumulated_depreciation_cents=11_500_000)
    assert compute_exit_tax(sale, hh).figures["exit_tax.released_loss_benefit"].value_cents == 444_460


# ------------------------------------------------------------------ bug 2: 1031 cash boot

BASE_PROP = {
    "id": "duplex", "property_type": "multifamily", "purchase_date": "2012-05-01", "purchase_price_cents": 31_000_000,
    "land_pct": "0.30", "improvements_cents": 2_000_000, "current_value_cents": 78_000_000, "appreciation_rate": "0.035",
    "rent_growth_rate": "0.03", "expense_growth_rate": "0.03", "vacancy_rate": "0.05", "capex_reserve_rate": "0.05",
    "selling_cost_rate": "0.06",
    "loans": [{"loan_type": "fixed", "balance_cents": 18_500_000, "balance_as_of": "2025-12-31", "rate": "0.0375", "term_months": 196}],
    "years": {"2025": {"gross_rent_cents": 5_040_000, "taxes_cents": 620_000, "insurance_cents": 210_000, "repairs_cents": 380_000,
                       "utilities_cents": 240_000, "other_cents": 90_000, "mortgage_interest_cents": 700_000,
                       "depreciation_cents": 840_000}},
}
HH = HouseholdModel(filing_status="mfj", state="CA", tax_year=2025, wages_cents=16_000_000, other_income_cents=1_200_000,
                    magi_cents=18_600_000, carryforward_cents=1_420_000)


def _exchange(cash: int, **kw) -> dict:
    r = compare_strategies(_prop(BASE_PROP), HH, StrategyAssumptions(horizon_years=10, reinvest_rate="0.06",
                                                                    exchange=ExchangeAssumptions(cash_taken_cents=cash, **kw)))
    return next(p for p in r["paths"] if p["path"] == "exchange")


def test_cash_boot_after_tax_is_invested_and_counted():
    # boot 50,000 (no mortgage boot). Tax year 2026 (sale Jan 2026), MFJ: ordinary 172,000 - 32,200 = 139,800; the boot is
    # all unrecaptured 1250 and lands 139,800..189,800, inside the 22% bracket (100,800..211,400) -> 11,000.00.
    # NIIT: MAGI 186,000 + 50,000 = 236,000 < 250,000 -> 0. CA 9.3% on 172,000..222,000 -> 4,650.00. Tax on boot 15,650.00.
    # After-tax cash = 50,000 - 15,650 = 34,350.00, invested at 6% for 10 years:
    #   34,350 x 1.06^10 = 34,350 x 1.7908476965 = 61,515.62 -> 6,151,562 cents.
    x = _exchange(5_000_000)
    t = x["terminal"]
    assert t["tax_on_boot_cents"] == 1_565_000
    assert t["cash_after_tax_cents"] == 3_435_000
    assert t["cash_after_tax_at_horizon_cents"] == 6_151_562
    # the replacement is bought with what is left: default replacement value = equity rolled + replacement debt
    assert t["replacement_value_cents"] == t["exchange_equity_cents"] + t["replacement_debt_cents"]
    # the series' wealth includes the invested cash every year (year 1: 34,350 x 1.06 = 36,411.00)
    x0 = _exchange(0)
    assert x["series"][-1]["wealth_cents"] == t["terminal_wealth"]["value_cents"]
    assert x0["terminal"]["cash_after_tax_at_horizon_cents"] == 0


def test_cash_boot_monotonic():
    # Taking cash out can never raise terminal wealth by more than that cash invested at the reinvest rate.
    w0 = _exchange(0)["terminal"]["terminal_wealth"]["value_cents"]
    w50 = _exchange(5_000_000)["terminal"]["terminal_wealth"]["value_cents"]
    assert w50 - w0 <= 6_151_562
    # and here (replacement earning ~7%+ vs 6% reinvest, boot tax paid now) it makes the client poorer, not richer
    assert w50 < w0
