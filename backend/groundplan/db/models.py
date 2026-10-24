"""SPEC §1 domain model. Every table carries advisor_id; every query goes through `scoped()` / `get_owned()`.

Money = BigInteger cents. Rates = Numeric(9, 6). IDs = UUID strings.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from groundplan.db.base import Base, new_id, utcnow

JSONType = JSON().with_variant(JSONB(), "postgresql")
Rate = Numeric(9, 6)


class TenantMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    advisor_id: Mapped[str] = mapped_column(String(36), ForeignKey("advisors.id", ondelete="CASCADE"), index=True)


class Advisor(Base):
    __tablename__ = "advisors"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    firm_name: Mapped[str] = mapped_column(String(200), default="")
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    # the advisor row is its own tenant root; advisor_id == id keeps the "advisor_id on every table" invariant
    advisor_id: Mapped[str] = mapped_column(String(36), index=True)
    # SPEC §8.1: an advisor row IS a no-login workspace (id = the X-Workspace-Id header)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now(), index=True)
    created_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorkspaceProvision(Base):
    """Per-client-IP, per-UTC-day counter of new workspaces (abuse guard, SPEC §8.1). Not tenant data."""

    __tablename__ = "workspace_provisions"
    ip: Mapped[str] = mapped_column(String(64), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Household(TenantMixin, Base):
    __tablename__ = "households"
    name: Mapped[str] = mapped_column(String(200))
    filing_status: Mapped[str] = mapped_column(String(8), default="mfj")
    state: Mapped[str] = mapped_column(String(2), default="CA")
    tax_year_latest: Mapped[int] = mapped_column(Integer, default=2025)
    wages_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    other_income_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    magi_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    active_participation: Mapped[bool] = mapped_column(Boolean, default=True)
    re_professional: Mapped[bool] = mapped_column(Boolean, default=False)
    net_worth_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    goal: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    properties: Mapped[list[Property]] = relationship(back_populates="household", cascade="all, delete-orphan",
                                                      order_by="Property.nickname")
    suspended_losses: Mapped[list[SuspendedLoss]] = relationship(cascade="all, delete-orphan")
    documents: Mapped[list[Document]] = relationship(cascade="all, delete-orphan")
    findings: Mapped[list[Finding]] = relationship(cascade="all, delete-orphan")
    alerts: Mapped[list[Alert]] = relationship(cascade="all, delete-orphan")


class Property(TenantMixin, Base):
    __tablename__ = "properties"
    household_id: Mapped[str] = mapped_column(String(36), ForeignKey("households.id", ondelete="CASCADE"), index=True)
    nickname: Mapped[str] = mapped_column(String(200))
    address_line1: Mapped[str] = mapped_column(String(200), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    state: Mapped[str] = mapped_column(String(2), default="")
    zip: Mapped[str] = mapped_column(String(10), default="")
    property_type: Mapped[str] = mapped_column(String(20), default="sfr")
    units: Mapped[int] = mapped_column(Integer, default=1)
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    purchase_price_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    placed_in_service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    land_pct: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    improvements_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_seg_study: Mapped[bool] = mapped_column(Boolean, default=False)
    current_value_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    value_source: Mapped[str] = mapped_column(String(12), default="estimated")
    value_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    appreciation_rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    rent_growth_rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    expense_growth_rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    vacancy_rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    mgmt_fee_rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    capex_reserve_rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    selling_cost_rate: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="active")
    former_residence_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    avg_stay_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    property_key: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)  # pipeline normalized address

    household: Mapped[Household] = relationship(back_populates="properties")
    loans: Mapped[list[Loan]] = relationship(cascade="all, delete-orphan", order_by="Loan.lien_position")
    rent_rolls: Mapped[list[RentRoll]] = relationship(cascade="all, delete-orphan", order_by="RentRoll.tax_year")
    expense_years: Mapped[list[ExpenseYear]] = relationship(cascade="all, delete-orphan", order_by="ExpenseYear.tax_year")
    depreciation_ledger: Mapped[list[DepreciationLedger]] = relationship(cascade="all, delete-orphan",
                                                                         order_by="DepreciationLedger.tax_year")
    scenarios: Mapped[list[Scenario]] = relationship(cascade="all, delete-orphan")


class Loan(TenantMixin, Base):
    __tablename__ = "loans"
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    lender: Mapped[str] = mapped_column(String(200), default="")
    loan_type: Mapped[str] = mapped_column(String(16), default="fixed")
    original_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    balance_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    balance_as_of: Mapped[date] = mapped_column(Date)
    rate: Mapped[Decimal] = mapped_column(Rate)
    term_months: Mapped[int] = mapped_column(Integer, default=360)
    io_months: Mapped[int] = mapped_column(Integer, default=0)
    arm_reset_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    arm_index_margin: Mapped[Decimal | None] = mapped_column(Rate, nullable=True)
    monthly_payment_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    maturity_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lien_position: Mapped[int] = mapped_column(Integer, default=1)
    is_paid_off: Mapped[bool] = mapped_column(Boolean, default=False)


class RentRoll(TenantMixin, Base):
    __tablename__ = "rent_rolls"
    __table_args__ = (UniqueConstraint("property_id", "tax_year"),)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    tax_year: Mapped[int] = mapped_column(Integer)
    gross_rent_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    other_income_cents: Mapped[int] = mapped_column(BigInteger, default=0)


class ExpenseYear(TenantMixin, Base):
    __tablename__ = "expense_years"
    __table_args__ = (UniqueConstraint("property_id", "tax_year"),)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    tax_year: Mapped[int] = mapped_column(Integer)
    taxes_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    insurance_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    repairs_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    mgmt_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    utilities_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    hoa_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    other_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    mortgage_interest_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    depreciation_cents: Mapped[int] = mapped_column(BigInteger, default=0)


class DepreciationLedger(TenantMixin, Base):
    __tablename__ = "depreciation_ledgers"
    __table_args__ = (UniqueConstraint("property_id", "tax_year"),)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    tax_year: Mapped[int] = mapped_column(Integer)
    allowed_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    allowable_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    method: Mapped[str] = mapped_column(String(10), default="sl_27_5")
    note: Mapped[str] = mapped_column(Text, default="")


class SuspendedLoss(TenantMixin, Base):
    __tablename__ = "suspended_losses"
    __table_args__ = (UniqueConstraint("household_id", "tax_year"),)
    household_id: Mapped[str] = mapped_column(String(36), ForeignKey("households.id", ondelete="CASCADE"), index=True)
    tax_year: Mapped[int] = mapped_column(Integer)
    carryforward_cents: Mapped[int] = mapped_column(BigInteger, default=0)


class Document(TenantMixin, Base):
    __tablename__ = "documents"
    household_id: Mapped[str] = mapped_column(String(36), ForeignKey("households.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="other")
    tax_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filename: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(12), default="queued")
    bytes_retained: Mapped[bool] = mapped_column(Boolean, default=False)
    fields: Mapped[list[ExtractedField]] = relationship(cascade="all, delete-orphan")


class ExtractedField(TenantMixin, Base):
    __tablename__ = "extracted_fields"
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    entity_hint: Mapped[str] = mapped_column(String(12), default="property")
    property_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    field: Mapped[str] = mapped_column(String(120))
    value: Mapped[Any] = mapped_column(JSONType, nullable=True)
    unit: Mapped[str] = mapped_column(String(8), default="text")
    page: Mapped[int] = mapped_column(Integer, default=1)
    bbox: Mapped[list] = mapped_column(JSONType, default=lambda: [0, 0, 0, 0])
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    extractor: Mapped[str] = mapped_column(String(8), default="rules")
    raw_text: Mapped[str] = mapped_column(Text, default="")


class Finding(TenantMixin, Base):
    __tablename__ = "findings"
    household_id: Mapped[str] = mapped_column(String(36), ForeignKey("households.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=True)
    key: Mapped[str | None] = mapped_column(String(200), nullable=True)  # stable key from the pipeline (idempotent import)
    tax_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(24))
    field: Mapped[str] = mapped_column(String(120), default="")
    severity: Mapped[str] = mapped_column(String(8), default="warn")
    message: Mapped[str] = mapped_column(Text, default="")
    candidates: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(12), default="open")
    resolution: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Scenario(TenantMixin, Base):
    __tablename__ = "scenarios"
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    horizon_years: Mapped[int] = mapped_column(Integer, default=10)
    assumptions: Mapped[dict] = mapped_column(JSONType, default=dict)
    results: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(TenantMixin, Base):
    __tablename__ = "alerts"
    household_id: Mapped[str] = mapped_column(String(36), ForeignKey("households.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(24))
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="open")


TENANT_TABLES = (Household, Property, Loan, RentRoll, ExpenseYear, DepreciationLedger, SuspendedLoss, Document,
                 ExtractedField, Finding, Scenario, Alert)


def scoped(model, advisor_id: str):
    """The ONLY way routes build a query: always filtered by advisor_id (tenant isolation at the DB layer)."""
    return select(model).where(model.advisor_id == advisor_id)
