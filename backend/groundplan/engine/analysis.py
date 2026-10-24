"""Compose the engine modules into the per-property analysis the API returns (still pure: no I/O)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from groundplan.engine import cashflow, depreciation, equity, loans
from groundplan.engine.exit_tax import HouseholdTax, SaleInput, compute_exit_tax
from groundplan.engine.figure import Input, derive_status, money
from groundplan.engine.models import HouseholdModel, PropertyModel, rate_or_default


def loan_schedules(p: PropertyModel) -> list[loans.LoanSchedule]:
    return [loans.build_schedule(ln) for ln in p.loans]


def annual_debt(scheds: list[loans.LoanSchedule], year: int) -> tuple[dict, list[str]]:
    """Combined annual debt figures; a year before a loan's statement date is back-filled from its first 12
    scheduled months (the statement balance is the year-end balance), with a note."""
    out = loans.combined_annual(scheds, year)
    notes: list[str] = []
    for s in scheds:
        if not s.rows or any(r.year == year for r in s.rows) or year >= s.rows[0].year:
            continue
        first = s.rows[:12]
        out["principal_cents"] += sum(r.principal_cents for r in first)
        out["interest_cents"] += sum(r.interest_cents for r in first)
        out["debt_service_cents"] += sum(r.payment_cents for r in first)
        out["balance_end_cents"] += s.loan.balance_cents
        notes.append(f"{s.loan.lender or 'loan'}: {year} debt service taken from the first 12 months after the "
                     f"{s.loan.balance_as_of.isoformat()} statement")
    return out, notes


def ops_for_year(p: PropertyModel, year: int) -> tuple[cashflow.YearOperations | None, int | None]:
    """Operations for `year`: the actual year if on file, else the latest year projected forward."""
    if year in p.years:
        return p.years[year], None
    prior = [y for y in p.years if y < year]
    if not prior:
        return None, None
    base_year = max(prior)
    rg, _ = rate_or_default(p.rent_growth_rate, "rent_growth_rate")
    eg, _ = rate_or_default(p.expense_growth_rate, "expense_growth_rate")
    return cashflow.project_operations(p.years[base_year], year - base_year, rg, eg), base_year


def household_tax(h: HouseholdModel, released: int = 0, rental_nii: int = 0, tax_year: int | None = None) -> HouseholdTax:
    return HouseholdTax(filing_status=h.filing_status, state=h.state, tax_year=tax_year or h.tax_year,
                        wages_cents=h.wages_cents, other_income_cents=h.other_income_cents, magi_cents=h.magi_cents,
                        released_suspended_losses_cents=released, rental_nii_cents=rental_nii)


def depreciation_for(p: PropertyModel, year: int, mode: str = "table") -> depreciation.DepreciationResult:
    return depreciation.compute_depreciation(
        p.purchase_price_cents, p.improvements_cents, p.land_pct, p.in_service, p.property_type, year, mode=mode,
        ledger=p.ledger, cost_seg_study=p.cost_seg_study,
        sources={"purchase_price_cents": Input.of("purchase_price_cents", p.purchase_price_cents, src="document",
                                                  ref="closing statement")})


def value_input(p: PropertyModel) -> Input:
    src = "manual" if p.value_source == "confirmed" else "public_data"
    return Input.of("current_value_cents", p.current_value_cents, src=src,
                    ref=f"value_as_of {p.value_as_of.isoformat() if p.value_as_of else 'unknown'}")


def analyze_property(p: PropertyModel, h: HouseholdModel, year: int | None = None, horizon: int = 10,
                     carryforward_release: int = 0, mode: str = "table") -> dict:
    year = year or h.tax_year
    out: dict = {"property_id": p.id, "year": year, "notes": []}
    scheds = loan_schedules(p)
    annual, debt_notes = annual_debt(scheds, year)
    out["notes"] += debt_notes
    ops, projected_from = ops_for_year(p, year)
    vac, vac_src = rate_or_default(p.vacancy_rate, "vacancy_rate")
    capex, capex_src = rate_or_default(p.capex_reserve_rate, "capex_reserve_rate")
    dep = depreciation_for(p, year, mode)
    # Cash flow
    cf: dict = {}
    if ops is not None:
        noi_fig = cashflow.noi(ops, vac, capex, p.blocked_keys)
        for inp in noi_fig.inputs:
            if (inp.key == "vacancy_rate" and vac_src == "default") or (inp.key == "capex_reserve_rate" and capex_src == "default"):
                inp.source.type = "default"
            elif inp.key in ("vacancy_rate", "capex_reserve_rate"):
                inp.source.type = "manual"
        noi_fig.status = derive_status(noi_fig.inputs, p.blocked_keys)
        net = cashflow.net_cash_flow(noi_fig, annual["principal_cents"], annual["interest_cents"])
        dscr = loans.dscr(noi_fig.value_cents or 0, annual["debt_service_cents"], [Input.figure(noi_fig)])
        line21 = cashflow.schedule_e_line21(ops)
        from_ret = cashflow.cash_flow_from_return(line21, ops.depreciation_cents, annual["principal_cents"],
                                                  p.capital_improvements_paid.get(year, 0))
        cf = {"noi": noi_fig.to_dict(), "net_annual": net.to_dict(), "dscr": dscr.to_dict(),
              "debt_service_cents": annual["debt_service_cents"],
              "schedule_e_bridge": {"line21": line21.to_dict(), "from_return": from_ret.to_dict(),
                                    "delta": cashflow.bridge_delta(net, from_ret).to_dict()},
              "projected_from_year": projected_from}
        out["_net_cents"] = net.value_cents
        out["_noi_cents"] = noi_fig.value_cents
        out["_line21_cents"] = line21.value_cents
        out["_dscr"] = dscr.value
        # projection
        rg, _ = rate_or_default(p.rent_growth_rate, "rent_growth_rate")
        eg, _ = rate_or_default(p.expense_growth_rate, "expense_growth_rate")
        proj = []
        for t in range(1, horizon + 1):
            o = cashflow.project_operations(ops, t, rg, eg)
            a = loans.combined_annual(scheds, year + t)
            n = cashflow.noi(o, vac, capex)
            proj.append({"year": year + t, "noi_cents": n.value_cents, "debt_service_cents": a["debt_service_cents"],
                         "net_cash_flow_cents": (n.value_cents or 0) - a["debt_service_cents"]})
        cf["projection"] = proj
    else:
        out["notes"].append(f"no operating data on file for {year} or earlier")
        out["_net_cents"] = None
    out["cash_flow"] = cf
    # Equity
    as_of = date(year, 12, 31)
    balances = [s.balance_at(as_of) for s in scheds]
    vin = value_input(p)
    appr, appr_src = rate_or_default(p.appreciation_rate, "appreciation_rate")
    eq = equity.equity(p.current_value_cents, balances, vin, p.blocked_keys)
    begin_balances = [s.balance_at(date(year - 1, 12, 31)) for s in scheds]
    value_begin = int(Decimal(p.current_value_cents) / (Decimal(1) + appr))
    eq_begin = value_begin - sum(begin_balances)
    appr_fig = equity.appreciation_this_year(value_begin, appr, appr_src)
    roe = equity.roe(out["_net_cents"] or 0, annual["principal_cents"], appr_fig.value_cents or 0, eq_begin)
    out["equity"] = {
        "value": money("equity.value", Decimal(p.current_value_cents), [vin], "current_value").to_dict(),
        "debt_cents": sum(balances),
        "net": eq.to_dict(), "lendable": equity.lendable_equity(p.current_value_cents, balances, vin).to_dict(),
        "roe": roe.to_dict(), "concentration": equity.concentration(p.current_value_cents, h.net_worth_cents).to_dict(),
        "loan_balances": [{"loan_id": ln.id, "lender": ln.lender, "balance_cents": b, "is_paid_off": ln.is_paid_off}
                          for ln, b in zip(p.loans, balances, strict=True)],
    }
    out["_equity_cents"] = eq.value_cents
    out["_roe"] = roe.value
    out["appreciation"] = {
        "rate": appr_fig.inputs[1].value, "rate_source": appr_src,
        "this_year": appr_fig.to_dict(),
        "cagr_since_purchase": equity.cagr(p.purchase_price_cents, p.current_value_cents, p.purchase_date, as_of).to_dict(),
        "projected": [equity.projected_value(p.current_value_cents, appr, n, vin, appr_src).to_dict()
                      for n in (1, 3, 5, 7, 10) if n <= max(horizon, 1)],
    }
    # Depreciation
    out["depreciation"] = dep.to_dict()
    out["depreciation"]["mode"] = mode
    out["depreciation"]["property_class"] = depreciation.property_class(p.property_type)
    # Exit tax (sale at start of `year + 1` == priced at current value, accumulated through `year`)
    dep_sale = depreciation_for(p, year + 1, mode)
    sc, _ = rate_or_default(p.selling_cost_rate, "selling_cost_rate")
    sale = SaleInput(sale_price_cents=p.current_value_cents, selling_cost_rate=sc, loan_payoff_cents=sum(balances),
                     purchase_price_cents=p.purchase_price_cents, improvements_cents=p.improvements_cents,
                     accumulated_depreciation_cents=(dep_sale.accumulated.value_cents or 0) - dep_sale.sec1245_cents,
                     sec1245_cents=dep_sale.sec1245_cents, sale_date=date(year + 1, 1, 15),
                     former_residence_until=p.former_residence_until,
                     sources={"sale_price_cents": vin})
    ex = compute_exit_tax(sale, household_tax(h, released=carryforward_release, tax_year=year + 1), p.blocked_keys)
    out["exit_tax"] = ex.to_dict()
    out["_exit_tax_cents"] = ex.total_cents
    out["_dep_outlier"] = dep.outlier
    out["loans"] = [{
        "loan_id": ln.id, "lender": ln.lender, "loan_type": ln.loan_type, "lien_position": ln.lien_position,
        "is_paid_off": ln.is_paid_off, "rate": str(ln.rate), "balance_cents": ln.balance_cents,
        "io_months": ln.io_months, "arm_reset_date": ln.arm_reset_date.isoformat() if ln.arm_reset_date else None,
        "maturity_date": ln.maturity_date.isoformat() if ln.maturity_date else None,
        "annual": [s.annual_summary(y) for y in range(year, year + horizon + 1)],
        "months": [r.to_dict() for r in s.rows[:120]], "months_total": len(s.rows), "notes": s.notes,
    } for ln, s in zip(p.loans, scheds, strict=True)]
    out["_balances"] = balances
    out["_annual_debt"] = annual
    return out
