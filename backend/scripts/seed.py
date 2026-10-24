"""Load the Okafor-Lindqvist demo household (SPEC §4.1) into the DB from ``fixtures/seed/okafor-lindqvist.json``.

That JSON is generated from the SAME facts that render the synthetic PDFs (``python -m gp_pipeline.synth``), so the
seeded properties carry the pipeline's normalized address keys and the documents' numbers: uploading a synthetic
return lands on the existing properties. The one planted gap: the Maple duplex 2025 rent roll is $1,600 short of
Schedule E line 3, which surfaces as a blocking conflict when the 2025 Schedule E is uploaded. The Go port loads the
same JSON (one seed, two backends).

Idempotent: deletes any previous copy of the demo household for the advisor first.
Run: `uv run python -m scripts.seed` (uses GP_DATABASE_URL, default groundplan_dev). Override the file with GP_SEED_PATH.
"""

from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from groundplan.config import get_settings
from groundplan.db import base
from groundplan.db import models as m

SEED_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "seed" / "okafor-lindqvist.json"
DEMO_NAME = "Okafor-Lindqvist household"

PROPERTY_DATES = ("purchase_date", "placed_in_service_date", "value_as_of", "former_residence_until")
PROPERTY_RATES = ("land_pct", "appreciation_rate", "rent_growth_rate", "expense_growth_rate", "vacancy_rate", "mgmt_fee_rate",
                  "capex_reserve_rate", "selling_cost_rate")


@lru_cache(maxsize=1)
def load_seed() -> dict:
    return json.loads(Path(os.environ.get("GP_SEED_PATH") or SEED_PATH).read_text())


def _date(x):
    return date.fromisoformat(x) if x else None


def _dec(x):
    return Decimal(x) if x is not None else None


def ensure_advisor(s: Session, advisor_id: str | None = None, name: str = "Dev Advisor",
                   firm: str = "Groundplan Demo Advisory") -> m.Advisor:
    advisor_id = advisor_id or get_settings().dev_advisor_id
    a = s.get(m.Advisor, advisor_id)
    if a is None:
        a = m.Advisor(id=advisor_id, advisor_id=advisor_id, firm_name=firm, name=name, email="advisor@example.com")
        s.add(a)
        s.flush()
    return a


def seed(s: Session, advisor_id: str | None = None) -> m.Household:
    data = load_seed()
    adv = ensure_advisor(s, advisor_id)
    aid = adv.id
    for old in s.execute(m.scoped(m.Household, aid).where(m.Household.name == DEMO_NAME)).scalars():
        s.delete(old)
    s.flush()
    h = m.Household(advisor_id=aid, **data["household"])
    s.add(h)
    s.flush()
    by_ref: dict[str, m.Property] = {}
    for pd in data["properties"]:
        cols = {k: v for k, v in pd.items() if k not in ("ref", "loans", "rent_rolls", "expense_years", "depreciation_ledger")}
        for k in PROPERTY_DATES:
            if k in cols:
                cols[k] = _date(cols[k])
        for k in PROPERTY_RATES:
            if k in cols:
                cols[k] = _dec(cols[k])
        p = m.Property(advisor_id=aid, household_id=h.id, **cols)
        s.add(p)
        s.flush()
        by_ref[pd["ref"]] = p
        for lo in pd["loans"]:
            s.add(m.Loan(advisor_id=aid, property_id=p.id, **{**lo, "balance_as_of": _date(lo["balance_as_of"]),
                                                              "rate": _dec(lo["rate"]), "arm_reset_date": _date(lo["arm_reset_date"]),
                                                              "arm_index_margin": _dec(lo["arm_index_margin"]),
                                                              "maturity_date": _date(lo["maturity_date"])}))
        for r in pd["rent_rolls"]:
            s.add(m.RentRoll(advisor_id=aid, property_id=p.id, **r))
        for e in pd["expense_years"]:
            s.add(m.ExpenseYear(advisor_id=aid, property_id=p.id, **e))
        for d in pd["depreciation_ledger"]:
            s.add(m.DepreciationLedger(advisor_id=aid, property_id=p.id, **d))
    for sl in data["suspended_losses"]:
        s.add(m.SuspendedLoss(advisor_id=aid, household_id=h.id, **sl))
    for f in data["findings"]:
        f = dict(f)
        ref = f.pop("property", None)
        s.add(m.Finding(advisor_id=aid, household_id=h.id, property_id=by_ref[ref].id if ref else None, **f))
    s.flush()
    return h


def main() -> None:
    Session = base.configure()
    with Session() as s:
        h = seed(s)
        s.commit()
        print(f"seeded {h.name} ({h.id}) with {len(h.properties)} properties for advisor {h.advisor_id}")


if __name__ == "__main__":
    main()
