"""Reconciliation (SPEC §4.4): extracted fields from many documents -> one ReconciledHousehold + Findings.

For every (property, field, year) across sources: agree -> the value is used; disagree -> a ``conflict`` Finding
with every candidate (never averaged; the Schedule E value stays the record until an advisor resolves it).
The rule table below is the whole reconciler; each rule is a pure function of the grouped fields.

| key prefix            | kind                  | rule                                                                  |
|-----------------------|-----------------------|-----------------------------------------------------------------------|
| str:                  | unsupported_structure | Schedule E line 1b type 3 (vacation / short-term rental)              |
| missing_latest:       | missing               | property on an earlier Schedule E, absent from the latest one         |
| dep_outlier:          | outlier               | line 18 differs from the MACRS 27.5 allowable by more than 5%         |
| dep_4562:             | conflict              | Schedule E line 18 != Form 4562 line 22 for the same property + year  |
| missing_land_split:   | missing               | closing statement has a price but no land / improvement allocation    |
| conflict:..interest   | conflict              | line 12 vs the lenders' year-to-date interest, > $100 and > 1%        |
| conflict:..balance    | conflict              | statement balance vs the amortization implied by its own terms, > 2%  |
| low_conf:             | conflict (info)       | an OCR value whose arithmetic self-check failed (confidence < 0.6)    |
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal

from gp_pipeline import __version__
from gp_pipeline.address import normalize
from gp_pipeline.finance import amortize, res_27_5_allowable_cents
from gp_pipeline.models import (
    Candidate,
    DepreciationLedgerOut,
    DocumentOut,
    ExpenseYearOut,
    ExtractedField,
    Finding,
    HouseholdOut,
    LoanOut,
    ParsedDocument,
    PropertyMatch,
    PropertyOut,
    ReconciledHousehold,
    RentRollOut,
    SuspendedLossOut,
)

TYPE_CODES = {1: "sfr", 2: "multifamily", 3: "vacation_str", 4: "commercial", 5: "land", 6: "other", 7: "self_rental",
              8: "other"}
EXPENSE_MAP = {  # Schedule E line -> ExpenseYear column (SPEC §1)
    "taxes_cents": ["line16.taxes"],
    "insurance_cents": ["line9.insurance"],
    "repairs_cents": ["line7.cleaning_maintenance", "line14.repairs"],
    "mgmt_cents": ["line11.management_fees"],
    "utilities_cents": ["line17.utilities"],
    "other_cents": ["line5.advertising", "line6.auto_travel", "line8.commissions", "line10.legal_professional",
                    "line15.supplies", "line19.other"],
    "mortgage_interest_cents": ["line12.mortgage_interest", "line13.other_interest"],
    "depreciation_cents": ["line18.depreciation"],
}
DEP_OUTLIER_PCT = Decimal("0.05")
BALANCE_CONFLICT_PCT = Decimal("0.02")


class Ix:
    """Fields grouped for lookups: ix.get(pk, 'schedule_e.line3.rents', 2025)."""

    def __init__(self, fields: list[ExtractedField]):
        self.by: dict[tuple, list[ExtractedField]] = defaultdict(list)
        for f in fields:
            self.by[(f.property_key, f.field, f.tax_year)].append(f)
        self.fields = fields

    def all(self, pk, field, year=None) -> list[ExtractedField]:
        if year is None:
            return [f for (p, fl, _y), fs in self.by.items() if p == pk and fl == field for f in fs]
        return self.by.get((pk, field, year), [])

    def get(self, pk, field, year=None):
        fs = self.all(pk, field, year)
        if not fs:
            return None
        return max(fs, key=lambda f: f.confidence).value

    def field(self, pk, field, year=None) -> ExtractedField | None:
        fs = self.all(pk, field, year)
        return max(fs, key=lambda f: f.confidence) if fs else None


def _cand(f: ExtractedField, source: str | None = None) -> Candidate:
    return Candidate(source=source or f"{f.document_kind} {f.tax_year} {f.field}", value=f.value, document_key=f.document_key,
                     page=f.page)


def _usd(c: int) -> str:
    return f"${c / 100:,.0f}"


def _iso(d) -> str | None:
    return d if d is None or isinstance(d, str) else d.isoformat()


def _month(s: str | None) -> date | None:
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})", str(s))
    return date(int(m.group(1)), int(m.group(2)), 1) if m else None


def _title(s: str) -> str:
    return " ".join(w.upper() if len(w) <= 2 and w.isalpha() and w.lower() in ("ne", "nw", "se", "sw") else w.capitalize()
                    for w in s.split())


# ----------------------------------------------------------------------------------------------- household


def _household(ix: Ix, docs: list[ParsedDocument], hint: dict) -> tuple[HouseholdOut, int | None]:
    years = sorted({d.tax_year for d in docs if d.kind == "form_1040" and d.tax_year})
    se_years = sorted({d.tax_year for d in docs if d.kind == "schedule_e" and d.tax_year})
    latest = max(years or se_years or [None], key=lambda x: x or 0)
    by_year = []
    for y in years:
        by_year.append({"tax_year": y, "wages_cents": ix.get(None, "form_1040.line1a.wages", y),
                        "agi_cents": ix.get(None, "form_1040.line11.agi", y),
                        "taxable_income_cents": ix.get(None, "form_1040.line15.taxable_income", y)})
    wages = ix.get(None, "form_1040.line1a.wages", latest) if years else None
    agi = ix.get(None, "form_1040.line11.agi", latest) if years else None
    magi = ix.get(None, "form_8582.line6.magi", latest) or agi
    status = ix.get(None, "form_1040.filing_status", latest) if years else None
    state = ix.get(None, "form_1040.home_state", latest) if years else None
    h = HouseholdOut(
        name=hint.get("name") or "Imported household",
        filing_status=status if status in ("single", "mfj", "mfs", "hoh") else None,
        state=state or hint.get("state"),
        tax_year_latest=latest,
        wages_cents=wages,
        other_income_cents=(agi - wages) if agi is not None and wages is not None else None,
        magi_cents=magi,
        goal=hint.get("goal", ""),
        by_year=by_year,
    )
    return h, latest


# ----------------------------------------------------------------------------------------------- loans


def _loan_type(text: str) -> str:
    t = (text or "").lower()
    if "line of credit" in t or "heloc" in t:
        return "heloc"
    if "arm" in t.split() or "adjustable" in t or re.search(r"\b\d+/\d+\b", t):
        return "arm"
    if "interest-only" in t or "interest only" in t:
        return "interest_only"
    if "balloon" in t:
        return "balloon"
    return "fixed"


def _loans(pk: str, fields: list[ExtractedField]) -> tuple[list[LoanOut], list[dict]]:
    """One LoanOut per loan (statements grouped by loan number, newest statement wins). Also returns the per-statement
    records the interest/balance rules need."""
    by_doc: dict[str, dict[str, ExtractedField]] = defaultdict(dict)
    for f in fields:
        if f.property_key == pk and f.field.startswith("mortgage."):
            by_doc[f.document_key][f.field.split(".", 1)[1]] = f
    stmts = []
    for doc_key, fs in by_doc.items():
        v = {k: f.value for k, f in fs.items()}
        stmts.append({"doc": doc_key, "year": next(iter(fs.values())).tax_year, "v": v, "f": fs})
    groups: dict[str, list[dict]] = defaultdict(list)
    for st in stmts:
        v = st["v"]
        groups[str(v.get("loan_number") or f"{v.get('lender', '')}:{v.get('lien_position', 1)}")].append(st)
    loans = []
    for key, sts in groups.items():
        st = max(sts, key=lambda s: s["v"].get("statement_date") or "")
        v = st["v"]
        paid = bool(v.get("paid_in_full"))
        as_of = v.get("statement_date") or v.get("payoff_date") or f"{st['year'] or 2000}-12-31"
        loans.append(LoanOut(
            key=key, lender=v.get("lender") or "", loan_type=_loan_type(v.get("loan_type_text", "")),
            original_cents=v.get("original_amount") or v.get("credit_limit"),
            balance_cents=0 if paid else (v.get("principal_balance") or 0), balance_as_of=as_of,
            rate=float(v.get("interest_rate") or 0.0), term_months=v.get("term_months"),
            io_end_date=v.get("io_period_end"), arm_reset_date=v.get("next_rate_change_date"),
            arm_index_margin=v.get("index_margin"), monthly_payment_cents=v.get("monthly_payment"),
            maturity_date=v.get("maturity_date"), lien_position=int(v.get("lien_position") or 1), is_paid_off=paid,
            source_document_keys=sorted({s["doc"] for s in sts}),
        ))
    loans.sort(key=lambda lo: lo.lien_position)
    return loans, stmts


# ----------------------------------------------------------------------------------------------- properties


def _property(pk: str, ix: Ix, matches: dict[str, PropertyMatch], se_years: list[int], fields: list[ExtractedField]):
    variants = sorted({m.raw_address for m in matches.values() if m.property_key == pk})
    se_raw = [f.address_raw for f in fields if f.property_key == pk and f.field == "schedule_e.line1a.address" and f.address_raw]
    best_raw = Counter(se_raw).most_common(1)[0][0] if se_raw else (variants[0] if variants else pk)
    pa = normalize(pk)
    street = best_raw.split(",")[0].strip() if "," in best_raw else pa.street_line()
    years = sorted({f.tax_year for f in fields if f.property_key == pk and f.document_kind == "schedule_e" and f.tax_year})
    type_code = None
    for y in reversed(years):
        type_code = ix.get(pk, "schedule_e.line1b.type", y)
        if type_code is not None:
            break
    ptype = TYPE_CODES.get(int(type_code), "other") if type_code is not None else "other"
    multi = bool(re.search(r"\b(unit|apt|#)\s*[a-z0-9]+\s*[/&-]\s*[a-z0-9]+", " ".join(variants).lower()))

    rent_rolls, expense_years, ledger = [], [], []
    basis = ix.get(pk, "form_4562.line19h.basis")
    pis = _month(ix.get(pk, "form_4562.line19h.placed_in_service"))
    for y in years:
        rents = ix.get(pk, "schedule_e.line3.rents", y)
        if rents is not None:
            rent_rolls.append(RentRollOut(tax_year=y, gross_rent_cents=rents,
                                          other_income_cents=ix.get(pk, "schedule_e.line4.royalties", y) or 0,
                                          fair_rental_days=ix.get(pk, "schedule_e.line2.fair_rental_days", y),
                                          personal_use_days=ix.get(pk, "schedule_e.line2.personal_use_days", y)))
        cols = {col: sum(ix.get(pk, f"schedule_e.{ln}", y) or 0 for ln in lines) for col, lines in EXPENSE_MAP.items()}
        expense_years.append(ExpenseYearOut(tax_year=y, **cols,
                                            line20_total_expenses_cents=ix.get(pk, "schedule_e.line20.total_expenses", y),
                                            line21_income_or_loss_cents=ix.get(pk, "schedule_e.line21.income_or_loss", y)))
        claimed = ix.get(pk, "schedule_e.line18.depreciation", y)
        if claimed is None:
            claimed = ix.get(pk, "form_4562.line22.total", y)
        if claimed is not None:
            allowable = res_27_5_allowable_cents(basis, pis, y) if basis and pis else None
            ledger.append(DepreciationLedgerOut(tax_year=y, allowed_cents=claimed, allowable_cents=allowable,
                                                method="sl_39" if ptype == "commercial" else "sl_27_5",
                                                note="Schedule E line 18" + ("; allowable from Form 4562 line 19h basis + "
                                                                              "placed-in-service, Pub 946 Table A-6"
                                                                              if allowable is not None else "")))
    loans, stmts = _loans(pk, fields)
    purchase = ix.get(pk, "closing.contract_sales_price")
    settle = ix.get(pk, "closing.settlement_date")
    value = ix.get(pk, "appraisal.market_value")
    po = PropertyOut(
        key=pk, nickname=_title(street.lower()) if street else pk, address_line1=_title(street.lower()),
        city=_title(pa.city), state=pa.state.upper(), zip=pa.zip, address_variants=variants, property_type=ptype,
        units=2 if multi or ptype == "multifamily" else 1, purchase_date=settle,
        purchase_price_cents=purchase, placed_in_service_date=_iso(pis), depreciable_basis_cents=basis,
        current_value_cents=value, value_source="confirmed" if value else "estimated",
        value_as_of=ix.get(pk, "appraisal.effective_date"), years_seen=years, loans=loans, rent_rolls=rent_rolls,
        expense_years=expense_years, depreciation_ledger=ledger,
    )
    return po, stmts, type_code


# ----------------------------------------------------------------------------------------------- rules


def _rules(po: PropertyOut, stmts: list[dict], type_code, ix: Ix, se_years: list[int]) -> list[Finding]:
    pk, out = po.key, []
    name = po.nickname
    # STR
    if type_code is not None and int(type_code) == 3:
        y = max(po.years_seen) if po.years_seen else None
        fair, pers = ix.field(pk, "schedule_e.line2.fair_rental_days", y), ix.field(pk, "schedule_e.line2.personal_use_days", y)
        cands = [c for c in (_cand(fair) if fair else None, _cand(pers) if pers else None) if c]
        out.append(Finding(key=f"str:{pk}", kind="unsupported_structure", field="schedule_e.line1b.type", severity="warn",
                           property_key=pk, tax_year=y, candidates=cands,
                           message=f"{name}: Schedule E type 3 (vacation / short-term rental). Short-term rental rules apply "
                                   "(average stay <= 7 days can make the activity non-passive or non-rental); not modeled. "
                                   "Verify with the CPA."))
    # missing from the latest return
    if se_years and po.years_seen and max(po.years_seen) < max(se_years):
        latest = max(se_years)
        cands = [_cand(f, f"schedule_e {f.tax_year} line 1a") for f in ix.all(pk, "schedule_e.line1a.address")]
        cands.append(Candidate(source=f"schedule_e {latest}", value=None))
        out.append(Finding(key=f"missing_latest:{pk}", kind="missing", field="schedule_e.property", severity="warn",
                           property_key=pk, tax_year=latest, candidates=cands,
                           message=f"{name} appears on the {', '.join(map(str, po.years_seen))} Schedule E but not on "
                                   f"{latest}: sold? converted to personal use? Confirm status before relying on {latest}."))
    # depreciation vs allowable, and Schedule E line 18 vs Form 4562 line 22
    for led in po.depreciation_ledger:
        y = led.tax_year
        if led.allowable_cents:
            gap = Decimal(led.allowed_cents - led.allowable_cents) / Decimal(led.allowable_cents)
            if abs(gap) > DEP_OUTLIER_PCT:
                f18 = ix.field(pk, "schedule_e.line18.depreciation", y)
                cands = ([_cand(f18)] if f18 else []) + [Candidate(source="MACRS 27.5 SL/MM allowable (Pub 946 Table A-6)",
                                                                   value=led.allowable_cents)]
                out.append(Finding(
                    key=f"dep_outlier:{pk}:{y}", kind="outlier", field="schedule_e.line18.depreciation", severity="warn",
                    property_key=pk, tax_year=y, candidates=cands,
                    message=f"{name}: {y} depreciation claimed {_usd(led.allowed_cents)} is {abs(gap):.0%} "
                            f"{'below' if gap < 0 else 'above'} the {_usd(led.allowable_cents)} allowable. Recapture uses "
                            "allowed-or-allowable; consider Form 3115."))
        f18, f22 = ix.field(pk, "schedule_e.line18.depreciation", y), ix.field(pk, "form_4562.line22.total", y)
        if f18 and f22 and f18.value != f22.value:
            out.append(Finding(key=f"dep_4562:{pk}:{y}", kind="conflict", field="schedule_e.line18.depreciation",
                               severity="warn", property_key=pk, tax_year=y, candidates=[_cand(f18), _cand(f22)],
                               message=f"{name} {y}: Schedule E line 18 ({_usd(f18.value)}) and Form 4562 line 22 "
                                       f"({_usd(f22.value)}) disagree."))
    # closing statement without a land allocation
    land = ix.field(pk, "closing.land_allocation_present")
    if land is not None and land.value is False:
        price = ix.field(pk, "closing.contract_sales_price")
        out.append(Finding(key=f"missing_land_split:{pk}", kind="missing", field="closing_statement.land_allocation",
                           severity="info", property_key=pk, candidates=[_cand(price)] if price else [],
                           message=f"{name}: the closing statement shows the price but no land / improvement split. "
                                   "Depreciable basis uses the default land share (30%) until an assessor ratio or "
                                   "appraisal allocation is entered."))
    # mortgage interest: Schedule E line 12 vs the lenders' year-to-date interest
    for y in po.years_seen:
        f12 = ix.field(pk, "schedule_e.line12.mortgage_interest", y)
        ys = [s for s in stmts if s["year"] == y and "interest_paid_ytd" in s["v"]]
        if not f12 or not ys:
            continue
        loan_keys = {lo.key for lo in po.loans
                     if not (lo.is_paid_off and (lo.balance_as_of or "")[:4] < str(y))}
        covered = {str(s["v"].get("loan_number") or "") for s in ys}
        if loan_keys - covered:
            continue  # a loan without a statement for that year: the sum would be partial
        lender_total = sum(s["v"]["interest_paid_ytd"] for s in ys)
        diff = f12.value - lender_total
        if abs(diff) > 10_000 and abs(Decimal(diff)) > Decimal(lender_total) * Decimal("0.01"):
            out.append(Finding(
                key=f"conflict:{pk}:mortgage_interest:{y}", kind="conflict", field="schedule_e.line12.mortgage_interest",
                severity="block" if abs(Decimal(diff)) > Decimal(lender_total) * Decimal("0.10") else "warn",
                property_key=pk, tax_year=y,
                candidates=[_cand(f12)] + [_cand(s["f"]["interest_paid_ytd"], f"mortgage_statement {y} interest_paid_ytd")
                                           for s in ys],
                message=f"{name} {y}: Schedule E line 12 mortgage interest {_usd(f12.value)} is {_usd(abs(diff))} "
                        f"{'above' if diff > 0 else 'below'} the lender's year-to-date interest {_usd(lender_total)}. "
                        "Not averaged: pick the right one."))
    # statement balance vs amortization implied by the statement's own terms
    for s in stmts:
        v = s["v"]
        if v.get("paid_in_full") or _loan_type(v.get("loan_type_text", "")) in ("heloc", "arm", "interest_only"):
            continue
        need = ("original_amount", "origination_date", "interest_rate", "term_months", "principal_balance", "statement_date")
        if not all(v.get(k) for k in need):
            continue
        orig = date.fromisoformat(v["origination_date"])
        first = date(orig.year + (orig.month // 12), orig.month % 12 + 1, 1)
        sched = amortize(v["original_amount"], Decimal(str(v["interest_rate"])), int(v["term_months"]), first)
        as_of = date.fromisoformat(v["statement_date"])
        rows = [r for r in sched if r["date"] <= as_of]
        implied = rows[-1]["balance"] if rows else v["original_amount"]
        if implied and abs(Decimal(v["principal_balance"] - implied)) > Decimal(implied) * BALANCE_CONFLICT_PCT:
            out.append(Finding(
                key=f"conflict:{pk}:loan_balance:{v.get('loan_number')}", kind="conflict", field="loan.balance_cents",
                severity="warn", property_key=pk, tax_year=s["year"],
                candidates=[_cand(s["f"]["principal_balance"], "mortgage_statement principal_balance"),
                            Candidate(source="amortization implied by the statement's own terms", value=implied)],
                message=f"{name}: statement balance {_usd(v['principal_balance'])} differs from the "
                        f"{_usd(implied)} its own rate/term/origination imply (> 2%): recast, extra principal, or a "
                        "misread."))
    return out


def _low_confidence(fields: list[ExtractedField]) -> list[Finding]:
    out = []
    for f in fields:
        if f.extractor == "ocr" and f.confidence < 0.6 and f.unit == "cents":
            out.append(Finding(key=f"low_conf:{f.document_key}:{f.field}:{f.property_key}", kind="conflict", field=f.field,
                               severity="info", property_key=f.property_key, tax_year=f.tax_year, candidates=[_cand(f, "ocr")],
                               message=f"Low-confidence OCR read of {f.field} on {f.document_key} page {f.page} "
                                       f"({f.raw_text!r}, confidence {f.confidence:.2f}); the form's arithmetic did not "
                                       "check out. Confirm against the page."))
    return out


# ----------------------------------------------------------------------------------------------- entry point


def reconcile(docs: list[ParsedDocument], fields: list[ExtractedField], matches: dict[str, PropertyMatch],
              extra_findings: list[Finding] | None = None, household_hint: dict | None = None) -> ReconciledHousehold:
    hint = household_hint or {}
    ix = Ix(fields)
    household, _latest = _household(ix, docs, hint)
    se_years = sorted({d.tax_year for d in docs if d.kind == "schedule_e" and d.tax_year})
    keys = list(dict.fromkeys(f.property_key for f in fields if f.property_key))
    props, findings = [], list(extra_findings or [])
    for pk in keys:
        po, stmts, type_code = _property(pk, ix, matches, se_years, fields)
        props.append(po)
        findings += _rules(po, stmts, type_code, ix, se_years)
    findings += _low_confidence(fields)
    suspended = []
    for y in sorted({f.tax_year for f in fields if f.field == "form_8582.unallowed_loss_total" and f.tax_year}):
        v = ix.get(None, "form_8582.unallowed_loss_total", y)
        if v is not None:
            suspended.append(SuspendedLossOut(tax_year=y, carryforward_cents=abs(int(v))))
    documents = [DocumentOut(key=d.filename, kind=d.kind, tax_year=d.tax_year, filename=d.filename, sha256=d.sha256,
                             page_count=d.page_count, classify_confidence=d.classify_confidence) for d in docs]
    seen, uniq = set(), []
    for f in findings:
        if f.key not in seen:
            seen.add(f.key)
            uniq.append(f)
    return ReconciledHousehold(generated_at=datetime.now(UTC).isoformat(timespec="seconds"), pipeline_version=__version__,
                               household=household, properties=props, suspended_losses=suspended, documents=documents,
                               extracted_fields=fields, findings=uniq, property_matches=list(matches.values()))
