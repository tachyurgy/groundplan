"""Extractor implementations behind one protocol.

* :class:`RulesExtractor` (default): the anchored-line / key-value extractors in ``forms/``.
  Deterministic, offline, every value carries page + bbox, and it is free.
* :class:`LLMExtractor` (optional, OFF by default, never used in tests): asks Claude to read the
  page text (words with coordinates) and return fields matching :data:`LLM_SCHEMA`. Enabled only
  when ``GP_LLM_EXTRACT=1`` *and* ``GP_LLM_PROVIDER`` is ``anthropic`` (reads ``ANTHROPIC_API_KEY``
  or an ``ant auth login`` profile) or ``bedrock`` (boto3 credentials + ``AWS_REGION``). It costs
  money per document, which is why it is opt-in.
* :class:`CrossCheckExtractor`: runs both, keeps the rules values as the record, and turns every
  disagreement into a ``conflict`` Finding with both candidates. The LLM never silently
  overrides the rules extractor; a human resolves the disagreement.

The prompt and the JSON schema are module constants so they are reviewable in one place.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Protocol

from gp_pipeline.extract.forms import (
    appraisal,
    closing_statement,
    form_1040,
    form_4562,
    form_8582,
    mortgage_statement,
    schedule_e,
)
from gp_pipeline.models import Candidate, ExtractedField, ExtractionResult, Finding, ParsedDocument

log = logging.getLogger(__name__)

FORM_EXTRACTORS = {
    "schedule_e": schedule_e.extract,
    "form_1040": form_1040.extract,
    "form_4562": form_4562.extract,
    "form_8582": form_8582.extract,
    "mortgage_statement": mortgage_statement.extract,
    "closing_statement": closing_statement.extract,
    "appraisal": appraisal.extract,
}


class Extractor(Protocol):
    name: str

    def extract(self, doc: ParsedDocument) -> ExtractionResult: ...


class RulesExtractor:
    name = "rules"

    def extract(self, doc: ParsedDocument) -> ExtractionResult:
        fn = FORM_EXTRACTORS.get(doc.kind)
        return ExtractionResult(fields=fn(doc) if fn else [])


# ----------------------------------------------------------------------------- LLM

LLM_SYSTEM_PROMPT = """You extract values from US tax and real-estate documents for a financial-planning tool.
You receive one document as a list of words with their page number and bounding box (PDF points, origin top-left).
Rules:
- Report ONLY values that are printed in the document. Never compute, infer, total, or fix a number.
- Copy each value exactly as printed in `raw_text`; put the normalized value in `value`:
  money as integer cents (negative for amounts in parentheses), dates as YYYY-MM-DD, rates as decimals
  (5.875% -> 0.05875), integers as integers, everything else as the printed string.
- Use the field keys listed in the user message. For Schedule E per-property lines, set `address` to the
  property address printed on line 1a for that column; for household-level lines leave it empty.
- `page` and `bbox` must point at the words you read the value from.
- If a field is not printed, omit it. Do not guess."""

LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "document_kind": {"type": "string"},
        "tax_year": {"type": ["integer", "null"]},
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "address": {"type": "string"},
                    "value": {"type": ["string", "integer", "number", "boolean"]},
                    "unit": {"type": "string", "enum": ["cents", "date", "text", "bool", "rate", "int"]},
                    "raw_text": {"type": "string"},
                    "page": {"type": "integer"},
                    "bbox": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["field", "address", "value", "unit", "raw_text", "page", "bbox"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["document_kind", "tax_year", "fields"],
    "additionalProperties": False,
}

FIELD_KEYS_HINT = {
    "schedule_e": "schedule_e.line1a.address, schedule_e.line1b.type, schedule_e.line2.fair_rental_days, "
    "schedule_e.line2.personal_use_days, schedule_e.line3.rents ... schedule_e.line22.deductible_loss, "
    "schedule_e.line23a.total_rents ... schedule_e.line26.total",
    "form_1040": "form_1040.filing_status (single|mfj|mfs|hoh|qss), form_1040.line1a.wages, form_1040.line11.agi, "
    "form_1040.line15.taxable_income, form_1040.line24.total_tax, ...",
    "form_4562": "form_4562.activity, form_4562.line17.prior_macrs, form_4562.line19h.basis, "
    "form_4562.line19h.placed_in_service (YYYY-MM), form_4562.line19h.deduction, form_4562.line22.total",
    "form_8582": "form_8582.line1a.net_income ... form_8582.line11.total_allowed, form_8582.ws5.unallowed_loss, "
    "form_8582.unallowed_loss_total",
    "mortgage_statement": "mortgage.lender, mortgage.property_address, mortgage.principal_balance, "
    "mortgage.interest_rate, mortgage.monthly_payment, mortgage.interest_paid_ytd, mortgage.next_rate_change_date, "
    "mortgage.io_period_end, mortgage.lien_position, mortgage.paid_in_full, ...",
}

DEFAULT_MODEL = "claude-opus-5-5"


def llm_enabled() -> bool:
    return os.environ.get("GP_LLM_EXTRACT") == "1" and os.environ.get("GP_LLM_PROVIDER") in ("anthropic", "bedrock")


class LLMExtractor:
    """Claude-backed extractor. Constructing it is free; calling ``extract`` costs money."""

    name = "llm"

    def __init__(self, provider: str | None = None, model: str | None = None):
        self.provider = provider or os.environ.get("GP_LLM_PROVIDER", "anthropic")
        self.model = model or os.environ.get("GP_LLM_MODEL", DEFAULT_MODEL)
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic  # optional dependency: `uv sync --extra llm`

            if self.provider == "bedrock":
                self._client = anthropic.AnthropicBedrockMantle(aws_region=os.environ.get("AWS_REGION", "us-west-2"))
                if not self.model.startswith("anthropic."):
                    self.model = f"anthropic.{self.model}"
            else:
                self._client = anthropic.Anthropic()
        return self._client

    @staticmethod
    def build_user_message(doc: ParsedDocument) -> str:
        words = [
            {"p": pg.number, "t": w.text, "b": [round(w.x0), round(w.top), round(w.x1), round(w.bottom)]}
            for pg in doc.pages
            for w in pg.words
        ]
        return (
            f"Document kind (from classifier): {doc.kind}; tax year: {doc.tax_year}.\n"
            f"Field keys to use: {FIELD_KEYS_HINT.get(doc.kind, 'use descriptive dotted keys')}\n"
            f"Words (JSON, p=page, t=text, b=bbox):\n{json.dumps(words, separators=(',', ':'))}"
        )

    def extract(self, doc: ParsedDocument) -> ExtractionResult:
        from gp_pipeline.address import key as address_key

        client = self._get_client()
        resp = client.messages.create(
            model=self.model,
            max_tokens=16000,
            system=LLM_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": self.build_user_message(doc)}],
            output_config={"format": {"type": "json_schema", "schema": LLM_SCHEMA}},
        )
        if resp.stop_reason == "refusal":
            log.warning("llm_extract_refusal %s", doc.filename)
            return ExtractionResult(fields=[])
        text = next(b.text for b in resp.content if b.type == "text")
        data = json.loads(text)
        fields = []
        for f in data.get("fields", []):
            addr = f.get("address") or None
            fields.append(ExtractedField(
                document_key=doc.filename, entity_hint="property" if addr else "household",
                property_key=address_key(addr) if addr else None, address_raw=addr, field=f["field"],
                value=f["value"], unit=f["unit"], page=f["page"], bbox=(f.get("bbox") or [0, 0, 0, 0])[:4],
                confidence=0.8, extractor="llm", raw_text=f.get("raw_text", ""),
            ))
        return ExtractionResult(fields=fields)


class CrossCheckExtractor:
    """Rules are the record; the second opinion only produces Findings where it disagrees."""

    name = "crosscheck"

    def __init__(self, primary: Extractor | None = None, secondary: Extractor | None = None):
        self.primary = primary or RulesExtractor()
        self.secondary = secondary or LLMExtractor()

    def extract(self, doc: ParsedDocument) -> ExtractionResult:
        a = self.primary.extract(doc)
        b = self.secondary.extract(doc)
        index = {(f.field, f.property_key): f for f in b.fields}
        findings: list[Finding] = []
        for f in a.fields:
            other = index.get((f.field, f.property_key))
            if other is None or _same(f.value, other.value):
                continue
            findings.append(Finding(
                key=f"xcheck:{doc.filename}:{f.field}:{f.property_key}",
                kind="conflict", field=f.field, severity="warn", property_key=f.property_key, tax_year=doc.tax_year,
                message=f"Extractors disagree on {f.field} in {doc.filename}: rules read {f.value!r}, "
                f"{self.secondary.name} read {other.value!r}. Confirm against page {f.page}.",
                candidates=[Candidate(source=self.primary.name, value=f.value, document_key=doc.filename, page=f.page),
                            Candidate(source=self.secondary.name, value=other.value, document_key=doc.filename,
                                      page=other.page)],
            ))
        return ExtractionResult(fields=a.fields, findings=a.findings + b.findings + findings)


def _same(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return " ".join(a.lower().split()) == " ".join(b.lower().split())
    return a == b


def default_extractor() -> Extractor:
    if llm_enabled() and os.environ.get("GP_LLM_CROSSCHECK", "1") == "1":
        return CrossCheckExtractor()
    return RulesExtractor()
