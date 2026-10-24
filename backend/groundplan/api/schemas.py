"""Request bodies (responses are plain dicts shaped like web/src/api/types.ts)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

FilingStatus = Literal["single", "mfj", "mfs", "hoh"]
PropertyType = Literal["sfr", "multifamily", "vacation_str", "commercial", "land", "self_rental", "other"]
LoanType = Literal["fixed", "arm", "interest_only", "heloc", "balloon"]


class HouseholdIn(BaseModel):
    name: str
    filing_status: FilingStatus = "mfj"
    state: str = Field("CA", min_length=2, max_length=2)
    tax_year_latest: int = 2025
    wages_cents: int = 0
    other_income_cents: int = 0
    magi_cents: int = 0
    active_participation: bool = True
    re_professional: bool = False
    net_worth_cents: int | None = None
    goal: str = ""
    notes: str = ""


class HouseholdPatch(BaseModel):
    name: str | None = None
    filing_status: FilingStatus | None = None
    state: str | None = Field(None, min_length=2, max_length=2)
    tax_year_latest: int | None = None
    wages_cents: int | None = None
    other_income_cents: int | None = None
    magi_cents: int | None = None
    active_participation: bool | None = None
    re_professional: bool | None = None
    net_worth_cents: int | None = None
    goal: str | None = None
    notes: str | None = None


class PropertyIn(BaseModel):
    nickname: str
    address_line1: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    property_type: PropertyType = "sfr"
    units: int = 1
    purchase_date: date | None = None
    purchase_price_cents: int = 0
    placed_in_service_date: date | None = None
    land_pct: float | None = Field(None, ge=0, le=1)
    improvements_cents: int = 0
    cost_seg_study: bool = False
    current_value_cents: int = 0
    value_source: Literal["estimated", "confirmed"] = "estimated"
    value_as_of: date | None = None
    appreciation_rate: float | None = None
    rent_growth_rate: float | None = None
    expense_growth_rate: float | None = None
    vacancy_rate: float | None = Field(None, ge=0, le=1)
    mgmt_fee_rate: float | None = Field(None, ge=0, le=1)
    capex_reserve_rate: float | None = Field(None, ge=0, le=1)
    selling_cost_rate: float | None = Field(None, ge=0, le=1)
    status: Literal["active", "sold", "converted"] = "active"
    former_residence_until: date | None = None
    avg_stay_days: float | None = None


class PropertyPatch(BaseModel):
    model_config = {"extra": "forbid"}
    nickname: str | None = None
    address_line1: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    property_type: PropertyType | None = None
    units: int | None = None
    purchase_date: date | None = None
    purchase_price_cents: int | None = None
    placed_in_service_date: date | None = None
    land_pct: float | None = Field(None, ge=0, le=1)
    improvements_cents: int | None = None
    cost_seg_study: bool | None = None
    current_value_cents: int | None = None
    value_source: Literal["estimated", "confirmed"] | None = None
    value_as_of: date | None = None
    appreciation_rate: float | None = None
    rent_growth_rate: float | None = None
    expense_growth_rate: float | None = None
    vacancy_rate: float | None = None
    mgmt_fee_rate: float | None = None
    capex_reserve_rate: float | None = None
    selling_cost_rate: float | None = None
    status: Literal["active", "sold", "converted"] | None = None
    former_residence_until: date | None = None
    avg_stay_days: float | None = None


class LoanIn(BaseModel):
    lender: str = ""
    loan_type: LoanType = "fixed"
    original_cents: int = 0
    balance_cents: int = 0
    balance_as_of: date
    rate: float = Field(..., ge=0, le=0.5)
    term_months: int = 360
    io_months: int = 0
    arm_reset_date: date | None = None
    arm_index_margin: float | None = None
    monthly_payment_cents: int | None = None
    maturity_date: date | None = None
    lien_position: int = 1
    is_paid_off: bool = False


class LoanPatch(BaseModel):
    lender: str | None = None
    loan_type: LoanType | None = None
    original_cents: int | None = None
    balance_cents: int | None = None
    balance_as_of: date | None = None
    rate: float | None = Field(None, ge=0, le=0.5)
    term_months: int | None = None
    io_months: int | None = None
    arm_reset_date: date | None = None
    arm_index_margin: float | None = None
    monthly_payment_cents: int | None = None
    maturity_date: date | None = None
    lien_position: int | None = None
    is_paid_off: bool | None = None


class YearIn(BaseModel):
    gross_rent_cents: int = 0
    other_income_cents: int = 0
    taxes_cents: int = 0
    insurance_cents: int = 0
    repairs_cents: int = 0
    mgmt_cents: int = 0
    utilities_cents: int = 0
    hoa_cents: int = 0
    other_cents: int = 0
    mortgage_interest_cents: int = 0
    depreciation_cents: int = 0
    depreciation: dict[str, Any] | None = Field(None, description="optional ledger row {allowed_cents, allowable_cents, method, note}")


class ScenarioIn(BaseModel):
    name: str
    horizon_years: int = Field(10, ge=1, le=40)
    assumptions: dict[str, Any] = Field(default_factory=dict)


class ResolveIn(BaseModel):
    value: Any = None
    note: str = ""
    who: str = "advisor"


class DismissIn(BaseModel):
    note: str = ""
    who: str = "advisor"


class SimEvent(BaseModel):
    model_config = {"extra": "allow"}
    id: str | None = None
    year: int
    type: Literal["buy", "sell", "exchange", "refi"]
    property_ref: str | None = None
    property_id: str | None = None
    amount_cents: int | None = None
    debt_cents: int | None = None
    rate: float | None = None
    note: str | None = None


class SimPropertyIn(BaseModel):
    model_config = {"extra": "allow"}
    id: str | None = None
    nickname: str | None = None
    property_type: str = "sfr"
    current_value_cents: int
    debt_cents: int = 0
    rate: float = 0.065
    remaining_years: int = 30
    noi_cents: int | None = None
    gross_rent_cents: int | None = None
    expenses_cents: int | None = None
    purchase_price_cents: int | None = None
    purchase_date: date | None = None
    land_pct: float | None = None
    accumulated_depreciation_cents: int | None = None


class SimAssumptions(BaseModel):
    appreciation_rate: float = 0.035
    rent_growth: float = 0.03
    expense_growth: float = 0.03
    reinvest_rate: float = 0.06
    cap_rate: float = 0.055
    vacancy_rate: float = 0.05
    filing_status: FilingStatus = "mfj"
    state: str = "CA"
    wages_cents: int = 0
    other_income_cents: int = 0
    magi_cents: int = 0
    starting_cash_cents: int = 0


class MonteCarlo(BaseModel):
    runs: int = Field(0, ge=0, le=5000)
    appr_sigma: float = Field(0.0, ge=0, le=1)
    rent_sigma: float = Field(0.0, ge=0, le=1)
    seed: int = 7


class SimulateIn(BaseModel):
    start_year: int = 2026
    years: int = Field(10, ge=1, le=40)
    household_id: str | None = None
    properties: list[SimPropertyIn] = Field(default_factory=list)
    events: list[SimEvent] = Field(default_factory=list)
    assumptions: SimAssumptions = Field(default_factory=SimAssumptions)
    monte_carlo: MonteCarlo = Field(default_factory=MonteCarlo)
