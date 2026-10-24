"""Per-property Fact Sheet mappings for planning platforms.

These are Groundplan's BEST-EFFORT mappings onto the field labels each platform shows advisors for a real-estate
asset and its mortgage. They are not an official integration, carry no vendor endorsement, and must be checked
against the platform's current import template before use.
"""

from __future__ import annotations

import csv
import io

PLATFORMS = {
    "emoney": "eMoney Advisor (best-effort mapping)",
    "rightcapital": "RightCapital (best-effort mapping)",
    "mgp": "MoneyGuidePro (best-effort mapping)",
    "json": "Groundplan native (JSON)",
    "csv": "Groundplan native (CSV)",
}

# groundplan_key -> platform field label
MAPPINGS = {
    "emoney": [
        ("property.nickname", "Real Estate Asset: Description"),
        ("property.property_type", "Real Estate Asset: Type"),
        ("equity.value", "Real Estate Asset: Market Value"),
        ("exit_tax.adjusted_basis", "Real Estate Asset: Cost Basis"),
        ("equity.total_debt", "Real Estate Asset: Mortgage Liability"),
        ("loan.rate", "Mortgage Liability: Interest Rate"),
        ("loan.monthly_payment", "Mortgage Liability: Monthly Payment"),
        ("cash_flow.noi", "Real Estate Asset: Net Rental Income"),
        ("cash_flow.net_annual", "Real Estate Asset: Net Cash Flow (after debt service)"),
        ("equity.net", "Real Estate Asset: Net Equity"),
        ("appreciation.rate", "Real Estate Asset: Growth Rate"),
    ],
    "rightcapital": [
        ("property.nickname", "Property: Name"),
        ("property.property_type", "Property: Type"),
        ("equity.value", "Property: Current Value"),
        ("exit_tax.adjusted_basis", "Property: Cost Basis"),
        ("cash_flow.gross_rent", "Property: Annual Rental Income"),
        ("cash_flow.operating_expenses", "Property: Annual Expenses"),
        ("equity.total_debt", "Property: Mortgage"),
        ("loan.rate", "Mortgage: Interest Rate"),
        ("loan.monthly_payment", "Mortgage: Monthly Payment"),
        ("appreciation.rate", "Property: Appreciation Rate"),
        ("equity.net", "Property: Equity"),
    ],
    "mgp": [
        ("property.nickname", "Asset Type: Real Estate - Description"),
        ("equity.value", "Asset Type: Real Estate - Value"),
        ("equity.total_debt", "Asset Type: Real Estate - Debt"),
        ("cash_flow.noi", "Asset Type: Real Estate - Income"),
        ("cash_flow.operating_expenses", "Asset Type: Real Estate - Expenses"),
        ("exit_tax.adjusted_basis", "Asset Type: Real Estate - Cost Basis"),
        ("appreciation.rate", "Asset Type: Real Estate - Growth Rate"),
        ("equity.net", "Asset Type: Real Estate - Net Equity"),
    ],
}
NATIVE = [k for k, _ in MAPPINGS["emoney"]] + ["cash_flow.gross_rent", "cash_flow.operating_expenses", "exit_tax.total",
                                                "exit_tax.net_proceeds", "equity.lendable"]


def _values(prop: dict, an: dict, loans: list[dict]) -> dict[str, tuple]:
    """groundplan_key -> (value_cents | None, value_text | None, status, note)."""
    cf, eq, ex = an["cash_flow"], an["equity"], an["exit_tax"]
    active = [ln for ln in loans if not ln["is_paid_off"]]
    first = sorted(active, key=lambda x: x["lien_position"])[0] if active else None
    pay = sum(ln.get("monthly_payment_cents") or 0 for ln in active)
    v = {
        "property.nickname": (None, prop["nickname"], "confirmed", prop.get("address_line1")),
        "property.property_type": (None, prop["property_type"], "confirmed", None),
        "equity.value": (eq["value"]["value_cents"], None, eq["value"]["status"], f"value source: {prop['value_source']}"),
        "equity.total_debt": (eq["total_debt"]["value_cents"], None, eq["total_debt"]["status"],
                              f"{len(active)} active lien(s) summed" if len(active) > 1 else None),
        "equity.net": (eq["equity"]["value_cents"], None, eq["equity"]["status"], None),
        "equity.lendable": (eq["lendable_equity"]["value_cents"], None, eq["lendable_equity"]["status"], "70% LTV"),
        "exit_tax.adjusted_basis": (ex["adjusted_basis"]["value_cents"], None, ex["adjusted_basis"]["status"],
                                    "adjusted basis after depreciation (allowed or allowable)"),
        "exit_tax.total": (ex["exit_tax_total"]["value_cents"], None, ex["exit_tax_total"]["status"], None),
        "exit_tax.net_proceeds": (ex["net_proceeds"]["value_cents"], None, ex["net_proceeds"]["status"], None),
        "cash_flow.gross_rent": (cf["gross_rent"]["value_cents"], None, cf["gross_rent"]["status"], None),
        "cash_flow.operating_expenses": (cf["operating_expenses"]["value_cents"], None, cf["operating_expenses"]["status"],
                                         "excludes mortgage interest and depreciation"),
        "cash_flow.noi": (cf["noi"]["value_cents"], None, cf["noi"]["status"], "NOI before debt service"),
        "cash_flow.net_annual": (cf["net_cash_flow"]["value_cents"], None, cf["net_cash_flow"]["status"], None),
        "loan.rate": (None, f"{first['rate'] * 100:.3f}%" if first else None, "confirmed",
                      f"first lien ({first['lender']})" if first else "no active loan"),
        "loan.monthly_payment": (pay or None, None, "confirmed", "sum of statement payments" if pay else "no payment on file"),
        "appreciation.rate": (None, f"{an['appreciation']['rate'] * 100:.2f}%", "estimated" if an["appreciation"]["rate_source"] == "default" else "confirmed",
                              "assumption"),
    }
    return v


def build(prop: dict, an: dict, loans: list[dict], fmt: str) -> dict:
    vals = _values(prop, an, loans)
    pairs = MAPPINGS.get(fmt) or [(k, k) for k in NATIVE]
    rows = []
    for key, label in pairs:
        cents, text, status, note = vals[key]
        rows.append({"groundplan_key": key, "platform_field": label, "value_cents": cents, "value_text": text, "status": status,
                     "note": note})
    return {"property_id": prop["id"], "format": fmt, "platform_label": PLATFORMS[fmt], "rows": rows,
            "as_of": f"{an['year']}-12-31",
            "disclaimer": "Best-effort field mapping by Groundplan; not an official integration. Verify against the platform's "
                          "current import template."}


def to_csv(sheet: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["groundplan_key", "platform_field", "value_dollars", "value_text", "status", "note"])
    for r in sheet["rows"]:
        w.writerow([r["groundplan_key"], r["platform_field"], f"{r['value_cents'] / 100:.2f}" if r["value_cents"] is not None else "",
                    r["value_text"] or "", r["status"], r["note"] or ""])
    return buf.getvalue()
