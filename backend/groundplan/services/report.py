"""Client-ready portfolio report (reportlab). Generated on the fly per request, never stored."""

from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

INK = colors.HexColor("#1f2933")
MUTED = colors.HexColor("#616e7c")
RULE = colors.HexColor("#d9dee4")
CHIP = {"confirmed": colors.HexColor("#2f6f4f"), "estimated": colors.HexColor("#8a6d1f"), "blocked": colors.HexColor("#9b2c2c")}


def usd(c: int | None) -> str:
    if c is None:
        return "n/a"
    return f"{'-' if c < 0 else ''}${abs(c) / 100:,.0f}"


def _styles():
    ss = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold", fontSize=18, textColor=INK, spaceAfter=4),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, textColor=INK, spaceBefore=10,
                             spaceAfter=4),
        "body": ParagraphStyle("body", parent=ss["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK),
        "muted": ParagraphStyle("muted", parent=ss["BodyText"], fontName="Helvetica", fontSize=8, leading=10.5, textColor=MUTED),
        "num": ParagraphStyle("num", parent=ss["BodyText"], fontName="Courier", fontSize=9, alignment=TA_RIGHT),
    }


def _table(rows, widths, header=True):
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    st = [("FONT", (0, 0), (-1, -1), "Helvetica", 8.5), ("TEXTCOLOR", (0, 0), (-1, -1), INK),
          ("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("FONT", (1, 1 if header else 0), (-1, -1), "Courier", 8.5),
          ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if header:
        st += [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
               ("LINEBELOW", (0, 0), (-1, 0), 0.75, INK)]
    t.setStyle(TableStyle(st))
    return t


def _status(fig: dict) -> str:
    return fig.get("status", "confirmed")


def render(dash: dict, analyses: list[tuple[dict, dict]], advisor: dict | None = None) -> bytes:
    """`dash` = services.portfolio.dashboard(); `analyses` = [(property_dict, analysis)] for the detail pages."""
    st = _styles()
    buf = io.BytesIO()
    h = dash["household"]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(0.75 * inch, 0.5 * inch, f"{h['name']}  |  prepared {date.today().isoformat()}  |  Groundplan")
        canvas.drawRightString(7.75 * inch, 0.5 * inch, f"page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=0.75 * inch, rightMargin=0.75 * inch, topMargin=0.7 * inch,
                            bottomMargin=0.75 * inch, title=f"{h['name']} real estate review", author=(advisor or {}).get("firm_name", ""))
    out = [Paragraph(f"{h['name']}: real estate portfolio review", st["h1"]),
           Paragraph(f"Tax year {h['tax_year_latest']} &middot; {h['state']} &middot; filing status {h['filing_status'].upper()} "
                     f"&middot; goal: {h['goal'] or 'not stated'}", st["muted"]), Spacer(1, 8)]
    met = dash["metrics"]
    rows = [["Measure", "Amount", "Status"]]
    for k in ("total_value", "total_debt", "total_equity", "net_cash_flow", "exit_tax_total", "suspended_losses"):
        f = met[k]
        rows.append([f.get("label", k), usd(f["value_cents"]), _status(f)])
    out += [Paragraph("Summary", st["h2"]), _table(rows, [3.3 * inch, 1.6 * inch, 1.2 * inch])]
    out += [Paragraph("Summary in plain English", st["h2"])]
    for para in dash["narrative"]["text"].split("\n\n"):
        out += [Paragraph(para, st["body"]), Spacer(1, 4)]
    out += [Paragraph(f"Narrative source: {dash['narrative']['provider']} (every number is drawn from the computed figures).",
                      st["muted"])]
    if dash["observations"]:
        out += [Paragraph("Observations", st["h2"])]
        obs_rows = [["", "Observation"]] + [[o["level"].upper(), Paragraph(o["message"], st["body"])] for o in dash["observations"]]
        t = _table(obs_rows, [0.7 * inch, 5.8 * inch])
        t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "LEFT"), ("FONT", (0, 1), (0, -1), "Helvetica-Bold", 7)]))
        out.append(t)
    rows = [["Property", "Value", "Debt", "Equity", "Net cash flow", "Exit tax today"]]
    for c in dash["properties"]:
        p = c["property"]
        rows.append([p["nickname"], usd(c["value"]["value_cents"]), usd(c["value"]["value_cents"] - c["equity"]["value_cents"]),
                     usd(c["equity"]["value_cents"]), usd(c["net_cash_flow"]["value_cents"]) + ("*" if _status(c["net_cash_flow"]) != "confirmed" else ""),
                     usd(c["exit_tax"]["value_cents"])])
    out += [Paragraph("Properties", st["h2"]), _table(rows, [1.6 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch, 1.0 * inch]),
            Paragraph("* estimated or blocked: depends on a default assumption, an estimated value, or an unresolved document conflict.",
                      st["muted"])]
    for p, an in analyses:
        out.append(PageBreak())
        ex = an["exit_tax"]
        cf = an["cash_flow"]
        eq = an["equity"]
        out += [Paragraph(f"{p['nickname']}: {p['address_line1']}, {p['city']}", st["h1"]),
                Paragraph(f"{p['property_type']} &middot; {p['units']} unit(s) &middot; bought {p['purchase_date']} for "
                          f"{usd(p['purchase_price_cents'])} &middot; value {usd(p['current_value_cents'])} ({p['value_source']})", st["muted"])]
        rows = [["Cash flow (" + str(an["year"]) + ")", "Amount", "Status"]]
        for k, lbl in (("gross_rent", "Gross rent"), ("vacancy_loss", "Vacancy"), ("operating_expenses", "Operating expenses"),
                       ("capex_reserve", "Capital reserve"), ("noi", "Net operating income"), ("debt_service", "Debt service"),
                       ("net_cash_flow", "Net cash flow")):
            rows.append([lbl, usd(cf[k]["value_cents"]), _status(cf[k])])
        br = cf["schedule_e_bridge"]
        rows2 = [["Schedule E bridge", "Amount", ""], ["Line 21 (income or loss)", usd(br["line21"]["value_cents"]), ""],
                 ["+ Line 18 depreciation", usd(br["line18_depreciation"]["value_cents"]), ""],
                 ["- Principal paid", usd(br["principal_paid"]["value_cents"]), ""],
                 ["- Capital improvements", usd(br["capital_improvements_paid"]["value_cents"]), ""],
                 ["= Cash flow from the return", usd(br["cash_flow_from_return"]["value_cents"]), ""],
                 ["Difference vs engine", usd(br["delta_vs_engine"]["value_cents"]), ""]]
        out += [Paragraph("Cash flow", st["h2"]), _table(rows, [3.3 * inch, 1.6 * inch, 1.2 * inch]), Spacer(1, 6),
                _table(rows2, [3.3 * inch, 1.6 * inch, 1.2 * inch])]
        rows = [["Equity", "Amount", "Status"], ["Value", usd(eq["value"]["value_cents"]), _status(eq["value"])],
                ["Debt", usd(eq["total_debt"]["value_cents"]), _status(eq["total_debt"])],
                ["Equity", usd(eq["equity"]["value_cents"]), _status(eq["equity"])],
                ["Lendable equity (70% LTV)", usd(eq["lendable_equity"]["value_cents"]), _status(eq["lendable_equity"])],
                ["Return on equity", f"{eq['roe_rate'] * 100:.1f}%" if eq["roe_rate"] is not None else "n/a", _status(eq["roe"])]]
        out += [Paragraph("Equity", st["h2"]), _table(rows, [3.3 * inch, 1.6 * inch, 1.2 * inch])]
        rows = [["If sold at today's value", "Amount", "Status"]]
        for k, lbl in (("sale_price", "Sale price"), ("selling_costs", "Selling costs"), ("loan_payoffs", "Loan payoffs"),
                       ("net_before_tax", "Net before tax"), ("adjusted_basis", "Adjusted basis"), ("total_gain", "Total gain"),
                       ("unrecaptured_1250", "Unrecaptured Sec 1250 gain"), ("ltcg", "Long-term capital gain"),
                       ("fed_1250", "Federal tax on 1250 gain (max 25%)"), ("fed_1245", "Federal tax on 1245 recapture"),
                       ("fed_ltcg", "Federal capital gains tax"), ("niit", "Net investment income tax"), ("state", "State tax"),
                       ("exit_tax_total", "Total exit tax"), ("net_proceeds", "Net proceeds after tax")):
            rows.append([lbl, usd(ex[k]["value_cents"]), _status(ex[k])])
        out += [KeepTogether([Paragraph("Exit tax", st["h2"]), _table(rows, [3.3 * inch, 1.6 * inch, 1.2 * inch])])]
        for n in ex["stacking_notes"]:
            out.append(Paragraph(n, st["muted"]))
        if an.get("observations"):
            out += [Paragraph("Observations", st["h2"])] + [Paragraph(f"&bull; {o['message']}", st["body"]) for o in an["observations"]]
    out += [Spacer(1, 14), Paragraph(
        "This report is an analytical illustration for discussion with your advisor. It is not tax or legal advice. Tax figures use "
        "published federal brackets and a simplified state table and must be verified by a CPA before any transaction. "
        "Comparisons show trade-offs; no path is recommended by this report.", st["muted"])]
    doc.build(out, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
