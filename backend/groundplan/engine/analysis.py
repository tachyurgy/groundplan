"""Compose the engine modules into the per-property analysis (still pure: no I/O).

The output shape matches web/src/api/types.ts `PropertyAnalysis` (minus `property` and `observations`, which the
API layer adds). Every number is a Figure; the private `_figs` map indexes all of them by key for the
traceability endpoint and the observation rules.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from groundplan.engine import cashflow, depreciation, equity, loans
from groundplan.engine.exit_tax import HouseholdTax, SaleInput, compute_exit_tax
from groundplan.engine.figure import Figure, Input, derive_status, money
from groundplan.engine.models import HouseholdModel, PropertyModel, rate_or_default

METHOD_FOR_CLASS = {"residential": "sl_27_5", "nonresidential": "sl_39", "land": "sl_27_5"}


def loan_schedules(p: PropertyModel) -> list[loans.LoanSchedule]:
    return [loans.build_schedule(ln) for ln in p.loans]


def annual_debt(scheds: list[loans.LoanSchedule], year: int) -> tuple[dict, list[str]]:
    """Combined annual debt figures; a year before a loan's statement date is back-filled from its first 12
    scheduled months (the statement balance is the year-end balance, already supplied by combined_annual), with a note."""
    out = loans.combined_annual(scheds, year)
    notes: list[str] = []
    for s in scheds:
        if not s.rows or any(r.year == year for r in s.rows) or year >= s.rows[0].year:
            continue
        first = s.rows[:12]
        out["principal_cents"] += sum(r.principal_cents for r in first)
        out["interest_cents"] += sum(r.interest_cents for r in first)
        out["debt_service_cents"] += sum(r.payment_cents for r in first)
        # balance_end_cents is NOT added here: combined_annual already returns the statement balance for a year
        # before the first schedule row (balance_at() before the schedule = statement balance)
        notes.append(f"{s.loan.lender or 'loan'}: {year} debt service taken from the first 12 months after the "
                     f"{s.loan.balance_as_of.isoformat()} statement")
    return out, notes


def loan_annual_for(s: loans.LoanSchedule, year: int) -> dict:
    a, _ = annual_debt([s], year)
    return a


def ops_for_year(p: PropertyModel, year: int) -> tuple[cashflow.YearOperations | None, int | None]:
    """Operations for `year`: the actual year if on file, else the latest earlier year projected forward."""
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
        sources={"purchase_price_cents": Input.of("purchase_price_cents", p.purchase_price_cents, src="manual",
                                                  ref="purchase price (closing statement / manual)")})


def value_input(p: PropertyModel) -> Input:
    src = "manual" if p.value_source == "confirmed" else "public_data"
    return Input.of("current_value_cents", p.current_value_cents, src=src,
                    ref=f"{p.value_source} value as of {p.value_as_of.isoformat() if p.value_as_of else 'unknown'}")


def _rate_num(x) -> float | None:
    return None if x is None else float(Decimal(str(x)))


def analyze_property(p: PropertyModel, h: HouseholdModel, year: int | None = None, horizon: int = 10,
                     carryforward_release: int = 0, mode: str = "table") -> dict:
    year = year or h.tax_year
    figs: dict[str, Figure] = {}

    def reg(f: Figure) -> Figure:
        figs[f.key] = f
        return f

    notes: list[str] = []
    scheds = loan_schedules(p)
    annual, debt_notes = annual_debt(scheds, year)
    notes += debt_notes
    ops, projected_from = ops_for_year(p, year)
    if projected_from:
        notes.append(f"no operating data for {year}: projected from {projected_from}")
    vac, vac_src = rate_or_default(p.vacancy_rate, "vacancy_rate")
    capex, capex_src = rate_or_default(p.capex_reserve_rate, "capex_reserve_rate")
    blocked = p.blocked_keys
    vac_in = Input.of("vacancy_rate", vac, src=vac_src)
    capex_in = Input.of("capex_reserve_rate", capex, src=capex_src)

    # ---------------- cash flow ----------------
    cf: dict = {}
    net_cents: int | None = None
    noi_fig: Figure | None = None
    if ops is None:
        ops = cashflow.YearOperations(tax_year=year, gross_rent_cents=0)
        notes.append(f"no operating data on file for {year} or earlier")
    rent_in = ops.inp("gross_rent_cents", ops.gross_rent_cents)
    gross_rent = reg(money("cash_flow.gross_rent", Decimal(ops.gross_rent_cents), [rent_in], "Schedule E line 3 rents received",
                           blocked_keys=blocked))
    vacancy_loss = reg(money("cash_flow.vacancy_loss", Decimal(ops.gross_rent_cents) * vac, [Input.figure(gross_rent), vac_in],
                             "gross_rent * vacancy_rate"))
    other_income = reg(money("cash_flow.other_income", Decimal(ops.other_income_cents),
                             [ops.inp("other_income_cents", ops.other_income_cents)], "other rental income"))
    exp_inputs = [ops.inp(f"{k}_cents", getattr(ops, f"{k}_cents")) for k in cashflow.EXPENSE_LINES]
    opex = reg(money("cash_flow.operating_expenses", Decimal(ops.expenses_total()), exp_inputs,
                     "taxes + insurance + repairs + mgmt + utilities + hoa + other (excludes interest and depreciation)",
                     blocked_keys=blocked))
    capex_res = reg(money("cash_flow.capex_reserve", Decimal(ops.gross_rent_cents) * capex, [Input.figure(gross_rent), capex_in],
                          "gross_rent * capex_reserve_rate"))
    noi_val = gross_rent.dec - vacancy_loss.dec + other_income.dec - opex.dec - capex_res.dec
    noi_fig = reg(money("cash_flow.noi", noi_val, [Input.figure(f) for f in (gross_rent, vacancy_loss, other_income, opex, capex_res)],
                        "gross_rent - vacancy_loss + other_income - operating_expenses - capex_reserve", blocked_keys=blocked))
    loan_inputs = [Input.of(f"loan[{i}].debt_service_cents", loan_annual_for(s, year)["debt_service_cents"], src="figure",
                            ref=f"loans.schedule[{s.loan.lender or i}]") for i, s in enumerate(scheds)]
    debt_service = reg(money("cash_flow.debt_service", Decimal(annual["debt_service_cents"]),
                             loan_inputs or [Input.of("debt_service_cents", 0)],
                             "sum over liens of (principal + interest) paid in the year", debt_notes))
    net = reg(money("cash_flow.net_annual", noi_fig.dec - debt_service.dec, [Input.figure(noi_fig), Input.figure(debt_service)],
                    "NOI - debt service (principal + interest)", blocked_keys=blocked))
    net_cents = net.value_cents
    line21 = reg(cashflow.schedule_e_line21(ops))
    dep_line = reg(money("cash_flow.schedule_e.line18_depreciation", Decimal(ops.depreciation_cents),
                         [ops.inp("depreciation_cents", ops.depreciation_cents)], "Schedule E line 18 depreciation"))
    principal = reg(money("cash_flow.principal_paid", Decimal(annual["principal_cents"]),
                          [Input.of("principal_cents", annual["principal_cents"], src="figure", ref="loans.schedule")],
                          "sum of principal paid on all liens in the year", debt_notes))
    capimp_c = p.capital_improvements_paid.get(year, 0)
    capimp = reg(money("cash_flow.capital_improvements_paid", Decimal(capimp_c), [Input.of("capital_improvements_paid_cents", capimp_c)],
                       "capital improvements paid in cash (Form 4562 additions)"))
    from_ret = reg(money("cash_flow.from_return", line21.dec + dep_line.dec - principal.dec - capimp.dec,
                         [Input.figure(line21), Input.figure(dep_line), Input.figure(principal), Input.figure(capimp)],
                         "line21 + line18_depreciation - principal_paid - capital_improvements_paid",
                         ["interest is already inside line 21 and is never subtracted twice"]))
    delta = reg(cashflow.bridge_delta(net, from_ret))
    rg, _ = rate_or_default(p.rent_growth_rate, "rent_growth_rate")
    eg, _ = rate_or_default(p.expense_growth_rate, "expense_growth_rate")
    projection = []
    for t in range(1, horizon + 1):
        o = cashflow.project_operations(ops, t, rg, eg)
        a, _ = annual_debt(scheds, year + t)
        n = cashflow.noi(o, vac, capex)
        projection.append({"year": year + t, "noi_cents": n.value_cents, "debt_service_cents": a["debt_service_cents"],
                           "net_cash_flow_cents": (n.value_cents or 0) - a["debt_service_cents"]})
    dscr = reg(loans.dscr(noi_fig.value_cents or 0, annual["debt_service_cents"], [Input.figure(noi_fig), Input.figure(debt_service)]))
    cf = {"gross_rent": gross_rent.to_dict(), "vacancy_loss": vacancy_loss.to_dict(), "other_income": other_income.to_dict(),
          "operating_expenses": opex.to_dict(), "capex_reserve": capex_res.to_dict(), "noi": noi_fig.to_dict(),
          "debt_service": debt_service.to_dict(), "net_cash_flow": net.to_dict(), "dscr": dscr.to_dict(),
          "projection": projection, "projected_from_year": projected_from,
          "schedule_e_bridge": {"line21": line21.to_dict(), "line18_depreciation": dep_line.to_dict(),
                                "principal_paid": principal.to_dict(), "capital_improvements_paid": capimp.to_dict(),
                                "cash_flow_from_return": from_ret.to_dict(), "delta_vs_engine": delta.to_dict()}}

    # ---------------- equity ----------------
    as_of = date(year, 12, 31)
    balances = [s.balance_at(as_of) if s.rows and s.rows[0].year <= year else (0 if s.loan.is_paid_off else s.loan.balance_cents)
                for s in scheds]
    vin = value_input(p)
    value_fig = reg(money("equity.value", Decimal(p.current_value_cents), [vin], "current value", blocked_keys=blocked))
    debt_fig = reg(money("equity.total_debt", Decimal(sum(balances)),
                         [Input.of(f"loan[{i}].balance_cents", b, src="figure", ref=f"loans.schedule[{s.loan.lender or i}]")
                          for i, (s, b) in enumerate(zip(scheds, balances, strict=True))] or [Input.of("balance_cents", 0)],
                         f"sum of lien balances at {as_of.isoformat()} (paid-off liens = 0)", blocked_keys=blocked))
    eq = reg(money("equity.net", value_fig.dec - debt_fig.dec, [Input.figure(value_fig), Input.figure(debt_fig)],
                   "current_value - sum(loan balances)", blocked_keys=blocked))
    lend = reg(equity.lendable_equity(p.current_value_cents, balances, vin))
    appr, appr_src = rate_or_default(p.appreciation_rate, "appreciation_rate")
    begin_balances = [s.balance_at(date(year - 1, 12, 31)) for s in scheds]
    value_begin = int(Decimal(p.current_value_cents) / (Decimal(1) + appr))
    eq_begin = value_begin - sum(begin_balances)
    appr_fig = reg(equity.appreciation_this_year(value_begin, appr, appr_src))
    roe_rate = None if eq_begin <= 0 else (Decimal(net_cents or 0) + principal.dec + appr_fig.dec) / Decimal(eq_begin)
    roe_fig = reg(money("equity.roe", Decimal(net_cents or 0) + principal.dec + appr_fig.dec,
                        [Input.figure(net), Input.figure(principal), Input.figure(appr_fig),
                         Input.of("equity_begin_cents", eq_begin, src="figure", ref="equity.net (begin of year)")],
                        "numerator = net_cash_flow + principal_paydown + appreciation_this_year; roe_rate = numerator / equity_begin_of_year",
                        [] if eq_begin > 0 else ["equity at start of year is not positive: ROE undefined"]))
    conc = equity.concentration(p.current_value_cents, h.net_worth_cents) if h.net_worth_cents else None
    eq_out = {"value": value_fig.to_dict(), "total_debt": debt_fig.to_dict(), "equity": eq.to_dict(), "lendable_equity": lend.to_dict(),
              "roe": roe_fig.to_dict(), "roe_rate": _rate_num(roe_rate.quantize(Decimal("0.000001"))) if roe_rate is not None else None,
              "concentration": conc.to_dict() if conc else None, "concentration_rate": _rate_num(conc.value) if conc else None,
              "appreciation_this_year": appr_fig.to_dict()}

    # ---------------- appreciation ----------------
    cagr = equity.cagr(p.purchase_price_cents, p.current_value_cents, p.purchase_date, as_of)
    proj_rows = []
    for n in range(0, horizon + 1):
        v = equity.projected_value(p.current_value_cents, appr, n, vin, appr_src).value_cents or 0
        d = sum(s.balance_at(date(year + n, 12, 31)) if s.rows and s.rows[0].year <= year + n else s.loan.balance_cents * (not s.loan.is_paid_off)
                for s in scheds)
        proj_rows.append({"year": year + n, "value_cents": v, "equity_cents": v - d, "debt_cents": d})
    proj_h = reg(equity.projected_value(p.current_value_cents, appr, horizon, vin, appr_src))
    appreciation = {"rate": _rate_num(appr), "rate_source": appr_src, "cagr_since_purchase": _rate_num(cagr.value),
                    "cagr": cagr.to_dict(), "projected": proj_rows, "projected_value_horizon": proj_h.to_dict()}

    # ---------------- depreciation ----------------
    dep = depreciation_for(p, year, mode)
    pclass = depreciation.property_class(p.property_type)
    method = "cost_seg" if p.cost_seg_study else METHOD_FOR_CLASS[pclass]
    reg(dep.basis)
    reg(dep.accumulated)
    reg(dep.current_year)
    dep_out = {
        "schedule": [{"year": r.year, "amount_cents": r.amount_cents, "method": method, "pct": float(r.pct)} for r in dep.schedule],
        "accumulated_cents": dep.accumulated.value_cents, "accumulated": dep.accumulated.to_dict(),
        "depreciable_basis": dep.basis.to_dict(), "annual": dep.current_year.to_dict(), "method": method, "mode": mode,
        "property_class": pclass, "land_pct_bounded": any("bounded" in n for n in dep.basis.notes),
        "sec1245_cents": dep.sec1245_cents, "outlier": dep.outlier, "notes": dep.notes,
        "accumulated_through_year": year - 1,
    }

    # ---------------- exit tax: sale at start of year+1 at current value, accumulated through `year` ----------------
    dep_sale = depreciation_for(p, year + 1, mode)
    sc, sc_src = rate_or_default(p.selling_cost_rate, "selling_cost_rate")
    sale = SaleInput(sale_price_cents=p.current_value_cents, selling_cost_rate=sc, loan_payoff_cents=sum(balances),
                     purchase_price_cents=p.purchase_price_cents, improvements_cents=p.improvements_cents,
                     accumulated_depreciation_cents=(dep_sale.accumulated.value_cents or 0) - dep_sale.sec1245_cents,
                     sec1245_cents=dep_sale.sec1245_cents, sale_date=date(year + 1, 1, 15),
                     former_residence_until=p.former_residence_until, sources={"sale_price_cents": vin})
    ex = compute_exit_tax(sale, household_tax(h, released=carryforward_release, tax_year=year + 1), blocked)
    if sc_src != "default":
        sel = ex.figures["exit_tax.selling_costs"]
        sel.inputs[1].source.type = "manual"
        sel.status = derive_status(sel.inputs, blocked)
    for f in ex.figures.values():
        reg(f)
    xf = ex.figures
    sale_price = reg(money("exit_tax.sale_price", Decimal(p.current_value_cents), [vin], "assumed sale price = current value",
                           blocked_keys=blocked))
    payoffs = reg(money("exit_tax.loan_payoffs", Decimal(sum(balances)), [Input.figure(debt_fig)], "sum of lien balances at sale"))
    exit_out = {
        "sale_price": sale_price.to_dict(), "selling_costs": xf["exit_tax.selling_costs"].to_dict(), "loan_payoffs": payoffs.to_dict(),
        **{k: xf[f"exit_tax.{k}"].to_dict() for k in ("net_before_tax", "adjusted_basis", "total_gain", "unrecaptured_1250",
                                                      "sec1245", "ltcg", "fed_1250", "fed_1245", "fed_ltcg", "niit", "state",
                                                      "net_proceeds", "sec121_excluded", "ordinary_taxable_other",
                                                      "amount_realized", "effective_rate_on_gain", "released_loss_benefit")},
        "exit_tax_total": xf["exit_tax.total"].to_dict(),
        "stacking_notes": ex.stack.notes + [
            "Order: ordinary income (wages + other - standard deduction - released suspended losses) fills the brackets first; "
            "Sec 1245 recapture stacks next at full ordinary rates; unrecaptured Sec 1250 gain stacks on top at min(bracket, 25%); "
            "the remaining long-term gain lands last at 0/15/20% by where it falls."],
        "layers_1250": [x.to_dict() for x in ex.stack.layers_1250], "layers_ltcg": [x.to_dict() for x in ex.stack.layers_ltcg],
        "findings": ex.findings, "sale_assumed_on": sale.sale_date.isoformat() if sale.sale_date else None,
        "suspended_losses_released_cents": carryforward_release,
    }

    # ---------------- loans ----------------
    loans_out = []
    for i, (ln, s) in enumerate(zip(p.loans, scheds, strict=True)):
        rows = []
        for y in range(year, year + horizon + 1):
            a = loan_annual_for(s, y)
            yr_rows = [r for r in s.rows if r.year == y]
            marker = None
            if any(r.phase == "balloon_due" for r in yr_rows):
                marker = "balloon"
            elif ln.arm_reset_date and ln.arm_reset_date.year == y:
                marker = "arm_reset"
            elif yr_rows and yr_rows[-1].phase in ("interest_only", "heloc"):
                marker = "io"
            elif ln.maturity_date and ln.maturity_date.year == y:
                marker = "maturity"
            rows.append({"year": y, "principal_cents": a["principal_cents"], "interest_cents": a["interest_cents"],
                         "debt_service_cents": a["debt_service_cents"], "balance_end_cents": a["balance_end_cents"],
                         "rate": float(yr_rows[-1].rate) if yr_rows else _rate_num(ln.rate), "marker": marker})
        la = loan_annual_for(s, year)
        ads = money(f"loans[{i}].annual_debt_service", Decimal(la["debt_service_cents"]),
                    [Input.of("schedule", f"{len(s.rows)} monthly rows", src="figure", ref=f"loans.schedule[{ln.lender or i}]"),
                     Input.of("rate", ln.rate), Input.of("balance_cents", ln.balance_cents, src="document", ref="mortgage statement")],
                    "sum of the monthly payments falling in the year", s.notes)
        bal = money(f"loans[{i}].balance_at_year_end", Decimal(balances[i]), [Input.of("balance_cents", ln.balance_cents, src="document",
                                                                                     ref=f"statement {ln.balance_as_of.isoformat()}")],
                    f"amortized balance at {as_of.isoformat()}")
        ldscr = loans.dscr(noi_fig.value_cents or 0, annual["debt_service_cents"], [Input.figure(noi_fig), Input.figure(debt_service)])
        loans_out.append({"loan_id": ln.id, "annual": rows, "dscr": ldscr.to_dict(), "annual_debt_service": ads.to_dict(),
                          "balance_at_year_end": bal.to_dict(), "months": [r.to_dict() for r in s.rows],
                          "months_total": len(s.rows), "notes": s.notes})

    return {
        "property_id": p.id, "year": year, "horizon": horizon, "notes": notes,
        "cash_flow": cf, "equity": eq_out, "appreciation": appreciation, "depreciation": dep_out, "exit_tax": exit_out,
        "loans": loans_out,
        "_figs": figs,
        "_net_cents": net_cents, "_noi_cents": noi_fig.value_cents, "_line21_cents": line21.value_cents, "_dscr": dscr.value,
        "_equity_cents": eq.value_cents, "_roe": str(roe_rate) if roe_rate is not None else None,
        "_exit_tax_cents": ex.total_cents, "_dep_outlier": dep.outlier, "_balances": balances, "_annual_debt": annual,
        "_concentration": conc.value if conc else None, "_land_bounded": dep_out["land_pct_bounded"],
        "_findings": ex.findings,
    }
