"""The Okafor-Lindqvist household: a deterministic, internally consistent synthetic data set.

Everything the renderers print is derived here, in whole dollars, from a handful of hand-set
inputs plus real amortization and the IRS mid-month depreciation table. The deliberate
"real-world messes" of SPEC §4.1 are planted here and recorded in ``planted`` so the eval
harness can check they are found:

* P1 "Maple duplex": the address is printed three different ways across the three years.
* P2 "Tahoe cabin": type 3 (vacation/short-term rental) with personal-use days on line 2.
* P3 "Elm SFR": bought Jun 2024 (partial-year depreciation), interest-only 7/1 ARM resetting
  2027-07-01 (assumed at closing, originated 2020), and the 2024 depreciation deduction is
  12% below allowable (preparer error). The closing statement has no land/improvement split.
* P4 "Oak condo": on the 2023 and 2024 returns, absent from 2025; HELOC second lien and a
  paid-off first lien.
* Form 8582 (2025) shows a $14,200 suspended-loss carryforward.
* Extra (not in SPEC, documented): P2's 2025 Schedule E line 12 is $312 higher than the lender's
  year-end statement — a planted ``conflict``.

A ``seed`` is accepted for API symmetry: the data set is fully determined and the seed only
feeds the SSN/loan-number digits so two runs with the same seed are byte-identical.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from gp_pipeline.finance import (
    amortize,
    balance_at_year_end,
    monthly_payment_cents,
    res_27_5_allowable_cents,
    year_totals,
)

YEARS = [2023, 2024, 2025]

# Schedule E Part I expense lines (2024/2025 form): number -> label
SCHEDULE_E_EXPENSE_LINES = [
    (5, "Advertising"),
    (6, "Auto and travel (see instructions)"),
    (7, "Cleaning and maintenance"),
    (8, "Commissions"),
    (9, "Insurance"),
    (10, "Legal and other professional fees"),
    (11, "Management fees"),
    (12, "Mortgage interest paid to banks, etc. (see instructions)"),
    (13, "Other interest"),
    (14, "Repairs"),
    (15, "Supplies"),
    (16, "Taxes"),
    (17, "Utilities"),
    (18, "Depreciation expense or depletion"),
    (19, "Other (list)"),
]

PROPERTY_TYPE_CODES = {
    1: ("Single Family Residence", "sfr"),
    2: ("Multi-Family Residence", "multifamily"),
    3: ("Vacation/Short-Term Rental", "vacation_str"),
    4: ("Commercial", "commercial"),
    5: ("Land", "land"),
    6: ("Royalties", "other"),
    7: ("Self-Rental", "self_rental"),
    8: ("Other (describe)", "other"),
}

STD_DEDUCTION_MFJ = {2023: 27_700, 2024: 29_200, 2025: 31_500}
MFJ_BRACKETS = {
    2023: [(22_000, 0.10), (89_450, 0.12), (190_750, 0.22), (364_200, 0.24), (462_500, 0.32), (693_750, 0.35), (None, 0.37)],
    2024: [(23_200, 0.10), (94_300, 0.12), (201_050, 0.22), (383_900, 0.24), (487_450, 0.32), (731_200, 0.35), (None, 0.37)],
    2025: [(23_850, 0.10), (96_950, 0.12), (206_700, 0.22), (394_600, 0.24), (501_050, 0.32), (751_600, 0.35), (None, 0.37)],
}


def ordinary_tax(taxable: int, year: int) -> int:
    tax = 0.0
    lower = 0
    for cap, rate in MFJ_BRACKETS[year]:
        if cap is None or taxable <= cap:
            tax += (taxable - lower) * rate
            break
        tax += (cap - lower) * rate
        lower = cap
    return round(tax)


# --------------------------------------------------------------------------- data classes


@dataclass
class Address:
    line1: str
    city: str
    state: str
    zip: str
    unit: str = ""

    def one_line(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        return f"{self.line1}{unit}, {self.city}, {self.state} {self.zip}"


@dataclass
class Asset:
    description: str
    placed_in_service: date
    cost: int  # dollars (incl. land for the building asset)
    land: int
    note: str = ""

    @property
    def basis(self) -> int:
        return self.cost - self.land

    def allowable(self, year: int) -> int:
        return round(res_27_5_allowable_cents(self.basis * 100, self.placed_in_service, year) / 100)

    def prior_depreciation(self, year: int) -> int:
        return sum(self.allowable(y) for y in range(self.placed_in_service.year, year))


@dataclass
class Loan:
    key: str
    lender: str
    loan_number: str
    loan_type: str  # fixed | arm | interest_only | heloc
    product: str  # printed product name
    original: int
    rate: Decimal  # current annual rate
    term_months: int
    first_payment: date
    lien_position: int = 1
    io_end: date | None = None
    arm_reset: date | None = None
    index_margin: Decimal | None = None
    index_name: str = ""
    maturity: date | None = None
    paid_off_date: date | None = None
    credit_limit: int | None = None
    heloc_balances: dict[int, int] = field(default_factory=dict)  # year-end balances for HELOC
    heloc_rates: dict[int, Decimal] = field(default_factory=dict)
    heloc_interest: dict[int, int] = field(default_factory=dict)
    assumed_on: date | None = None
    originated: date | None = None
    statement_address: str = ""
    schedule: list[dict] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.loan_type == "fixed":
            self.schedule = amortize(self.original * 100, self.rate, self.term_months, self.first_payment)
            if self.maturity is None:
                last = self.schedule[-1]["date"]
                self.maturity = last

    def monthly_payment(self, year: int) -> int:
        if self.loan_type == "fixed":
            return round(monthly_payment_cents(self.original * 100, self.rate, self.term_months) / 100)
        if self.loan_type == "interest_only":
            return round(self.original * float(self.rate) / 12)
        if self.loan_type == "heloc":
            bal = self.heloc_balances[year]
            return round(bal * float(self.heloc_rates[year]) / 12)
        return 0

    def balance_year_end(self, year: int) -> int:
        if self.paid_off_date and self.paid_off_date.year <= year:
            return 0
        if self.loan_type == "fixed":
            return round(balance_at_year_end(self.schedule, year, self.original * 100) / 100)
        if self.loan_type == "interest_only":
            return self.original
        if self.loan_type == "heloc":
            return self.heloc_balances[year]
        return 0

    def interest_in_year(self, year: int) -> int:
        if self.paid_off_date and self.paid_off_date.year <= year:
            return 0
        if self.loan_type == "fixed":
            return round(year_totals(self.schedule, year)["interest"] / 100)
        if self.loan_type == "interest_only":
            months = 12 if year > self.first_payment.year else 13 - self.first_payment.month
            return round(self.original * float(self.rate) / 12 * months)
        if self.loan_type == "heloc":
            return self.heloc_interest[year]
        return 0

    def principal_in_year(self, year: int) -> int:
        if self.loan_type == "fixed":
            return round(year_totals(self.schedule, year)["principal"] / 100)
        if self.loan_type == "heloc":
            prev = self.heloc_balances.get(year - 1, self.heloc_balances[year])
            return max(0, prev - self.heloc_balances[year])
        return 0

    def active_in(self, year: int) -> bool:
        if self.paid_off_date and self.paid_off_date.year < year:
            return False
        if self.loan_type == "fixed" and self.first_payment.year > year:
            return False
        if self.loan_type == "interest_only" and self.first_payment.year > year:
            return False
        if self.loan_type == "heloc" and year not in self.heloc_balances:
            return False
        return True


@dataclass
class PropertyYear:
    year: int
    rents: int
    fair_rental_days: int
    personal_use_days: int
    expenses: dict[int, int]  # Schedule E line -> dollars
    other_label: str = ""
    depreciation_allowable: int = 0
    # filled by Form 8582 netting:
    allowed_loss: int = 0  # Schedule E line 22 (negative or 0)
    unallowed_loss: int = 0

    @property
    def total_expenses(self) -> int:  # line 20
        return sum(self.expenses.values())

    @property
    def net(self) -> int:  # line 21
        return self.rents - self.total_expenses


@dataclass
class Property:
    key: str
    nickname: str
    type_code: int
    units: int
    address: Address
    address_by_year: dict[int, str]  # Schedule E line 1a text per year
    purchase_date: date
    purchase_price: int
    closing_costs: int
    assets: list[Asset]
    loans: list[Loan]
    years: dict[int, PropertyYear]
    avg_stay_nights: int | None = None
    appraisal: tuple[date, int, str] | None = None  # (as_of, value, printed address)

    @property
    def property_type(self) -> str:
        return PROPERTY_TYPE_CODES[self.type_code][1]

    def depreciation_allowable(self, year: int) -> int:
        return sum(a.allowable(year) for a in self.assets)


@dataclass
class Form8582:
    year: int
    line1a: int
    line1b: int
    line1c: int
    line1d: int
    line3: int
    line4: int
    line5: int
    line6: int
    line7: int
    line8: int
    line9: int
    line10: int
    line11: int
    unallowed_total: int
    activities: list[dict]  # [{property_key, name, net_income, net_loss, prior_unallowed, overall, ratio, unallowed, allowed}]


@dataclass
class HouseholdYear:
    year: int
    wages: int
    taxable_interest: int
    tax_exempt_interest: int
    ordinary_dividends: int
    qualified_dividends: int
    schedule_1_line_10: int  # = Schedule E line 26
    total_income: int
    adjustments: int
    agi: int
    std_deduction: int
    taxable_income: int
    tax: int
    withholding: int
    estimated_payments: int
    total_payments: int
    refund: int
    owed: int
    magi: int
    form_8582: Form8582 | None = None
    schedule_e_totals: dict = field(default_factory=dict)


@dataclass
class Household:
    seed: int
    name: str
    taxpayer: str
    spouse: str
    ssn_masked: str
    spouse_ssn_masked: str
    address: Address
    filing_status: str
    goal: str
    properties: list[Property]
    years: dict[int, HouseholdYear]
    planted: list[dict]
    preparer: str = "Capitol Valley Tax & Accounting, Sacramento CA"

    def properties_in(self, year: int) -> list[Property]:
        return [p for p in self.properties if year in p.years]

    def by_key(self, key: str) -> Property:
        return next(p for p in self.properties if p.key == key)


# --------------------------------------------------------------------------- the data set


def _mgmt(rent: int, pct: float = 0.08) -> int:
    return round(rent * pct)


def build_household(seed: int = 20240601) -> Household:
    rng = random.Random(seed)
    ssn = f"XXX-XX-{rng.randint(1000, 9999)}"
    ssn2 = f"XXX-XX-{rng.randint(1000, 9999)}"

    def loan_no(prefix: str) -> str:
        return f"{prefix}{rng.randint(10_000_000, 99_999_999)}"

    # ---- P1 Maple duplex ------------------------------------------------------------
    p1_addr = Address("1420 Maple St", "Sacramento", "CA", "95838")
    p1_loan = Loan(
        key="p1-first",
        lender="Golden State Mortgage Co.",
        loan_number=loan_no("GSM-"),
        loan_type="fixed",
        product="30-Year Fixed Rate Mortgage",
        original=214_000,
        rate=Decimal("0.03875"),
        term_months=360,
        first_payment=date(2012, 7, 1),
        originated=date(2012, 5, 15),
        statement_address="1420 Maple St, Sacramento, CA 95838",
    )
    p1_assets = [
        Asset("Duplex building - 1420 Maple St", date(2012, 6, 1), 285_000, 72_000),
        Asset("Roof replacement (capital improvement)", date(2019, 4, 15), 18_000, 0),
    ]
    p1_years: dict[int, PropertyYear] = {}
    p1_rents = {2023: 38_400, 2024: 40_800, 2025: 42_600}
    p1_exp = {
        2023: {5: 0, 6: 240, 7: 600, 8: 0, 9: 1_840, 10: 0, 13: 0, 14: 2_650, 15: 180, 16: 3_420, 17: 1_140, 19: 0},
        2024: {5: 120, 6: 260, 7: 0, 8: 0, 9: 1_960, 10: 350, 13: 0, 14: 3_180, 15: 210, 16: 3_490, 17: 1_190, 19: 0},
        2025: {5: 0, 6: 280, 7: 900, 8: 0, 9: 2_110, 10: 0, 13: 0, 14: 2_900, 15: 240, 16: 3_560, 17: 1_260, 19: 0},
    }
    for y in YEARS:
        e = dict(p1_exp[y])
        e[11] = _mgmt(p1_rents[y])
        e[12] = p1_loan.interest_in_year(y)
        e[18] = sum(a.allowable(y) for a in p1_assets)
        p1_years[y] = PropertyYear(y, p1_rents[y], 365, 0, dict(sorted(e.items())))
        p1_years[y].depreciation_allowable = e[18]
    p1 = Property(
        key="p1",
        nickname="Maple duplex",
        type_code=2,
        units=2,
        address=p1_addr,
        address_by_year={
            2023: "1420 Maple St, Sacramento, CA 95838",
            2024: "1420 MAPLE STREET UNIT A/B, SACRAMENTO, CA 95838",
            2025: "1420 Maple St., Sacramento, CA 95838",
        },
        purchase_date=date(2012, 5, 15),
        purchase_price=285_000,
        closing_costs=0,
        assets=p1_assets,
        loans=[p1_loan],
        years=p1_years,
        appraisal=(date(2025, 3, 10), 545_000, "1420 Maple Street, Sacramento, CA 95838"),
    )

    # ---- P2 Tahoe cabin -------------------------------------------------------------
    p2_addr = Address("1187 Lakeview Dr", "South Lake Tahoe", "CA", "96150")
    p2_loan = Loan(
        key="p2-first",
        lender="Sierra Nevada Credit Union",
        loan_number=loan_no("SNCU-"),
        loan_type="fixed",
        product="30-Year Fixed Rate Mortgage",
        original=372_000,
        rate=Decimal("0.04125"),
        term_months=360,
        first_payment=date(2019, 10, 1),
        originated=date(2019, 8, 20),
        statement_address="1187 Lakeview Dr, South Lake Tahoe, CA 96150",
    )
    p2_assets = [Asset("Cabin - 1187 Lakeview Dr", date(2019, 8, 20), 465_000, 162_750)]
    p2_rents = {2023: 46_200, 2024: 49_800, 2025: 47_800}
    p2_days = {2023: (168, 24), 2024: (175, 21), 2025: (171, 18)}
    p2_exp = {
        2023: {5: 480, 6: 620, 7: 6_720, 9: 2_860, 10: 0, 11: 0, 13: 0, 14: 2_380, 15: 940, 16: 5_180, 17: 4_060, 19: 0},
        2024: {5: 520, 6: 680, 7: 7_000, 9: 3_040, 10: 0, 11: 0, 13: 0, 14: 2_910, 15: 1_020, 16: 5_290, 17: 4_210, 19: 0},
        2025: {5: 560, 6: 710, 7: 7_240, 9: 3_250, 10: 450, 11: 0, 13: 0, 14: 2_640, 15: 1_080, 16: 5_400, 17: 4_390, 19: 0},
    }
    P2_2025_INTEREST_OVERSTATEMENT = 312  # planted conflict vs. lender statement
    p2_years: dict[int, PropertyYear] = {}
    for y in YEARS:
        e = dict(p2_exp[y])
        e[8] = round(p2_rents[y] * 0.03)
        e[12] = p2_loan.interest_in_year(y) + (P2_2025_INTEREST_OVERSTATEMENT if y == 2025 else 0)
        e[18] = sum(a.allowable(y) for a in p2_assets)
        p2_years[y] = PropertyYear(y, p2_rents[y], p2_days[y][0], p2_days[y][1], dict(sorted(e.items())))
        p2_years[y].depreciation_allowable = e[18]
    p2 = Property(
        key="p2",
        nickname="Tahoe cabin",
        type_code=3,
        units=1,
        address=p2_addr,
        address_by_year={y: "1187 Lakeview Dr, South Lake Tahoe, CA 96150" for y in YEARS},
        purchase_date=date(2019, 8, 20),
        purchase_price=465_000,
        closing_costs=0,
        assets=p2_assets,
        loans=[p2_loan],
        years=p2_years,
        avg_stay_nights=4,
    )

    # ---- P3 Elm SFR -----------------------------------------------------------------
    p3_addr = Address("2875 Elm Ct", "Roseville", "CA", "95661")
    p3_loan = Loan(
        key="p3-first",
        lender="Pacific Crest Bank",
        loan_number=loan_no("PCB-"),
        loan_type="interest_only",
        product="7/1 Interest-Only ARM",
        original=457_500,
        rate=Decimal("0.05875"),
        term_months=360,
        first_payment=date(2024, 8, 1),
        io_end=date(2030, 6, 30),
        arm_reset=date(2027, 7, 1),
        index_margin=Decimal("0.0275"),
        index_name="30-Day Average SOFR",
        maturity=date(2050, 7, 1),
        assumed_on=date(2024, 6, 14),
        originated=date(2020, 7, 1),
        statement_address="2875 Elm Ct, Roseville, CA 95661",
    )
    p3_closing_costs = 7_850
    p3_assets = [
        Asset(
            "SFR - 2875 Elm Ct (incl. capitalized closing costs)",
            date(2024, 7, 1),
            610_000 + p3_closing_costs,
            173_000,
        )
    ]
    p3_rents = {2024: 20_100, 2025: 40_800}
    p3_days = {2024: (184, 0), 2025: (365, 0)}
    p3_exp = {
        2024: {5: 275, 6: 190, 7: 450, 8: 0, 9: 1_340, 10: 600, 13: 0, 14: 1_920, 15: 160, 16: 3_410, 17: 0, 19: 0},
        2025: {5: 0, 6: 310, 7: 380, 8: 0, 9: 2_760, 10: 0, 13: 0, 14: 2_180, 15: 230, 16: 7_080, 17: 0, 19: 0},
    }
    p3_years: dict[int, PropertyYear] = {}
    for y in (2024, 2025):
        e = dict(p3_exp[y])
        e[11] = _mgmt(p3_rents[y])
        e[12] = p3_loan.interest_in_year(y)
        allowable = sum(a.allowable(y) for a in p3_assets)
        e[18] = round(allowable * 0.88) if y == 2024 else allowable  # planted: 12% low in 2024
        p3_years[y] = PropertyYear(y, p3_rents[y], p3_days[y][0], p3_days[y][1], dict(sorted(e.items())))
        p3_years[y].depreciation_allowable = allowable
    p3 = Property(
        key="p3",
        nickname="Elm SFR",
        type_code=1,
        units=1,
        address=p3_addr,
        address_by_year={y: "2875 Elm Ct, Roseville, CA 95661" for y in (2024, 2025)},
        purchase_date=date(2024, 6, 14),
        purchase_price=610_000,
        closing_costs=p3_closing_costs,
        assets=p3_assets,
        loans=[p3_loan],
        years=p3_years,
    )

    # ---- P4 Oak condo ---------------------------------------------------------------
    p4_addr = Address("915 Oak Hollow Way", "Elk Grove", "CA", "95758", unit="Unit 204")
    p4_first = Loan(
        key="p4-first",
        lender="Wells Harbor Bank, N.A.",
        loan_number=loan_no("WHB-"),
        loan_type="fixed",
        product="30-Year Fixed Rate Mortgage",
        original=160_000,
        rate=Decimal("0.04250"),
        term_months=360,
        first_payment=date(2015, 5, 1),
        originated=date(2015, 3, 10),
        paid_off_date=date(2022, 12, 28),
        statement_address="915 Oak Hollow Way Unit 204, Elk Grove, CA 95758",
    )
    p4_heloc = Loan(
        key="p4-heloc",
        lender="Capital Valley Credit Union",
        loan_number=loan_no("CVCU-HE-"),
        loan_type="heloc",
        product="Home Equity Line of Credit (variable rate, interest-only draw period)",
        original=90_000,
        rate=Decimal("0.0850"),
        term_months=360,
        first_payment=date(2019, 5, 1),
        lien_position=2,
        io_end=date(2029, 4, 30),
        maturity=date(2049, 4, 30),
        credit_limit=90_000,
        heloc_balances={2022: 62_400, 2023: 62_400, 2024: 58_900},
        heloc_rates={2023: Decimal("0.0825"), 2024: Decimal("0.0850")},
        heloc_interest={2023: 5_148, 2024: 5_155},
        originated=date(2019, 4, 2),
        statement_address="915 Oak Hollow Way #204, Elk Grove, CA 95758",
    )
    p4_assets = [Asset("Condominium - 915 Oak Hollow Way Unit 204", date(2015, 4, 1), 228_000, 45_600)]
    p4_rents = {2023: 27_600, 2024: 28_800}
    p4_exp = {
        2023: {5: 0, 6: 120, 7: 0, 8: 0, 9: 940, 10: 0, 13: 0, 14: 1_180, 15: 90, 16: 2_870, 17: 0, 19: 4_560},
        2024: {5: 0, 6: 130, 7: 350, 8: 0, 9: 1_010, 10: 0, 13: 0, 14: 1_450, 15: 110, 16: 2_930, 17: 0, 19: 8_400},
    }
    p4_other_label = {2023: "HOA dues", 2024: "HOA dues and special assessment"}
    p4_years: dict[int, PropertyYear] = {}
    for y in (2023, 2024):
        e = dict(p4_exp[y])
        e[11] = _mgmt(p4_rents[y])
        e[12] = p4_heloc.interest_in_year(y)
        e[18] = sum(a.allowable(y) for a in p4_assets)
        p4_years[y] = PropertyYear(y, p4_rents[y], 365, 0, dict(sorted(e.items())), other_label=p4_other_label[y])
        p4_years[y].depreciation_allowable = e[18]
    p4 = Property(
        key="p4",
        nickname="Oak condo",
        type_code=1,
        units=1,
        address=p4_addr,
        address_by_year={y: "915 Oak Hollow Way Unit 204, Elk Grove, CA 95758" for y in (2023, 2024)},
        purchase_date=date(2015, 3, 10),
        purchase_price=228_000,
        closing_costs=0,
        assets=p4_assets,
        loans=[p4_first, p4_heloc],
        years=p4_years,
    )

    properties = [p1, p2, p3, p4]

    # ---- Household-level income ------------------------------------------------------
    hh_inputs = {
        2023: dict(wages=168_200, ti=1_120, tei=0, od=3_520, qd=3_180),
        2024: dict(wages=174_300, ti=1_480, tei=0, od=3_870, qd=3_540),
        2025: dict(wages=180_100, ti=1_640, tei=0, od=4_210, qd=3_900),
    }

    # ---- Solve the Form 8582 netting so 2024 carries 4,000 and 2025 carries 14,200 -----
    # Tuning knobs: P4 2024 repairs (line 14) and P1 2025 repairs (line 14).
    def total_net(year: int) -> int:
        return sum(p.years[year].net for p in properties if year in p.years)

    target_loss = {2024: -4_000, 2025: -10_200}  # current-year net loss targets
    gap24 = total_net(2024) - target_loss[2024]
    p4.years[2024].expenses[14] += gap24
    gap25 = total_net(2025) - target_loss[2025]
    p1.years[2025].expenses[14] += gap25
    assert total_net(2024) == -4_000 and total_net(2025) == -10_200

    years: dict[int, HouseholdYear] = {}
    prior_unallowed = 0
    for y in YEARS:
        hi = hh_inputs[y]
        magi = hi["wages"] + hi["ti"] + hi["od"]
        f8582, allowed_by_key = _net_passive(properties, y, magi, prior_unallowed)
        for p in properties:
            if y in p.years:
                p.years[y].allowed_loss, p.years[y].unallowed_loss = allowed_by_key[p.key]
        prior_unallowed = f8582.unallowed_total
        active = [p.years[y] for p in properties if y in p.years]
        line24 = sum(py.net for py in active if py.net > 0)
        line25 = sum(py.allowed_loss for py in active if py.net < 0)
        line26 = line24 + line25
        totals = {
            "23a": sum(py.rents for py in active),
            "23b": 0,
            "23c": sum(py.expenses[12] for py in active),
            "23d": sum(py.expenses[18] for py in active),
            "23e": sum(py.total_expenses for py in active),
            "24": line24,
            "25": line25,
            "26": line26,
        }
        total_income = hi["wages"] + hi["ti"] + hi["od"] + line26
        agi = total_income
        std = STD_DEDUCTION_MFJ[y]
        taxable = max(0, agi - std)
        tax = ordinary_tax(taxable, y)
        withholding = round(tax * 0.94 + 2_200)
        est = 4_000 if y >= 2024 else 0
        payments = withholding + est
        years[y] = HouseholdYear(
            year=y,
            wages=hi["wages"],
            taxable_interest=hi["ti"],
            tax_exempt_interest=hi["tei"],
            ordinary_dividends=hi["od"],
            qualified_dividends=hi["qd"],
            schedule_1_line_10=line26,
            total_income=total_income,
            adjustments=0,
            agi=agi,
            std_deduction=std,
            taxable_income=taxable,
            tax=tax,
            withholding=withholding,
            estimated_payments=est,
            total_payments=payments,
            refund=max(0, payments - tax),
            owed=max(0, tax - payments),
            magi=magi,
            form_8582=f8582,
            schedule_e_totals=totals,
        )
    assert years[2025].form_8582 is not None and years[2025].form_8582.unallowed_total == 14_200

    planted = [
        {
            "id": "p1_address_three_spellings",
            "check": "entity_resolution",
            "property_key": "p1",
            "detail": "Line 1a prints the Maple duplex three different ways across 2023/2024/2025; all must resolve to one property.",
            "variants": list(p1.address_by_year.values()),
        },
        {
            "id": "p2_str_unsupported",
            "check": "finding",
            "kind": "unsupported_structure",
            "property_key": "p2",
            "field": "schedule_e.line1b.type",
            "detail": "Type 3 vacation/short-term rental with personal-use days (avg stay 4 nights) -> STR rules not modeled.",
        },
        {
            "id": "p3_depreciation_12pct_low_2024",
            "check": "finding",
            "kind": "outlier",
            "property_key": "p3",
            "tax_year": 2024,
            "field": "depreciation",
            "detail": f"2024 depreciation claimed {p3.years[2024].expenses[18]:,} vs allowable "
            f"{p3.years[2024].depreciation_allowable:,} (basis {p3_assets[0].basis:,}, placed in service Jul 2024, 1.667%).",
        },
        {
            "id": "p4_missing_from_2025",
            "check": "finding",
            "kind": "missing",
            "property_key": "p4",
            "tax_year": 2025,
            "field": "schedule_e.property",
            "detail": "Oak condo appears on the 2023 and 2024 Schedule E but not 2025: sold? converted?",
        },
        {
            "id": "p3_closing_statement_no_land_split",
            "check": "finding",
            "kind": "missing",
            "property_key": "p3",
            "field": "closing_statement.land_allocation",
            "detail": "Closing statement has purchase price and closing costs but no land/improvement split.",
        },
        {
            "id": "p2_2025_mortgage_interest_conflict",
            "check": "finding",
            "kind": "conflict",
            "property_key": "p2",
            "tax_year": 2025,
            "field": "mortgage_interest",
            "detail": f"Schedule E line 12 ({p2.years[2025].expenses[12]:,}) is {P2_2025_INTEREST_OVERSTATEMENT} "
            f"above the lender's year-end statement ({p2_loan.interest_in_year(2025):,}). Not in SPEC; added so the "
            "conflict kind has a planted case.",
        },
    ]

    return Household(
        seed=seed,
        name="Okafor-Lindqvist",
        taxpayer="Erik Lindqvist",
        spouse="Nkechi Okafor-Lindqvist",
        ssn_masked=ssn,
        spouse_ssn_masked=ssn2,
        address=Address("4412 Camellia Ave", "Sacramento", "CA", "95819"),
        filing_status="mfj",
        goal="retire in 7 years, stop managing property",
        properties=properties,
        years=years,
        planted=planted,
    )


def _net_passive(
    properties: list[Property], year: int, magi: int, prior_unallowed: int
) -> tuple[Form8582, dict[str, tuple[int, int]]]:
    """Form 8582 Parts I-III plus the unallowed-loss allocation (Parts VIII/IX worksheets).

    Returns the form and, per property, (Schedule E line 22 allowed loss, unallowed loss carried).
    """
    active = [p for p in properties if year in p.years]
    incomes = {p.key: p.years[year].net for p in active if p.years[year].net > 0}
    losses = {p.key: -p.years[year].net for p in active if p.years[year].net < 0}
    line1a = sum(incomes.values())
    line1b = -sum(losses.values())
    line1c = -prior_unallowed
    line1d = line1a + line1b + line1c
    line3 = line1d  # no "other passive activities"
    allowed_by_key: dict[str, tuple[int, int]] = {}
    if line1d >= 0:
        # all losses allowed
        for p in active:
            n = p.years[year].net
            allowed_by_key[p.key] = (n if n < 0 else 0, 0)
        form = Form8582(
            year, line1a, line1b, line1c, line1d, line3, 0, 150_000, magi, 0, 0, 0, line1a, line1a, 0,
            activities=[
                {
                    "property_key": p.key,
                    "name": f"Rental - {p.address_by_year[year]}",
                    "net_income": max(0, p.years[year].net),
                    "net_loss": min(0, p.years[year].net),
                    "prior_unallowed": 0,
                    "overall": p.years[year].net,
                    "ratio": 0.0,
                    "unallowed": 0,
                    "allowed": min(0, p.years[year].net),
                }
                for p in active
            ],
        )
        return form, allowed_by_key

    line4 = -line1d
    line5 = 150_000
    line6 = magi
    line7 = max(0, line5 - line6)
    line8 = min(25_000, round(line7 * 0.5))
    line9 = min(line4, line8)
    line10 = line1a
    line11 = line9 + line10
    unallowed_total = line4 - line9
    # Allocate unallowed losses across loss activities in proportion to (loss + prior unallowed share).
    # Prior unallowed losses are attributed to the loss activities pro rata to this year's loss.
    total_loss_pool = sum(losses.values()) + prior_unallowed
    keys = list(losses)
    acts = []
    remaining = unallowed_total
    for i, k in enumerate(keys):
        prior_share = round(prior_unallowed * losses[k] / sum(losses.values())) if prior_unallowed else 0
        pool = losses[k] + prior_share
        ratio = pool / total_loss_pool
        unallowed = remaining if i == len(keys) - 1 else round(unallowed_total * ratio)
        remaining -= unallowed
        allowed = pool - unallowed
        acts.append((k, pool, prior_share, ratio, unallowed, allowed))
    activities = []
    for p in active:
        n = p.years[year].net
        if p.key in losses:
            k, pool, prior_share, ratio, unallowed, allowed = next(a for a in acts if a[0] == p.key)
            allowed_by_key[p.key] = (-allowed, unallowed)
            activities.append(
                {
                    "property_key": p.key,
                    "name": f"Rental - {p.address_by_year[year]}",
                    "net_income": 0,
                    "net_loss": n,
                    "prior_unallowed": -prior_share,
                    "overall": -pool,
                    "ratio": round(ratio, 4),
                    "unallowed": unallowed,
                    "allowed": -allowed,
                }
            )
        else:
            allowed_by_key[p.key] = (0, 0)
            activities.append(
                {
                    "property_key": p.key,
                    "name": f"Rental - {p.address_by_year[year]}",
                    "net_income": n,
                    "net_loss": 0,
                    "prior_unallowed": 0,
                    "overall": n,
                    "ratio": 0.0,
                    "unallowed": 0,
                    "allowed": 0,
                }
            )
    form = Form8582(
        year, line1a, line1b, line1c, line1d, line3, line4, line5, line6, line7, line8, line9, line10, line11,
        unallowed_total, activities,
    )
    return form, allowed_by_key
