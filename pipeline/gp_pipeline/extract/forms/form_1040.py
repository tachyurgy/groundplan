"""Form 1040 pages 1-2: filing status, home state, and the income/tax lines the planner uses."""

from __future__ import annotations

import re

from gp_pipeline.extract.forms.base import (
    LineSpec,
    find_anchors,
    is_checked,
    make_field,
    pick_money,
    value_tokens,
    zone_span,
)
from gp_pipeline.extract.zones import zone_words
from gp_pipeline.models import ExtractedField, Page, ParsedDocument

ZONES = {"M": (397.0, 482.0), "R": (497.0, 590.0)}

PAGE1 = [
    LineSpec("1a", "Total amount from Form(s) W-2, box 1", "line1a.wages", "R"),
    LineSpec("1b", "Household employee wages not reported", None, "R", "b"),
    LineSpec("1c", "Tip income not reported on line 1a", None, "R", "c"),
    LineSpec("1d", "Medicaid waiver payments not reported", None, "R", "d"),
    LineSpec("1e", "Taxable dependent care benefits", None, "R", "e"),
    LineSpec("1f", "Employer-provided adoption benefits", None, "R", "f"),
    LineSpec("1g", "Wages from Form 8919, line 6", None, "R", "g"),
    LineSpec("1h", "Other earned income", None, "R", "h"),
    LineSpec("1i", "Nontaxable combat pay election", None, "M", "i"),
    LineSpec("1z", "Add lines 1a through 1h", "line1z.total_wages", "R", "z"),
    LineSpec("2a", "Tax-exempt interest", "line2a.tax_exempt_interest", "M"),
    LineSpec("2b", "Taxable interest", "line2b.taxable_interest", "R"),
    LineSpec("3a", "Qualified dividends", "line3a.qualified_dividends", "M"),
    LineSpec("3b", "Ordinary dividends", "line3b.ordinary_dividends", "R"),
    LineSpec("4a", "IRA distributions", None, "M"),
    LineSpec("4b", "Taxable amount", None, "R"),
    LineSpec("5a", "Pensions and annuities", None, "M"),
    LineSpec("5b", "Taxable amount", None, "R"),
    LineSpec("6a", "Social security benefits", None, "M"),
    LineSpec("6b", "Taxable amount", None, "R"),
    LineSpec("7", "Capital gain or (loss)", "line7.capital_gain", "R"),
    LineSpec("8", "Additional income from Schedule 1, line 10", "line8.schedule_1_income", "R"),
    LineSpec("9", "Add lines 1z, 2b, 3b, 4b, 5b, 6b, 7, and 8", "line9.total_income", "R"),
    LineSpec("10", "Adjustments to income from Schedule 1", "line10.adjustments", "R"),
    LineSpec("11", "Subtract line 10 from line 9. This is your adjusted gross income", "line11.agi", "R"),
    LineSpec("12", "Standard deduction or itemized deductions", "line12.deduction", "R"),
    LineSpec("13", "Qualified business income deduction", "line13.qbi_deduction", "R"),
    LineSpec("14", "Add lines 12 and 13", "line14.total_deductions", "R"),
    LineSpec("15", "Subtract line 14 from line 11", "line15.taxable_income", "R"),
]
PAGE2 = [
    LineSpec("16", "Tax (see instructions)", "line16.tax", "R"),
    LineSpec("17", "Amount from Schedule 2, line 3", None, "R"),
    LineSpec("18", "Add lines 16 and 17", "line18.tax_plus_sch2", "R"),
    LineSpec("19", "Child tax credit or credit for other dependents", None, "R"),
    LineSpec("20", "Amount from Schedule 3, line 8", None, "R"),
    LineSpec("21", "Add lines 19 and 20", None, "R"),
    LineSpec("22", "Subtract line 21 from line 18", "line22.tax_after_credits", "R"),
    LineSpec("23", "Other taxes, including self-employment tax", None, "R"),
    LineSpec("24", "Add lines 22 and 23. This is your total tax", "line24.total_tax", "R"),
    LineSpec("25", "Federal income tax withheld from", None, "R"),
    LineSpec("25a", "Form(s) W-2", "line25a.w2_withholding", "M", "a"),
    LineSpec("25b", "Form(s) 1099", None, "M", "b"),
    LineSpec("25c", "Other forms (see instructions)", None, "M", "c"),
    LineSpec("25d", "Add lines 25a through 25c", "line25d.total_withholding", "R", "d"),
    LineSpec("26", "estimated tax payments and amount applied from", "line26.estimated_payments", "R"),
    LineSpec("32", "Add lines 27, 28, 29, and 31", None, "R"),
    LineSpec("33", "Add lines 25d, 26, and 32. These are your total payments", "line33.total_payments", "R"),
    LineSpec("34", "If line 33 is more than line 24, subtract line 24 from line 33", "line34.overpaid", "R"),
    LineSpec("35a", "Amount of line 34 you want refunded to you", "line35a.refund", "R"),
    LineSpec("37", "Subtract line 33 from line 24. This is the amount you owe", "line37.amount_owed", "R"),
]
STATUSES = [("single", "Single"), ("mfj", "Married filing jointly"), ("mfs", "Married filing separately"),
            ("hoh", "Head of household"), ("qss", "Qualifying surviving spouse")]


def _lines(doc: ParsedDocument, page: Page, specs: list[LineSpec]) -> list[ExtractedField]:
    anchors = find_anchors(page, specs)
    out = []
    spans = {z: zone_span(anchors, [s.line for s in specs if s.zone == z]) for z in ZONES}
    for ln, anc in anchors.items():
        if not anc.spec.field:
            continue
        top, bottom = spans[anc.spec.zone]
        toks = value_tokens(page, ZONES[anc.spec.zone], anc.row.cy, top, bottom)
        v, ws, corr = pick_money(toks, exclude={ln, (anc.spec.display or ln)})
        if v is not None:
            out.append(make_field(page, doc.filename, f"form_1040.{anc.spec.field}", v, "cents", ws, corrected=corr))
    return out


def _header(doc: ParsedDocument, page: Page) -> list[ExtractedField]:
    out = []
    specs = [LineSpec(code, label) for code, label in STATUSES]
    anchors = find_anchors(page, [LineSpec("fs", "Filing Status")] + specs, accept=0.7)
    # status labels sit at x~132, so find_anchors' label_text (x>=52) sees them
    for code, _ in STATUSES:
        if code in anchors:
            cy = anchors[code].row.cy
            if is_checked(page, 119.0, cy - 5.0, 128.5, cy + 4.0):
                w = [x for x in anchors[code].row.words if x.x0 > 125][:3]
                out.append(make_field(page, doc.filename, "form_1040.filing_status", code, "text", w,
                                      raw_text="[X] " + " ".join(x.text for x in w)))
                break
    city = find_anchors(page, [LineSpec("city", "City, town, or post office")], label_x_min=0)
    if "city" in city:
        cy = city["city"].row.cy
        ws = zone_words(page, 295.0, cy + 4, 345.0, cy + 15, psm=7)
        ws = [w for w in ws if re.fullmatch(r"[A-Z]{2}", w.text)]
        if ws:
            out.append(make_field(page, doc.filename, "form_1040.home_state", ws[0].text, "text", ws[:1]))
    home = find_anchors(page, [LineSpec("home", "Home address (number and street)")], label_x_min=0)
    if "home" in home:
        cy = home["home"].row.cy
        ws = zone_words(page, 34.0, cy + 4, 375.0, cy + 15, psm=7)
        if ws:
            out.append(make_field(page, doc.filename, "form_1040.home_address", " ".join(w.text for w in ws), "text",
                                  ws))
    return out


def extract(doc: ParsedDocument) -> list[ExtractedField]:
    out: list[ExtractedField] = []
    if doc.pages:
        out += _header(doc, doc.pages[0])
        out += _lines(doc, doc.pages[0], PAGE1)
    if len(doc.pages) > 1:
        out += _lines(doc, doc.pages[1], PAGE2)
    return out
