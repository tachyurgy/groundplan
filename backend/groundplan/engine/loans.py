"""Loan amortization: monthly schedules for fixed, interest-only, ARM, HELOC and balloon loans.

The schedule starts the month AFTER `balance_as_of` from `balance_cents` and runs to maturity (or term_months
when no maturity is given). Monthly interest = round_half_up(balance x rate / 12) to the cent; principal = payment
- interest; the final payment clears the remaining balance exactly. Payment = standard annuity formula on the
remaining amortization term, rounded half-up to the cent once (Decimal, 28 digits), unless `monthly_payment_cents`
is supplied, in which case the statement's payment is used as-is.

Types: fixed (level payment); interest_only (io_months of interest, then re-amortized over the remaining term);
arm (fixed `rate` until `arm_reset_date`, then `arm_index` + `arm_index_margin` with the payment recast over the
remaining term; combinable with io_months); heloc (interest-only revolving at `rate`, balance never amortizes);
balloon (amortize on `term_months`, remaining balance due at `maturity_date`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, getcontext

from groundplan.engine.figure import D, Figure, Input, cents, ratio

getcontext().prec = 28

ARM_INDEX_DEFAULT = Decimal("0.045")  # assumption: forward index (e.g. 1-yr CMT / SOFR) when none supplied
LOAN_TYPES = ("fixed", "arm", "interest_only", "heloc", "balloon")


@dataclass
class LoanInput:
    loan_type: str = "fixed"
    balance_cents: int = 0
    balance_as_of: date = date(2025, 1, 1)
    rate: Decimal | float | str = "0.065"
    term_months: int = 360  # remaining amortization term from balance_as_of unless maturity_date overrides
    io_months: int = 0
    arm_reset_date: date | None = None
    arm_index_margin: Decimal | float | str | None = None
    arm_index: Decimal | float | str | None = None  # assumption; default ARM_INDEX_DEFAULT
    monthly_payment_cents: int | None = None
    maturity_date: date | None = None
    lien_position: int = 1
    is_paid_off: bool = False
    lender: str = ""
    id: str | None = None

    def __post_init__(self) -> None:
        if self.loan_type not in LOAN_TYPES:
            raise ValueError(f"unknown loan_type {self.loan_type!r}")


@dataclass(frozen=True)
class MonthRow:
    index: int  # 1-based month index from balance_as_of
    year: int
    month: int
    rate: str
    payment_cents: int
    interest_cents: int
    principal_cents: int
    balance_cents: int  # end of month
    phase: str  # amortizing | interest_only | arm_reset | heloc | balloon_due | paid_off

    def to_dict(self) -> dict:
        return {
            "index": self.index, "year": self.year, "month": self.month, "rate": self.rate,
            "payment_cents": self.payment_cents, "interest_cents": self.interest_cents,
            "principal_cents": self.principal_cents, "balance_cents": self.balance_cents, "phase": self.phase,
        }


@dataclass
class LoanSchedule:
    loan: LoanInput
    rows: list[MonthRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def principal_paid_in_year(self, year: int) -> int:
        return sum(r.principal_cents for r in self.rows if r.year == year and r.phase != "balloon_due")

    def interest_paid_in_year(self, year: int) -> int:
        return sum(r.interest_cents for r in self.rows if r.year == year)

    def debt_service_in_year(self, year: int) -> int:
        return sum(r.payment_cents for r in self.rows if r.year == year and r.phase != "balloon_due")

    def balloon_in_year(self, year: int) -> int:
        return sum(r.principal_cents for r in self.rows if r.year == year and r.phase == "balloon_due")

    def balance_at(self, on: date) -> int:
        """Balance at the end of the month containing `on` (balance_as_of balance before the first row)."""
        if not self.rows or (on.year, on.month) < (self.rows[0].year, self.rows[0].month):
            return 0 if self.loan.is_paid_off else self.loan.balance_cents
        bal = self.loan.balance_cents
        for r in self.rows:
            if (r.year, r.month) > (on.year, on.month):
                break
            bal = r.balance_cents
        return bal

    def balance_end_of_year(self, year: int) -> int:
        return self.balance_at(date(year, 12, 31))

    def annual_summary(self, year: int) -> dict:
        return {
            "year": year,
            "principal_cents": self.principal_paid_in_year(year),
            "interest_cents": self.interest_paid_in_year(year),
            "debt_service_cents": self.debt_service_in_year(year),
            "balloon_cents": self.balloon_in_year(year),
            "balance_end_cents": self.balance_end_of_year(year),
        }


def _add_months(y: int, m: int, n: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + n
    return idx // 12, idx % 12 + 1


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def annuity_payment(balance: Decimal, annual_rate: Decimal, n_months: int) -> int:
    """Level monthly payment, rounded half-up to the cent once."""
    if n_months <= 0:
        return cents(balance)
    r = annual_rate / Decimal(12)
    if r == 0:
        return cents(balance / Decimal(n_months))
    factor = (Decimal(1) + r) ** n_months
    return cents(balance * r * factor / (factor - Decimal(1)))


def build_schedule(loan: LoanInput) -> LoanSchedule:
    sched = LoanSchedule(loan=loan)
    if loan.is_paid_off or loan.balance_cents <= 0:
        sched.notes.append("lien is paid off; contributes 0 to debt service but is kept in the trace")
        return sched
    rate = D(loan.rate)
    total_months = months_between(loan.balance_as_of, loan.maturity_date) if loan.maturity_date else loan.term_months
    total_months = max(1, total_months)
    amort_months = loan.term_months if loan.loan_type == "balloon" else total_months
    y0, m0 = loan.balance_as_of.year, loan.balance_as_of.month
    balance = Decimal(loan.balance_cents)
    reset_idx = None
    if loan.loan_type == "arm" and loan.arm_reset_date:
        reset_idx = months_between(loan.balance_as_of, loan.arm_reset_date)
        if reset_idx < 1:
            # already reset before balance_as_of: the whole schedule runs at the reset rate
            reset_idx = 1
    reset_rate = None
    if loan.loan_type == "arm":
        idx = D(loan.arm_index) if loan.arm_index is not None else ARM_INDEX_DEFAULT
        margin = D(loan.arm_index_margin) if loan.arm_index_margin is not None else Decimal("0.0225")
        reset_rate = idx + margin
        if loan.arm_index is None:
            sched.notes.append(f"ARM reset rate assumes index {ARM_INDEX_DEFAULT} + margin {margin} (assumption)")
    io_months = loan.io_months if loan.loan_type in ("interest_only", "arm", "fixed") else 0
    if loan.loan_type == "heloc":
        io_months = total_months
        sched.notes.append("HELOC modeled as interest-only revolving at the stated rate on the current balance")
    payment: int | None = None
    cur_rate = rate
    for i in range(1, total_months + 1):
        yr, mo = _add_months(y0, m0, i)
        phase = "amortizing"
        if reset_idx is not None and i == reset_idx and reset_rate is not None:
            cur_rate = reset_rate
            payment = None  # recast
        interest = cents(balance * cur_rate / Decimal(12))
        if i <= io_months:
            principal = 0
            pay = interest
            phase = "heloc" if loan.loan_type == "heloc" else "interest_only"
        else:
            if payment is None:
                remaining_amort = (amort_months - i + 1) if loan.loan_type == "balloon" else (total_months - i + 1)
                use_statement = (
                    loan.monthly_payment_cents is not None and i == io_months + 1 and cur_rate == rate
                )
                payment = (
                    loan.monthly_payment_cents
                    if use_statement and loan.monthly_payment_cents
                    else annuity_payment(balance, cur_rate, remaining_amort)
                )
            pay = payment
            principal = pay - interest
            if reset_idx is not None and i >= reset_idx:
                phase = "arm_reset"
            if principal > balance or i == total_months:
                principal = int(balance) if loan.loan_type != "balloon" or i == total_months else principal
                if loan.loan_type == "balloon" and i == total_months:
                    # regular payment this month, then the balloon
                    reg_principal = min(pay - interest, int(balance))
                    balance -= reg_principal
                    sched.rows.append(
                        MonthRow(i, yr, mo, str(cur_rate), pay, interest, reg_principal, int(balance), "amortizing")
                    )
                    if balance > 0:
                        sched.rows.append(
                            MonthRow(i, yr, mo, str(cur_rate), int(balance), 0, int(balance), 0, "balloon_due")
                        )
                        balance = Decimal(0)
                    break
                pay = principal + interest
        balance -= principal
        sched.rows.append(MonthRow(i, yr, mo, str(cur_rate), pay, interest, principal, int(balance), phase))
        if balance <= 0 and loan.loan_type != "heloc":
            break
    if loan.loan_type == "heloc" and balance > 0:
        sched.notes.append("HELOC balance outstanding at end of draw/maturity: assumed refinanced or repaid from equity")
    return sched


def combined_annual(schedules: list[LoanSchedule], year: int) -> dict:
    out = {"year": year, "principal_cents": 0, "interest_cents": 0, "debt_service_cents": 0, "balloon_cents": 0,
           "balance_end_cents": 0}
    for s in schedules:
        a = s.annual_summary(year)
        for k in ("principal_cents", "interest_cents", "debt_service_cents", "balloon_cents", "balance_end_cents"):
            out[k] += a[k]
    return out


def total_balance_at(schedules: list[LoanSchedule], on: date) -> int:
    return sum(s.balance_at(on) for s in schedules)


def dscr(noi_cents: int, annual_debt_service_cents: int, inputs: list[Input] | None = None) -> Figure:
    val = None if annual_debt_service_cents <= 0 else Decimal(noi_cents) / Decimal(annual_debt_service_cents)
    notes = [] if annual_debt_service_cents > 0 else ["no debt service: DSCR undefined"]
    return ratio(
        "loans.dscr", val,
        inputs or [Input.of("noi_cents", noi_cents), Input.of("annual_debt_service_cents", annual_debt_service_cents)],
        "NOI / annual debt service", unit="ratio", notes=notes, places=4,
    )
