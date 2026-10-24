"""Golden-fixture dispatcher: maps the plain-JSON `input` of a fixture case onto an engine call and returns the
plain-JSON result whose keys are compared against `expected`. The Go port implements the same `fn` names.

Fixture file shape (fixtures/engine/<name>.json): {"description": str, "cases": [{"name", "fn", "input", "expected"}]}.
Comparison: every key in `expected` must equal the same key in the result (integers exactly, strings exactly);
keys not listed in `expected` are not compared.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from groundplan.engine import cashflow, depreciation, loans, passive, tax_tables
from groundplan.engine.cashflow import YearOperations
from groundplan.engine.exit_tax import HouseholdTax, SaleInput, compute_exit_tax
from groundplan.engine.loans import LoanInput
from groundplan.engine.models import HouseholdModel, PropertyModel
from groundplan.engine.state_tax import state_exit_tax
from groundplan.engine.strategies import ExchangeAssumptions, StrategyAssumptions, compare_strategies


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def depreciation_schedule(i: dict) -> dict:
    sched = depreciation.annual_schedule(i["basis_cents"], _d(i["placed_in_service"]), i.get("class", "residential"),
                                         i.get("mode", "table"))
    out = {"years": len(sched), "first_year_cents": sched[0].amount_cents, "first_year_pct": sched[0].pct,
           "last_year": sched[-1].year, "last_year_cents": sched[-1].amount_cents, "total_cents": sum(r.amount_cents for r in sched)}
    if len(sched) > 1:
        out["second_year_cents"] = sched[1].amount_cents
    if "accumulated_through" in i:
        out["accumulated_cents"] = depreciation.accumulated_through(sched, i["accumulated_through"])
    if len(sched) >= 28:
        out["year28_cents"] = sched[27].amount_cents
    return out


def depreciation_basis(i: dict) -> dict:
    f = depreciation.depreciable_basis(i["purchase_price_cents"], i.get("improvements_cents", 0), i.get("land_pct"))
    return {"basis_cents": f.value_cents, "land_pct": str(f.inputs[2].value), "bounded": any("bounded" in n for n in f.notes),
            "status": f.status}


def depreciation_full(i: dict) -> dict:
    r = depreciation.compute_depreciation(i["purchase_price_cents"], i.get("improvements_cents", 0), i.get("land_pct"),
                                          _d(i["placed_in_service"]), i.get("property_type", "sfr"), i["as_of_year"],
                                          mode=i.get("mode", "table"), ledger=i.get("ledger"),
                                          cost_seg_study=i.get("cost_seg_study", False))
    return {"accumulated_cents": r.accumulated.value_cents, "current_year_cents": r.current_year.value_cents,
            "sec1245_cents": r.sec1245_cents, "outlier": r.outlier}


def _loan(i: dict) -> LoanInput:
    return LoanInput(loan_type=i["loan_type"], balance_cents=i["balance_cents"], balance_as_of=_d(i["balance_as_of"]),
                     rate=i["rate"], term_months=i.get("term_months", 360), io_months=i.get("io_months", 0),
                     arm_reset_date=_d(i.get("arm_reset_date")), arm_index_margin=i.get("arm_index_margin"),
                     arm_index=i.get("arm_index"), monthly_payment_cents=i.get("monthly_payment_cents"),
                     maturity_date=_d(i.get("maturity_date")), is_paid_off=i.get("is_paid_off", False))


def loan_schedule(i: dict) -> dict:
    s = loans.build_schedule(_loan(i))
    out = {"months": len(s.rows), "annual": [s.annual_summary(y) for y in i["years"]]}
    if s.rows:
        out["first_payment_cents"] = s.rows[0].payment_cents
        out["last_balance_cents"] = s.rows[-1].balance_cents
    for idx in i.get("rows", []):
        out[f"row{idx}"] = s.rows[idx - 1].to_dict()
    return out


def annual_debt(i: dict) -> dict:
    """The loans table's yearly row (analysis.annual_debt), incl. a back-filled year before the first scheduled payment."""
    from groundplan.engine.analysis import annual_debt as _annual_debt

    a, notes = _annual_debt([loans.build_schedule(_loan(x)) for x in i["loans"]], i["year"])
    return {k: a[k] for k in ("principal_cents", "interest_cents", "debt_service_cents", "balance_end_cents")} | {
        "backfilled": bool(notes)}


def _ops(i: dict) -> YearOperations:
    keys = ("gross_rent_cents", "other_income_cents", "taxes_cents", "insurance_cents", "repairs_cents", "mgmt_cents",
            "utilities_cents", "hoa_cents", "other_cents", "mortgage_interest_cents", "depreciation_cents")
    return YearOperations(tax_year=i.get("tax_year", 2025), **{k: i.get(k, 0) for k in keys})


def cash_flow_bridge(i: dict) -> dict:
    ops = _ops(i)
    line21 = cashflow.schedule_e_line21(ops)
    ret = cashflow.cash_flow_from_return(line21, ops.depreciation_cents, i["principal_paid_cents"],
                                         i.get("capital_improvements_paid_cents", 0))
    noi = cashflow.noi(ops, i.get("vacancy_rate", "0"), i.get("capex_reserve_rate", "0"))
    net = cashflow.net_cash_flow(noi, i["principal_paid_cents"], ops.mortgage_interest_cents)
    return {"line21_cents": line21.value_cents, "cash_flow_from_return_cents": ret.value_cents, "noi_cents": noi.value_cents,
            "net_cash_flow_cents": net.value_cents, "delta_cents": cashflow.bridge_delta(net, ret).value_cents}


def passive_allowance(i: dict) -> dict:
    r = passive.apply_passive_rules(i["net_rental_cents"], i.get("prior_carryforward_cents", 0), i["magi_cents"],
                                    i.get("filing_status", "mfj"), i.get("active_participation", True),
                                    i.get("re_professional", False))
    return {"allowance_cents": r.allowance.value_cents, "deductible_cents": r.deductible.value_cents,
            "suspended_new_cents": r.suspended_new.value_cents, "carryforward_end_cents": r.carryforward_end.value_cents}


def passive_release(i: dict) -> dict:
    return {"released_cents": passive.released_on_sale(i["carryforward_cents"], i["disposition"]).value_cents}


def tax_stack(i: dict) -> dict:
    s = tax_tables.stack(i["ordinary_taxable_cents"], i.get("sec1245_cents", 0), i["sec1250_cents"], i["ltcg_cents"],
                         i.get("tax_year", 2025), i["filing_status"])
    return {"tax_ordinary_cents": s.tax_ordinary.value_cents, "tax_1245_cents": s.tax_1245.value_cents,
            "tax_1250_cents": s.tax_1250.value_cents, "tax_ltcg_cents": s.tax_ltcg.value_cents,
            "rates_1250": [x.rate for x in s.layers_1250], "rates_ltcg": [x.rate for x in s.layers_ltcg]}


def niit(i: dict) -> dict:
    return {"niit_cents": tax_tables.niit(i["nii_cents"], i["magi_cents"], i["filing_status"]).value_cents}


def state_tax(i: dict) -> dict:
    f, findings = state_exit_tax(i["state"], i["gain_cents"], i["other_income_cents"], i["filing_status"],
                                 i.get("replacement_state"))
    return {"state_tax_cents": f.value_cents, "status": f.status, "finding_kinds": [x["kind"] for x in findings]}


def _hh_tax(i: dict) -> HouseholdTax:
    return HouseholdTax(filing_status=i["filing_status"], state=i.get("state", "WA"), tax_year=i.get("tax_year", 2025),
                        wages_cents=i.get("wages_cents", 0), other_income_cents=i.get("other_income_cents", 0),
                        magi_cents=i.get("magi_cents", 0), released_suspended_losses_cents=i.get("released_cents", 0),
                        rental_nii_cents=i.get("rental_nii_cents", 0))


def exit_tax(i: dict) -> dict:
    s = i["sale"]
    sale = SaleInput(sale_price_cents=s["sale_price_cents"], selling_cost_rate=s.get("selling_cost_rate", "0.06"),
                     loan_payoff_cents=s.get("loan_payoff_cents", 0), purchase_price_cents=s["purchase_price_cents"],
                     improvements_cents=s.get("improvements_cents", 0),
                     accumulated_depreciation_cents=s["accumulated_depreciation_cents"], sec1245_cents=s.get("sec1245_cents", 0),
                     sale_date=_d(s.get("sale_date")), former_residence_until=_d(s.get("former_residence_until")),
                     recognized_gain_cap_cents=s.get("recognized_gain_cap_cents"))
    r = compute_exit_tax(sale, _hh_tax(i["household"]))
    keys = ("total_gain", "unrecaptured_1250", "sec1245", "ltcg", "sec121_excluded", "fed_1250", "fed_1245", "fed_ltcg",
            "niit", "state", "released_loss_benefit", "total", "net_before_tax", "net_proceeds")
    out = {f"{k}_cents": r.figures[f"exit_tax.{k}"].value_cents for k in keys}
    out["rates_1250"] = [x.rate for x in r.stack.layers_1250]
    out["finding_count"] = len(r.findings)
    return out


def _prop(i: dict) -> PropertyModel:
    years = {int(y): _ops({**v, "tax_year": int(y)}) for y, v in i.get("years", {}).items()}
    return PropertyModel(id=i.get("id", "p1"), property_type=i.get("property_type", "sfr"),
                         purchase_date=_d(i["purchase_date"]), purchase_price_cents=i["purchase_price_cents"],
                         placed_in_service_date=_d(i.get("placed_in_service_date")), land_pct=i.get("land_pct"),
                         improvements_cents=i.get("improvements_cents", 0), current_value_cents=i["current_value_cents"],
                         value_source=i.get("value_source", "confirmed"), appreciation_rate=i.get("appreciation_rate"),
                         rent_growth_rate=i.get("rent_growth_rate"), expense_growth_rate=i.get("expense_growth_rate"),
                         vacancy_rate=i.get("vacancy_rate"), capex_reserve_rate=i.get("capex_reserve_rate"),
                         selling_cost_rate=i.get("selling_cost_rate"), loans=[_loan(x) for x in i.get("loans", [])], years=years)


def strategies(i: dict) -> dict:
    p = _prop(i["property"])
    hh = i["household"]
    h = HouseholdModel(filing_status=hh["filing_status"], state=hh.get("state", "WA"), tax_year=hh.get("tax_year", 2025),
                       wages_cents=hh.get("wages_cents", 0), other_income_cents=hh.get("other_income_cents", 0),
                       magi_cents=hh.get("magi_cents", 0), carryforward_cents=hh.get("carryforward_cents", 0))
    x = i.get("exchange", {})
    a = StrategyAssumptions(horizon_years=i.get("horizon_years", 10), reinvest_rate=i.get("reinvest_rate", "0.06"),
                            exchange=ExchangeAssumptions(replacement_value_cents=x.get("replacement_value_cents"),
                                                         replacement_debt_cents=x.get("replacement_debt_cents"),
                                                         dst=x.get("dst", False), load_rate=x.get("load_rate", "0.085"),
                                                         dst_yield=x.get("dst_yield", "0.05"),
                                                         cash_taken_cents=x.get("cash_taken_cents", 0)))
    r = compare_strategies(p, h, a)
    by = {pp["path"]: pp["terminal"] for pp in r["paths"]}
    return {
        "hold_terminal_wealth_cents": by["hold"]["terminal_wealth"]["value_cents"],
        "sell_terminal_wealth_cents": by["sell"]["terminal_wealth"]["value_cents"],
        "exchange_terminal_wealth_cents": by["exchange"]["terminal_wealth"]["value_cents"],
        "sell_tax_now_cents": by["sell"]["tax_paid_now_cents"],
        "sell_released_cents": by["sell"]["suspended_losses_released_cents"],
        "exchange_released_cents": by["exchange"]["suspended_losses_released_cents"],
        "boot_cents": by["exchange"]["boot_cents"], "mortgage_boot_cents": by["exchange"]["mortgage_boot_cents"],
        "tax_on_boot_cents": by["exchange"]["tax_on_boot_cents"], "gain_deferred_cents": by["exchange"]["gain_deferred_cents"],
        "dst_load_cents": by["exchange"]["dst_load_cents"],
        "cash_after_tax_cents": by["exchange"]["cash_after_tax_cents"],
        "cash_after_tax_at_horizon_cents": by["exchange"]["cash_after_tax_at_horizon_cents"],
        "replacement_value_cents": by["exchange"]["replacement_value_cents"],
    }


FUNCTIONS = {f.__name__: f for f in (depreciation_schedule, depreciation_basis, depreciation_full, loan_schedule, annual_debt,
                                     cash_flow_bridge, passive_allowance, passive_release, tax_stack, niit, state_tax,
                                     exit_tax, strategies)}


def run_case(case: dict) -> dict:
    return FUNCTIONS[case["fn"]](case["input"])


def compare(expected: dict, actual: dict) -> list[str]:
    diffs = []
    for k, v in expected.items():
        if k not in actual:
            diffs.append(f"missing key {k}")
        elif actual[k] != v:
            diffs.append(f"{k}: expected {v!r} got {actual[k]!r}")
    return diffs


__all__ = ["FUNCTIONS", "run_case", "compare", "Decimal"]
