"""State income tax on a real-estate gain, table-driven from fixtures/engine/states.json.

Every taxing state treats the gain as ordinary income (stacked on the household's other income, marginal method:
tax(other + gain) - tax(other)) unless the table carries a `ltcg_exclusion` fraction. No-tax states return 0.
An unsupported state returns a Figure of 0 with status estimated plus a Finding(kind=unsupported_structure);
we never invent brackets. Clawback states (CA, OR, MA, MT) get an informational note for 1031 replacements out of
state. State standard deductions / exemptions are ignored (noted) -- the shape matters more than the last dollar.
"""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from groundplan.engine.figure import D, Figure, Input, cents, money

STATES_PATH = Path(__file__).resolve().parents[3] / "fixtures" / "engine" / "states.json"


@lru_cache(maxsize=1)
def load_states(path: str | None = None) -> dict:
    with open(path or STATES_PATH) as f:
        return json.load(f)


def _brackets_for(row: dict, filing_status: str) -> list[list]:
    br = row.get("brackets") or {}
    if filing_status in br:
        return br[filing_status]
    if filing_status == "mfs" and "single" in br:
        return br["single"]
    if filing_status == "hoh" and "single" in br:
        return br.get("hoh", br["single"])
    return br.get("all") or next(iter(br.values()))


def state_tax_on_cents(taxable_cents: Decimal, row: dict, filing_status: str) -> Decimal:
    kind = row["kind"]
    if kind == "none":
        return Decimal(0)
    taxable = max(Decimal(0), taxable_cents)
    if kind == "flat":
        return taxable * D(row["rate"])
    tax = Decimal(0)
    lower = Decimal(0)
    for rate, upper in _brackets_for(row, filing_status):
        up = None if upper is None else Decimal(upper) * 100
        seg_hi = taxable if up is None else min(taxable, up)
        if seg_hi > lower:
            tax += (seg_hi - lower) * D(rate)
        if up is None or taxable <= up:
            break
        lower = up
    for s in row.get("surtaxes", []):
        thr = Decimal(s["over"]) * 100
        if taxable > thr:
            tax += (taxable - thr) * D(s["rate"])
    return tax


def state_exit_tax(state: str, gain_cents: int, other_income_cents: int, filing_status: str,
                   replacement_state: str | None = None, states: dict | None = None) -> tuple[Figure, list[dict]]:
    """Marginal state tax on the gain; returns (Figure, findings)."""
    table = states or load_states()
    row = table["states"].get((state or "").upper())
    findings: list[dict] = []
    inputs = [Input.of("state", state), Input.of("gain_cents", gain_cents, src="figure", ref="exit_tax.total_gain"),
              Input.of("other_income_cents", other_income_cents), Input.of("filing_status", filing_status)]
    if row is None:
        findings.append({"kind": "unsupported_structure", "field": "household.state", "severity": "warn",
                         "message": f"state {state!r} is not in the state tax table; state tax shown as 0 (unsupported state)"})
        return Figure("exit_tax.state", 0, "estimated", inputs + [Input.of("state_table", "unsupported", src="default")],
                      "0 (unsupported state)", ["state not in table; verify with the client's CPA"]), findings
    inputs.append(Input.of("state_table_row", {"kind": row["kind"], "source": row.get("source")},
                           src="manual", ref=row.get("source")))
    notes = [f"{row.get('name', state)}: {row.get('note', row['kind'])}", "state standard deduction/exemptions ignored"]
    taxable_gain = Decimal(gain_cents)
    if row.get("ltcg_exclusion"):
        excl = D(row["ltcg_exclusion"])
        taxable_gain = taxable_gain * (Decimal(1) - excl)
        notes.append(f"{excl:.0%} long-term gain exclusion applied")
    other = Decimal(other_income_cents)
    tax = state_tax_on_cents(other + taxable_gain, row, filing_status) - state_tax_on_cents(other, row, filing_status)
    tax = max(Decimal(0), tax)
    if replacement_state and replacement_state.upper() != (state or "").upper() and \
            (state or "").upper() in table.get("clawback_states", []):
        findings.append({"kind": "info", "field": "exchange.replacement_state", "severity": "info",
                         "message": f"{state.upper()} is a clawback state: deferred gain on an out-of-state 1031 replacement "
                                    "remains reportable to the source state when eventually sold (informational)"})
    fig = money("exit_tax.state", tax, inputs, "state_tax(other_income + gain) - state_tax(other_income)", notes)
    return fig, findings


def state_tax_cents(state: str, taxable_cents: int, filing_status: str) -> int:
    row = load_states()["states"].get((state or "").upper())
    if row is None:
        return 0
    return cents(state_tax_on_cents(Decimal(taxable_cents), row, filing_status))
