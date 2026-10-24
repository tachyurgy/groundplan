"""Reference implementation of the engine wire API (groundplan.engine.wire). The Go port serves the same two
endpoints; with GP_ENGINE=go the Python API forwards to it. Pure compute: no workspace, no database."""

from __future__ import annotations

from fastapi import APIRouter, Body
from fastapi.encoders import jsonable_encoder

from groundplan.api.problems import Problem
from groundplan.engine import wire
from groundplan.engine.analysis import analyze_property
from groundplan.engine.strategies import compare_strategies

router = APIRouter(prefix="/engine", tags=["engine (internal wire API)"])


def _public(an: dict) -> dict:
    return {k: v for k, v in an.items() if not k.startswith("_")}


@router.post("/analyze", summary="Pure engine: PropertyModel + HouseholdModel -> analysis JSON")
def engine_analyze(body: dict = Body(..., description="{property, household, year, horizon} in the wire format")):
    try:
        pm, hm = wire.decode_property(body["property"]), wire.decode_household(body["household"])
        an = analyze_property(pm, hm, body.get("year") or hm.tax_year, int(body.get("horizon") or 10))
    except (KeyError, TypeError, ValueError, ArithmeticError) as e:
        raise Problem(422, "Invalid engine input", f"{type(e).__name__}: {e}") from e
    return jsonable_encoder(_public(an))


@router.post("/strategies", summary="Pure engine: PropertyModel + HouseholdModel + StrategyAssumptions -> comparison JSON")
def engine_strategies(body: dict = Body(..., description="{property, household, assumptions} in the wire format")):
    try:
        pm, hm = wire.decode_property(body["property"]), wire.decode_household(body["household"])
        r = compare_strategies(pm, hm, wire.decode_assumptions(body.get("assumptions") or {}))
    except (KeyError, TypeError, ValueError, ArithmeticError) as e:
        raise Problem(422, "Invalid engine input", f"{type(e).__name__}: {e}") from e
    return jsonable_encoder(r)
