"""Regenerate fixtures/engine/*.json from the case definitions below.

Each case has `hand` (expected values worked out by hand / from the spec's worked examples; the generator ASSERTS
the engine reproduces them) and optional `capture` (extra result keys recorded from the engine after review, so
the Go port is held to the same cents). Run: `uv run python -m scripts.gen_fixtures` (writes, then verifies).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from groundplan.engine.golden import compare, run_case

OUT = Path(__file__).resolve().parents[2] / "fixtures" / "engine"
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
FIRST_PCT = ["3.485", "3.182", "2.879", "2.576", "2.273", "1.970", "1.667", "1.364", "1.061", "0.758", "0.455", "0.152"]


def C(name, fn, inp, hand=None, capture=()):  # noqa: N802
    return {"name": name, "fn": fn, "input": inp, "hand": hand or {}, "capture": list(capture)}


FILES: dict[str, tuple[str, list[dict]]] = {}

# ---------------------------------------------------------------- depreciation
dep = []
for m in range(1, 13):
    dep.append(C(f"residential_27_5_{MONTHS[m - 1]}", "depreciation_schedule",
                 {"basis_cents": 10_000_000, "placed_in_service": f"2000-{m:02d}-15", "class": "residential"},
                 {"first_year_pct": FIRST_PCT[m - 1], "first_year_cents": int(round(float(FIRST_PCT[m - 1]) * 100_000)),
                  "second_year_cents": 363_600, "total_cents": 10_000_000},
                 ["years", "last_year", "last_year_cents", "year28_cents"]))
dep.append(C("residential_year28_remainder_jan", "depreciation_schedule",
             {"basis_cents": 10_000_000, "placed_in_service": "2000-01-15"},
             # 100,000 - 3,485 - 26 x 3,636 = 1,979.00 (IRS table shows 1.970 because it alternates 3.637/3.636 in yrs 10-27)
             {"years": 28, "year28_cents": 197_900, "last_year": 2027}))
dep.append(C("nonresidential_39_mar", "depreciation_schedule",
             {"basis_cents": 10_000_000, "placed_in_service": "2010-03-01", "class": "nonresidential"},
             {"first_year_pct": "2.033", "first_year_cents": 203_300, "second_year_cents": 256_400, "total_cents": 10_000_000},
             ["years", "last_year_cents"]))
dep.append(C("worked_example_d_table", "depreciation_schedule",
             {"basis_cents": 28_000_000, "placed_in_service": "2011-10-15", "mode": "table", "accumulated_through": 2025},
             {"first_year_cents": 212_240, "second_year_cents": 1_018_080, "accumulated_cents": 14_465_360}))
dep.append(C("worked_example_d_simple", "depreciation_schedule",
             {"basis_cents": 28_000_000, "placed_in_service": "2011-10-15", "mode": "simple", "accumulated_through": 2025},
             # 280,000/27.5 = 10,181.82; Oct = 3/12 first year; 14.25 years -> 145,090.93
             {"first_year_cents": 254_545, "second_year_cents": 1_018_182, "accumulated_cents": 14_509_093}))
dep.append(C("basis_worked_example_d", "depreciation_basis", {"purchase_price_cents": 40_000_000, "land_pct": "0.30"},
             {"basis_cents": 28_000_000, "bounded": False}))
dep.append(C("basis_land_bounded_high", "depreciation_basis",
             {"purchase_price_cents": 40_000_000, "improvements_cents": 0, "land_pct": "0.70"},
             {"basis_cents": 16_000_000, "land_pct": "0.60", "bounded": True}))
dep.append(C("basis_default_land_estimated", "depreciation_basis", {"purchase_price_cents": 50_000_000, "improvements_cents": 5_000_000},
             {"basis_cents": 38_500_000, "land_pct": "0.30", "status": "estimated"}))
dep.append(C("allowed_less_than_allowable_outlier", "depreciation_full",
             {"purchase_price_cents": 60_000_000, "land_pct": "0.30", "placed_in_service": "2024-06-10", "property_type": "sfr",
              "as_of_year": 2025, "ledger": [{"tax_year": 2024, "allowed_cents": 728_112, "allowable_cents": 827_400, "method": "sl_27_5"}]},
             # allowable 2024 = 420,000 x 1.970% = 8,274; return claimed 12% less = 7,281.12; recapture uses allowable
             {"accumulated_cents": 827_400, "outlier": True, "current_year_cents": 1_527_120}))
dep.append(C("cost_seg_bonus_tagged_1245", "depreciation_full",
             {"purchase_price_cents": 100_000_000, "land_pct": "0.30", "placed_in_service": "2022-01-15", "property_type": "sfr",
              "as_of_year": 2024, "cost_seg_study": True,
              "ledger": [{"tax_year": 2022, "allowed_cents": 15_000_000, "method": "bonus"},
                         {"tax_year": 2023, "allowed_cents": 2_000_000, "method": "cost_seg"}]},
             # SL table 2022 = 700,000 x 3.485% = 24,395; 2023 = 25,452; ledger 170,000 -> 1245 = 170,000 - 49,847 = 120,153
             {"accumulated_cents": 17_000_000, "sec1245_cents": 12_015_300}))
FILES["depreciation"] = ("MACRS 27.5/39-yr mid-month table by month, year-28 remainder, worked example (d) in both modes, "
                         "land bounding, allowed-vs-allowable, cost-seg 1245 tagging", dep)

# ---------------------------------------------------------------- loans
ln = [
    C("fixed_30yr_300k_6_5", "loan_schedule",
      {"loan_type": "fixed", "balance_cents": 30_000_000, "balance_as_of": "2024-12-31", "rate": "0.065", "term_months": 360,
       "years": [2025, 2054], "rows": [1, 360]},
      {"months": 360, "first_payment_cents": 189_620, "last_balance_cents": 0}, ["annual", "row1", "row360"]),
    C("interest_only_36_then_amortizing", "loan_schedule",
      {"loan_type": "interest_only", "balance_cents": 50_000_000, "balance_as_of": "2024-12-31", "rate": "0.0575",
       "term_months": 360, "io_months": 36, "years": [2025, 2027, 2028], "rows": [36, 37]},
      # IO: 500,000 x 5.75% / 12 = 2,395.83/month; 2025 interest = 12 x 2,395.83
      {"first_payment_cents": 239_583, "months": 360}, ["annual", "row36", "row37"]),
    C("arm_7_1_io_reset_2027", "loan_schedule",
      {"loan_type": "arm", "balance_cents": 50_000_000, "balance_as_of": "2024-12-31", "rate": "0.0575", "term_months": 360,
       "io_months": 30, "arm_reset_date": "2027-07-01", "arm_index": "0.04", "arm_index_margin": "0.0275",
       "years": [2026, 2027, 2028], "rows": [30, 31]},
      {"first_payment_cents": 239_583}, ["annual", "row30", "row31", "months"]),
    C("heloc_interest_only_revolving", "loan_schedule",
      {"loan_type": "heloc", "balance_cents": 6_000_000, "balance_as_of": "2024-12-31", "rate": "0.085", "term_months": 120,
       "years": [2025, 2030]},
      # 60,000 x 8.5% = 5,100/yr interest, no principal
      {"first_payment_cents": 42_500, "last_balance_cents": 6_000_000,
       "annual": [{"year": 2025, "principal_cents": 0, "interest_cents": 510_000, "debt_service_cents": 510_000,
                   "balloon_cents": 0, "balance_end_cents": 6_000_000},
                  {"year": 2030, "principal_cents": 0, "interest_cents": 510_000, "debt_service_cents": 510_000,
                   "balloon_cents": 0, "balance_end_cents": 6_000_000}]}, ["months"]),
    C("balloon_25yr_amort_5yr_maturity", "loan_schedule",
      {"loan_type": "balloon", "balance_cents": 100_000_000, "balance_as_of": "2024-12-31", "rate": "0.07", "term_months": 300,
       "maturity_date": "2029-12-31", "years": [2025, 2029]},
      {"last_balance_cents": 0}, ["annual", "months", "first_payment_cents"]),
    C("paid_off_first_lien_contributes_zero", "loan_schedule",
      {"loan_type": "fixed", "balance_cents": 0, "balance_as_of": "2024-12-31", "rate": "0.04", "is_paid_off": True,
       "years": [2025]},
      {"months": 0, "annual": [{"year": 2025, "principal_cents": 0, "interest_cents": 0, "debt_service_cents": 0,
                                "balloon_cents": 0, "balance_end_cents": 0}]}),
]
FILES["loans"] = ("Monthly amortization: fixed, interest-only, ARM reset, HELOC, balloon, paid-off lien", ln)

# ---------------------------------------------------------------- cash flow
cf = [
    C("worked_example_a_duplex", "cash_flow_bridge",
      {"gross_rent_cents": 4_800_000, "other_cents": 1_800_000, "mortgage_interest_cents": 900_000,
       "depreciation_cents": 900_000, "principal_paid_cents": 600_000},
      {"line21_cents": 1_200_000, "cash_flow_from_return_cents": 1_500_000, "net_cash_flow_cents": 1_500_000, "delta_cents": 0}),
    C("worked_example_b_sfr", "cash_flow_bridge",
      {"gross_rent_cents": 3_000_000, "other_cents": 1_200_000, "mortgage_interest_cents": 1_400_000,
       "depreciation_cents": 1_200_000, "principal_paid_cents": 400_000},
      {"line21_cents": -800_000, "cash_flow_from_return_cents": 0, "net_cash_flow_cents": 0, "delta_cents": 0}),
    C("vacancy_and_capex_reserve_create_delta", "cash_flow_bridge",
      {"gross_rent_cents": 4_800_000, "taxes_cents": 600_000, "insurance_cents": 200_000, "repairs_cents": 300_000,
       "mgmt_cents": 400_000, "utilities_cents": 100_000, "hoa_cents": 0, "other_cents": 200_000,
       "mortgage_interest_cents": 900_000, "depreciation_cents": 900_000, "principal_paid_cents": 600_000,
       "vacancy_rate": "0.05", "capex_reserve_rate": "0.05"},
      # NOI = 48,000 x 0.95 - 18,000 - 2,400 = 25,200; net = 25,200 - 15,000 = 10,200; return view 15,000
      {"noi_cents": 2_520_000, "net_cash_flow_cents": 1_020_000, "cash_flow_from_return_cents": 1_500_000, "delta_cents": -480_000}),
    C("capital_improvements_reduce_return_cash_flow", "cash_flow_bridge",
      {"gross_rent_cents": 4_800_000, "other_cents": 1_800_000, "mortgage_interest_cents": 900_000, "depreciation_cents": 900_000,
       "principal_paid_cents": 600_000, "capital_improvements_paid_cents": 500_000},
      {"cash_flow_from_return_cents": 1_000_000}),
]
FILES["cashflow"] = ("NOI, net cash flow and the Schedule E bridge incl. worked examples (a) and (b)", cf)

# ---------------------------------------------------------------- passive
pa = [
    C("magi_100k_full_allowance", "passive_allowance", {"net_rental_cents": -3_000_000, "magi_cents": 10_000_000},
      {"allowance_cents": 2_500_000, "deductible_cents": 2_500_000, "suspended_new_cents": 500_000, "carryforward_end_cents": 500_000}),
    C("worked_example_c_magi_130k", "passive_allowance", {"net_rental_cents": -2_000_000, "magi_cents": 13_000_000},
      {"allowance_cents": 1_000_000, "deductible_cents": 1_000_000, "suspended_new_cents": 1_000_000}),
    C("worked_example_c_magi_140k", "passive_allowance", {"net_rental_cents": -2_000_000, "magi_cents": 14_000_000},
      {"allowance_cents": 500_000, "deductible_cents": 500_000, "suspended_new_cents": 1_500_000}),
    C("worked_example_c_magi_150k", "passive_allowance",
      {"net_rental_cents": -2_000_000, "magi_cents": 15_000_000, "prior_carryforward_cents": 1_420_000},
      {"allowance_cents": 0, "deductible_cents": 0, "suspended_new_cents": 2_000_000, "carryforward_end_cents": 3_420_000}),
    C("mfs_living_together_zero", "passive_allowance",
      {"net_rental_cents": -1_000_000, "magi_cents": 5_000_000, "filing_status": "mfs"}, {"allowance_cents": 0, "deductible_cents": 0}),
    C("no_active_participation_zero", "passive_allowance",
      {"net_rental_cents": -1_000_000, "magi_cents": 5_000_000, "active_participation": False}, {"allowance_cents": 0}),
    C("re_professional_fully_deductible", "passive_allowance",
      {"net_rental_cents": -6_000_000, "magi_cents": 30_000_000, "re_professional": True},
      {"deductible_cents": 6_000_000, "suspended_new_cents": 0}),
    C("net_income_absorbs_carryforward", "passive_allowance",
      {"net_rental_cents": 500_000, "magi_cents": 20_000_000, "prior_carryforward_cents": 1_420_000},
      {"deductible_cents": 500_000, "carryforward_end_cents": 920_000}),
    C("taxable_sale_releases_suspended", "passive_release", {"carryforward_cents": 1_420_000, "disposition": "taxable_sale"},
      {"released_cents": 1_420_000}),
    C("exchange_does_not_release", "passive_release", {"carryforward_cents": 1_420_000, "disposition": "exchange"},
      {"released_cents": 0}),
]
FILES["passive"] = ("Passive loss allowance phase-out (worked example (c)), MFS, RE professional, release vs 1031", pa)

# ---------------------------------------------------------------- tax stacking / exit tax
tx = [
    C("stack_low_income_1250_under_25pct", "tax_stack",
      {"ordinary_taxable_cents": 3_000_000, "sec1250_cents": 10_000_000, "ltcg_cents": 5_000_000, "filing_status": "mfj"},
      # 1250: 12% on 66,950 (30,000->96,950) = 8,034 + 22% on 33,050 = 7,271 -> 15,305; LTCG at 130k+ -> 15% x 50,000
      {"tax_1250_cents": 1_530_500, "rates_1250": ["0.12", "0.22"], "tax_ltcg_cents": 750_000, "rates_ltcg": ["0.15"]}),
    C("stack_mid_income", "tax_stack",
      {"ordinary_taxable_cents": 15_000_000, "sec1250_cents": 10_000_000, "ltcg_cents": 20_000_000, "filing_status": "mfj"},
      # 1250: 22% x 56,700 + 24% x 43,300 = 22,866; LTCG 250k->450k all 15% = 30,000
      {"tax_1250_cents": 2_286_600, "rates_1250": ["0.22", "0.24"], "tax_ltcg_cents": 3_000_000}),
    C("stack_high_income_1250_capped", "tax_stack",
      {"ordinary_taxable_cents": 45_000_000, "sec1250_cents": 10_000_000, "ltcg_cents": 20_000_000, "filing_status": "mfj"},
      # ordinary on 450k MFJ = 98,126; 1250 entirely in 32%/35% brackets -> capped 25% = 25,000;
      # LTCG 550k->750k: 15% x 50,050 + 20% x 149,950 = 37,497.50
      {"tax_ordinary_cents": 9_812_600, "tax_1250_cents": 2_500_000, "rates_1250": ["0.25", "0.25"],
       "tax_ltcg_cents": 3_749_750, "rates_ltcg": ["0.15", "0.20"]}),
    C("stack_with_1245_no_cap", "tax_stack",
      {"ordinary_taxable_cents": 45_000_000, "sec1245_cents": 5_000_000, "sec1250_cents": 0, "ltcg_cents": 0, "filing_status": "mfj"},
      # 1245 from 450k to 500k entirely in the 32% bracket (to 501,050) -> 16,000
      {"tax_1245_cents": 1_600_000}),
    C("niit_exactly_at_threshold", "niit", {"nii_cents": 5_000_000, "magi_cents": 25_000_000, "filing_status": "mfj"}, {"niit_cents": 0}),
    C("niit_one_dollar_over", "niit", {"nii_cents": 5_000_000, "magi_cents": 25_000_100, "filing_status": "mfj"}, {"niit_cents": 4}),
    C("niit_capped_by_nii", "niit", {"nii_cents": 2_000_000, "magi_cents": 30_000_000, "filing_status": "mfj"}, {"niit_cents": 76_000}),
    C("niit_single_threshold", "niit", {"nii_cents": 10_000_000, "magi_cents": 23_000_000, "filing_status": "single"}, {"niit_cents": 114_000}),
    C("exit_tax_wa_mfj_hand_checked", "exit_tax",
      {"sale": {"sale_price_cents": 100_000_000, "purchase_price_cents": 50_000_000, "accumulated_depreciation_cents": 15_000_000},
       "household": {"filing_status": "mfj", "state": "WA", "wages_cents": 20_000_000, "magi_cents": 20_000_000}},
      # see README "worked exit tax": gain 590k, 1250 150k -> 35,236; LTCG 440k -> 73,922.50; NIIT 540k x 3.8% = 20,520
      {"total_gain_cents": 59_000_000, "unrecaptured_1250_cents": 15_000_000, "ltcg_cents": 44_000_000, "fed_1250_cents": 3_523_600,
       "fed_ltcg_cents": 7_392_250, "niit_cents": 2_052_000, "state_cents": 0, "total_cents": 12_967_850,
       "net_before_tax_cents": 94_000_000, "net_proceeds_cents": 81_032_150, "rates_1250": ["0.22", "0.24"]}),
    C("exit_tax_ca_with_payoff", "exit_tax",
      {"sale": {"sale_price_cents": 85_000_000, "loan_payoff_cents": 18_000_000, "purchase_price_cents": 31_000_000,
                "improvements_cents": 2_000_000, "accumulated_depreciation_cents": 11_500_000},
       "household": {"filing_status": "mfj", "state": "CA", "wages_cents": 16_000_000, "other_income_cents": 2_600_000,
                     "magi_cents": 18_600_000}},
      {"total_gain_cents": 58_400_000, "unrecaptured_1250_cents": 11_500_000},
      ["fed_1250_cents", "fed_ltcg_cents", "niit_cents", "state_cents", "total_cents", "net_proceeds_cents"]),
    C("exit_tax_released_suspended_losses", "exit_tax",
      {"sale": {"sale_price_cents": 100_000_000, "purchase_price_cents": 50_000_000, "accumulated_depreciation_cents": 15_000_000},
       "household": {"filing_status": "mfj", "state": "WA", "wages_cents": 20_000_000, "magi_cents": 20_000_000,
                     "released_cents": 1_420_000}},
      # released losses lower ordinary taxable income by 14,200 -> the 1250 layer shifts down
      {"total_gain_cents": 59_000_000}, ["fed_1250_cents", "fed_ltcg_cents", "niit_cents", "total_cents"]),
    C("section_121_converted_residence", "exit_tax",
      {"sale": {"sale_price_cents": 90_000_000, "purchase_price_cents": 40_000_000, "accumulated_depreciation_cents": 2_000_000,
                "sale_date": "2025-12-31", "former_residence_until": "2024-06-30"},
       "household": {"filing_status": "mfj", "state": "WA", "wages_cents": 10_000_000, "magi_cents": 10_000_000}},
      # realized 846k, basis 380k, gain 466k; 1250 20k stays taxable; 446k excluded (cap 500k) -> LTCG 0
      {"total_gain_cents": 46_600_000, "unrecaptured_1250_cents": 2_000_000, "sec121_excluded_cents": 44_600_000, "ltcg_cents": 0,
       "fed_ltcg_cents": 0, "finding_count": 1}, ["fed_1250_cents", "total_cents"]),
    C("section_121_outside_window", "exit_tax",
      {"sale": {"sale_price_cents": 90_000_000, "purchase_price_cents": 40_000_000, "accumulated_depreciation_cents": 2_000_000,
                "sale_date": "2025-12-31", "former_residence_until": "2019-06-30"},
       "household": {"filing_status": "mfj", "state": "WA", "wages_cents": 10_000_000, "magi_cents": 10_000_000}},
      {"sec121_excluded_cents": 0, "ltcg_cents": 44_600_000}),
    C("state_ca_marginal", "state_tax", {"state": "CA", "gain_cents": 50_000_000, "other_income_cents": 18_600_000, "filing_status": "mfj"},
      {"finding_kinds": []}, ["state_tax_cents"]),
    C("state_wa_real_estate_exempt", "state_tax", {"state": "WA", "gain_cents": 50_000_000, "other_income_cents": 0, "filing_status": "mfj"},
      {"state_tax_cents": 0}),
    C("state_unsupported_finding", "state_tax", {"state": "HI", "gain_cents": 50_000_000, "other_income_cents": 0, "filing_status": "mfj"},
      {"state_tax_cents": 0, "status": "estimated", "finding_kinds": ["unsupported_structure"]}),
    C("state_flat_co", "state_tax", {"state": "CO", "gain_cents": 10_000_000, "other_income_cents": 5_000_000, "filing_status": "single"},
      {"state_tax_cents": 440_000}),
    C("state_clawback_out_of_state_replacement", "state_tax",
      {"state": "OR", "gain_cents": 10_000_000, "other_income_cents": 5_000_000, "filing_status": "mfj", "replacement_state": "TX"},
      {"finding_kinds": ["info"]}),
]
FILES["tax"] = ("Bracket stacking at 3 income levels (one with 1250 under 25%), 1245, NIIT threshold edges, exit tax, "
                "Section 121, state table incl. unsupported state", tx)

# ---------------------------------------------------------------- strategies
base_prop = {
    "id": "duplex", "property_type": "multifamily", "purchase_date": "2012-05-01", "purchase_price_cents": 31_000_000,
    "land_pct": "0.30", "improvements_cents": 2_000_000, "current_value_cents": 78_000_000, "appreciation_rate": "0.035",
    "rent_growth_rate": "0.03", "expense_growth_rate": "0.03", "vacancy_rate": "0.05", "capex_reserve_rate": "0.05",
    "selling_cost_rate": "0.06",
    "loans": [{"loan_type": "fixed", "balance_cents": 18_500_000, "balance_as_of": "2025-12-31", "rate": "0.0375", "term_months": 196}],
    "years": {"2025": {"gross_rent_cents": 5_040_000, "taxes_cents": 620_000, "insurance_cents": 210_000, "repairs_cents": 380_000,
                       "utilities_cents": 240_000, "other_cents": 90_000, "mortgage_interest_cents": 700_000,
                       "depreciation_cents": 840_000}},
}
hh = {"filing_status": "mfj", "state": "CA", "tax_year": 2025, "wages_cents": 16_000_000, "other_income_cents": 1_200_000,
      "magi_cents": 18_600_000, "carryforward_cents": 1_420_000}
debt_2025 = 18_500_000
st = [
    C("1031_no_boot_release_vs_not", "strategies", {"property": base_prop, "household": hh, "horizon_years": 10},
      {"boot_cents": 0, "tax_on_boot_cents": 0, "sell_released_cents": 1_420_000, "exchange_released_cents": 0, "recommended": None},
      ["hold_terminal_wealth_cents", "sell_terminal_wealth_cents", "exchange_terminal_wealth_cents", "sell_tax_now_cents",
       "gain_deferred_cents"]),
    C("1031_full_mortgage_boot", "strategies",
      {"property": base_prop, "household": hh, "exchange": {"replacement_debt_cents": 0}},
      {"mortgage_boot_cents": debt_2025, "boot_cents": debt_2025}, ["tax_on_boot_cents", "gain_deferred_cents",
                                                                   "exchange_terminal_wealth_cents"]),
    C("1031_partial_mortgage_boot_plus_cash", "strategies",
      {"property": base_prop, "household": hh, "exchange": {"replacement_debt_cents": 10_000_000, "cash_taken_cents": 2_000_000}},
      {"mortgage_boot_cents": 8_500_000, "boot_cents": 10_500_000}, ["tax_on_boot_cents", "gain_deferred_cents",
                                                                    "exchange_terminal_wealth_cents"]),
    C("dst_load_reduces_working_equity", "strategies",
      {"property": base_prop, "household": hh, "exchange": {"dst": True, "load_rate": "0.085", "dst_yield": "0.05"}},
      # exchange equity = 780,000 x 0.94 - 185,000 = 548,200; load 8.5% = 46,597
      {"dst_load_cents": 4_659_700, "boot_cents": 0}, ["exchange_terminal_wealth_cents"]),
]
FILES["strategies"] = ("Hold / sell / 1031 incl. full and partial mortgage boot, DST load, suspended-loss release vs carry", st)


def build() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    failures = 0
    for name, (desc, cases) in FILES.items():
        out_cases = []
        for c in cases:
            actual = run_case(c)
            diffs = compare(c["hand"], actual)
            if diffs:
                failures += 1
                print(f"HAND MISMATCH {name}/{c['name']}: {diffs}", file=sys.stderr)
            expected = dict(c["hand"])
            for k in c["capture"]:
                expected.setdefault(k, actual[k])
            out_cases.append({"name": c["name"], "fn": c["fn"], "input": c["input"], "expected": expected,
                              "hand_checked": sorted(c["hand"].keys())})
        doc = {"description": desc, "rounding": "Decimal exact, ROUND_HALF_UP to the cent once per figure/row",
               "cases": out_cases}
        (OUT / f"{name}.json").write_text(json.dumps(doc, indent=2) + "\n")
        print(f"wrote {name}.json ({len(out_cases)} cases)")
    return failures


if __name__ == "__main__":
    sys.exit(1 if build() else 0)
