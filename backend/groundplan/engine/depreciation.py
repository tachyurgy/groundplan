"""Depreciation: MACRS straight-line, mid-month convention (IRS Pub 946 Tables A-6 / A-7a).

Residential rental property: 27.5 years. Nonresidential real property: 39 years.
Table mode (default) uses the published first-year percentages by month placed in service; the final year is the
exact remainder of basis so the schedule always sums to the depreciable basis (the published final-year
percentages are those remainders rounded to 3 decimals). Simple mode = basis / life, first year prorated by whole
months remaining in the year (so a property placed in service in October gets 3/12).

Depreciable basis = (purchase_price + improvements) x (1 - land_pct).
DEVIATION FROM SPEC: the spec writes land_pct "0.6..0.8 default 0.70" while its own worked example (d) needs a
$400k purchase to yield a $280k basis (land = 30%). Real land shares are 20-40%, so land_pct is bounded to
[0.20, 0.40], default 0.30, with a Figure note whenever the bound bites.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from groundplan.engine.figure import D, Figure, Input, cents, derive_status, money, pct

LAND_PCT_MIN = Decimal("0.20")
LAND_PCT_MAX = Decimal("0.40")
LAND_PCT_DEFAULT = Decimal("0.30")

# First-year percentage by month placed in service (1..12), Pub 946 Table A-6 (27.5-yr, mid-month).
RESIDENTIAL_FIRST_YEAR = {
    1: "3.485", 2: "3.182", 3: "2.879", 4: "2.576", 5: "2.273", 6: "1.970",
    7: "1.667", 8: "1.364", 9: "1.061", 10: "0.758", 11: "0.455", 12: "0.152",
}
RESIDENTIAL_MID_YEAR = "3.636"
RESIDENTIAL_LIFE_YEARS = Decimal("27.5")

# Pub 946 Table A-7a (39-yr nonresidential, mid-month).
NONRESIDENTIAL_FIRST_YEAR = {
    1: "2.461", 2: "2.247", 3: "2.033", 4: "1.819", 5: "1.605", 6: "1.391",
    7: "1.177", 8: "0.963", 9: "0.749", 10: "0.535", 11: "0.321", 12: "0.107",
}
NONRESIDENTIAL_MID_YEAR = "2.564"
NONRESIDENTIAL_LIFE_YEARS = Decimal("39")

RESIDENTIAL_TYPES = {"sfr", "multifamily", "vacation_str", "self_rental", "other"}
NONRESIDENTIAL_TYPES = {"commercial"}
NON_DEPRECIABLE_TYPES = {"land"}


@dataclass(frozen=True)
class ScheduleRow:
    year: int
    amount_cents: int
    pct: str  # percentage of basis applied this year, 3 decimals, as in the IRS table

    def to_dict(self) -> dict:
        return {"year": self.year, "amount_cents": self.amount_cents, "pct": self.pct}


def property_class(property_type: str) -> str:
    if property_type in NONRESIDENTIAL_TYPES:
        return "nonresidential"
    if property_type in NON_DEPRECIABLE_TYPES:
        return "land"
    return "residential"


def bounded_land_pct(land_pct: Decimal | float | str | None) -> tuple[Decimal, list[str], str]:
    """Return (bounded value, notes, source_type)."""
    if land_pct is None:
        return LAND_PCT_DEFAULT, [f"land_pct not provided; default {LAND_PCT_DEFAULT} applied"], "default"
    lp = D(land_pct)
    if lp < LAND_PCT_MIN:
        return LAND_PCT_MIN, [f"land_pct {lp} below floor; bounded to {LAND_PCT_MIN}"], "manual"
    if lp > LAND_PCT_MAX:
        return LAND_PCT_MAX, [f"land_pct {lp} above ceiling; bounded to {LAND_PCT_MAX}"], "manual"
    return lp, [], "manual"


def depreciable_basis(
    purchase_price_cents: int,
    improvements_cents: int = 0,
    land_pct: Decimal | float | str | None = None,
    sources: dict[str, Input] | None = None,
) -> Figure:
    lp, notes, lp_src = bounded_land_pct(land_pct)
    sources = sources or {}
    inputs = [
        sources.get("purchase_price_cents", Input.of("purchase_price_cents", purchase_price_cents)),
        sources.get("improvements_cents", Input.of("improvements_cents", improvements_cents)),
        Input.of("land_pct", lp, src=lp_src),
    ]
    basis = (Decimal(purchase_price_cents) + Decimal(improvements_cents)) * (Decimal(1) - lp)
    return money(
        "depreciation.depreciable_basis",
        basis,
        inputs,
        "(purchase_price + improvements) * (1 - land_pct)",
        notes,
    )


def annual_schedule(
    basis_cents: int,
    placed_in_service: date,
    prop_class: str = "residential",
    mode: str = "table",
) -> list[ScheduleRow]:
    """Full depreciation schedule, one row per calendar year, summing exactly to basis_cents."""
    if prop_class == "land" or basis_cents <= 0:
        return []
    if prop_class == "nonresidential":
        first, mid, life = NONRESIDENTIAL_FIRST_YEAR, NONRESIDENTIAL_MID_YEAR, NONRESIDENTIAL_LIFE_YEARS
    else:
        first, mid, life = RESIDENTIAL_FIRST_YEAR, RESIDENTIAL_MID_YEAR, RESIDENTIAL_LIFE_YEARS
    basis = Decimal(basis_cents)
    month = placed_in_service.month
    rows: list[ScheduleRow] = []
    remaining = basis
    year = placed_in_service.year
    if mode == "simple":
        annual = basis / life
        first_fraction = Decimal(13 - month) / Decimal(12)
        amt = cents(annual * first_fraction)
        rows.append(ScheduleRow(year, amt, _pct_of(amt, basis)))
        remaining -= amt
        year += 1
        while remaining > 0:
            amt = min(cents(annual), int(remaining))
            rows.append(ScheduleRow(year, amt, _pct_of(amt, basis)))
            remaining -= amt
            year += 1
        return rows
    if mode != "table":
        raise ValueError(f"unknown depreciation mode {mode!r}")
    first_amt = cents(basis * pct(first[month]))
    rows.append(ScheduleRow(year, first_amt, first[month]))
    remaining -= first_amt
    mid_amt = cents(basis * pct(mid))
    year += 1
    # years 2..N-1 at the mid rate; the final year(s) take the exact remainder, as the IRS table does
    while remaining > mid_amt + Decimal(1):  # leave at least a cent for the final-year remainder
        rows.append(ScheduleRow(year, mid_amt, mid))
        remaining -= mid_amt
        year += 1
    if remaining > 0:
        rows.append(ScheduleRow(year, int(remaining), _pct_of(int(remaining), basis)))
    return rows


def _pct_of(amount: int, basis: Decimal) -> str:
    if basis == 0:
        return "0.000"
    return str((Decimal(amount) / basis * 100).quantize(Decimal("0.001")))


def accumulated_through(schedule: list[ScheduleRow], through_year: int) -> int:
    """Accumulated depreciation through the END of `through_year` (for a sale in Y pass Y-1)."""
    return sum(r.amount_cents for r in schedule if r.year <= through_year)


def amount_in_year(schedule: list[ScheduleRow], year: int) -> int:
    return sum(r.amount_cents for r in schedule if r.year == year)


def allowed_or_allowable(allowable_cents: int, allowed_cents: int | None) -> tuple[int, list[str], bool]:
    """Recapture is computed on the greater of what was allowed (claimed) and what was allowable.

    Returns (recapture_basis_cents, notes, outlier_flag). The outlier flag means the ledger claimed less than
    allowable by more than 5% and a Finding(kind=outlier) should be raised by the caller.
    """
    if allowed_cents is None:
        return allowable_cents, [], False
    if allowed_cents < allowable_cents:
        gap = Decimal(allowable_cents - allowed_cents) / Decimal(allowable_cents) if allowable_cents else Decimal(0)
        outlier = gap > Decimal("0.05")
        return (
            allowable_cents,
            [
                f"return claimed {allowed_cents} but allowable is {allowable_cents}; "
                "allowed-or-allowable rule: recapture uses allowable"
            ],
            outlier,
        )
    if allowed_cents > allowable_cents:
        return allowed_cents, ["return claimed more than table allowable; basis reduced by amount claimed"], False
    return allowable_cents, [], False


@dataclass
class DepreciationResult:
    basis: Figure
    schedule: list[ScheduleRow]
    accumulated: Figure  # through end of (as_of_year - 1) i.e. the figure used for a sale in as_of_year
    current_year: Figure  # depreciation deductible in as_of_year
    sec1245_cents: int  # bonus / cost-seg portion (ordinary recapture, no 25% cap)
    outlier: bool
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "basis": self.basis.to_dict(),
            "schedule": [r.to_dict() for r in self.schedule],
            "accumulated": self.accumulated.to_dict(),
            "accumulated_cents": self.accumulated.value_cents,
            "current_year": self.current_year.to_dict(),
            "sec1245_cents": self.sec1245_cents,
            "outlier": self.outlier,
            "notes": self.notes,
        }


def compute_depreciation(
    purchase_price_cents: int,
    improvements_cents: int,
    land_pct: Decimal | float | str | None,
    placed_in_service: date,
    property_type: str,
    as_of_year: int,
    mode: str = "table",
    ledger: list[dict] | None = None,
    cost_seg_study: bool = False,
    sources: dict[str, Input] | None = None,
) -> DepreciationResult:
    """Everything the API needs for the depreciation tab and the exit-tax recapture inputs.

    `ledger` rows: {tax_year, allowed_cents, allowable_cents, method} (DepreciationLedger). When the study flag is
    set or any ledger row has method bonus/cost_seg, ledger amounts override the table and the excess over the
    straight-line table amount is tagged Sec 1245.
    """
    basis = depreciable_basis(purchase_price_cents, improvements_cents, land_pct, sources)
    pclass = property_class(property_type)
    schedule = annual_schedule(basis.value_cents or 0, placed_in_service, pclass, mode)
    ledger = ledger or []
    by_year = {row["tax_year"]: row for row in ledger}
    notes: list[str] = []
    sec1245 = 0
    accelerated = cost_seg_study or any(r.get("method") in ("bonus", "cost_seg") for r in ledger)
    outlier = False
    table_through = accumulated_through(schedule, as_of_year - 1)
    recapture_basis = table_through
    if accelerated:
        # ledger overrides the table for the years it covers; bonus = ledger - straight-line table amount
        ledger_total = 0
        sl_total = 0
        for yr in sorted(by_year):
            if yr >= as_of_year:
                continue
            row = by_year[yr]
            amt = int(row.get("allowed_cents") or row.get("allowable_cents") or 0)
            ledger_total += amt
            sl_total += amount_in_year(schedule, yr)
        sec1245 = max(0, ledger_total - sl_total)
        recapture_basis = max(ledger_total, table_through)
        notes.append("cost-seg/bonus ledger overrides the table; excess over straight-line tagged Sec 1245")
    else:
        claimed_rows = [r for r in ledger if r["tax_year"] < as_of_year and r.get("allowed_cents") is not None]
        if claimed_rows:
            claimed = sum(int(r["allowed_cents"]) for r in claimed_rows)
            allowable = sum(amount_in_year(schedule, r["tax_year"]) for r in claimed_rows)
            recapture_basis_rows, n, outlier = allowed_or_allowable(allowable, claimed)
            notes.extend(n)
            # years without a ledger row use the table
            other_years = table_through - allowable
            recapture_basis = recapture_basis_rows + other_years
            for r in claimed_rows:
                table_amt = amount_in_year(schedule, r["tax_year"])
                if table_amt and abs(int(r["allowed_cents"]) - table_amt) > table_amt * Decimal("0.05"):
                    notes.append(
                        f"{r['tax_year']}: return shows {int(r['allowed_cents'])} vs allowable {table_amt} (>5% gap)"
                    )
    inputs = [Input.figure(basis), Input.of("placed_in_service", placed_in_service), Input.of("as_of_year", as_of_year)]
    if ledger:
        inputs.append(Input.of("depreciation_ledger", [dict(r) for r in ledger], src="document", ref="Form 4562"))
    accumulated = Figure(
        key="depreciation.accumulated",
        value_cents=recapture_basis,
        status=derive_status(inputs),
        inputs=inputs,
        formula=f"sum(schedule[year] for year <= {as_of_year - 1}); allowed-or-allowable",
        notes=notes,
    )
    current = money(
        "depreciation.current_year",
        Decimal(amount_in_year(schedule, as_of_year)),
        [Input.figure(basis), Input.of("as_of_year", as_of_year)],
        f"schedule[{as_of_year}] ({mode} mode, {pclass}, mid-month convention)",
    )
    return DepreciationResult(basis, schedule, accumulated, current, sec1245, outlier, notes)
