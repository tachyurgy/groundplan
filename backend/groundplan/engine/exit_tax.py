"""Exit tax on a fully taxable sale (and on recognized boot in a 1031).

amount_realized = sale_price - selling_costs;      net_before_tax = amount_realized - loan payoffs
adjusted_basis  = purchase + improvements - accumulated depreciation (allowed or allowable)
total_gain      = amount_realized - adjusted_basis
unrecaptured_1250 = min(total_gain, accumulated straight-line depreciation);  sec1245 = bonus/cost-seg portion
ltcg            = total_gain - 1250 - 1245
federal         = stacking (tax_tables.stack) on the household's other taxable income
                  (wages + other - standard deduction - released suspended losses)
NIIT            = 3.8% on min(gain + rental NII, MAGI incl. gain - threshold)
state           = table-driven marginal tax on the gain
released_loss_benefit = ordinary fed + state tax saved by released suspended losses (IRC 469(g))
exit_tax_total  = fed_1250 + fed_1245 + fed_ltcg + niit + state - released_loss_benefit;   net_proceeds = net_before_tax - exit_tax_total
Section 121: a converted former residence sold within 3 years of move-out (2-of-5 window) excludes up to
250k/500k of the NON-depreciation gain, with a Finding warn to verify nonqualified use with a CPA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from groundplan.engine import tax_tables
from groundplan.engine.figure import D, Figure, Input, derive_status, money, ratio
from groundplan.engine.state_tax import load_states, state_exit_tax, state_tax_on_cents

SEC121_EXCLUSION = {"single": 25_000_000, "mfs": 25_000_000, "hoh": 25_000_000, "mfj": 50_000_000}


@dataclass
class HouseholdTax:
    filing_status: str = "mfj"
    state: str = "CA"
    tax_year: int = 2025
    wages_cents: int = 0
    other_income_cents: int = 0
    magi_cents: int = 0
    released_suspended_losses_cents: int = 0
    rental_nii_cents: int = 0  # other net rental income counted toward NIIT
    sources: dict[str, Input] = field(default_factory=dict)

    def inp(self, key: str) -> Input:
        return self.sources.get(key) or Input.of(key, getattr(self, key))


@dataclass
class SaleInput:
    sale_price_cents: int
    selling_cost_rate: Decimal | float | str = "0.06"
    loan_payoff_cents: int = 0
    purchase_price_cents: int = 0
    improvements_cents: int = 0
    accumulated_depreciation_cents: int = 0  # allowed-or-allowable straight-line portion
    sec1245_cents: int = 0
    sale_date: date | None = None
    former_residence_until: date | None = None
    replacement_state: str | None = None
    disposition: str = "taxable_sale"  # taxable_sale | exchange_boot
    recognized_gain_cap_cents: int | None = None  # for 1031 boot: gain recognized = min(boot, total_gain)
    sources: dict[str, Input] = field(default_factory=dict)

    def inp(self, key: str, src: str = "manual") -> Input:
        return self.sources.get(key) or Input.of(key, getattr(self, key), src=src)


@dataclass
class ExitTaxResult:
    figures: dict[str, Figure]
    findings: list[dict]
    stack: tax_tables.StackResult

    @property
    def total_cents(self) -> int:
        return self.figures["exit_tax.total"].value_cents or 0

    @property
    def net_proceeds_cents(self) -> int:
        return self.figures["exit_tax.net_proceeds"].value_cents or 0

    def to_dict(self) -> dict:
        out = {k.split(".", 1)[1]: v.to_dict() for k, v in self.figures.items()}
        out["stack"] = self.stack.to_dict()
        out["findings"] = self.findings
        out["exit_tax_total_cents"] = self.total_cents
        out["net_proceeds_cents"] = self.net_proceeds_cents
        return out


def compute_exit_tax(sale: SaleInput, hh: HouseholdTax, blocked: set[str] | None = None) -> ExitTaxResult:
    f: dict[str, Figure] = {}
    findings: list[dict] = []
    rate = D(sale.selling_cost_rate)
    price = Decimal(sale.sale_price_cents)
    f["exit_tax.selling_costs"] = money("exit_tax.selling_costs", price * rate,
                                        [sale.inp("sale_price_cents"), Input.of("selling_cost_rate", rate, src="default")],
                                        "sale_price * selling_cost_rate")
    amount_realized = price - f["exit_tax.selling_costs"].dec
    f["exit_tax.amount_realized"] = money("exit_tax.amount_realized", amount_realized,
                                          [sale.inp("sale_price_cents"), Input.figure(f["exit_tax.selling_costs"])],
                                          "sale_price - selling_costs", blocked_keys=blocked)
    f["exit_tax.net_before_tax"] = money("exit_tax.net_before_tax", amount_realized - Decimal(sale.loan_payoff_cents),
                                         [Input.figure(f["exit_tax.amount_realized"]),
                                          Input.of("loan_payoff_cents", sale.loan_payoff_cents, src="figure", ref="loans.schedule")],
                                         "amount_realized - loan payoffs")
    acc = Decimal(sale.accumulated_depreciation_cents)
    adjusted_basis = Decimal(sale.purchase_price_cents) + Decimal(sale.improvements_cents) - acc - Decimal(sale.sec1245_cents)
    f["exit_tax.adjusted_basis"] = money("exit_tax.adjusted_basis", adjusted_basis,
                                         [sale.inp("purchase_price_cents"), sale.inp("improvements_cents"),
                                          Input.of("accumulated_depreciation_cents", sale.accumulated_depreciation_cents,
                                                   src="figure", ref="depreciation.accumulated"),
                                          Input.of("sec1245_cents", sale.sec1245_cents, src="figure", ref="depreciation.sec1245")],
                                         "purchase + improvements - accumulated depreciation (allowed or allowable, incl. bonus)")
    total_gain = max(Decimal(0), amount_realized - adjusted_basis)
    gain_notes: list[str] = []
    if amount_realized - adjusted_basis < 0:
        gain_notes.append("sale below adjusted basis: loss (Sec 1231), no exit tax; loss treatment not modeled")
    f["exit_tax.total_gain"] = money("exit_tax.total_gain", total_gain,
                                     [Input.figure(f["exit_tax.amount_realized"]), Input.figure(f["exit_tax.adjusted_basis"])],
                                     "amount_realized - adjusted_basis", gain_notes)
    recognized = total_gain
    if sale.recognized_gain_cap_cents is not None:
        recognized = min(total_gain, Decimal(max(0, sale.recognized_gain_cap_cents)))
        f["exit_tax.recognized_gain"] = money("exit_tax.recognized_gain", recognized,
                                              [Input.figure(f["exit_tax.total_gain"]),
                                               Input.of("boot_cents", sale.recognized_gain_cap_cents, src="figure", ref="exchange.boot")],
                                              "min(total_gain, boot)", ["1031: gain recognized only to the extent of boot"])
    # recapture is recognized first (Reg. 1.1250-1 ordering for boot): 1245, then 1250, then LTCG
    sec1245 = min(recognized, Decimal(sale.sec1245_cents))
    unrec_1250 = min(recognized - sec1245, acc)
    f["exit_tax.sec1245"] = money("exit_tax.sec1245", sec1245,
                                  [Input.of("sec1245_cents", sale.sec1245_cents, src="figure", ref="depreciation.sec1245"),
                                   Input.figure(f["exit_tax.total_gain"])],
                                  "min(recognized gain, bonus/cost-seg depreciation) -> ordinary income, no 25% cap")
    f["exit_tax.unrecaptured_1250"] = money("exit_tax.unrecaptured_1250", unrec_1250,
                                            [Input.figure(f["exit_tax.total_gain"]),
                                             Input.of("accumulated_depreciation_cents", sale.accumulated_depreciation_cents,
                                                      src="figure", ref="depreciation.accumulated")],
                                            "min(recognized gain - 1245, accumulated straight-line depreciation)")
    ltcg = recognized - sec1245 - unrec_1250
    ltcg_notes: list[str] = []
    excluded = Decimal(0)
    if sale.former_residence_until and sale.sale_date:
        gap_days = (sale.sale_date - sale.former_residence_until).days
        if 0 <= gap_days <= 3 * 365:
            cap = Decimal(SEC121_EXCLUSION[hh.filing_status])
            excluded = min(ltcg, cap)
            ltcg -= excluded
            ltcg_notes.append(f"Section 121: {int(excluded)} cents of non-depreciation gain excluded "
                              f"(former residence until {sale.former_residence_until.isoformat()}, within 2-of-5 window)")
            findings.append({"kind": "info", "field": "sale.former_residence_until", "severity": "warn",
                             "message": "Section 121 exclusion applied to a converted residence: verify with CPA "
                                        "(nonqualified use after 2008 reduces the exclusion; depreciation gain is never excluded)"})
        else:
            ltcg_notes.append("former residence outside the 2-of-5 window: no Section 121 exclusion")
    f["exit_tax.sec121_excluded"] = money("exit_tax.sec121_excluded", excluded,
                                          [Input.of("former_residence_until", sale.former_residence_until),
                                           Input.of("sale_date", sale.sale_date), Input.of("filing_status", hh.filing_status)],
                                          "min(non-depreciation gain, 250k/500k) if within 2-of-5 window else 0")
    f["exit_tax.ltcg"] = money("exit_tax.ltcg", ltcg, [Input.figure(f["exit_tax.total_gain"]), Input.figure(f["exit_tax.sec1245"]),
                                                       Input.figure(f["exit_tax.unrecaptured_1250"]),
                                                       Input.figure(f["exit_tax.sec121_excluded"])],
                               "recognized gain - 1245 - 1250 - sec121 exclusion", ltcg_notes)
    std = tax_tables.standard_deduction_cents(hh.tax_year, hh.filing_status)
    ordinary_taxable = (Decimal(hh.wages_cents) + Decimal(hh.other_income_cents) - Decimal(std)
                        - Decimal(hh.released_suspended_losses_cents))
    f["exit_tax.ordinary_taxable_other"] = money(
        "exit_tax.ordinary_taxable_other", ordinary_taxable,
        [hh.inp("wages_cents"), hh.inp("other_income_cents"), Input.of("standard_deduction_cents", std, src="manual",
                                                                     ref=tax_tables.SOURCES[tax_tables.table_year(hh.tax_year)]),
         Input.of("released_suspended_losses_cents", hh.released_suspended_losses_cents, src="figure", ref="passive.released_on_sale")],
        "wages + other income - standard deduction - released suspended losses",
        ["released suspended losses are an ordinary deduction in the year of a fully taxable sale"] if hh.released_suspended_losses_cents else [])
    st = tax_tables.stack(int(ordinary_taxable), int(sec1245), int(unrec_1250), int(ltcg), hh.tax_year, hh.filing_status,
                          [Input.figure(f["exit_tax.ordinary_taxable_other"])])
    f["exit_tax.fed_1245"] = st.tax_1245
    f["exit_tax.fed_1250"] = st.tax_1250
    f["exit_tax.fed_ltcg"] = st.tax_ltcg
    for key, comp in (("exit_tax.fed_1245", "exit_tax.sec1245"), ("exit_tax.fed_1250", "exit_tax.unrecaptured_1250"),
                      ("exit_tax.fed_ltcg", "exit_tax.ltcg")):
        f[key].notes = st.notes[:1] + f[key].notes
        f[key].inputs.append(Input.figure(f[comp]))
        f[key].status = derive_status(f[key].inputs, blocked)
    nii = int(recognized - excluded) + hh.rental_nii_cents
    magi_with_gain = hh.magi_cents + int(recognized - excluded) - hh.released_suspended_losses_cents
    f["exit_tax.niit"] = tax_tables.niit(nii, magi_with_gain, hh.filing_status, [
        Input.of("net_investment_income_cents", nii, src="figure", ref="exit_tax.total_gain + rental NII"),
        hh.inp("magi_cents"), Input.of("magi_with_gain_cents", magi_with_gain, src="figure", ref="household.magi + recognized gain"),
        Input.of("filing_status", hh.filing_status), Input.figure(f["exit_tax.total_gain"])])
    other_income_for_state = hh.wages_cents + hh.other_income_cents - hh.released_suspended_losses_cents
    state_fig, state_findings = state_exit_tax(hh.state, int(recognized - excluded), other_income_for_state, hh.filing_status,
                                               sale.replacement_state)
    state_fig.inputs.append(Input.figure(f["exit_tax.total_gain"]))
    state_fig.status = derive_status(state_fig.inputs, blocked)
    f["exit_tax.state"] = state_fig
    findings += state_findings
    f["exit_tax.released_loss_benefit"] = released_loss_benefit(hh, std)
    total = (f["exit_tax.fed_1250"].dec + f["exit_tax.fed_1245"].dec + f["exit_tax.fed_ltcg"].dec + f["exit_tax.niit"].dec
             + f["exit_tax.state"].dec - f["exit_tax.released_loss_benefit"].dec)
    f["exit_tax.total"] = money("exit_tax.total", total, [Input.figure(f[k]) for k in
                                                          ("exit_tax.fed_1250", "exit_tax.fed_1245", "exit_tax.fed_ltcg",
                                                           "exit_tax.niit", "exit_tax.state", "exit_tax.released_loss_benefit")],
                                "fed_1250 + fed_1245 + fed_ltcg + niit + state - released_loss_benefit", st.notes)
    f["exit_tax.net_proceeds"] = money("exit_tax.net_proceeds", f["exit_tax.net_before_tax"].dec - total,
                                       [Input.figure(f["exit_tax.net_before_tax"]), Input.figure(f["exit_tax.total"])],
                                       "net_before_tax - exit_tax_total")
    eff = None if recognized <= 0 else total / recognized
    f["exit_tax.effective_rate_on_gain"] = ratio("exit_tax.effective_rate_on_gain", eff,
                                                 [Input.figure(f["exit_tax.total"]), Input.figure(f["exit_tax.total_gain"])],
                                                 "exit_tax_total / recognized gain", places=4)
    return ExitTaxResult(f, findings, st)


def released_loss_benefit(hh: HouseholdTax, std_cents: int) -> Figure:
    """Ordinary-income tax saved by suspended passive losses released on a fully taxable sale (IRC 469(g)).

    benefit = [fed ordinary tax(W + O - std) + state tax(W + O)] - [same with the released loss deducted]
    i.e. household tax without the release minus household tax with it, on the non-sale income only. The gain itself
    is stacked from the lowered base elsewhere, so total exit tax = tax(with sale) - tax(without sale).
    """
    rel = max(0, hh.released_suspended_losses_cents)
    base_fed = hh.wages_cents + hh.other_income_cents - std_cents
    base_state = hh.wages_cents + hh.other_income_cents
    fed_without = tax_tables.ordinary_tax_cents(max(0, base_fed), hh.tax_year, hh.filing_status)
    fed_with = tax_tables.ordinary_tax_cents(max(0, base_fed - rel), hh.tax_year, hh.filing_status)
    row = load_states()["states"].get((hh.state or "").upper())
    st_saving = Decimal(0)
    if row is not None:
        st_saving = (state_tax_on_cents(Decimal(base_state), row, hh.filing_status)
                     - state_tax_on_cents(Decimal(base_state - rel), row, hh.filing_status))
    notes: list[str] = []
    if rel:
        notes.append("IRC 469(g): suspended losses released by a fully taxable disposition are deductible against wages and "
                     "other nonpassive income; this is the federal + state ordinary tax they save")
        if rel > max(0, base_fed):
            notes.append("released losses exceed other ordinary taxable income; the excess offsetting the gain itself is not modeled")
        if row is None:
            notes.append("state not in the table: state saving shown as 0")
    return money("exit_tax.released_loss_benefit", Decimal(fed_without - fed_with) + st_saving,
                 [hh.inp("wages_cents"), hh.inp("other_income_cents"),
                  Input.of("standard_deduction_cents", std_cents, src="manual",
                           ref=tax_tables.SOURCES[tax_tables.table_year(hh.tax_year)]),
                  Input.of("released_suspended_losses_cents", rel, src="figure", ref="passive.released_on_sale"),
                  Input.of("state", hh.state), Input.of("filing_status", hh.filing_status)],
                 "[fed_tax(W + O - std) + state_tax(W + O)] - [fed_tax(W + O - std - released) + state_tax(W + O - released)]",
                 notes)
