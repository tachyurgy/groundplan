"""JSON wire format for the engine inputs: what the Python API sends to an external engine (the Go port) and what the
reference endpoints `POST /engine/analyze` and `POST /engine/strategies` accept (SPEC §6, the strangler migration).

Encoding rules (both directions, lossless for everything the engine reads):
  Decimal -> string ("0.035"), date -> "YYYY-MM-DD", set -> sorted list, int dict keys (tax years) -> strings,
  Input -> {key, value, source: {type, ref, page, document_id?, bbox?}, label?}  (provenance travels with the numbers).

    POST /engine/analyze     {"property": PropertyModel, "household": HouseholdModel, "year": int|null, "horizon": int}
                             -> the analysis JSON (the public part of GET /properties/{id}/analysis, before the API adds
                                property/loan/finding/observation decorations)
    POST /engine/strategies  {"property": PropertyModel, "household": HouseholdModel, "assumptions": StrategyAssumptions}
                             -> compare_strategies JSON (before the API's present() step)
"""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from typing import Any

from groundplan.engine.cashflow import YearOperations
from groundplan.engine.figure import Input, Source
from groundplan.engine.loans import LoanInput
from groundplan.engine.models import HouseholdModel, PropertyModel
from groundplan.engine.strategies import ExchangeAssumptions, StrategyAssumptions

WIRE_VERSION = "1"


def encode(x: Any) -> Any:
    if isinstance(x, Input):
        d = {"key": x.key, "value": encode(x.value), "source": {k: v for k, v in dataclasses.asdict(x.source).items()
                                                                if v is not None}}
        if x.label:
            d["label"] = x.label
        return d
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return {f.name: encode(getattr(x, f.name)) for f in dataclasses.fields(x)}
    if isinstance(x, Decimal):
        return str(x)
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, set | frozenset):
        return sorted(encode(v) for v in x)
    if isinstance(x, dict):
        return {str(k): encode(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [encode(v) for v in x]
    return x


def _d(s) -> date | None:
    return date.fromisoformat(s) if s else None


def _dec(s) -> Decimal | None:
    return None if s is None else Decimal(str(s))


def _input(d: dict) -> Input:
    return Input(key=d["key"], value=d.get("value"), source=Source(**d.get("source", {})), label=d.get("label"))


def decode_property(d: dict) -> PropertyModel:
    rates = ("land_pct", "appreciation_rate", "rent_growth_rate", "expense_growth_rate", "vacancy_rate", "mgmt_fee_rate",
             "capex_reserve_rate", "selling_cost_rate")
    loans = []
    for lo in d.get("loans", []):
        loans.append(LoanInput(**{**lo, "balance_as_of": _d(lo["balance_as_of"]), "rate": _dec(lo["rate"]),
                                  "arm_reset_date": _d(lo.get("arm_reset_date")), "arm_index_margin": _dec(lo.get("arm_index_margin")),
                                  "arm_index": _dec(lo.get("arm_index")), "maturity_date": _d(lo.get("maturity_date"))}))
    years = {}
    for k, y in (d.get("years") or {}).items():
        years[int(k)] = YearOperations(**{**y, "sources": {sk: _input(sv) for sk, sv in (y.get("sources") or {}).items()}})
    kw = {**d, "loans": loans, "years": years,
          "purchase_date": _d(d.get("purchase_date")) or date(2015, 1, 1),
          "placed_in_service_date": _d(d.get("placed_in_service_date")), "value_as_of": _d(d.get("value_as_of")),
          "former_residence_until": _d(d.get("former_residence_until")),
          "capital_improvements_paid": {int(k): v for k, v in (d.get("capital_improvements_paid") or {}).items()},
          "blocked_keys": set(d.get("blocked_keys") or [])}
    for r in rates:
        kw[r] = _dec(d.get(r))
    return PropertyModel(**kw)


def decode_household(d: dict) -> HouseholdModel:
    return HouseholdModel(**d)


def decode_assumptions(d: dict) -> StrategyAssumptions:
    x = d.get("exchange") or {}
    ex = ExchangeAssumptions(**{**x, "load_rate": _dec(x["load_rate"]) if "load_rate" in x else ExchangeAssumptions.load_rate,
                                "dst_yield": _dec(x["dst_yield"]) if "dst_yield" in x else ExchangeAssumptions.dst_yield})
    return StrategyAssumptions(**{**{k: v for k, v in d.items() if k != "exchange"}, "exchange": ex})
