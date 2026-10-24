"""Canonical data models for the Groundplan document pipeline.

Every model here maps onto SPEC §1. Money is integer cents, rates are decimals,
dates are ISO ``YYYY-MM-DD`` strings. ``ReconciledHousehold`` is the JSON contract
consumed by the backend's ``POST /households/{id}/import-reconciled``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr

DocumentKind = Literal[
    "form_1040",
    "schedule_e",
    "form_4562",
    "form_8582",
    "mortgage_statement",
    "closing_statement",
    "lease",
    "appraisal",
    "other",
]
Unit = Literal["cents", "date", "text", "bool", "rate", "int"]
ExtractorName = Literal["rules", "ocr", "llm"]
FindingKind = Literal["conflict", "missing", "outlier", "stale", "unsupported_structure"]
Severity = Literal["info", "warn", "block"]
PropertyType = Literal[
    "sfr", "multifamily", "vacation_str", "commercial", "land", "self_rental", "other"
]
LoanType = Literal["fixed", "arm", "interest_only", "heloc", "balloon"]


# --------------------------------------------------------------------------- words / pages


class Word(BaseModel):
    """One token on a page. Coordinates are PDF points, origin top-left."""

    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    conf: float = 1.0  # 0..1; OCR word confidence, 1.0 for a text layer


class Page(BaseModel):
    number: int  # 1-based
    width: float
    height: float
    words: list[Word]
    source: Literal["text", "ocr"]
    skew_deg: float = 0.0  # skew estimated (and removed) before OCR
    # the deskewed raster for OCR pages, kept in memory only so extractors can re-OCR value zones
    _image: Any = PrivateAttr(default=None)
    _dpi: int = PrivateAttr(default=300)
    _zone_cache: dict = PrivateAttr(default_factory=dict)

    def text(self) -> str:
        return " ".join(w.text for w in self.words)


class ParsedDocument(BaseModel):
    filename: str
    sha256: str
    page_count: int
    pages: list[Page]
    kind: DocumentKind = "other"
    tax_year: int | None = None
    classify_confidence: float = 0.0


# --------------------------------------------------------------------------- extraction


class ExtractedField(BaseModel):
    """SPEC §1 ExtractedField (minus the DB ids)."""

    document_key: str  # filename of the source document
    entity_hint: Literal["household", "property", "loan"]
    property_key: str | None = None  # normalized address, or column id if no address
    address_raw: str | None = None  # the address as printed on this document (provenance for resolution)
    field: str  # e.g. "schedule_e.line3.rents"
    value: Any
    unit: Unit
    page: int
    bbox: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    confidence: float
    extractor: ExtractorName
    raw_text: str = ""


class Candidate(BaseModel):
    source: str  # "schedule_e 2025 line 12", "mortgage_statement 2025 interest_paid_ytd", "rules", "llm"
    value: Any
    document_key: str | None = None
    page: int | None = None


class Finding(BaseModel):
    key: str
    kind: FindingKind
    field: str
    severity: Severity
    message: str
    property_key: str | None = None
    tax_year: int | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    status: Literal["open", "resolved", "dismissed"] = "open"
    resolution: dict[str, Any] | None = None


class ExtractionResult(BaseModel):
    fields: list[ExtractedField]
    findings: list[Finding] = Field(default_factory=list)


# --------------------------------------------------------------------------- resolution


class PropertyMatch(BaseModel):
    raw_address: str
    normalized: str
    property_key: str
    confidence: float
    candidates: list[dict[str, Any]] = Field(default_factory=list)  # [{property_key, score}]


# --------------------------------------------------------------------------- reconciled household (SPEC §1)


class LoanOut(BaseModel):
    key: str
    lender: str
    loan_type: LoanType
    original_cents: int | None = None
    balance_cents: int
    balance_as_of: str
    rate: float
    term_months: int | None = None
    io_months: int = 0
    io_end_date: str | None = None
    arm_reset_date: str | None = None
    arm_index_margin: float | None = None
    monthly_payment_cents: int | None = None
    maturity_date: str | None = None
    lien_position: int = 1
    is_paid_off: bool = False
    source_document_keys: list[str] = Field(default_factory=list)


class RentRollOut(BaseModel):
    tax_year: int
    gross_rent_cents: int
    other_income_cents: int = 0
    fair_rental_days: int | None = None
    personal_use_days: int | None = None


class ExpenseYearOut(BaseModel):
    tax_year: int
    taxes_cents: int = 0
    insurance_cents: int = 0
    repairs_cents: int = 0
    mgmt_cents: int = 0
    utilities_cents: int = 0
    hoa_cents: int = 0
    other_cents: int = 0
    mortgage_interest_cents: int = 0
    depreciation_cents: int = 0
    line20_total_expenses_cents: int | None = None
    line21_income_or_loss_cents: int | None = None


class DepreciationLedgerOut(BaseModel):
    tax_year: int
    allowed_cents: int
    allowable_cents: int | None = None
    method: Literal["sl_27_5", "sl_39", "cost_seg", "bonus"] = "sl_27_5"
    note: str | None = None


class PropertyOut(BaseModel):
    key: str  # normalized address = ExtractedField.property_key
    nickname: str
    address_line1: str
    city: str
    state: str
    zip: str
    address_variants: list[str] = Field(default_factory=list)
    property_type: PropertyType
    units: int = 1
    purchase_date: str | None = None
    purchase_price_cents: int | None = None
    placed_in_service_date: str | None = None
    land_pct: float | None = None  # SPEC §1 formula: depreciable basis = cost * (1 - land_pct)
    depreciable_basis_cents: int | None = None
    improvements_cents: int = 0
    cost_seg_study: bool = False
    current_value_cents: int | None = None
    value_source: Literal["estimated", "confirmed"] = "estimated"
    value_as_of: str | None = None
    status: Literal["active", "sold", "converted"] = "active"
    years_seen: list[int] = Field(default_factory=list)
    loans: list[LoanOut] = Field(default_factory=list)
    rent_rolls: list[RentRollOut] = Field(default_factory=list)
    expense_years: list[ExpenseYearOut] = Field(default_factory=list)
    depreciation_ledger: list[DepreciationLedgerOut] = Field(default_factory=list)


class HouseholdOut(BaseModel):
    name: str
    filing_status: Literal["single", "mfj", "mfs", "hoh"]
    state: str
    tax_year_latest: int
    wages_cents: int
    other_income_cents: int = 0
    magi_cents: int
    active_participation: bool = True
    re_professional: bool = False
    goal: str = ""
    notes: str = ""
    by_year: list[dict[str, Any]] = Field(default_factory=list)  # [{tax_year, wages_cents, agi_cents, taxable_income_cents}]


class SuspendedLossOut(BaseModel):
    tax_year: int
    carryforward_cents: int


class DocumentOut(BaseModel):
    key: str  # filename
    kind: DocumentKind
    tax_year: int | None
    filename: str
    sha256: str
    page_count: int
    status: Literal["queued", "extracted", "reconciled", "discarded"] = "reconciled"
    bytes_retained: bool = False
    classify_confidence: float = 0.0


class ReconciledHousehold(BaseModel):
    schema_version: str = "1.0"
    generated_at: str
    pipeline_version: str = "0.1.0"
    household: HouseholdOut
    properties: list[PropertyOut]
    suspended_losses: list[SuspendedLossOut]
    documents: list[DocumentOut]
    extracted_fields: list[ExtractedField]
    findings: list[Finding]
    property_matches: list[PropertyMatch] = Field(default_factory=list)
