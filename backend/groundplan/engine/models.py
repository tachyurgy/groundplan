"""Plain engine input models (no ORM). The service layer maps DB rows onto these; the Go port mirrors them."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from groundplan.engine.cashflow import YearOperations
from groundplan.engine.loans import LoanInput


@dataclass
class PropertyModel:
    id: str = "p1"
    nickname: str = ""
    property_type: str = "sfr"
    units: int = 1
    purchase_date: date = date(2015, 1, 1)
    purchase_price_cents: int = 0
    placed_in_service_date: date | None = None
    land_pct: Decimal | str | None = None
    improvements_cents: int = 0
    cost_seg_study: bool = False
    current_value_cents: int = 0
    value_source: str = "estimated"  # estimated | confirmed
    value_as_of: date | None = None
    appreciation_rate: Decimal | str | None = None
    rent_growth_rate: Decimal | str | None = None
    expense_growth_rate: Decimal | str | None = None
    vacancy_rate: Decimal | str | None = None
    mgmt_fee_rate: Decimal | str | None = None
    capex_reserve_rate: Decimal | str | None = None
    selling_cost_rate: Decimal | str | None = None
    status: str = "active"
    former_residence_until: date | None = None
    avg_stay_days: float | None = None
    loans: list[LoanInput] = field(default_factory=list)
    years: dict[int, YearOperations] = field(default_factory=dict)
    ledger: list[dict] = field(default_factory=list)  # DepreciationLedger rows
    capital_improvements_paid: dict[int, int] = field(default_factory=dict)
    blocked_keys: set[str] = field(default_factory=set)  # inputs touched by open blocking Findings

    @property
    def in_service(self) -> date:
        return self.placed_in_service_date or self.purchase_date


@dataclass
class HouseholdModel:
    filing_status: str = "mfj"
    state: str = "CA"
    tax_year: int = 2025
    wages_cents: int = 0
    other_income_cents: int = 0
    magi_cents: int = 0
    active_participation: bool = True
    re_professional: bool = False
    carryforward_cents: int = 0
    net_worth_cents: int | None = None
    goal: str = ""


DEFAULTS = {
    "appreciation_rate": Decimal("0.035"),
    "rent_growth_rate": Decimal("0.03"),
    "expense_growth_rate": Decimal("0.03"),
    "vacancy_rate": Decimal("0.05"),
    "capex_reserve_rate": Decimal("0.05"),
    "selling_cost_rate": Decimal("0.06"),
    "reinvest_rate": Decimal("0.06"),
    "dst_load_rate": Decimal("0.085"),
    "dst_yield": Decimal("0.05"),
}


def rate_or_default(value, name: str) -> tuple[Decimal, str]:
    """(rate, source_type): a None rate falls back to the documented default and marks the figure estimated."""
    if value is None:
        return DEFAULTS[name], "default"
    return Decimal(str(value)), "manual"
