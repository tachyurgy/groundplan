"""Export the Okafor-Lindqvist household as the backend demo seed: ``fixtures/seed/okafor-lindqvist.json``.

One source of truth: the same facts that render the synthetic PDFs become the rows every new workspace is seeded with
(Python ``backend/scripts/seed.py`` and the Go port both load this JSON). So uploading a synthetic return lands on the
EXISTING properties (same normalized address keys as the pipeline produces) and the values agree line for line,
with one deliberate exception that makes the demo's reconciliation moment:

* Maple duplex 2025 rent roll: the advisor's rent roll says $1,600 less than Schedule E line 3 (unit B vacant in
  March). Nothing flags it until the 2025 Schedule E is uploaded; then the importer raises a BLOCKING conflict, the
  cash flow goes blocked, and resolving it writes the chosen value back.

Money is integer cents, rates are decimal strings, dates ISO. Findings carry the pipeline's stable keys so a
re-upload updates them instead of duplicating.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from gp_pipeline.address import key as address_key
from gp_pipeline.finance import balance_at_year_end, monthly_payment_cents
from gp_pipeline.reconcile import EXPENSE_MAP
from gp_pipeline.synth.household import Household, build_household

SEED_VERSION = "2"
MAPLE_RENT_ROLL_SHORTFALL = 1_600  # dollars, 2025: the advisor's rent roll vs Schedule E line 3
DEMO_NAME = "Okafor-Lindqvist household"

# advisor assumptions + values the documents do not carry (estimated values are public-data style estimates)
ASSUMPTIONS = {
    "p1": dict(appreciation_rate="0.035", rent_growth_rate="0.03", expense_growth_rate="0.03", vacancy_rate="0.04",
               capex_reserve_rate="0.05", selling_cost_rate="0.06"),
    "p2": dict(appreciation_rate="0.03", vacancy_rate="0", capex_reserve_rate="0.04"),
    "p3": dict(appreciation_rate="0.03", vacancy_rate="0.05", capex_reserve_rate="0.05"),
    "p4": dict(appreciation_rate="0.03", vacancy_rate="0.05", capex_reserve_rate="0.03"),
}
ESTIMATED_VALUE = {"p2": (560_000, date(2025, 11, 1)), "p3": (625_000, date(2025, 10, 1)), "p4": (330_000, date(2024, 6, 1))}
LINE_FIELD = {"gross_rent_cents": "schedule_e.line3.rents"}  # field names the backend maps back to columns


def _c(dollars: int | float) -> int:
    return int(round(dollars * 100))


def _months_between(a: date, b: date) -> int:
    return max(0, (b.year - a.year) * 12 + b.month - a.month)


def _loans(p) -> list[dict]:
    out = []
    eoy = date(2025, 12, 31)
    for lo in p.loans:
        if lo.loan_type == "heloc":
            y = max(lo.heloc_balances)
            as_of, bal, rate = date(y, 12, 31), lo.heloc_balances[y], lo.heloc_rates.get(y, lo.rate)
            payment = round(bal * float(rate) / 12)
        elif lo.paid_off_date:
            as_of, bal, rate, payment = lo.paid_off_date, 0, lo.rate, lo.monthly_payment(lo.paid_off_date.year)
        else:
            as_of, bal, rate, payment = eoy, lo.balance_year_end(2025), lo.rate, lo.monthly_payment(2025)
        exact = None
        if lo.loan_type == "fixed" and not lo.paid_off_date:  # cents, exactly what the lender statement prints
            exact = (balance_at_year_end(lo.schedule, 2025, lo.original * 100),
                     monthly_payment_cents(lo.original * 100, lo.rate, lo.term_months))
        ltype = "arm" if lo.arm_reset else lo.loan_type
        io_months = _months_between(as_of, lo.io_end) if lo.io_end and ltype == "arm" else 0
        maturity = lo.maturity
        out.append({
            "lender": lo.lender, "loan_type": ltype, "original_cents": _c(lo.credit_limit or lo.original),
            "balance_cents": exact[0] if exact else _c(bal), "balance_as_of": as_of.isoformat(), "rate": str(rate),
            "term_months": max(1, _months_between(as_of, maturity)) if maturity else 360, "io_months": io_months,
            "arm_reset_date": lo.arm_reset.isoformat() if lo.arm_reset else None,
            "arm_index_margin": str(lo.index_margin) if lo.index_margin is not None else None,
            "monthly_payment_cents": exact[1] if exact else _c(payment), "maturity_date": maturity.isoformat() if maturity else None,
            "lien_position": lo.lien_position, "is_paid_off": lo.paid_off_date is not None,
        })
    return out


def _years(p) -> tuple[list[dict], list[dict], list[dict]]:
    rr, ex, led = [], [], []
    for y, py in sorted(p.years.items()):
        rent = py.rents - (MAPLE_RENT_ROLL_SHORTFALL if p.key == "p1" and y == 2025 else 0)
        rr.append({"tax_year": y, "gross_rent_cents": _c(rent), "other_income_cents": 0})
        row = {"tax_year": y, "hoa_cents": 0}
        for col, lines in EXPENSE_MAP.items():
            row[col] = _c(sum(py.expenses.get(int(ln.split(".")[0][4:]), 0) for ln in lines))
        ex.append(row)
        led.append({"tax_year": y, "allowed_cents": _c(py.expenses[18]), "allowable_cents": _c(py.depreciation_allowable),
                    "method": "sl_27_5",
                    "note": "Schedule E line 18; allowable per Pub 946 Table A-6" +
                            ("; return claimed 12% below allowable (preparer error)" if py.expenses[18] < py.depreciation_allowable else "")})
    return rr, ex, led


def build_seed(h: Household | None = None) -> dict:
    h = h or build_household()
    keys = {p.key: address_key(p.address_by_year[max(p.years)]) for p in h.properties}
    props = []
    for p in h.properties:
        building = p.assets[0]
        improvements = sum(a.cost for a in p.assets[1:]) + p.closing_costs
        cost = p.purchase_price + improvements
        land_pct = (Decimal(building.land) / Decimal(cost)).quantize(Decimal("0.000001"))
        rr, ex, led = _years(p)
        if p.appraisal:
            value, as_of, source = p.appraisal[1], p.appraisal[0], "confirmed"
        else:
            (value, as_of), source = ESTIMATED_VALUE[p.key], "estimated"
        props.append({
            "ref": p.key, "nickname": p.nickname,
            "address_line1": p.address.line1 + (f" {p.address.unit}" if p.address.unit else ""),
            "city": p.address.city, "state": p.address.state, "zip": p.address.zip, "property_key": keys[p.key],
            "property_type": p.property_type, "units": p.units, "purchase_date": p.purchase_date.isoformat(),
            "purchase_price_cents": _c(p.purchase_price), "placed_in_service_date": building.placed_in_service.isoformat(),
            "land_pct": str(land_pct), "improvements_cents": _c(improvements), "cost_seg_study": False,
            "current_value_cents": _c(value), "value_source": source, "value_as_of": as_of.isoformat(),
            "avg_stay_days": float(p.avg_stay_nights) if p.avg_stay_nights else None, "status": "active",
            **ASSUMPTIONS[p.key], "loans": _loans(p), "rent_rolls": rr, "expense_years": ex, "depreciation_ledger": led,
        })
    y25 = h.years[2025]
    p1, p2, p3, p4 = (h.by_key(k) for k in ("p1", "p2", "p3", "p4"))
    lender_int = p2.loans[0].interest_in_year(2025)
    se_int = p2.years[2025].expenses[12]
    d24 = p3.years[2024]
    findings = [
        {"property": "p2", "key": f"str:{keys['p2']}", "kind": "unsupported_structure", "field": "schedule_e.line1b.type",
         "severity": "warn", "tax_year": 2025,
         "message": f"Tahoe cabin: Schedule E type 3 (vacation / short-term rental), average stay {p2.avg_stay_nights} nights "
                    f"(<= 7). Short-term rental rules apply; not modeled. Losses may be non-passive with material "
                    "participation, or not a rental activity at all; verify with the CPA.",
         "candidates": [{"source": "schedule_e 2025 line 2 fair rental days", "value": p2.years[2025].fair_rental_days},
                        {"source": "schedule_e 2025 line 2 personal use days", "value": p2.years[2025].personal_use_days}]},
        {"property": "p3", "key": f"dep_outlier:{keys['p3']}:2024", "kind": "outlier", "field": "schedule_e.line18.depreciation",
         "severity": "warn", "tax_year": 2024,
         "message": f"Elm SFR: 2024 depreciation claimed ${d24.expenses[18]:,} is 12% below the ${d24.depreciation_allowable:,} "
                    "allowable (27.5 SL, July placed-in-service). Recapture uses allowed-or-allowable; consider Form 3115.",
         "candidates": [{"source": "schedule_e 2024 line 18", "value": _c(d24.expenses[18])},
                        {"source": "MACRS 27.5 SL/MM allowable (Pub 946 Table A-6)", "value": _c(d24.depreciation_allowable)}]},
        {"property": "p4", "key": f"missing_latest:{keys['p4']}", "kind": "missing", "field": "schedule_e.property",
         "severity": "warn", "tax_year": 2025,
         "message": "Oak condo appears on the 2023 and 2024 Schedule E but not on 2025: sold? converted to personal use? "
                    "Confirm status before relying on the 2025 numbers.",
         "candidates": [{"source": "schedule_e 2023 line 1a", "value": p4.address_by_year[2023]},
                        {"source": "schedule_e 2024 line 1a", "value": p4.address_by_year[2024]},
                        {"source": "schedule_e 2025", "value": None}]},
        {"property": "p2", "key": f"conflict:{keys['p2']}:mortgage_interest:2025", "kind": "conflict",
         "field": "schedule_e.line12.mortgage_interest", "severity": "warn", "tax_year": 2025,
         "message": f"Tahoe cabin 2025: Schedule E line 12 mortgage interest ${se_int:,} is ${se_int - lender_int:,} above the "
                    f"lender's year-to-date interest ${lender_int:,}. Not averaged: pick the right one.",
         "candidates": [{"source": "schedule_e 2025 line 12", "value": _c(se_int)},
                        {"source": "mortgage_statement 2025 interest_paid_ytd", "value": _c(lender_int)}]},
        {"property": "p1", "key": f"address_variants:{keys['p1']}", "kind": "conflict", "field": "property.address_line1",
         "severity": "info", "status": "resolved",
         "message": "Maple duplex address printed three ways across years (" + " / ".join(p1.address_by_year[y].split(",")[0]
                                                                                       for y in sorted(p1.address_by_year))
                    + "); matched to one property by entity resolution.",
         "candidates": [{"source": f"schedule_e {y} line 1a", "value": a} for y, a in sorted(p1.address_by_year.items())],
         "resolution": {"value": p1.address.line1, "who": "entity resolution (auto)", "when": "2026-01-15T00:00:00Z",
                        "note": "token-set ratio >= 0.85, same house number and ZIP"}},
    ]
    return {
        "seed_version": SEED_VERSION,
        "source": "generated by `python -m gp_pipeline.synth` from gp_pipeline/synth/household.py; do not hand-edit",
        "household": {
            "name": DEMO_NAME, "filing_status": h.filing_status, "state": h.address.state, "tax_year_latest": 2025,
            "wages_cents": _c(y25.wages), "other_income_cents": _c(y25.agi - y25.wages), "magi_cents": _c(y25.magi),
            "active_participation": True, "re_professional": False, "net_worth_cents": _c(2_950_000), "goal": h.goal,
            "notes": "Both W-2 (hospital pharmacist + school administrator). Self-manage the duplex; Tahoe cabin run by a "
                     "local STR manager. Ages 56 and 54.",
        },
        "properties": props,
        "suspended_losses": [{"tax_year": y, "carryforward_cents": _c(hy.form_8582.unallowed_total)}
                             for y, hy in sorted(h.years.items()) if hy.form_8582 is not None],
        "findings": findings,
        "demo": {"maple_2025_rent_roll_shortfall_cents": _c(MAPLE_RENT_ROLL_SHORTFALL),
                 "explain": "Upload 2025_schedule_e.pdf: Maple duplex line 3 disagrees with the rent roll -> blocking "
                            "conflict -> resolve it -> the cash flow is no longer blocked."},
    }


def write_seed(path: Path, h: Household | None = None) -> dict:
    data = build_seed(h)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return data
