"""Load the Okafor-Lindqvist demo household (SPEC §4.1) straight into the DB, without the pipeline.

Idempotent: deletes any previous copy of the demo household for the dev advisor first.
Run: `uv run python -m scripts.seed` (uses GP_DATABASE_URL, default groundplan_dev).
Numbers are realistic for Sacramento-area / Tahoe rentals; the planted mess mirrors what the pipeline raises.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from groundplan.config import get_settings
from groundplan.db import base
from groundplan.db import models as m
from groundplan.engine.loans import LoanInput, build_schedule

DEMO_NAME = "Okafor-Lindqvist household"


def _usd(x: float) -> int:
    return int(round(x * 100))


def _balance(original: float, rate: str, term: int, start: date, as_of: date) -> int:
    s = build_schedule(LoanInput("fixed", _usd(original), start, rate, term_months=term))
    return s.balance_at(as_of)


def ensure_advisor(s: Session, advisor_id: str | None = None, name: str = "Dev Advisor",
                   firm: str = "Groundplan Demo Advisory") -> m.Advisor:
    advisor_id = advisor_id or get_settings().dev_advisor_id
    a = s.get(m.Advisor, advisor_id)
    if a is None:
        a = m.Advisor(id=advisor_id, advisor_id=advisor_id, firm_name=firm, name=name, email="advisor@example.com")
        s.add(a)
        s.flush()
    return a


def seed(s: Session, advisor_id: str | None = None) -> m.Household:
    adv = ensure_advisor(s, advisor_id)
    aid = adv.id
    for old in s.execute(m.scoped(m.Household, aid).where(m.Household.name == DEMO_NAME)).scalars():
        s.delete(old)
    s.flush()
    h = m.Household(advisor_id=aid, name=DEMO_NAME, filing_status="mfj", state="CA", tax_year_latest=2025,
                    wages_cents=_usd(171_800), other_income_cents=_usd(14_600), magi_cents=_usd(186_400),
                    active_participation=True, re_professional=False, net_worth_cents=_usd(3_350_000),
                    goal="retire in 7 years, stop managing property",
                    notes="Both W-2 (hospital pharmacist + school administrator). Self-manage the duplex; Tahoe cabin run by a "
                          "local STR manager. Ages 56 and 54.")
    s.add(h)
    s.flush()

    def prop(**kw) -> m.Property:
        p = m.Property(advisor_id=aid, household_id=h.id, **kw)
        s.add(p)
        s.flush()
        return p

    def year(p: m.Property, y: int, rent: float, other_inc: float = 0, **exp) -> None:
        s.add(m.RentRoll(advisor_id=aid, property_id=p.id, tax_year=y, gross_rent_cents=_usd(rent), other_income_cents=_usd(other_inc)))
        s.add(m.ExpenseYear(advisor_id=aid, property_id=p.id, tax_year=y, **{f"{k}_cents": _usd(v) for k, v in exp.items()}))

    def ledger(p: m.Property, y: int, allowed: float, allowable: float | None = None, method: str = "sl_27_5", note: str = "") -> None:
        s.add(m.DepreciationLedger(advisor_id=aid, property_id=p.id, tax_year=y, allowed_cents=_usd(allowed),
                                   allowable_cents=_usd(allowable) if allowable is not None else None, method=method, note=note))

    def loan(p: m.Property, **kw) -> m.Loan:
        ln = m.Loan(advisor_id=aid, property_id=p.id, **kw)
        s.add(ln)
        return ln

    eoy = date(2025, 12, 31)

    # P1 Maple duplex -----------------------------------------------------------------------------
    p1 = prop(nickname="Maple duplex", address_line1="1420 Maple St", city="Sacramento", state="CA", zip="95816",
              property_type="multifamily", units=2, purchase_date=date(2012, 5, 15), purchase_price_cents=_usd(310_000),
              placed_in_service_date=date(2012, 6, 1), land_pct=Decimal("0.30"), improvements_cents=_usd(28_000),
              current_value_cents=_usd(785_000), value_source="confirmed", value_as_of=date(2025, 9, 18),
              appreciation_rate=Decimal("0.035"), rent_growth_rate=Decimal("0.03"), expense_growth_rate=Decimal("0.03"),
              vacancy_rate=Decimal("0.04"), capex_reserve_rate=Decimal("0.05"), selling_cost_rate=Decimal("0.06"),
              property_key="1420 maple st sacramento ca 95816")
    b1 = _balance(248_000, "0.03875", 360, date(2012, 6, 30), eoy)
    loan(p1, lender="Golden 1 Credit Union", loan_type="fixed", original_cents=_usd(248_000), balance_cents=b1, balance_as_of=eoy,
         rate=Decimal("0.03875"), term_months=198, monthly_payment_cents=_usd(1_166.18), maturity_date=date(2042, 6, 1), lien_position=1)
    year(p1, 2023, 48_000, taxes=3_780, insurance=1_850, repairs=4_100, utilities=1_720, other=540, mortgage_interest=7_310,
         depreciation=8_604)
    year(p1, 2024, 49_800, taxes=3_855, insurance=1_990, repairs=2_950, utilities=1_760, other=560, mortgage_interest=7_090,
         depreciation=8_604)
    year(p1, 2025, 51_600, taxes=3_930, insurance=2_240, repairs=3_400, utilities=1_810, other=610, mortgage_interest=6_860,
         depreciation=8_604)
    for y in (2023, 2024, 2025):
        ledger(p1, y, 8_604, note="Form 4562 line 22 (27.5 SL/MM)")

    # P2 Tahoe cabin (STR) ------------------------------------------------------------------------
    p2 = prop(nickname="Tahoe cabin", address_line1="885 Pine Cone Rd", city="South Lake Tahoe", state="CA", zip="96150",
              property_type="vacation_str", units=1, purchase_date=date(2019, 7, 10), purchase_price_cents=_usd(640_000),
              placed_in_service_date=date(2019, 8, 1), land_pct=Decimal("0.40"), improvements_cents=_usd(35_000),
              current_value_cents=_usd(805_000), value_source="estimated", value_as_of=date(2025, 11, 1),
              appreciation_rate=Decimal("0.03"), vacancy_rate=Decimal("0"), capex_reserve_rate=Decimal("0.04"),
              avg_stay_days=4.0, property_key="885 pine cone rd south lake tahoe ca 96150")
    b2 = _balance(512_000, "0.0425", 360, date(2019, 7, 31), eoy)
    loan(p2, lender="Chase", loan_type="fixed", original_cents=_usd(512_000), balance_cents=b2, balance_as_of=eoy,
         rate=Decimal("0.0425"), term_months=283, monthly_payment_cents=_usd(2_518.73), maturity_date=date(2049, 8, 1), lien_position=1)
    year(p2, 2023, 61_400, taxes=7_180, insurance=4_350, repairs=4_900, mgmt=14_740, utilities=5_870, other=4_620,
         mortgage_interest=20_150, depreciation=14_727)
    year(p2, 2024, 57_900, taxes=7_320, insurance=4_980, repairs=6_300, mgmt=13_900, utilities=6_040, other=4_390,
         mortgage_interest=19_790, depreciation=14_727)
    year(p2, 2025, 58_300, taxes=7_470, insurance=5_610, repairs=5_200, mgmt=13_990, utilities=6_150, other=4_480,
         mortgage_interest=19_400, depreciation=14_727)
    for y in (2023, 2024, 2025):
        ledger(p2, y, 14_727)

    # P3 Elm SFR: IO 7/1 ARM resetting 2027, bought Jun 2024, 2024 depreciation 12% under allowable ---------------
    p3 = prop(nickname="Elm SFR", address_line1="214 Elm Ct", city="Roseville", state="CA", zip="95678", property_type="sfr",
              units=1, purchase_date=date(2024, 6, 14), purchase_price_cents=_usd(615_000), placed_in_service_date=date(2024, 6, 20),
              land_pct=Decimal("0.30"), current_value_cents=_usd(632_000), value_source="estimated", value_as_of=date(2025, 10, 1),
              appreciation_rate=Decimal("0.03"), vacancy_rate=Decimal("0.05"), capex_reserve_rate=Decimal("0.05"),
              property_key="214 elm ct roseville ca 95678")
    loan(p3, lender="Rocket Mortgage", loan_type="arm", original_cents=_usd(492_000), balance_cents=_usd(492_000), balance_as_of=eoy,
         rate=Decimal("0.06125"), term_months=342, io_months=18, arm_reset_date=date(2027, 7, 1), arm_index_margin=Decimal("0.0275"),
         monthly_payment_cents=_usd(2_511.25), maturity_date=date(2054, 7, 1), lien_position=1)
    basis3 = 615_000 * 0.70
    allow24 = round(basis3 * 0.01970, 2)
    year(p3, 2024, 18_300, taxes=3_440, insurance=950, repairs=380, mgmt=1_460, other=210, mortgage_interest=15_068,
         depreciation=round(allow24 * 0.88))
    year(p3, 2025, 36_600, taxes=6_920, insurance=1_940, repairs=1_150, mgmt=2_930, other=420, mortgage_interest=30_135,
         depreciation=round(basis3 * 0.03636))
    ledger(p3, 2024, round(allow24 * 0.88), allow24, note="Return claimed 12% below allowable (preparer error)")
    ledger(p3, 2025, round(basis3 * 0.03636), round(basis3 * 0.03636))

    # P4 Oak condo: on 2023 + 2024 returns, ABSENT from 2025; HELOC 2nd, paid-off 1st ----------------------------
    p4 = prop(nickname="Oak condo", address_line1="77 Oak Ln Unit 12", city="Folsom", state="CA", zip="95630", property_type="sfr",
              units=1, purchase_date=date(2015, 3, 2), purchase_price_cents=_usd(285_000), placed_in_service_date=date(2015, 4, 1),
              land_pct=Decimal("0.25"), current_value_cents=_usd(415_000), value_source="estimated", value_as_of=date(2024, 6, 1),
              appreciation_rate=Decimal("0.03"), vacancy_rate=Decimal("0.05"), capex_reserve_rate=Decimal("0.03"),
              property_key="77 oak ln unit 12 folsom ca 95630")
    loan(p4, lender="Wells Fargo", loan_type="fixed", original_cents=_usd(228_000), balance_cents=0, balance_as_of=date(2023, 8, 31),
         rate=Decimal("0.04"), term_months=360, maturity_date=date(2045, 4, 1), lien_position=1, is_paid_off=True)
    loan(p4, lender="SAFE Credit Union HELOC", loan_type="heloc", original_cents=_usd(60_000), balance_cents=_usd(44_800),
         balance_as_of=eoy, rate=Decimal("0.0875"), term_months=96, maturity_date=date(2033, 12, 1), lien_position=2)
    year(p4, 2023, 25_800, taxes=3_210, insurance=640, repairs=1_350, utilities=0, hoa=4_680, other=300, mortgage_interest=5_120,
         depreciation=7_773)
    year(p4, 2024, 26_400, taxes=3_275, insurance=690, repairs=900, hoa=4_800, other=320, mortgage_interest=4_210, depreciation=7_773)
    for y in (2023, 2024):
        ledger(p4, y, 7_773)

    # Household: Form 8582 carryforwards ---------------------------------------------------------------------------
    for y, v in ((2023, 4_900), (2024, 9_650), (2025, 14_200)):
        s.add(m.SuspendedLoss(advisor_id=aid, household_id=h.id, tax_year=y, carryforward_cents=_usd(v)))

    # Findings (what the pipeline raises on this household) --------------------------------------------------------
    def finding(**kw) -> None:
        s.add(m.Finding(advisor_id=aid, household_id=h.id, **kw))

    finding(property_id=p2.id, key="str:p2", kind="unsupported_structure", field="property.property_type", severity="warn",
            message="Tahoe cabin: average stay 4 nights (<= 7): short-term rental rules apply; not modeled. Losses may be "
                    "nonpassive with material participation, or not deductible at all; verify with CPA.",
            candidates=[{"source": "schedule_e 2025 line 2 (fair rental 212 days / personal use 18 days)", "value": 4,
                         "document_id": None, "page": 1}])
    finding(property_id=p3.id, key="dep_outlier:p3:2024", tax_year=2024, kind="outlier", field="form_4562.depreciation", severity="warn",
            message=f"Elm SFR: 2024 depreciation claimed ${round(allow24 * 0.88):,} is 12% below the ${allow24:,.0f} allowable "
                    "(27.5 SL, June placed-in-service). Recapture uses allowable; consider Form 3115.",
            candidates=[{"source": "schedule_e 2024 line 18", "value": _usd(round(allow24 * 0.88)), "document_id": None, "page": 1},
                        {"source": "engine allowable (Pub 946 Table A-6)", "value": _usd(allow24), "document_id": None, "page": None}])
    finding(property_id=p4.id, key="missing_latest:p4", kind="missing", field="schedule_e.property", severity="warn",
            message="Oak condo appears on the 2023 and 2024 Schedule E but not on 2025: sold? converted to personal use? "
                    "Confirm status before relying on the 2025 numbers.",
            candidates=[{"source": "schedule_e 2023 column C", "value": "77 Oak Ln Unit 12", "document_id": None, "page": 1},
                        {"source": "schedule_e 2024 column C", "value": "77 OAK LANE #12", "document_id": None, "page": 1},
                        {"source": "schedule_e 2025", "value": None, "document_id": None, "page": None}])
    finding(property_id=p1.id, key="conflict:p1:rents:2025", tax_year=2025, kind="conflict", field="schedule_e.line3.rents", severity="block",
            message="Maple duplex 2025 rents disagree: Schedule E line 3 shows $51,600, the rent roll totals $50,400 "
                    "(unit B vacant in March?). Cash flow for this property is blocked until resolved.",
            candidates=[{"source": "schedule_e 2025 line 3 column A", "value": _usd(51_600), "document_id": None, "page": 1},
                        {"source": "rent roll 2025 (advisor upload)", "value": _usd(50_400), "document_id": None, "page": 1}])
    finding(property_id=p1.id, key="address_variants:p1", kind="conflict", field="property.address_line1", severity="info",
            message="Maple duplex address printed three ways across years (1420 Maple St / 1420 MAPLE STREET UNIT A/B / "
                    "1420 Maple St.); matched to one property (confidence 0.93).", status="resolved",
            candidates=[{"source": "schedule_e 2023", "value": "1420 Maple St", "document_id": None, "page": 1},
                        {"source": "schedule_e 2024", "value": "1420 MAPLE STREET UNIT A/B", "document_id": None, "page": 1},
                        {"source": "schedule_e 2025", "value": "1420 Maple St.", "document_id": None, "page": 1}],
            resolution={"value": "1420 Maple St", "who": "entity resolution (auto)", "when": "2026-01-15T00:00:00Z",
                        "note": "token-set ratio >= 0.85 + property type match"})
    s.flush()
    return h


def main() -> None:
    Session = base.configure()
    with Session() as s:
        h = seed(s)
        s.commit()
        print(f"seeded {h.name} ({h.id}) with {len(h.properties)} properties for advisor {h.advisor_id}")


if __name__ == "__main__":
    main()
