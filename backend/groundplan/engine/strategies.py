"""Hold vs Sell-now vs 1031 (incl. DST) over the same horizon on IDENTICAL assumptions.

Conventions (stated in the API output as `conventions`):
- t = 0 is "today" (start of `start_year`); year t ends Dec 31 of start_year + t - 1.
- Cash flows are pre-income-tax; only disposition taxes are modeled. Every cash flow is reinvested at
  reinvest_rate (end-of-year contributions).
- Terminal wealth = what the household would hold if everything were liquidated at the horizon, net of selling
  costs, loan payoffs and the exit tax due then. For the 1031 path the deferred liability is shown as its own
  line, never netted silently.
- No path is ever labelled as the advised choice, and there is no such field: the comparison is a leads/trails/neutral matrix per measure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from groundplan.engine import cashflow, depreciation, loans
from groundplan.engine.analysis import depreciation_for, household_tax, loan_schedules, ops_for_year
from groundplan.engine.exit_tax import SaleInput, compute_exit_tax
from groundplan.engine.figure import D, Input, cents, money
from groundplan.engine.models import DEFAULTS, HouseholdModel, PropertyModel, rate_or_default

MEASURES = ("terminal_wealth", "cumulative_cash_flow", "tax_paid_now", "liquidity", "management_burden", "concentration")
NEUTRAL_BAND = Decimal("0.01")  # values within 1% of each other are neutral


@dataclass
class ExchangeAssumptions:
    replacement_value_cents: int | None = None  # default: amount realized on the relinquished property
    replacement_debt_cents: int | None = None  # default: equal to the debt paid off (no mortgage boot)
    dst: bool = False
    load_rate: Decimal | str = DEFAULTS["dst_load_rate"]
    dst_yield: Decimal | str = DEFAULTS["dst_yield"]
    cash_taken_cents: int = 0
    replacement_state: str | None = None


@dataclass
class StrategyAssumptions:
    horizon_years: int = 10
    appreciation_rate: Decimal | str | None = None
    rent_growth: Decimal | str | None = None
    expense_growth: Decimal | str | None = None
    reinvest_rate: Decimal | str = DEFAULTS["reinvest_rate"]
    start_year: int | None = None
    exchange: ExchangeAssumptions = field(default_factory=ExchangeAssumptions)


def _row(year: int, cf: int, equity: int, value: int, debt: int, deferred: int, wealth: int) -> dict:
    return {"year": year, "cash_flow_cents": cf, "equity_cents": equity, "value_cents": value, "debt_cents": debt,
            "cumulative_tax_deferred_cents": deferred, "wealth_cents": wealth}


def _grow(amount: Decimal, rate: Decimal, n: int) -> Decimal:
    return amount * (Decimal(1) + rate) ** n


def compare_strategies(p: PropertyModel, h: HouseholdModel, a: StrategyAssumptions) -> dict:
    start = a.start_year or (h.tax_year + 1)
    n = max(1, int(a.horizon_years))
    appr, appr_src = rate_or_default(a.appreciation_rate if a.appreciation_rate is not None else p.appreciation_rate,
                                     "appreciation_rate")
    rg, _ = rate_or_default(a.rent_growth if a.rent_growth is not None else p.rent_growth_rate, "rent_growth_rate")
    eg, _ = rate_or_default(a.expense_growth if a.expense_growth is not None else p.expense_growth_rate, "expense_growth_rate")
    vac, _ = rate_or_default(p.vacancy_rate, "vacancy_rate")
    capex, _ = rate_or_default(p.capex_reserve_rate, "capex_reserve_rate")
    sc, _ = rate_or_default(p.selling_cost_rate, "selling_cost_rate")
    rr = D(a.reinvest_rate)
    shared = {"horizon_years": n, "start_year": start, "appreciation_rate": str(appr), "appreciation_source": appr_src,
              "rent_growth": str(rg), "expense_growth": str(eg), "reinvest_rate": str(rr), "selling_cost_rate": str(sc),
              "vacancy_rate": str(vac), "capex_reserve_rate": str(capex)}
    scheds = loan_schedules(p)
    today = date(start - 1, 12, 31)
    debt_now = loans.total_balance_at(scheds, today)
    value_now = Decimal(p.current_value_cents)
    base_ops, _ = ops_for_year(p, start - 1)
    carry = h.carryforward_cents
    value_in = Input.of("current_value_cents", p.current_value_cents,
                        src="manual" if p.value_source == "confirmed" else "public_data")
    assumption_inputs = [value_in, Input.of("appreciation_rate", appr, src=appr_src), Input.of("reinvest_rate", rr),
                         Input.of("horizon_years", n)]

    def sale_at(value_cents: int, debt_cents: int, through_year: int, released: int, tax_year: int,
                cap: int | None = None, basis_override: dict | None = None):
        dep = depreciation_for(p, through_year + 1)
        acc = (dep.accumulated.value_cents or 0) - dep.sec1245_cents
        s = SaleInput(sale_price_cents=value_cents, selling_cost_rate=sc, loan_payoff_cents=debt_cents,
                      purchase_price_cents=p.purchase_price_cents, improvements_cents=p.improvements_cents,
                      accumulated_depreciation_cents=acc, sec1245_cents=dep.sec1245_cents,
                      sale_date=date(through_year + 1, 1, 15), former_residence_until=p.former_residence_until,
                      recognized_gain_cap_cents=cap, replacement_state=a.exchange.replacement_state)
        if basis_override:
            for k, v in basis_override.items():
                setattr(s, k, v)
        return compute_exit_tax(s, household_tax(h, released=released, tax_year=tax_year), p.blocked_keys)

    # ---------------- HOLD ----------------
    hold_series = []
    reinvested = Decimal(0)
    cum_cf = 0
    hold_exit = None
    for t in range(1, n + 1):
        yr = start + t - 1
        if base_ops is not None:
            o = cashflow.project_operations(base_ops, t, rg, eg)
            noi_c = cashflow.noi(o, vac, capex).value_cents or 0
        else:
            noi_c = 0
        ann = loans.combined_annual(scheds, yr)
        cf = noi_c - ann["debt_service_cents"] - ann["balloon_cents"]
        cum_cf += cf
        reinvested = reinvested * (Decimal(1) + rr) + Decimal(cf)
        value_t = cents(_grow(value_now, appr, t))
        debt_t = loans.total_balance_at(scheds, date(yr, 12, 31))
        ex = sale_at(value_t, debt_t, yr, carry, yr + 1)
        hold_exit = ex
        wealth = ex.net_proceeds_cents + cents(reinvested)
        hold_series.append(_row(yr, cf, value_t - debt_t, value_t, debt_t, ex.total_cents, wealth))
    assert hold_exit is not None
    hold_terminal = hold_series[-1]["wealth_cents"]
    hold = {
        "path": "hold", "label": "Hold", "series": hold_series,
        "terminal": {
            "terminal_wealth": money("strategy.hold.terminal_wealth", Decimal(hold_terminal),
                                     assumption_inputs + [Input.figure(hold_exit.figures["exit_tax.net_proceeds"])],
                                     "net proceeds if sold at horizon (equity - selling costs - exit tax) + cash flows reinvested").to_dict(),
            "ending_equity_cents": hold_series[-1]["equity_cents"],
            "exit_tax_at_horizon_cents": hold_exit.total_cents,
            "cumulative_cash_flow_cents": cum_cf,
            "reinvested_cash_flow_cents": cents(reinvested),
            "tax_paid_now_cents": 0,
            "suspended_losses_released_cents": 0,
        },
        "caveats": ["Concentration: the household stays exposed to this one property and market.",
                    "The deferred exit tax grows every year as depreciation accumulates and the property appreciates.",
                    "Assumes the property keeps being managed (tenants, repairs, capital reserves).",
                    "Cash flows are pre-income-tax and assumed reinvested at the reinvest rate."],
    }

    # ---------------- SELL NOW ----------------
    sell_ex = sale_at(int(value_now), debt_now, start - 1, carry, start)
    proceeds = Decimal(sell_ex.net_proceeds_cents)
    sell_series = []
    for t in range(1, n + 1):
        w = cents(_grow(proceeds, rr, t))
        sell_series.append(_row(start + t - 1, 0, 0, 0, 0, 0, w))
    sell = {
        "path": "sell", "label": "Sell now (taxable)", "series": sell_series,
        "terminal": {
            "terminal_wealth": money("strategy.sell.terminal_wealth", Decimal(sell_series[-1]["wealth_cents"]),
                                     assumption_inputs + [Input.figure(sell_ex.figures["exit_tax.net_proceeds"])],
                                     "net proceeds today x (1 + reinvest_rate)^horizon").to_dict(),
            "net_proceeds_today_cents": sell_ex.net_proceeds_cents,
            "exit_tax_today_cents": sell_ex.total_cents,
            "cumulative_cash_flow_cents": 0,
            "tax_paid_now_cents": sell_ex.total_cents,
            "suspended_losses_released_cents": carry,
            "exit_tax": sell_ex.to_dict(),
        },
        "caveats": ["The full exit tax is paid now.",
                    "Terminal wealth depends on actually earning the reinvest rate on the proceeds.",
                    f"Suspended passive losses ({carry} cents) are released and reduce the tax." if carry else
                    "No suspended passive losses to release."],
    }

    # ---------------- 1031 / DST ----------------
    x = a.exchange
    net_before = sell_ex.figures["exit_tax.net_before_tax"].value_cents or 0
    total_gain = sell_ex.figures["exit_tax.total_gain"].value_cents or 0
    old_adj_basis = sell_ex.figures["exit_tax.adjusted_basis"].value_cents or 0
    repl_debt = x.replacement_debt_cents if x.replacement_debt_cents is not None else debt_now
    mortgage_boot = max(0, debt_now - repl_debt)
    boot = x.cash_taken_cents + mortgage_boot
    boot_fig = money("exchange.boot", Decimal(boot),
                     [Input.of("cash_taken_cents", x.cash_taken_cents), Input.of("old_debt_paid_off_cents", debt_now, src="figure",
                                                                                 ref="loans.schedule"),
                      Input.of("replacement_debt_cents", repl_debt, src="manual" if x.replacement_debt_cents is not None else "default")],
                     "cash_taken + max(0, old_debt_paid_off - replacement_debt)",
                     [f"mortgage boot {mortgage_boot} cents"] if mortgage_boot else [])
    boot_ex = sale_at(int(value_now), debt_now, start - 1, 0, start, cap=boot) if boot > 0 else None
    boot_tax = boot_ex.total_cents if boot_ex else 0
    recognized = min(boot, total_gain)
    deferred_gain = total_gain - recognized
    # equity that goes into the replacement: net proceeds minus cash taken minus tax on boot (paid from cash taken)
    exchange_equity = net_before - x.cash_taken_cents
    # default replacement = what the rolled equity plus the new debt can buy (sources = uses); cash taken out of the
    # exchange shrinks it, so the same dollars are never both kept and reinvested in the replacement
    repl_value = x.replacement_value_cents if x.replacement_value_cents is not None else exchange_equity + repl_debt
    # cash taken out, after paying the tax on all boot (negative = the tax on boot comes from other funds), is invested at
    # the reinvest rate exactly like sell-now proceeds and counted in terminal wealth
    cash_after_tax = x.cash_taken_cents - boot_tax
    findings = list(sell_ex.findings)
    if boot_ex:
        findings += [f for f in boot_ex.findings if f not in findings]
    # replacement basis = replacement cost - deferred gain (carryover basis + new basis)
    repl_basis = repl_value - deferred_gain
    carryover_part = old_adj_basis
    new_basis_part = max(0, repl_basis - carryover_part)
    lp, _, _ = depreciation.bounded_land_pct(p.land_pct)
    new_dep_basis = cents(Decimal(new_basis_part) * (Decimal(1) - lp))
    old_sched = depreciation.annual_schedule(
        depreciation.depreciable_basis(p.purchase_price_cents, p.improvements_cents, p.land_pct).value_cents or 0,
        p.in_service, depreciation.property_class(p.property_type))
    new_sched = depreciation.annual_schedule(new_dep_basis, date(start, 1, 15), "residential")
    dep_before = (sell_ex.figures["exit_tax.unrecaptured_1250"].value_cents or 0)
    old_1245 = sell_ex.figures["exit_tax.sec1245"].value_cents or 0
    load = D(x.load_rate) if x.dst else Decimal(0)
    dst_y = D(x.dst_yield)
    load_cost = cents(Decimal(exchange_equity) * load)
    working_value = Decimal(repl_value - load_cost)
    if x.dst:
        repl_rate = Decimal("0.05")
    else:
        weighted = [D(ln.rate) for ln in p.loans if not ln.is_paid_off]
        repl_rate = sum(weighted) / len(weighted) if weighted else Decimal("0.065")
    if x.dst:
        repl_loan = loans.LoanInput("interest_only", repl_debt, today, repl_rate, term_months=n * 12, io_months=n * 12)
    else:
        repl_loan = loans.LoanInput("fixed", repl_debt, today, repl_rate, term_months=360)
    repl_sched = loans.build_schedule(repl_loan) if repl_debt > 0 else None
    base_noi = cashflow.noi(base_ops, vac, capex).value_cents if base_ops is not None else 0
    cap_rate = Decimal(base_noi or 0) / value_now if value_now else Decimal(0)
    x_series = []
    reinv = Decimal(0)
    cum = 0
    x_exit = None
    for t in range(1, n + 1):
        yr = start + t - 1
        if x.dst:
            cf = cents(Decimal(exchange_equity - load_cost) * dst_y)
        else:
            noi_t = cents(working_value * cap_rate * (Decimal(1) + rg) ** (t - 1))
            ds = repl_sched.debt_service_in_year(yr) if repl_sched else 0
            cf = noi_t - ds
        cum += cf
        reinv = reinv * (Decimal(1) + rr) + Decimal(cf)
        value_t = cents(_grow(working_value, appr, t))
        debt_t = repl_sched.balance_at(date(yr, 12, 31)) if repl_sched else 0
        acc_new = sum(r.amount_cents for r in new_sched if r.year <= yr)
        acc_old_cont = sum(r.amount_cents for r in old_sched if start <= r.year <= yr)
        acc_total = dep_before + acc_old_cont + acc_new
        # adjusted basis at sale = repl_basis - depreciation since exchange; express via purchase/acc fields
        ex = sale_at(value_t, debt_t, yr, carry, yr + 1, basis_override={
            "purchase_price_cents": repl_basis + dep_before + old_1245, "improvements_cents": 0,
            "accumulated_depreciation_cents": acc_total, "sec1245_cents": old_1245, "former_residence_until": None})
        x_exit = ex
        cash_t = cents(_grow(Decimal(cash_after_tax), rr, t))
        wealth = ex.net_proceeds_cents + cents(reinv) + cash_t
        x_series.append(_row(yr, cf, value_t - debt_t, value_t, debt_t, ex.total_cents, wealth))
    assert x_exit is not None
    cash_at_horizon = cents(_grow(Decimal(cash_after_tax), rr, n))
    cash_fig = money("exchange.cash_after_tax", Decimal(cash_after_tax),
                     [Input.of("cash_taken_cents", x.cash_taken_cents), Input.of("tax_on_boot_cents", boot_tax, src="figure",
                                                                                  ref="exchange.tax_on_boot")],
                     "cash_taken - tax_on_boot (negative: the tax on boot is paid from other funds)",
                     ["invested at the reinvest rate like sell-now proceeds and included in terminal wealth"] if boot else [])
    label = "1031 exchange into a DST" if x.dst else "1031 exchange (direct replacement)"
    x_caveats = ["Deferred, not forgiven: the deferred liability is shown at the horizon and grows with depreciation.",
                 "Suspended passive losses are NOT released by an exchange; they carry into the replacement.",
                 "45-day identification and 180-day closing deadlines; a qualified intermediary is required."]
    if x.dst:
        x_caveats += ["DST interests are illiquid (typically 5-10 year hold, no secondary market).",
                      "No control: the sponsor makes every property decision.",
                      "Sponsor risk and fees: the load reduces working equity on day one.",
                      "Distributions are not guaranteed."]
    else:
        x_caveats += ["A direct replacement keeps the management burden and concentration."]
    exch = {
        "path": "exchange", "label": label, "dst": x.dst, "series": x_series,
        "terminal": {
            "terminal_wealth": money("strategy.exchange.terminal_wealth", Decimal(x_series[-1]["wealth_cents"]),
                                     assumption_inputs + [Input.figure(boot_fig), Input.figure(cash_fig),
                                                          Input.figure(x_exit.figures["exit_tax.net_proceeds"])],
                                     "replacement liquidated at horizon net of selling costs, debt and the deferred tax "
                                     "+ distributions reinvested + (cash taken - tax on boot) x (1 + reinvest_rate)^horizon",
                                     ["the deferred liability is subtracted explicitly (deferred_liability_at_horizon_cents)"]).to_dict(),
            "boot": boot_fig.to_dict(),
            "boot_cents": boot, "mortgage_boot_cents": mortgage_boot, "cash_taken_cents": x.cash_taken_cents,
            "tax_on_boot_cents": boot_tax, "tax_paid_now_cents": boot_tax,
            "cash_after_tax_cents": cash_after_tax,
            "cash_after_tax_at_horizon_cents": cash_at_horizon,
            "gain_recognized_cents": recognized, "gain_deferred_cents": deferred_gain,
            "replacement_value_cents": repl_value, "replacement_debt_cents": repl_debt,
            "replacement_basis_cents": repl_basis, "exchange_equity_cents": exchange_equity,
            "dst_load_cents": load_cost, "deferred_liability_at_horizon_cents": x_exit.total_cents,
            "cumulative_cash_flow_cents": cum, "suspended_losses_released_cents": 0,
            "suspended_losses_carried_cents": carry,
            "exit_tax_on_boot": boot_ex.to_dict() if boot_ex else None,
        },
        "caveats": x_caveats,
    }
    if x.cash_taken_cents and boot_tax > x.cash_taken_cents:
        exch["caveats"].append("Tax on boot exceeds the cash taken out; the difference must come from other funds "
                               "(subtracted from terminal wealth).")
    if x.cash_taken_cents:
        exch["caveats"].append("Cash taken out (after the tax on boot) is assumed invested at the reinvest rate.")
    paths = [hold, sell, exch]
    matrix = leads_trails(paths, h, p)
    return {"property_id": p.id, "assumptions": shared, "paths": paths, "matrix": matrix, "findings": findings,
            "conventions": __doc__.split("Conventions (stated in the API output as `conventions`):")[1].strip()}


def _rank(values: dict[str, int], higher_is_better: bool) -> dict[str, str]:
    """leads for the best, trails for the worst, neutral otherwise and for anything within 1% of the best/worst."""
    vals = list(values.values())
    best = max(vals) if higher_is_better else min(vals)
    worst = min(vals) if higher_is_better else max(vals)
    scale = max(abs(best), abs(worst), 1)
    out = {}
    for k, v in values.items():
        if abs(Decimal(best - worst)) / Decimal(scale) <= NEUTRAL_BAND:
            out[k] = "neutral"
        elif v == best:
            out[k] = "leads"
        elif v == worst:
            out[k] = "trails"
        else:
            out[k] = "neutral"
    return out


def leads_trails(paths: list[dict], h: HouseholdModel, p: PropertyModel) -> dict:
    by = {pp["path"]: pp for pp in paths}
    dst = by["exchange"].get("dst", False)
    m = {
        "terminal_wealth": _rank({k: v["terminal"]["terminal_wealth"]["value_cents"] for k, v in by.items()}, True),
        "cumulative_cash_flow": _rank({k: v["terminal"]["cumulative_cash_flow_cents"] for k, v in by.items()}, True),
        "tax_paid_now": _rank({k: v["terminal"]["tax_paid_now_cents"] for k, v in by.items()}, False),
        "liquidity": {"hold": "neutral", "sell": "leads", "exchange": "trails"},
        "management_burden": {"hold": "trails", "sell": "leads", "exchange": "leads" if dst else "trails"},
        "concentration": {"hold": "trails", "sell": "leads", "exchange": "neutral" if dst else "trails"},
    }
    m["_explain"] = {
        "terminal_wealth": "higher terminal after-tax wealth leads",
        "cumulative_cash_flow": "more cash received over the horizon leads",
        "tax_paid_now": "less tax due at decision time leads",
        "liquidity": "cash in hand leads; a held property is neutral; an exchange (esp. DST) locks capital up",
        "management_burden": "no landlord duties leads (sell, DST); hands-on ownership trails",
        "concentration": "diversified proceeds lead; one property trails; a DST is diversified across a sponsor portfolio",
        "note": "a measure is neutral when all three paths are within 1% of each other; there is no overall winner",
    }
    return m


def _f(key: str, cents_: int, formula: str, inputs: list[Input] | None = None, notes: list[str] | None = None,
       status: str | None = None) -> dict:
    fig = money(key, Decimal(cents_), inputs or [Input.of(key, cents_, src="figure", ref="strategies")], formula, notes)
    if status:
        fig.status = status
    return fig.to_dict()


_ORDER = {"confirmed": 0, "estimated": 1, "blocked": 2}


def _worst(a: str, b: str) -> str:
    return a if _ORDER[a] >= _ORDER[b] else b


def present(r: dict, base_status: str = "confirmed", base_reason: str | None = None) -> dict:
    """Add the Figure-shaped fields the web client renders (types.ts StrategyComparison) without dropping the
    scalar *_cents fields the golden fixtures and the Go port compare.

    `base_status` is the worst status of the property's base analysis (cash flow, equity, exit tax): every strategy
    figure inherits it, so a strategy built on an estimated value or a blocked rent figure is never shown as confirmed.
    """
    a = r["assumptions"]
    for pth in r["paths"]:
        tw = pth["terminal"]["terminal_wealth"]
        new = _worst(tw["status"], base_status)
        if new != tw["status"]:
            tw["status"] = new
            tw["inputs"].append({"key": "base_analysis.status", "value": base_status, "status": base_status,
                                 "source": {"type": "figure", "ref": base_reason or "property analysis", "page": None}})
        boot = pth["terminal"].get("boot")
        if boot:
            boot["status"] = _worst(boot["status"], base_status)
    for pth in r["paths"]:
        t = pth["terminal"]
        st = t["terminal_wealth"]["status"]
        key = pth["path"]
        t["cumulative_cash_flow"] = _f(f"strategy.{key}.cumulative_cash_flow", t["cumulative_cash_flow_cents"],
                                       "sum of yearly net cash flow over the horizon", status=st)
        t["tax_paid_now"] = _f(f"strategy.{key}.tax_paid_now", t["tax_paid_now_cents"], "tax due at decision time", status=st)
        if key == "hold":
            t["deferred_liability"] = _f("strategy.hold.deferred_liability", t["exit_tax_at_horizon_cents"],
                                         "exit tax if sold at the horizon (grows with depreciation and appreciation)", status=st)
            t["ending_equity"] = _f("strategy.hold.ending_equity", t["ending_equity_cents"], "value - debt at horizon", status=st)
        elif key == "sell":
            t["deferred_liability"] = _f("strategy.sell.deferred_liability", 0, "nothing deferred: tax paid now", status=st)
            t["ending_equity"] = _f("strategy.sell.ending_equity", 0, "no property held", status=st)
            pth["proceeds_use"] = [
                {"label": "Net proceeds after tax, today", "value": _f("strategy.sell.net_proceeds", t["net_proceeds_today_cents"],
                                                                       "net before tax - exit tax", status=st)},
                {"label": "Exit tax paid now", "value": _f("strategy.sell.exit_tax", t["exit_tax_today_cents"],
                                                           "fed_1250 + fed_1245 + fed_ltcg + niit + state - released_loss_benefit", status=st)},
                {"label": f"Proceeds invested at {Decimal(a['reinvest_rate']) * 100:.1f}% for {a['horizon_years']} years",
                 "value": t["terminal_wealth"]},
            ]
        else:
            t["deferred_liability"] = _f("strategy.exchange.deferred_liability", t["deferred_liability_at_horizon_cents"],
                                         "tax due if the replacement is sold at the horizon (carryover basis)",
                                         notes=["shown explicitly and subtracted from terminal wealth"], status=st)
            last = pth["series"][-1]
            t["ending_equity"] = _f("strategy.exchange.ending_equity", last["equity_cents"], "replacement value - debt at horizon",
                                    status=st)
            pth["boot"] = {
                "cash_boot": _f("exchange.cash_boot", t["cash_taken_cents"], "cash taken out of the exchange", status=st),
                "mortgage_boot": _f("exchange.mortgage_boot", t["mortgage_boot_cents"], "max(0, old debt paid off - replacement debt)",
                                    status=st),
                "total_boot": t["boot"],
                "gain_recognized": _f("exchange.gain_recognized", t["gain_recognized_cents"], "min(boot, total gain)", status=st),
                "tax_on_boot": _f("exchange.tax_on_boot", t["tax_on_boot_cents"], "boot taxed through the same exit-tax stack",
                                  status=st),
                "cash_after_tax": _f("exchange.cash_after_tax", t["cash_after_tax_cents"], "cash taken - tax on boot", status=st),
            }
            pth["proceeds_use"] = [
                {"label": "Equity rolled into the replacement", "value": _f("exchange.equity_rolled", t["exchange_equity_cents"],
                                                                            "net before tax - cash taken", status=st)},
                {"label": "Gain deferred (carried into the replacement basis)",
                 "value": _f("exchange.gain_deferred", t["gain_deferred_cents"], "total gain - gain recognized", status=st)},
            ]
            if pth.get("dst"):
                pth["proceeds_use"].append({"label": "DST load (fees and sponsor costs)",
                                            "value": _f("exchange.dst_load", t["dst_load_cents"], "exchange equity x load_rate",
                                                        status=st)})
    r["base_status"] = base_status
    r["horizon_years"] = a["horizon_years"]
    r["caveats"] = {pp["path"]: pp["caveats"] for pp in r["paths"]}
    r["matrix_explain"] = r["matrix"].pop("_explain")
    return r
