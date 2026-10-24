"""Small, dependency-free finance helpers shared by the synthesizer and the reconciler.

The backend engine (SPEC §2) is the system of record for these computations; the pipeline
carries its own copy only so that it can (a) generate internally consistent synthetic
documents and (b) judge whether a depreciation figure on a return is an outlier against
"allowable" (SPEC §4.4). Decimal math, half-up rounding to whole cents.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# IRS Pub 946 Table A-6: residential rental, 27.5-year straight line, mid-month convention.
# First-year percentage by month placed in service (1 = January).
RES_27_5_FIRST_YEAR_PCT = {
    1: Decimal("3.485"),
    2: Decimal("3.182"),
    3: Decimal("2.879"),
    4: Decimal("2.576"),
    5: Decimal("2.273"),
    6: Decimal("1.970"),
    7: Decimal("1.667"),
    8: Decimal("1.364"),
    9: Decimal("1.061"),
    10: Decimal("0.758"),
    11: Decimal("0.455"),
    12: Decimal("0.152"),
}
RES_27_5_MID_PCT = Decimal("3.636")


def _cents(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def res_27_5_year_pct(placed_in_service: date, tax_year: int) -> Decimal:
    """Percentage of basis deductible in ``tax_year`` for an asset placed in service on the given date."""
    yr = tax_year - placed_in_service.year + 1
    if yr < 1:
        return Decimal(0)
    if yr == 1:
        return RES_27_5_FIRST_YEAR_PCT[placed_in_service.month]
    if yr <= 27:
        return RES_27_5_MID_PCT
    if yr == 28:
        # remainder so the total is exactly 100%
        used = RES_27_5_FIRST_YEAR_PCT[placed_in_service.month] + RES_27_5_MID_PCT * 26
        return Decimal(100) - used
    return Decimal(0)


def res_27_5_allowable_cents(basis_cents: int, placed_in_service: date, tax_year: int) -> int:
    pct = res_27_5_year_pct(placed_in_service, tax_year)
    return _cents(Decimal(basis_cents) * pct / Decimal(100))


def res_27_5_accumulated_cents(basis_cents: int, placed_in_service: date, through_year: int) -> int:
    total = 0
    for y in range(placed_in_service.year, through_year + 1):
        total += res_27_5_allowable_cents(basis_cents, placed_in_service, y)
    return total


# --------------------------------------------------------------------------- amortization


def monthly_payment_cents(principal_cents: int, annual_rate: Decimal, term_months: int) -> int:
    r = annual_rate / Decimal(12)
    p = Decimal(principal_cents)
    if r == 0:
        return _cents(p / term_months)
    factor = (1 + r) ** term_months
    return _cents(p * r * factor / (factor - 1))


def amortize(
    principal_cents: int,
    annual_rate: Decimal,
    term_months: int,
    first_payment: date,
    payment_cents: int | None = None,
) -> list[dict]:
    """Monthly schedule: [{date, payment, interest, principal, balance}] (cents).

    Interest accrues on the prior balance each month; the last payment clears rounding.
    """
    pay = payment_cents or monthly_payment_cents(principal_cents, annual_rate, term_months)
    r = annual_rate / Decimal(12)
    bal = Decimal(principal_cents)
    rows = []
    y, m = first_payment.year, first_payment.month
    for i in range(term_months):
        interest = _cents(bal * r)
        princ = pay - interest
        if i == term_months - 1 or princ > bal:
            princ = int(bal)
        bal -= princ
        rows.append(
            {
                "date": date(y, m, min(first_payment.day, 28)),
                "payment": interest + princ,
                "interest": interest,
                "principal": princ,
                "balance": int(bal),
            }
        )
        m += 1
        if m > 12:
            m = 1
            y += 1
        if bal <= 0:
            break
    return rows


def year_totals(schedule: list[dict], year: int) -> dict:
    rows = [r for r in schedule if r["date"].year == year]
    return {
        "interest": sum(r["interest"] for r in rows),
        "principal": sum(r["principal"] for r in rows),
        "payments": len(rows),
        "end_balance": rows[-1]["balance"] if rows else None,
    }


def balance_at_year_end(schedule: list[dict], year: int, original_cents: int) -> int:
    rows = [r for r in schedule if r["date"].year <= year]
    return rows[-1]["balance"] if rows else original_cents


def implied_balance_after_months(
    balance_cents: int, annual_rate: Decimal, payment_cents: int, months: int, interest_only: bool = False
) -> int:
    """Roll a balance forward ``months`` payments; used by the reconciler's statement-vs-amortization check."""
    if interest_only:
        return balance_cents
    r = annual_rate / Decimal(12)
    bal = Decimal(balance_cents)
    for _ in range(months):
        interest = _cents(bal * r)
        bal -= payment_cents - interest
    return max(0, int(bal))
