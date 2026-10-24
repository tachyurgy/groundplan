"""Passive activity loss rules for rental real estate (IRC 469(i)).

allowance = 25,000 - 0.5 x max(0, MAGI - 100,000), floored at 0, only with active participation; MFS = 0 (the
spec treats MFS as "living together" = no allowance). Real-estate professionals are not subject to the limit.
Deductible this year = min(net loss, allowance); the remainder is suspended (Form 8582) and carried forward.
Suspended losses release in full on a fully taxable disposition of the entire interest; a 1031 exchange does NOT
release them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from groundplan.engine.figure import Figure, Input, money

ALLOWANCE_MAX = Decimal(2_500_000)  # $25,000 in cents
PHASEOUT_START = Decimal(10_000_000)  # $100,000
PHASEOUT_RATE = Decimal("0.5")


@dataclass
class PassiveResult:
    net_rental_cents: int
    allowance: Figure
    deductible: Figure
    suspended_new: Figure
    carryforward_end: Figure
    findings: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "net_rental_cents": self.net_rental_cents,
            "allowance": self.allowance.to_dict(),
            "deductible": self.deductible.to_dict(),
            "suspended_new": self.suspended_new.to_dict(),
            "carryforward_end": self.carryforward_end.to_dict(),
            "findings": self.findings,
        }


def special_allowance(magi_cents: int, filing_status: str, active_participation: bool, re_professional: bool,
                      magi_input: Input | None = None) -> Figure:
    inputs = [magi_input or Input.of("magi_cents", magi_cents), Input.of("filing_status", filing_status),
              Input.of("active_participation", active_participation), Input.of("re_professional", re_professional)]
    notes: list[str] = []
    if re_professional:
        return money("passive.allowance", Decimal(0), inputs, "n/a: real estate professional, losses not passive",
                     ["real estate professional: losses are nonpassive, no 25k cap applies"])
    if not active_participation:
        return money("passive.allowance", Decimal(0), inputs, "0 (no active participation)",
                     ["no active participation: the 25,000 special allowance does not apply"])
    if filing_status == "mfs":
        return money("passive.allowance", Decimal(0), inputs, "0 (MFS)",
                     ["married filing separately (living together): special allowance is 0"])
    reduction = PHASEOUT_RATE * max(Decimal(0), Decimal(magi_cents) - PHASEOUT_START)
    allowance = max(Decimal(0), ALLOWANCE_MAX - reduction)
    if reduction > 0:
        notes.append(f"MAGI above 100,000: allowance reduced by 50% of the excess ({int(reduction)} cents)")
    return money("passive.allowance", allowance, inputs, "max(0, 25000 - 0.5*max(0, MAGI - 100000))", notes)


def apply_passive_rules(net_rental_cents: int, prior_carryforward_cents: int, magi_cents: int, filing_status: str,
                        active_participation: bool, re_professional: bool, str_avg_stay_days: dict[str, float] | None = None,
                        magi_input: Input | None = None) -> PassiveResult:
    allowance = special_allowance(magi_cents, filing_status, active_participation, re_professional, magi_input)
    loss = max(0, -net_rental_cents)
    net_input = Input.of("net_rental_cents", net_rental_cents, src="figure", ref="cash_flow.schedule_e.line21")
    prior_input = Input.of("prior_carryforward_cents", prior_carryforward_cents, src="document", ref="Form 8582")
    findings: list[dict] = []
    if re_professional:
        deductible_amt = Decimal(loss)
        formula = "loss (RE professional: fully deductible against nonpassive income)"
    else:
        deductible_amt = min(Decimal(loss), allowance.dec)
        formula = "min(net rental loss, allowance)"
    if net_rental_cents > 0 and prior_carryforward_cents > 0:
        # passive income absorbs prior suspended losses
        used = min(prior_carryforward_cents, net_rental_cents)
        deductible = money("passive.deductible_this_year", Decimal(used), [net_input, prior_input, Input.figure(allowance)],
                           "min(prior carryforward, net passive income)",
                           ["net rental income absorbs suspended losses first"])
        suspended_new = money("passive.suspended_this_year", Decimal(0), [net_input], "0 (no loss this year)")
        carry = money("passive.carryforward_end", Decimal(prior_carryforward_cents - used), [prior_input, Input.figure(deductible)],
                      "prior carryforward - losses used against passive income")
    else:
        deductible = money("passive.deductible_this_year", deductible_amt, [net_input, Input.figure(allowance)], formula)
        suspended_new = money("passive.suspended_this_year", Decimal(loss) - deductible_amt, [net_input, Input.figure(deductible)],
                              "net rental loss - deductible this year")
        carry = money("passive.carryforward_end", Decimal(prior_carryforward_cents) + suspended_new.dec,
                      [prior_input, Input.figure(suspended_new)], "prior carryforward + suspended this year")
    if loss and allowance.value_cents == 0 and active_participation and not re_professional and filing_status != "mfs":
        findings.append({"kind": "info", "field": "household.magi_cents", "severity": "info",
                         "message": "MAGI at or above 150,000: the 25,000 special allowance is fully phased out"})
    for key, days in (str_avg_stay_days or {}).items():
        if days is not None and days <= 7:
            findings.append({"kind": "unsupported_structure", "property_key": key, "field": "property.property_type",
                             "severity": "warn",
                             "message": f"short-term rental (average stay {days:g} days <= 7): short-term rental rules apply; not modeled"})
    return PassiveResult(net_rental_cents, allowance, deductible, suspended_new, carry, findings)


def released_on_sale(carryforward_cents: int, disposition: str) -> Figure:
    """Fully taxable sale releases suspended losses in full; a 1031 exchange carries them forward."""
    inputs = [Input.of("carryforward_cents", carryforward_cents, src="document", ref="Form 8582"),
              Input.of("disposition", disposition)]
    if disposition == "taxable_sale":
        return money("passive.released_on_sale", Decimal(carryforward_cents), inputs,
                     "carryforward (fully taxable disposition of entire interest releases all suspended losses)")
    return money("passive.released_on_sale", Decimal(0), inputs, "0 (1031 exchange does not release suspended losses)",
                 ["suspended losses carry forward into the replacement property"])
