"""Deterministic observation rules. The whole rule list lives in RULES so it is reviewable in one place.

Each rule: (id, severity, predicate(ctx) -> bool, message(ctx) -> str, cites(ctx) -> list[figure keys]).
`ctx` is a flat dict built by `property_context` / `household_context` from engine output; the rules never
compute money themselves beyond simple comparisons, and every number in a message comes from ctx.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


def usd(c: int | None) -> str:
    if c is None:
        return "n/a"
    sign = "-" if c < 0 else ""
    return f"{sign}${abs(c) / 100:,.0f}"


def pct(x) -> str:
    return "n/a" if x is None else f"{Decimal(str(x)) * 100:.1f}%"


@dataclass(frozen=True)
class Rule:
    id: str
    scope: str  # property | household
    severity: str  # info | warn | alert
    when: Callable[[dict], bool]
    message: Callable[[dict], str]
    cites: tuple[str, ...]


def _months_until(d: date | None, today: date) -> int | None:
    if d is None:
        return None
    return (d.year - today.year) * 12 + (d.month - today.month)


def _within(months: int | None, limit: int) -> bool:
    return months is not None and 0 <= months <= limit


RULES: tuple[Rule, ...] = (
    Rule("cash_flow_negative", "property", "alert", lambda c: c.get("net_cash_flow_cents") is not None and c["net_cash_flow_cents"] < 0,
         lambda c: f"{c['name']} runs negative cash flow of {usd(c['net_cash_flow_cents'])} a year after debt service.",
         ("cash_flow.net_annual",)),
    Rule("dscr_low", "property", "warn", lambda c: c.get("dscr") is not None and Decimal(c["dscr"]) < Decimal("1.2"),
         lambda c: f"{c['name']} covers its debt service {Decimal(c['dscr']):.2f}x, below the 1.20x lenders look for.",
         ("loans.dscr",)),
    Rule("roe_below_reinvest", "property", "warn",
         lambda c: c.get("roe") is not None and Decimal(c["roe"]) < Decimal(c["reinvest_rate"]),
         lambda c: f"{c['name']} returns {pct(c['roe'])} on its equity, below the {pct(c['reinvest_rate'])} reinvestment assumption.",
         ("equity.roe",)),
    Rule("recapture_heavy", "property", "warn",
         lambda c: c.get("equity_cents", 0) > 0 and c.get("exit_tax_cents", 0) > Decimal("0.15") * c["equity_cents"],
         lambda c: f"Selling {c['name']} today would cost {usd(c['exit_tax_cents'])} in tax, more than 15% of its {usd(c['equity_cents'])} equity.",
         ("exit_tax.total", "equity.net")),
    Rule("io_ending", "property", "alert", lambda c: _within(c.get("io_end_months"), 24),
         lambda c: f"The interest-only period on {c['name']} ends in {c['io_end_months']} months; payments step up to amortizing.",
         ("loans.schedule",)),
    Rule("arm_reset", "property", "alert", lambda c: _within(c.get("arm_reset_months"), 24),
         lambda c: f"The ARM on {c['name']} resets in {c['arm_reset_months']} months.", ("loans.schedule",)),
    Rule("loan_maturity", "property", "warn", lambda c: _within(c.get("maturity_months"), 36),
         lambda c: f"A loan on {c['name']} matures in {c['maturity_months']} months.", ("loans.schedule",)),
    Rule("land_pct_bounded", "property", "info", lambda c: bool(c.get("land_pct_bounded")),
         lambda c: f"The land share for {c['name']} was outside 20-60% and was bounded; confirm with the assessor split.",
         ("depreciation.depreciable_basis",)),
    Rule("depreciation_gap", "property", "warn", lambda c: bool(c.get("dep_outlier")),
         lambda c: f"Depreciation claimed on the return for {c['name']} differs from the allowable amount by more than 5%; recapture still uses allowable.",
         ("depreciation.accumulated",)),
    Rule("value_estimated", "property", "info", lambda c: c.get("value_source") == "estimated",
         lambda c: f"The value of {c['name']} ({usd(c['value_cents'])}) is an estimate, not an appraisal.",
         ("equity.value",)),
    Rule("concentration_high", "property", "warn",
         lambda c: c.get("concentration") is not None and Decimal(c["concentration"]) > Decimal("0.40"),
         lambda c: f"{c['name']} is {pct(c['concentration'])} of household net worth.", ("equity.concentration",)),
    Rule("str_flagged", "property", "warn", lambda c: c.get("avg_stay_days") is not None and c["avg_stay_days"] <= 7,
         lambda c: f"{c['name']} is a short-term rental (average stay {c['avg_stay_days']:g} nights): short-term rental rules apply and are not modeled.",
         ("passive.allowance",)),
    Rule("suspended_losses", "household", "info", lambda c: c.get("carryforward_cents", 0) > 0,
         lambda c: f"The household carries {usd(c['carryforward_cents'])} of suspended passive losses; a fully taxable sale would release them, a 1031 would not.",
         ("passive.carryforward_end",)),
    Rule("magi_phaseout", "household", "info",
         lambda c: c.get("magi_cents", 0) > 10_000_000 and c.get("net_rental_cents", 0) < 0,
         lambda c: f"MAGI of {usd(c['magi_cents'])} reduces the $25,000 rental loss allowance to {usd(c['allowance_cents'])}.",
         ("passive.allowance",)),
)


def property_context(name: str, an: dict, p, reinvest_rate: Decimal, today: date) -> dict:
    io_end = None
    arm = None
    mat = None
    for ln in p.loans:
        if ln.is_paid_off:
            continue
        if ln.io_months and ln.loan_type != "heloc":
            y, m = ln.balance_as_of.year, ln.balance_as_of.month + ln.io_months
            end = date(y + (m - 1) // 12, (m - 1) % 12 + 1, 1)
            v = _months_until(end, today)
            io_end = v if io_end is None else min(io_end, v)
        if ln.arm_reset_date:
            v = _months_until(ln.arm_reset_date, today)
            arm = v if arm is None else min(arm, v)
        if ln.maturity_date:
            v = _months_until(ln.maturity_date, today)
            mat = v if mat is None else min(mat, v)
    return {
        "name": name, "net_cash_flow_cents": an.get("_net_cents"), "dscr": an.get("_dscr"), "roe": an.get("_roe"),
        "reinvest_rate": reinvest_rate, "equity_cents": an.get("_equity_cents") or 0, "exit_tax_cents": an.get("_exit_tax_cents") or 0,
        "io_end_months": io_end, "arm_reset_months": arm, "maturity_months": mat,
        "land_pct_bounded": an.get("_land_bounded"), "dep_outlier": an.get("_dep_outlier"),
        "value_source": p.value_source, "value_cents": p.current_value_cents,
        "concentration": an.get("_concentration"), "avg_stay_days": p.avg_stay_days,
    }


def evaluate(ctx: dict, scope: str, property_id: str | None = None) -> list[dict]:
    out = []
    for r in RULES:
        if r.scope != scope:
            continue
        try:
            hit = r.when(ctx)
        except (KeyError, TypeError, ArithmeticError):
            hit = False
        if hit:
            out.append({"rule": r.id, "severity": r.severity, "message": r.message(ctx), "cites": list(r.cites),
                        "property_id": property_id})
    order = {"alert": 0, "warn": 1, "info": 2}
    return sorted(out, key=lambda o: order[o["severity"]])


def rule_table() -> list[dict]:
    return [{"id": r.id, "scope": r.scope, "severity": r.severity, "cites": list(r.cites)} for r in RULES]
