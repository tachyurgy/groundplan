"""Federal tax tables and the bracket-stacking rule.

Tax year 2025 figures are from the spec (post-OBBBA standard deduction). 2026 figures are from the IRS inflation
adjustments announced October 2025 (Rev. Proc. 2025-32) and are marked verify=True: they are carried for the
demo, not warranted.

Stacking order for a sale (the whole point of exit_tax):
  1. ordinary taxable income (wages + other - standard deduction - released suspended losses) + Sec 1245 recapture
     (bonus / cost-seg) fills the ordinary brackets at full rates;
  2. unrecaptured Sec 1250 gain stacks on top and fills the remaining brackets at min(bracket rate, 25%);
  3. long-term capital gain stacks on top of that and is taxed at 0/15/20% by where it lands against the LTCG
     thresholds measured on total taxable income.
  NIIT 3.8% applies to min(net investment income, MAGI - threshold).
All amounts are integer cents; thresholds below are dollars and converted once.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from groundplan.engine.figure import Decimal as _D  # noqa: F401  (re-export clarity)
from groundplan.engine.figure import Figure, Input, cents, money

FILING_STATUSES = ("single", "mfj", "mfs", "hoh")
ORDINARY_RATES = ("0.10", "0.12", "0.22", "0.24", "0.32", "0.35", "0.37")
SEC1250_CAP = Decimal("0.25")
NIIT_RATE = Decimal("0.038")
LTCG_RATES = ("0", "0.15", "0.20")

# Upper bounds (dollars) of the first six ordinary brackets; the 37% bracket is open-ended.
ORDINARY_BRACKETS: dict[int, dict[str, list[int]]] = {
    2025: {
        "single": [11_925, 48_475, 103_350, 197_300, 250_525, 626_350],
        "mfj": [23_850, 96_950, 206_700, 394_600, 501_050, 751_600],
        "hoh": [17_000, 64_850, 103_350, 197_300, 250_500, 626_350],
        "mfs": [11_925, 48_475, 103_350, 197_300, 250_525, 375_800],
    },
    2026: {
        "single": [12_400, 50_400, 105_700, 201_775, 256_225, 640_600],
        "mfj": [24_800, 100_800, 211_400, 403_550, 512_450, 768_700],
        "hoh": [17_700, 67_450, 105_700, 201_775, 256_200, 640_600],
        "mfs": [12_400, 50_400, 105_700, 201_775, 256_225, 384_350],
    },
}
STANDARD_DEDUCTION: dict[int, dict[str, int]] = {
    2025: {"single": 15_750, "mfj": 31_500, "hoh": 23_625, "mfs": 15_750},
    2026: {"single": 16_100, "mfj": 32_200, "hoh": 24_150, "mfs": 16_100},
}
# LTCG: upper bound of the 0% layer and of the 15% layer (dollars).
LTCG_THRESHOLDS: dict[int, dict[str, tuple[int, int]]] = {
    2025: {"single": (48_350, 533_400), "mfj": (96_700, 600_050), "hoh": (64_750, 566_700), "mfs": (48_350, 300_000)},
    2026: {"single": (49_450, 545_500), "mfj": (98_900, 613_700), "hoh": (66_200, 579_600), "mfs": (49_450, 306_850)},
}
NIIT_THRESHOLD = {"single": 200_000, "hoh": 200_000, "mfj": 250_000, "mfs": 125_000}  # not inflation indexed
SOURCES = {
    2025: "spec (IRS Rev. Proc. 2024-40 brackets; OBBBA 2025 standard deduction)",
    2026: "IRS Rev. Proc. 2025-32 (Oct 2025) -- verify",
}
VERIFY = {2025: False, 2026: True}


def table_year(tax_year: int) -> int:
    """Nearest table year we carry (2025 for anything earlier, 2026 for anything later)."""
    if tax_year <= 2025:
        return 2025
    return 2026


def _bounds_cents(tax_year: int, filing_status: str) -> list[Decimal]:
    yr = table_year(tax_year)
    return [Decimal(b) * 100 for b in ORDINARY_BRACKETS[yr][filing_status]]


def standard_deduction_cents(tax_year: int, filing_status: str) -> int:
    return STANDARD_DEDUCTION[table_year(tax_year)][filing_status] * 100


@dataclass(frozen=True)
class Layer:
    rate: str
    lower_cents: int
    upper_cents: int
    amount_cents: int
    tax_cents: int

    def to_dict(self) -> dict:
        return {"rate": self.rate, "lower_cents": self.lower_cents, "upper_cents": self.upper_cents,
                "amount_cents": self.amount_cents, "tax_cents": self.tax_cents}


def ordinary_layers(from_cents: Decimal, amount_cents: Decimal, tax_year: int, filing_status: str,
                    cap: Decimal | None = None) -> list[Layer]:
    """Tax `amount` stacked on top of `from` through the ordinary brackets, each bracket rate capped at `cap`.

    Returns one Layer per bracket touched; tax per layer is exact Decimal rounded per layer to the cent.
    """
    bounds = _bounds_cents(tax_year, filing_status)
    layers: list[Layer] = []
    pos = max(Decimal(0), from_cents)
    end = pos + max(Decimal(0), amount_cents)
    lower = Decimal(0)
    for i, rate_s in enumerate(ORDINARY_RATES):
        upper = bounds[i] if i < len(bounds) else None
        seg_lo = max(pos, lower)
        seg_hi = end if upper is None else min(end, upper)
        if seg_hi > seg_lo:
            rate = Decimal(rate_s)
            if cap is not None and rate > cap:
                rate = cap
            amt = seg_hi - seg_lo
            layers.append(Layer(str(rate), int(seg_lo), int(seg_hi), int(amt), cents(amt * rate)))
        if upper is None or end <= upper:
            break
        lower = upper
    return layers


def ordinary_tax_cents(taxable_cents: int, tax_year: int, filing_status: str) -> int:
    return sum(layer.tax_cents for layer in ordinary_layers(Decimal(0), Decimal(taxable_cents), tax_year, filing_status))


def ltcg_layers(from_cents: Decimal, amount_cents: Decimal, tax_year: int, filing_status: str) -> list[Layer]:
    zero_top, fifteen_top = (Decimal(x) * 100 for x in LTCG_THRESHOLDS[table_year(tax_year)][filing_status])
    layers: list[Layer] = []
    pos = max(Decimal(0), from_cents)
    end = pos + max(Decimal(0), amount_cents)
    for rate_s, lower, upper in (("0", Decimal(0), zero_top), ("0.15", zero_top, fifteen_top), ("0.20", fifteen_top, None)):
        seg_lo = max(pos, lower)
        seg_hi = end if upper is None else min(end, upper)
        if seg_hi > seg_lo:
            amt = seg_hi - seg_lo
            layers.append(Layer(rate_s, int(seg_lo), int(seg_hi), int(amt), cents(amt * Decimal(rate_s))))
        if upper is None or end <= upper:
            break
    return layers


@dataclass
class StackResult:
    ordinary_taxable_cents: int
    tax_ordinary: Figure
    tax_1245: Figure
    tax_1250: Figure
    tax_ltcg: Figure
    layers_1250: list[Layer]
    layers_ltcg: list[Layer]
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "ordinary_taxable_cents": self.ordinary_taxable_cents,
            "tax_ordinary": self.tax_ordinary.to_dict(), "tax_1245": self.tax_1245.to_dict(),
            "tax_1250": self.tax_1250.to_dict(), "tax_ltcg": self.tax_ltcg.to_dict(),
            "layers_1250": [x.to_dict() for x in self.layers_1250], "layers_ltcg": [x.to_dict() for x in self.layers_ltcg],
            "notes": self.notes,
        }


def stack(ordinary_taxable_cents: int, sec1245_cents: int, sec1250_cents: int, ltcg_cents: int, tax_year: int,
          filing_status: str, extra_inputs: list[Input] | None = None) -> StackResult:
    """Apply the stacking order and return every federal component as its own Figure."""
    if filing_status not in FILING_STATUSES:
        raise ValueError(f"unknown filing status {filing_status!r}")
    yr = table_year(tax_year)
    base_inputs = [Input.of("tax_year", tax_year), Input.of("table_year", yr, src="public_data" if VERIFY[yr] else "manual",
                                                            ref=SOURCES[yr]), Input.of("filing_status", filing_status)]
    base_inputs += extra_inputs or []
    ord_base = max(0, ordinary_taxable_cents)
    base_tax = ordinary_tax_cents(ord_base, tax_year, filing_status)
    tax_ordinary = money("tax.federal.ordinary_on_other_income", Decimal(base_tax),
                         base_inputs + [Input.of("ordinary_taxable_cents", ordinary_taxable_cents)],
                         "bracket tax on (wages + other income - standard deduction - released suspended losses)")
    # layer 1b: Sec 1245 ordinary recapture on top of other ordinary income (no cap)
    l1245 = ordinary_layers(Decimal(ord_base), Decimal(sec1245_cents), tax_year, filing_status)
    tax_1245 = money("exit_tax.fed_1245", Decimal(sum(x.tax_cents for x in l1245)),
                     base_inputs + [Input.of("sec1245_cents", sec1245_cents, src="figure", ref="exit_tax.sec1245"),
                                    Input.of("stack_from_cents", ord_base)],
                     "ordinary brackets on sec1245 stacked above other ordinary income (no 25% cap)")
    pos = Decimal(ord_base + sec1245_cents)
    # layer 2: unrecaptured 1250 at min(bracket, 25%)
    l1250 = ordinary_layers(pos, Decimal(sec1250_cents), tax_year, filing_status, cap=SEC1250_CAP)
    notes = [f"stack: ordinary {ord_base} (+1245 {sec1245_cents}) -> 1250 {sec1250_cents} at min(bracket,25%) -> LTCG {ltcg_cents} at 0/15/20"]
    under_cap = [x for x in l1250 if Decimal(x.rate) < SEC1250_CAP]
    if under_cap:
        notes.append(f"{sum(x.amount_cents for x in under_cap)} cents of the 1250 gain landed in brackets below 25% "
                     "and is taxed at the lower ordinary rate")
    tax_1250 = money("exit_tax.fed_1250", Decimal(sum(x.tax_cents for x in l1250)),
                     base_inputs + [Input.of("unrecaptured_1250_cents", sec1250_cents, src="figure", ref="exit_tax.unrecaptured_1250"),
                                    Input.of("stack_from_cents", int(pos))],
                     "ordinary brackets capped at 25% on the 1250 gain stacked above ordinary income", notes[1:])
    pos += Decimal(sec1250_cents)
    lltcg = ltcg_layers(pos, Decimal(ltcg_cents), tax_year, filing_status)
    tax_ltcg = money("exit_tax.fed_ltcg", Decimal(sum(x.tax_cents for x in lltcg)),
                     base_inputs + [Input.of("ltcg_cents", ltcg_cents, src="figure", ref="exit_tax.ltcg"),
                                    Input.of("stack_from_cents", int(pos))],
                     "0/15/20% by where the LTCG lands on top of ordinary + 1250 income")
    return StackResult(ordinary_taxable_cents, tax_ordinary, tax_1245, tax_1250, tax_ltcg, l1250, lltcg, notes)


def niit(net_investment_income_cents: int, magi_cents: int, filing_status: str, inputs: list[Input] | None = None) -> Figure:
    threshold = Decimal(NIIT_THRESHOLD[filing_status]) * 100
    base = max(Decimal(0), min(Decimal(net_investment_income_cents), Decimal(magi_cents) - threshold))
    notes = [] if base > 0 else ["MAGI below the NIIT threshold or no net investment income: NIIT is 0"]
    return money("exit_tax.niit", base * NIIT_RATE, inputs or [
        Input.of("net_investment_income_cents", net_investment_income_cents),
        Input.of("magi_cents", magi_cents), Input.of("filing_status", filing_status),
        Input.of("niit_threshold_cents", int(threshold), src="manual", ref="IRC 1411 (not indexed)")],
        "3.8% x max(0, min(NII, MAGI - threshold))", notes)
