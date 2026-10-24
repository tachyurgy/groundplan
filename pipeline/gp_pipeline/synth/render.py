"""Render the household's documents as text-layer PDFs that resemble the IRS forms.

Line numbers and labels are the real ones from the 2024/2025 IRS forms (Form 1040, Schedule E
Part I, Form 4562 Part III/IV, Form 8582 Parts I-III + Worksheets 1 and 5). Layout is close in
spirit (line numbers on the left, labels, right-aligned values in boxes), not pixel-identical.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from gp_pipeline.finance import year_totals
from gp_pipeline.synth.canvas import GoldField, Sheet, money, money_cents
from gp_pipeline.synth.household import (
    PROPERTY_TYPE_CODES,
    SCHEDULE_E_EXPENSE_LINES,
    Household,
    Loan,
    Property,
)

SE_FIELD = {
    3: "line3.rents",
    4: "line4.royalties",
    5: "line5.advertising",
    6: "line6.auto_travel",
    7: "line7.cleaning_maintenance",
    8: "line8.commissions",
    9: "line9.insurance",
    10: "line10.legal_professional",
    11: "line11.management_fees",
    12: "line12.mortgage_interest",
    13: "line13.other_interest",
    14: "line14.repairs",
    15: "line15.supplies",
    16: "line16.taxes",
    17: "line17.utilities",
    18: "line18.depreciation",
    19: "line19.other",
    20: "line20.total_expenses",
    21: "line21.income_or_loss",
    22: "line22.deductible_loss",
}

COLS = {"A": (336, 416), "B": (420, 500), "C": (504, 584)}


def _names(h: Household) -> str:
    return f"{h.taxpayer} & {h.spouse}"


# ============================================================================ Schedule E


def render_schedule_e(h: Household, year: int, path: str) -> dict:
    props = h.properties_in(year)
    pages = [props[i : i + 3] for i in range(0, len(props), 3)]
    s = Sheet(path, "schedule_e", year, title=f"Schedule E (Form 1040) {year}")
    for pi, group in enumerate(pages):
        if pi:
            s.newpage()
        _schedule_e_page(s, h, year, group, totals=(pi == 0), continuation=pi > 0)
    return s.save()


def _schedule_e_page(s: Sheet, h: Household, year: int, props: list[Property], totals: bool,
                     continuation: bool) -> None:
    hy = h.years[year]
    s.t(36, 44, "SCHEDULE E", "Helvetica-Bold", 11)
    s.t(36, 55, "(Form 1040)", "Helvetica", 8)
    s.t(36, 68, "Department of the Treasury", "Helvetica", 6)
    s.t(36, 75, "Internal Revenue Service", "Helvetica", 6)
    s.ct(306, 46, "Supplemental Income and Loss", "Helvetica-Bold", 12)
    s.ct(306, 57, "(From rental real estate, royalties, partnerships, S corporations, estates, trusts, REMICs, etc.)",
         "Helvetica", 6.5)
    s.ct(306, 65, "Attach to Form 1040, 1040-SR, 1040-SS, 1040-NR, or 1041.", "Helvetica", 6.5)
    s.ct(306, 73, "Go to www.irs.gov/ScheduleE for instructions and the latest information.", "Helvetica", 6.5)
    s.t(500, 42, "OMB No. 1545-0074", "Helvetica", 6)
    s.t(506, 64, str(year), "Helvetica-Bold", 20)
    s.t(500, 77, "Attachment Sequence No. 13", "Helvetica", 6)
    s.hline(36, 584, 82, gray=0, width=1.0)
    s.t(36, 91, "Name(s) shown on return", "Helvetica", 6)
    s.t(36, 101, _names(h), "Courier-Bold", 8.6)
    s.t(470, 91, "Your identifying number", "Helvetica", 6)
    s.t(470, 101, h.ssn_masked, "Courier-Bold", 8.6)
    if continuation:
        s.t(300, 101, "(continuation - additional properties)", "Helvetica-Oblique", 6.5)
    s.hline(36, 584, 105)
    s.bar(116, "Part I", "Income or Loss From Rental Real Estate and Royalties")
    s.t(86, 127, "Note: If you are in the business of renting personal property, use Schedule C. "
        "See instructions. If you are an individual, report farm rental income or loss from Form 4835 on page 2, line 40.",
        "Helvetica", 5.6)
    s.t(38, 138, "A", "Helvetica-Bold", 7)
    s.t(62, 138, f"Did you make any payments in {year} that would require you to file Form(s) 1099? See instructions",
        "Helvetica", 6.6)
    s.checkbox(500, 138, False)
    s.t(510, 138, "Yes", "Helvetica", 6.6)
    s.checkbox(535, 138, True)
    s.t(545, 138, "No", "Helvetica", 6.6)
    s.t(38, 148, "B", "Helvetica-Bold", 7)
    s.t(62, 148, "If \"Yes,\" did you or will you file required Form(s) 1099?", "Helvetica", 6.6)
    s.checkbox(500, 148, False)
    s.t(510, 148, "Yes", "Helvetica", 6.6)
    s.checkbox(535, 148, False)
    s.t(545, 148, "No", "Helvetica", 6.6)
    s.hline(36, 584, 152)

    # ---- 1a addresses
    y = 162
    s.t(38, y, "1a", "Helvetica-Bold", 7)
    s.t(62, y, "Physical address of each property (street, city, state, ZIP code)", "Helvetica", 6.6)
    letters = ["A", "B", "C"]
    for i, L in enumerate(letters):
        yy = y + 13 + i * 13
        s.t(48, yy, L, "Helvetica-Bold", 7)
        s.hline(58, 584, yy + 3)
        if i < len(props):
            p = props[i]
            addr = p.address_by_year[year]
            s.val(66, yy, addr, "schedule_e.line1a.address", addr, "text", prop=p.key, address=addr, align="left")
    # ---- 1b type + 2 days
    y = 214
    s.t(38, y, "1b", "Helvetica-Bold", 7)
    s.t(62, y, "Type of Property", "Helvetica", 6.6)
    s.t(62, y + 8, "(from list below)", "Helvetica", 6.6)
    s.t(160, y, "2", "Helvetica-Bold", 7)
    s.wrap(172, y, "For each rental real estate property listed above, report the number of fair rental and personal "
           "use days. Check the QJV box only if you meet the requirements to file as a qualified joint venture. "
           "See instructions.", 200)
    s.ct(430, y + 6, "Fair Rental Days", "Helvetica-Bold", 6.6)
    s.ct(500, y + 6, "Personal Use Days", "Helvetica-Bold", 6.6)
    s.ct(560, y + 6, "QJV", "Helvetica-Bold", 6.6)
    for i, L in enumerate(letters):
        yy = y + 30 + i * 13
        s.t(48, yy, L, "Helvetica-Bold", 7)
        s.t(150, yy, L, "Helvetica-Bold", 7)
        s.hline(58, 584, yy + 3)
        s.checkbox(556, yy, False)
        if i < len(props):
            p = props[i]
            py = p.years[year]
            addr = p.address_by_year[year]
            s.val(110, yy, str(p.type_code), "schedule_e.line1b.type", p.type_code, "int", prop=p.key, address=addr)
            s.val(452, yy, str(py.fair_rental_days), "schedule_e.line2.fair_rental_days", py.fair_rental_days, "int",
                  prop=p.key, address=addr)
            s.val(522, yy, str(py.personal_use_days), "schedule_e.line2.personal_use_days", py.personal_use_days,
                  "int", prop=p.key, address=addr)
    y = 290
    s.t(62, y, "Type of Property:", "Helvetica-Bold", 6.6)
    tl = [(1, 3, 5, 7), (2, 4, 6, 8)]
    for r, row in enumerate(tl):
        for c_i, code in enumerate(row):
            s.t(70 + c_i * 128, y + 9 + r * 8, f"{code} {PROPERTY_TYPE_CODES[code][0]}", "Helvetica", 6.3)
    s.hline(36, 584, y + 22)

    # ---- column header
    y = 324
    s.t(62, y, "Income:", "Helvetica-Bold", 7)
    s.t(270, y, "Properties:", "Helvetica-Bold", 7)
    for L, (x0, x1) in COLS.items():
        s.ct((x0 + x1) / 2, y, L, "Helvetica-Bold", 8)
    s.hline(36, 584, y + 3)

    def row(y: float, num: str, label: str, line: int | None, getter, wide: bool = False) -> float:
        s.t(38, y, num, "Helvetica-Bold", 7)
        nlines = s.wrap(62, y, label, 268)
        for i, p in enumerate(props):
            L = letters[i]
            v = getter(p)
            if v is None or v == 0:
                continue
            addr = p.address_by_year[year]
            s.val(COLS[L][1] - 4, y, money(v), f"schedule_e.{SE_FIELD[line]}", v * 100, "cents", prop=p.key,
                  address=addr)
        step = 13 if nlines == 1 else 6 + 7.6 * nlines
        s.hline(36, 584, y + step - 9.5)
        for x0, _ in COLS.values():
            s.vline(x0 - 2, y - 9.5, y + step - 9.5)
        return y + step

    y = 337
    y = row(y, "3", "Rents received", 3, lambda p: p.years[year].rents)
    y = row(y, "4", "Royalties received", 4, lambda p: 0)
    s.t(62, y, "Expenses:", "Helvetica-Bold", 7)
    y += 11
    for line, label in SCHEDULE_E_EXPENSE_LINES:
        lbl = label
        if line == 19:
            other = next((p.years[year].other_label for p in props if p.years[year].other_label), "")
            lbl = f"Other (list) {other}" if other else label
        y = row(y, str(line), lbl, line, lambda p, ln=line: p.years[year].expenses.get(ln, 0))
    y = row(y, "20", "Total expenses. Add lines 5 through 19", 20, lambda p: p.years[year].total_expenses)
    y = row(y, "21", "Subtract line 20 from line 3 (rents) and/or 4 (royalties). If result is a (loss), see "
            "instructions to find out if you must file Form 6198", 21, lambda p: p.years[year].net)
    y = row(y, "22", "Deductible rental real estate loss after limitation, if any, on Form 8582 (see instructions)",
            22, lambda p: p.years[year].allowed_loss)

    if not totals:
        s.t(62, y + 4, "Lines 23a through 26 are completed on the first page only.", "Helvetica-Oblique", 6.5)
        return
    tot = hy.schedule_e_totals
    trows = [
        ("23a", "Total of all amounts reported on line 3 for all rental properties", "line23a.total_rents", "inner"),
        ("b", "Total of all amounts reported on line 4 for all royalty properties", "line23b.total_royalties", "inner"),
        ("c", "Total of all amounts reported on line 12 for all properties", "line23c.total_mortgage_interest",
         "inner"),
        ("d", "Total of all amounts reported on line 18 for all properties", "line23d.total_depreciation", "inner"),
        ("e", "Total of all amounts reported on line 20 for all properties", "line23e.total_expenses", "inner"),
        ("24", "Income. Add positive amounts shown on line 21. Do not include any losses", "line24.income", "outer"),
        ("25", "Losses. Add royalty losses from line 21 and rental real estate losses from line 22. "
         "Enter total losses here", "line25.losses", "outer"),
        ("26", "Total rental real estate and royalty income or (loss). Combine lines 24 and 25. Enter the result "
         "here. If Parts II, III, IV, and line 40 on page 2 do not apply to you, also enter this amount on "
         "Schedule 1 (Form 1040), line 5. Otherwise, include this amount in the total on line 41 on page 2",
         "line26.total", "outer"),
    ]
    key_map = {"line23a.total_rents": "23a", "line23b.total_royalties": "23b",
               "line23c.total_mortgage_interest": "23c", "line23d.total_depreciation": "23d",
               "line23e.total_expenses": "23e", "line24.income": "24", "line25.losses": "25", "line26.total": "26"}
    y += 2
    for num, label, fname, pos in trows:
        x_label = 38 if num[0].isdigit() else 48
        s.t(x_label, y, num, "Helvetica-Bold", 7)
        nlines = s.wrap(62, y, label, 330 if pos == "inner" else 420)
        v = tot[key_map[fname]]
        if v or fname in ("line26.total",):
            xr = COLS["B"][1] - 4 if pos == "inner" else COLS["C"][1] - 4
            s.val(xr, y, money(v), f"schedule_e.{fname}", v * 100, "cents")
        step = 12 if nlines == 1 else 4.5 + 7.6 * nlines
        y += step
    s.t(36, 778, "For Paperwork Reduction Act Notice, see the separate instructions.", "Helvetica-Bold", 6)
    s.t(300, 778, "Cat. No. 11344L", "Helvetica", 6)
    s.t(500, 778, f"Schedule E (Form 1040) {year}", "Helvetica-Bold", 6)


# ============================================================================ Form 1040


def render_form_1040(h: Household, year: int, path: str) -> dict:
    hy = h.years[year]
    s = Sheet(path, "form_1040", year, title=f"Form 1040 {year}")
    s.t(36, 44, "Form", "Helvetica", 7)
    s.t(56, 46, "1040", "Helvetica-Bold", 16)
    s.t(110, 40, "Department of the Treasury - Internal Revenue Service", "Helvetica", 6)
    s.t(110, 52, "U.S. Individual Income Tax Return", "Helvetica-Bold", 11)
    s.t(330, 50, str(year), "Helvetica-Bold", 18)
    s.t(390, 44, "OMB No. 1545-0074", "Helvetica", 6)
    s.t(390, 52, "IRS Use Only - Do not write or staple in this space.", "Helvetica", 6)
    s.t(36, 64, f"For the year Jan. 1 - Dec. 31, {year}, or other tax year beginning , {year}, ending , 20",
        "Helvetica", 6.5)
    s.t(440, 64, "See separate instructions.", "Helvetica", 6.5)
    s.hline(36, 584, 68, gray=0, width=1.0)
    first, last = h.taxpayer.split(" ", 1)
    sfirst, slast = h.spouse.split(" ", 1)
    s.t(36, 76, "Your first name and middle initial", "Helvetica", 6)
    s.t(220, 76, "Last name", "Helvetica", 6)
    s.t(470, 76, "Your social security number", "Helvetica", 6)
    s.t(36, 86, first.upper(), "Courier-Bold", 8.6)
    s.t(220, 86, last.upper(), "Courier-Bold", 8.6)
    s.t(470, 86, h.ssn_masked, "Courier-Bold", 8.6)
    s.hline(36, 584, 90)
    s.t(36, 98, "If joint return, spouse's first name and middle initial", "Helvetica", 6)
    s.t(220, 98, "Last name", "Helvetica", 6)
    s.t(470, 98, "Spouse's social security number", "Helvetica", 6)
    s.t(36, 108, sfirst.upper(), "Courier-Bold", 8.6)
    s.t(220, 108, slast.upper(), "Courier-Bold", 8.6)
    s.t(470, 108, h.spouse_ssn_masked, "Courier-Bold", 8.6)
    s.hline(36, 584, 112)
    s.t(36, 120, "Home address (number and street). If you have a P.O. box, see instructions.", "Helvetica", 6)
    s.t(380, 120, "Apt. no.", "Helvetica", 6)
    s.val(36, 130, h.address.line1.upper(), "form_1040.home_address", h.address.line1.upper(), "text", align="left")
    s.hline(36, 584, 134)
    s.t(36, 142, "City, town, or post office. If you have a foreign address, also complete spaces below.", "Helvetica",
        6)
    s.t(300, 142, "State", "Helvetica", 6)
    s.t(360, 142, "ZIP code", "Helvetica", 6)
    s.t(36, 152, h.address.city.upper(), "Courier-Bold", 8.6)
    s.val(300, 152, h.address.state, "form_1040.home_state", h.address.state, "text", align="left")
    s.t(360, 152, h.address.zip, "Courier-Bold", 8.6)
    s.hline(36, 584, 156, gray=0, width=0.8)
    s.t(36, 168, "Filing Status", "Helvetica-Bold", 8)
    statuses = [
        ("single", "Single"),
        ("mfj", "Married filing jointly (even if only one had income)"),
        ("mfs", "Married filing separately (MFS)"),
        ("hoh", "Head of household (HOH)"),
        ("qss", "Qualifying surviving spouse (QSS)"),
    ]
    for i, (code, label) in enumerate(statuses):
        yy = 168 + i * 10
        s.checkbox(120, yy, code == h.filing_status)
        s.t(132, yy - 0.5, label, "Helvetica", 6.8)
    # gold for filing status (the X itself is the evidence)
    idx = [c for c, _ in statuses].index(h.filing_status)
    s.fields.append(GoldField(field="form_1040.filing_status", value=h.filing_status, unit="text", page=1,
                              bbox=[120, 161 + idx * 10, 127, 168 + idx * 10], text="X"))
    s.t(36, 228, "Digital Assets", "Helvetica-Bold", 7)
    s.t(120, 228, f"At any time during {year}, did you: (a) receive (as a reward, award, or payment for property or "
        "services); or (b) sell, exchange, or otherwise dispose of a digital asset?", "Helvetica", 5.8)
    s.checkbox(520, 228, False)
    s.t(530, 228, "Yes", "Helvetica", 6.5)
    s.checkbox(550, 228, True)
    s.t(560, 228, "No", "Helvetica", 6.5)
    s.hline(36, 584, 234, gray=0, width=0.8)

    p1 = [
        ("1a", "Total amount from Form(s) W-2, box 1 (see instructions)", "line1a.wages", hy.wages, "R"),
        ("b", "Household employee wages not reported on Form(s) W-2", None, None, "R"),
        ("c", "Tip income not reported on line 1a (see instructions)", None, None, "R"),
        ("d", "Medicaid waiver payments not reported on Form(s) W-2 (see instructions)", None, None, "R"),
        ("e", "Taxable dependent care benefits from Form 2441, line 26", None, None, "R"),
        ("f", "Employer-provided adoption benefits from Form 8839, line 29", None, None, "R"),
        ("g", "Wages from Form 8919, line 6", None, None, "R"),
        ("h", "Other earned income (see instructions)", None, None, "R"),
        ("i", "Nontaxable combat pay election (see instructions)", None, None, "M"),
        ("z", "Add lines 1a through 1h", "line1z.total_wages", hy.wages, "R"),
        ("2a", "Tax-exempt interest", "line2a.tax_exempt_interest", hy.tax_exempt_interest, "M"),
        ("2b", "Taxable interest", "line2b.taxable_interest", hy.taxable_interest, "R"),
        ("3a", "Qualified dividends", "line3a.qualified_dividends", hy.qualified_dividends, "M"),
        ("3b", "Ordinary dividends", "line3b.ordinary_dividends", hy.ordinary_dividends, "R"),
        ("4a", "IRA distributions", None, None, "M"),
        ("4b", "Taxable amount", None, None, "R"),
        ("5a", "Pensions and annuities", None, None, "M"),
        ("5b", "Taxable amount", None, None, "R"),
        ("6a", "Social security benefits", None, None, "M"),
        ("6b", "Taxable amount", None, None, "R"),
        ("7", "Capital gain or (loss). Attach Schedule D if required", None, None, "R"),
        ("8", "Additional income from Schedule 1, line 10", "line8.schedule_1_income", hy.schedule_1_line_10, "R"),
        ("9", "Add lines 1z, 2b, 3b, 4b, 5b, 6b, 7, and 8. This is your total income", "line9.total_income",
         hy.total_income, "R"),
        ("10", "Adjustments to income from Schedule 1, line 26", "line10.adjustments", hy.adjustments, "R"),
        ("11", "Subtract line 10 from line 9. This is your adjusted gross income", "line11.agi", hy.agi, "R"),
        ("12", "Standard deduction or itemized deductions (from Schedule A)", "line12.deduction", hy.std_deduction,
         "R"),
        ("13", "Qualified business income deduction from Form 8995 or Form 8995-A", None, None, "R"),
        ("14", "Add lines 12 and 13", "line14.total_deductions", hy.std_deduction, "R"),
        ("15", "Subtract line 14 from line 11. If zero or less, enter -0-. This is your taxable income",
         "line15.taxable_income", hy.taxable_income, "R"),
    ]
    _lines_1040(s, p1, 246)
    s.t(36, 778, "For Disclosure, Privacy Act, and Paperwork Reduction Act Notice, see separate instructions.",
        "Helvetica-Bold", 6)
    s.t(400, 778, "Cat. No. 11320B", "Helvetica", 6)
    s.t(500, 778, f"Form 1040 ({year})", "Helvetica-Bold", 6)

    s.newpage()
    s.t(36, 40, f"Form 1040 ({year})", "Helvetica", 7)
    s.t(560, 40, "Page 2", "Helvetica", 7)
    s.hline(36, 584, 44, gray=0, width=1.0)
    p2 = [
        ("16", "Tax (see instructions). Check if any from Form(s): 1 8814 2 4972 3", "line16.tax", hy.tax, "R"),
        ("17", "Amount from Schedule 2, line 3", None, None, "R"),
        ("18", "Add lines 16 and 17", "line18.tax_plus_sch2", hy.tax, "R"),
        ("19", "Child tax credit or credit for other dependents from Schedule 8812", None, None, "R"),
        ("20", "Amount from Schedule 3, line 8", None, None, "R"),
        ("21", "Add lines 19 and 20", None, None, "R"),
        ("22", "Subtract line 21 from line 18. If zero or less, enter -0-", "line22.tax_after_credits", hy.tax, "R"),
        ("23", "Other taxes, including self-employment tax, from Schedule 2, line 21", None, None, "R"),
        ("24", "Add lines 22 and 23. This is your total tax", "line24.total_tax", hy.tax, "R"),
        ("25", "Federal income tax withheld from:", None, None, "R"),
        ("a", "Form(s) W-2", "line25a.w2_withholding", hy.withholding, "M"),
        ("b", "Form(s) 1099", None, None, "M"),
        ("c", "Other forms (see instructions)", None, None, "M"),
        ("d", "Add lines 25a through 25c", "line25d.total_withholding", hy.withholding, "R"),
        ("26", f"{year} estimated tax payments and amount applied from {year - 1} return", "line26.estimated_payments",
         hy.estimated_payments, "R"),
        ("32", "Add lines 27, 28, 29, and 31. These are your total other payments and refundable credits", None, None,
         "R"),
        ("33", "Add lines 25d, 26, and 32. These are your total payments", "line33.total_payments",
         hy.total_payments, "R"),
        ("34", "If line 33 is more than line 24, subtract line 24 from line 33. This is the amount you overpaid",
         "line34.overpaid", hy.refund, "R"),
        ("35a", "Amount of line 34 you want refunded to you. If Form 8888 is attached, check here",
         "line35a.refund", hy.refund, "R"),
        ("37", "Subtract line 33 from line 24. This is the amount you owe. For details on how to pay, go to "
         "www.irs.gov/Payments or see instructions", "line37.amount_owed", hy.owed, "R"),
    ]
    y = _lines_1040(s, p2, 58)
    y += 10
    s.t(36, y, "Sign Here", "Helvetica-Bold", 8)
    s.t(110, y, "Under penalties of perjury, I declare that I have examined this return and accompanying schedules "
        "and statements, and to the best of my knowledge and belief, they are true, correct, and complete.",
        "Helvetica", 5.6)
    s.t(110, y + 14, "Your signature", "Helvetica", 6)
    s.t(300, y + 14, "Date", "Helvetica", 6)
    s.t(360, y + 14, "Your occupation", "Helvetica", 6)
    s.t(360, y + 24, "SOFTWARE ENGINEER", "Courier-Bold", 8)
    s.t(110, y + 34, "Spouse's signature. If a joint return, both must sign.", "Helvetica", 6)
    s.t(360, y + 34, "Spouse's occupation", "Helvetica", 6)
    s.t(360, y + 44, "PHYSICAL THERAPIST", "Courier-Bold", 8)
    s.hline(36, 584, y + 50, gray=0, width=0.8)
    s.t(36, y + 62, "Paid Preparer Use Only", "Helvetica-Bold", 8)
    s.t(160, y + 62, "Firm's name", "Helvetica", 6)
    s.t(210, y + 62, h.preparer.upper(), "Courier-Bold", 8)
    s.t(36, 778, "Go to www.irs.gov/Form1040 for instructions and the latest information.", "Helvetica-Bold", 6)
    s.t(500, 778, f"Form 1040 ({year})", "Helvetica-Bold", 6)
    return s.save()


def _lines_1040(s: Sheet, rows: list, y: float) -> float:
    for num, label, fname, v, pos in rows:
        x_num = 38 if num[0].isdigit() else 48
        s.t(x_num, y, num, "Helvetica-Bold", 7)
        s.wrap(62, y, label, 320 if pos == "M" else 400)
        box_num_x = 392 if pos == "M" else 486
        s.t(box_num_x, y, num, "Helvetica-Bold", 6.5)
        if fname and v:
            xr = 476 if pos == "M" else 580
            s.val(xr, y, money(v), f"form_1040.{fname}", v * 100, "cents")
        s.hline(36, 584, y + 3.5)
        y += 14
    return y


# ============================================================================ Form 4562


def render_form_4562(h: Household, p: Property, year: int, path: str) -> dict:
    s = Sheet(path, "form_4562", year, title=f"Form 4562 {year}")
    y = s.header_irs("Form 4562", "", "Depreciation and Amortization",
                     ["(Including Information on Listed Property)", "Attach to your tax return.",
                      "Go to www.irs.gov/Form4562 for instructions and the latest information."],
                     year, "Attachment Sequence No. 179", omb="OMB No. 1545-0172")
    addr = p.address_by_year[year]
    s.t(36, y, "Name(s) shown on return", "Helvetica", 6)
    s.t(250, y, "Business or activity to which this form relates", "Helvetica", 6)
    s.t(500, y, "Identifying number", "Helvetica", 6)
    s.t(36, y + 10, _names(h), "Courier-Bold", 7.6)
    s.val(250, y + 10, f"RENTAL - {addr}", "form_4562.activity", addr, "text", prop=p.key, address=addr,
          align="left", size=7.6)
    s.t(500, y + 10, h.ssn_masked, "Courier-Bold", 7.6)
    s.hline(36, 584, y + 14)
    s.bar(y + 26, "Part I", "Election To Expense Certain Property Under Section 179")
    s.t(86, y + 37, "Note: If you have any listed property, complete Part V before you complete Part I.", "Helvetica",
        6.3)
    s.t(38, y + 48, "1", "Helvetica-Bold", 7)
    s.t(62, y + 48, "Maximum amount (see instructions)", "Helvetica", 6.6)
    s.t(38, y + 60, "12", "Helvetica-Bold", 7)
    s.t(62, y + 60, "Section 179 expense deduction. Add lines 9 and 10, but don't enter more than line 11",
        "Helvetica", 6.6)
    s.bar(y + 76, "Part II", "Special Depreciation Allowance and Other Depreciation (Don't include listed property. "
          "See instructions.)")
    s.t(38, y + 88, "14", "Helvetica-Bold", 7)
    s.t(62, y + 88, "Special depreciation allowance for qualified property (other than listed property) placed in "
        "service during the tax year. See instructions", "Helvetica", 6.3)
    s.bar(y + 104, "Part III", "MACRS Depreciation (Don't include listed property. See instructions.)")
    s.ct(310, y + 115, "Section A", "Helvetica-Bold", 7)
    yy = y + 127
    prior = sum(a.allowable(year) for a in p.assets if a.placed_in_service.year < year)
    s.t(38, yy, "17", "Helvetica-Bold", 7)
    s.t(62, yy, f"MACRS deductions for assets placed in service in tax years beginning before {year}", "Helvetica",
        6.6)
    s.t(492, yy, "17", "Helvetica-Bold", 6.5)
    if prior:
        s.val(580, yy, money(prior), "form_4562.line17.prior_macrs", prior * 100, "cents", prop=p.key, address=addr)
    s.hline(36, 584, yy + 3.5)
    yy += 12
    s.t(38, yy, "18", "Helvetica-Bold", 7)
    s.wrap(62, yy, "If you are electing to group any assets placed in service during the tax year into one or more "
           "general asset accounts, check here", 420)
    s.hline(36, 584, yy + 11)
    yy += 22
    s.ct(310, yy, f"Section B - Assets Placed in Service During {year} Tax Year Using the General Depreciation System",
         "Helvetica-Bold", 7)
    yy += 8
    heads = [(62, "(a) Classification of property"), (172, "(b) Month and year placed in service"),
             (250, "(c) Basis for depreciation (business/investment use only - see instructions)"),
             (360, "(d) Recovery period"), (420, "(e) Convention"), (470, "(f) Method"),
             (520, "(g) Depreciation deduction")]
    for x, hd in heads:
        s.wrap(x, yy + 4, hd, 70 if x != 250 else 100, size=5.8, leading=6.4)
    s.hline(36, 584, yy + 28)
    yy += 38
    classes = [
        ("19a", "3-year property", "", "", "", ""),
        ("b", "5-year property", "", "", "", ""),
        ("c", "7-year property", "", "", "", ""),
        ("d", "10-year property", "", "", "", ""),
        ("e", "15-year property", "", "", "", ""),
        ("f", "20-year property", "", "", "", ""),
        ("g", "25-year property", "25 yrs.", "", "S/L", ""),
        ("h", "Residential rental property", "27.5 yrs.", "MM", "S/L", "h"),
        ("i", "Nonresidential real property", "39 yrs.", "MM", "S/L", ""),
    ]
    new_assets = [a for a in p.assets if a.placed_in_service.year == year]
    for num, label, rp, conv, meth, key in classes:
        s.t(38 if num[0].isdigit() else 48, yy, num, "Helvetica-Bold", 7)
        s.t(62, yy, label, "Helvetica", 6.6)
        if rp:
            s.t(362, yy, rp, "Helvetica", 6.6)
        if conv:
            s.t(424, yy, conv, "Helvetica", 6.6)
        if meth:
            s.t(472, yy, meth, "Helvetica", 6.6)
        if key == "h" and new_assets:
            a = new_assets[0]
            claimed = p.years[year].expenses[18] - prior
            pis = f"{a.placed_in_service.month:02d}/{a.placed_in_service.year}"
            s.val(176, yy, pis, "form_4562.line19h.placed_in_service", f"{a.placed_in_service.year}-"
                  f"{a.placed_in_service.month:02d}", "text", prop=p.key, address=addr, align="left")
            s.val(346, yy, money(a.basis), "form_4562.line19h.basis", a.basis * 100, "cents", prop=p.key,
                  address=addr)
            s.val(580, yy, money(claimed), "form_4562.line19h.deduction", claimed * 100, "cents", prop=p.key,
                  address=addr)
        s.hline(36, 584, yy + 3.5)
        yy += 12
    yy += 6
    s.bar(yy, "Part IV", "Summary (See instructions.)")
    yy += 13
    s.t(38, yy, "21", "Helvetica-Bold", 7)
    s.t(62, yy, "Listed property. Enter amount from line 28", "Helvetica", 6.6)
    s.hline(36, 584, yy + 3.5)
    yy += 12
    total = p.years[year].expenses[18]
    s.t(38, yy, "22", "Helvetica-Bold", 7)
    s.wrap(62, yy, "Total. Add amounts from line 12, lines 14 through 17, lines 19 and 20 in column (g), and line 21. "
           "Enter here and on the appropriate lines of your return. Partnerships and S corporations - see "
           "instructions", 400)
    s.t(492, yy, "22", "Helvetica-Bold", 6.5)
    s.val(580, yy, money(total), "form_4562.line22.total", total * 100, "cents", prop=p.key, address=addr)
    s.t(36, 778, "For Paperwork Reduction Act Notice, see separate instructions.", "Helvetica-Bold", 6)
    s.t(320, 778, "Cat. No. 12906N", "Helvetica", 6)
    s.t(510, 778, f"Form 4562 ({year})", "Helvetica-Bold", 6)
    return s.save()


# ============================================================================ Form 8582


def render_form_8582(h: Household, year: int, path: str) -> dict:
    f = h.years[year].form_8582
    assert f is not None
    s = Sheet(path, "form_8582", year, title=f"Form 8582 {year}")
    y = s.header_irs("Form 8582", "", "Passive Activity Loss Limitations",
                     ["See separate instructions.", "Attach to Form 1040, 1040-SR, or 1041.",
                      "Go to www.irs.gov/Form8582 for instructions and the latest information."],
                     year, "Attachment Sequence No. 858", omb="OMB No. 1545-1008")
    s.t(36, y, "Name(s) shown on return", "Helvetica", 6)
    s.t(470, y, "Identifying number", "Helvetica", 6)
    s.t(36, y + 10, _names(h), "Courier-Bold", 8.6)
    s.t(470, y + 10, h.ssn_masked, "Courier-Bold", 8.6)
    s.hline(36, 584, y + 14)
    s.bar(y + 26, "Part I", f"{year} Passive Activity Loss")
    s.t(86, y + 37, "Caution: Complete Worksheets 1, 2, and 3 before completing Part I.", "Helvetica", 6.3)
    yy = y + 50
    s.t(62, yy, "Rental Real Estate Activities With Active Participation (For the definition of active "
        "participation, see Special Allowance for Rental Real Estate Activities in the instructions.)",
        "Helvetica-Bold", 5.8)
    yy += 12

    def ln(num: str, label: str, fname: str | None, v: int | None, pos: str = "M", force: bool = False) -> None:
        nonlocal yy
        s.t(38 if num[0].isdigit() else 48, yy, num, "Helvetica-Bold", 7)
        n = s.wrap(62, yy, label, 320 if pos == "M" else 400)
        if fname and (v or force):
            xr = 476 if pos == "M" else 580
            s.val(xr, yy, money(v), f"form_8582.{fname}", v * 100, "cents")
        s.hline(36, 584, yy + 3.5 + 7.6 * (n - 1))
        yy += 13 + 7.6 * (n - 1)

    ln("1a", "Activities with net income (enter the amount from Worksheet 1, column (a))", "line1a.net_income",
       f.line1a, "M")
    ln("b", "Activities with net loss (enter the amount from Worksheet 1, column (b))", "line1b.net_loss", f.line1b,
       "M")
    ln("c", "Prior years' unallowed losses (enter the amount from Worksheet 1, column (c))",
       "line1c.prior_unallowed", f.line1c, "M")
    ln("d", "Combine lines 1a, 1b, and 1c", "line1d.combined", f.line1d, "R", force=True)
    s.t(62, yy, "All Other Passive Activities", "Helvetica-Bold", 5.8)
    yy += 11
    ln("2a", "Activities with net income (enter the amount from Worksheet 3, column (a))", None, None)
    ln("b", "Activities with net loss (enter the amount from Worksheet 3, column (b))", None, None)
    ln("c", "Prior years' unallowed losses (enter the amount from Worksheet 3, column (c))", None, None)
    ln("d", "Combine lines 2a, 2b, and 2c", None, None, "R")
    ln("3", "Combine lines 1d and 2d. If this line is zero or more, stop here and include this form with your "
       "return; all losses are allowed, including any prior year unallowed losses entered on line 1c or 2c. Report "
       "the losses on the forms and schedules normally used", "line3.combined", f.line3, "R", force=True)
    s.t(62, yy, "If line 3 is a loss and: Line 1d is a loss, go to Part II. Line 2d is a loss (and line 1d is zero "
        "or more), skip Part II and enter -0- on line 9. Go to line 10.", "Helvetica", 5.6)
    yy += 12
    s.bar(yy, "Part II", "Special Allowance for Rental Real Estate Activities With Active Participation")
    yy += 11
    s.t(86, yy, "Note: Enter all numbers in Part II as positive amounts. See instructions for an example.",
        "Helvetica", 6.3)
    yy += 12
    loss = f.line1d < 0
    ln("4", "Enter the smaller of the loss on line 1d or the loss on line 3", "line4.loss", f.line4 if loss else None,
       "R")
    ln("5", "Enter $150,000. If married filing separately, see instructions", "line5.threshold",
       f.line5 if loss else None, "M")
    ln("6", "Enter modified adjusted gross income, but not less than zero (see instructions)", "line6.magi",
       f.line6 if loss else None, "M")
    s.t(62, yy - 2, "Note: If line 6 is greater than or equal to line 5, skip lines 7 and 8 and enter -0- on line 9. "
        "Otherwise, go to line 7.", "Helvetica", 5.6)
    yy += 8
    ln("7", "Subtract line 6 from line 5", "line7.excess", f.line7 if loss else None, "M")
    ln("8", "Multiply line 7 by 50% (0.50). Don't enter more than $25,000. If married filing separately, see "
       "instructions", "line8.allowance", f.line8 if loss else None, "R")
    ln("9", "Enter the smaller of line 4 or line 8", "line9.special_allowance", f.line9 if loss else None, "R",
       force=loss)
    s.bar(yy, "Part III", "Total Losses Allowed")
    yy += 13
    ln("10", "Add the income, if any, on lines 1a and 2a and enter the total", "line10.passive_income",
       f.line10 if loss else None, "R")
    ln("11", f"Total losses allowed from all passive activities for {year}. Add lines 9 and 10. See instructions "
       "to find out how to report the losses on your tax return", "line11.total_allowed",
       f.line11 if loss else None, "R")
    s.t(36, 778, "For Paperwork Reduction Act Notice, see instructions.", "Helvetica-Bold", 6)
    s.t(320, 778, "Cat. No. 63704F", "Helvetica", 6)
    s.t(510, 778, f"Form 8582 ({year})", "Helvetica-Bold", 6)

    # ---- page 2: worksheets
    s.newpage()
    s.t(36, 40, f"Form 8582 ({year})", "Helvetica", 7)
    s.t(560, 40, "Page 2", "Helvetica", 7)
    s.hline(36, 584, 44, gray=0, width=1.0)
    s.t(36, 58, "Worksheet 1 - For Form 8582, Lines 1a, 1b, and 1c (See instructions.)", "Helvetica-Bold", 7.5)
    yy = 70
    cols = [(250, "(a) Net income (line 1a)"), (316, "(b) Net loss (line 1b)"), (382, "(c) Unallowed loss (line 1c)"),
            (448, "(d) Gain"), (516, "(e) Loss")]
    s.t(40, yy + 6, "Name of activity", "Helvetica-Bold", 6.3)
    s.ct(316, yy - 4, "Current year", "Helvetica", 6)
    s.ct(382, yy - 4, "Prior years", "Helvetica", 6)
    s.ct(482, yy - 4, "Overall gain or loss", "Helvetica", 6)
    for x, hd in cols:
        s.wrap(x + 2, yy + 2, hd, 60, size=5.8, leading=6.4)
    s.hline(36, 584, yy + 12)
    yy += 24
    for a in f.activities:
        p = h.by_key(a["property_key"])
        addr = p.address_by_year[year]
        s.t(40, yy, f"Rental - {addr}", "Courier", 5.8)
        vals = [a["net_income"], a["net_loss"], a["prior_unallowed"], a["overall"] if a["overall"] > 0 else 0,
                a["overall"] if a["overall"] < 0 else 0]
        for (x, _), v in zip(cols, vals, strict=True):
            if v:
                s.t(x + 62 - 4 - len(money(v)) * 4.4, yy, money(v), "Courier-Bold", 7.4)
        s.hline(36, 584, yy + 3.5)
        yy += 12
    s.t(40, yy, "Total. Enter on Form 8582, lines 1a, 1b, and 1c", "Helvetica-Bold", 6.3)
    for (x, _), v in zip(cols[:3], [f.line1a, f.line1b, f.line1c], strict=True):
        if v:
            s.t(x + 62 - 4 - len(money(v)) * 4.4, yy, money(v), "Courier-Bold", 7.4)
    s.hline(36, 584, yy + 3.5, gray=0)
    yy += 26
    if f.unallowed_total:
        s.t(36, yy, "Worksheet 5 - Allocation of Unallowed Losses (See instructions.)", "Helvetica-Bold", 7.5)
        yy += 12
        heads5 = [(40, "Name of activity"), (258, "Form or schedule and line number to be reported on"),
                  (390, "(a) Loss"), (450, "(b) Ratio"), (510, "(c) Unallowed loss")]
        for x, hd in heads5:
            s.wrap(x, yy, hd, 120 if x == 258 else 60, size=5.8, leading=6.4)
        s.hline(36, 584, yy + 10)
        yy += 22
        for a in f.activities:
            if not a["unallowed"]:
                continue
            p = h.by_key(a["property_key"])
            addr = p.address_by_year[year]
            s.t(40, yy, f"Rental - {addr}", "Courier", 5.8)
            s.t(258, yy, "Schedule E, line 22", "Courier", 6.6)
            s.t(440 - len(money(a["overall"])) * 4.4, yy, money(a["overall"]), "Courier-Bold", 7.4)
            s.t(452, yy, f"{a['ratio']:.4f}", "Courier-Bold", 7.4)
            s.val(580, yy, money(a["unallowed"]), "form_8582.ws5.unallowed_loss", a["unallowed"] * 100, "cents",
                  prop=p.key, address=addr, size=7.4)
            s.hline(36, 584, yy + 3.5)
            yy += 12
        s.t(40, yy, "Total", "Helvetica-Bold", 6.6)
        s.t(452, yy, "1.00", "Courier-Bold", 7.4)
        s.val(580, yy, money(f.unallowed_total), "form_8582.unallowed_loss_total", f.unallowed_total * 100, "cents",
              size=7.4)
        s.hline(36, 584, yy + 3.5, gray=0)
    return s.save()


# ============================================================================ mortgage statements


def _kv(s: Sheet, x: float, xr: float, y: float, label: str, text: str, fname: str | None = None, value=None,
        unit: str = "cents", prop: str | None = None, address: str | None = None) -> None:
    s.t(x, y, label, "Helvetica", 7.4)
    if fname:
        s.val(xr, y, text, fname, value, unit, prop=prop, address=address, entity="loan", font="Helvetica-Bold",
              size=7.6)
    else:
        s.rt(xr, y, text, "Helvetica-Bold", 7.6)


def _loan_snapshot(loan: Loan, year: int) -> dict:
    """Year-end figures for a statement, in cents."""
    if loan.loan_type == "fixed":
        sched = loan.schedule
        yt = year_totals(sched, year)
        nxt = next((r for r in sched if r["date"].year == year + 1), None)
        return {
            "balance": yt["end_balance"],
            "interest_ytd": yt["interest"],
            "principal_ytd": yt["principal"],
            "payment": sched[1]["payment"],
            "next_principal": nxt["principal"] if nxt else 0,
            "next_interest": nxt["interest"] if nxt else 0,
        }
    if loan.loan_type == "interest_only":
        pay = round(loan.original * 100 * float(loan.rate) / 12)
        months = 12 if year > loan.first_payment.year else 13 - loan.first_payment.month
        return {"balance": loan.original * 100, "interest_ytd": pay * months, "principal_ytd": 0, "payment": pay,
                "next_principal": 0, "next_interest": pay}
    bal = loan.heloc_balances[year] * 100
    pay = round(bal * float(loan.heloc_rates[year]) / 12)
    return {"balance": bal, "interest_ytd": loan.heloc_interest[year] * 100,
            "principal_ytd": (loan.heloc_balances[year - 1] - loan.heloc_balances[year]) * 100, "payment": pay,
            "next_principal": 0, "next_interest": pay}


def render_mortgage_statement(h: Household, p: Property, loan: Loan, year: int, path: str) -> dict:
    s = Sheet(path, "mortgage_statement", year, title=f"{loan.lender} statement")
    addr = loan.statement_address
    pk = p.key
    s.t(40, 50, loan.lender, "Helvetica-Bold", 13)
    s.t(40, 62, "Customer Service: 1-800-555-0142   Mon-Fri 8am-8pm PT", "Helvetica", 7)
    s.t(40, 71, "P.O. Box 4410, Sacramento, CA 95812", "Helvetica", 7)
    heloc = loan.loan_type == "heloc"
    paid_off = loan.paid_off_date is not None
    title = ("Paid-in-Full Confirmation" if paid_off else
             "Home Equity Line of Credit Statement" if heloc else "Mortgage Statement")
    s.rt(572, 50, title, "Helvetica-Bold", 13)
    stmt_date = date(year + 1, 1, 5) if not paid_off else date(2023, 1, 15)
    s.t(380, 66, "Statement Date:", "Helvetica", 7.4)
    s.val(572, 66, stmt_date.strftime("%m/%d/%Y"), "mortgage.statement_date", stmt_date.isoformat(), "date",
          prop=pk, address=addr, entity="loan", font="Helvetica-Bold", size=7.6)
    s.t(380, 76, "Loan Number:", "Helvetica", 7.4)
    s.val(572, 76, loan.loan_number, "mortgage.loan_number", loan.loan_number, "text", prop=pk, address=addr,
          entity="loan", font="Helvetica-Bold", size=7.6)
    s.hline(36, 584, 84, gray=0, width=1.0)
    s.t(40, 98, f"{h.taxpayer.upper()} AND {h.spouse.upper()}", "Courier-Bold", 8)
    s.t(40, 108, h.address.line1.upper(), "Courier", 8)
    s.t(40, 118, f"{h.address.city.upper()} {h.address.state} {h.address.zip}", "Courier", 8)
    s.t(330, 98, "Property Address:", "Helvetica", 7.4)
    s.val(330, 108, addr, "mortgage.property_address", addr, "text", prop=pk, address=addr, entity="loan",
          font="Helvetica-Bold", size=7.6, align="left")
    s.hline(36, 584, 128)

    s.rect(36, 136, 304, 330)
    s.t(42, 148, "Account Information", "Helvetica-Bold", 8.5)
    lien_txt = {1: "1st", 2: "2nd", 3: "3rd"}[loan.lien_position]
    if paid_off:
        snap = {"balance": 0}
    else:
        snap = _loan_snapshot(loan, year)
    asof = date(year, 12, 31) if not paid_off else loan.paid_off_date
    rows: list[tuple] = []
    if loan.original:
        label = "Credit Limit" if heloc else "Original Principal Balance"
        fname = "mortgage.credit_limit" if heloc else "mortgage.original_amount"
        rows.append((label, money_cents(loan.original * 100), fname, loan.original * 100, "cents"))
    if loan.originated:
        rows.append(("Origination Date", loan.originated.strftime("%m/%d/%Y"), "mortgage.origination_date",
                     loan.originated.isoformat(), "date"))
    if loan.assumed_on:
        rows.append(("Assumed By Current Borrower", loan.assumed_on.strftime("%m/%d/%Y"), None, None, None))
    rows.append((f"Outstanding Principal Balance (as of {asof.strftime('%m/%d/%Y')})", money_cents(snap["balance"]),
                 "mortgage.principal_balance", snap["balance"], "cents"))
    rate = loan.heloc_rates.get(year, loan.rate) if heloc else loan.rate
    if not paid_off:
        rate_label = "Annual Percentage Rate (variable)" if heloc else (
            f"Interest Rate (until {loan.arm_reset.strftime('%m/%d/%Y')})" if loan.arm_reset else "Interest Rate")
        rows.append((rate_label, f"{Decimal(rate) * 100:.3f}%", "mortgage.interest_rate", float(rate), "rate"))
    rows.append(("Loan Type", loan.product if len(loan.product) < 34 else "HELOC - Variable Rate",
                 "mortgage.loan_type_text", loan.product if len(loan.product) < 34 else "HELOC - Variable Rate",
                 "text"))
    rows.append(("Lien Position", lien_txt, "mortgage.lien_position", loan.lien_position, "int"))
    if not heloc:
        rows.append(("Original Term", f"{loan.term_months} months", "mortgage.term_months", loan.term_months, "int"))
    if loan.maturity:
        rows.append(("Maturity Date", loan.maturity.strftime("%m/%d/%Y"), "mortgage.maturity_date",
                     loan.maturity.isoformat(), "date"))
    if loan.arm_reset:
        rows.append(("Next Rate Change Date", loan.arm_reset.strftime("%m/%d/%Y"), "mortgage.next_rate_change_date",
                     loan.arm_reset.isoformat(), "date"))
        rows.append(("Index / Margin", f"{loan.index_name} + {Decimal(loan.index_margin) * 100:.2f}%",
                     "mortgage.index_margin", float(loan.index_margin), "rate"))
    if loan.io_end:
        lbl = "Draw Period (Interest-Only) Ends" if heloc else "Interest-Only Period Ends"
        rows.append((lbl, loan.io_end.strftime("%m/%d/%Y"), "mortgage.io_period_end", loan.io_end.isoformat(),
                     "date"))
    if paid_off:
        rows.append(("Payoff Date", loan.paid_off_date.strftime("%m/%d/%Y"), "mortgage.payoff_date",
                     loan.paid_off_date.isoformat(), "date"))
        rows.append(("Loan Status", "PAID IN FULL", "mortgage.paid_in_full", True, "bool"))
    yy = 162
    for label, text, fname, value, unit in rows:
        _kv(s, 42, 298, yy, label, text, fname, value, unit or "text", prop=pk, address=addr)
        yy += 12

    if paid_off:
        s.rect(320, 136, 584, 330)
        s.t(326, 148, "Lien Release", "Helvetica-Bold", 8.5)
        s.wrap(326, 162, f"This confirms that the loan referenced above was paid in full on "
               f"{loan.paid_off_date.strftime('%B %d, %Y')}. A full reconveyance has been recorded with the "
               "Sacramento County Recorder. No further payments are due. Please retain this letter for your "
               "records.", 250, size=7.4, leading=9)
        return s.save()

    s.rect(320, 136, 584, 250)
    s.t(326, 148, "Explanation of Amount Due", "Helvetica-Bold", 8.5)
    due = date(year + 1, 2, 1)
    escrow = {"p1-first": 52_500, "p2-first": 71_200, "p3-first": 87_400}.get(loan.key, 0)
    pay_label = "Minimum Payment Due (interest only)" if heloc else (
        "Regular Monthly Payment (interest only)" if loan.loan_type == "interest_only" else
        "Regular Monthly Payment (principal and interest)")
    rows2 = [
        ("Principal", money_cents(snap["next_principal"]), None, None),
        ("Interest", money_cents(snap["next_interest"]), None, None),
        ("Escrow (for Taxes and Insurance)", money_cents(escrow), None, None),
        (pay_label, money_cents(snap["payment"]), "mortgage.monthly_payment", snap["payment"]),
        ("Total Amount Due", money_cents(snap["next_principal"] + snap["next_interest"] + escrow), None, None),
        ("Payment Due Date", due.strftime("%m/%d/%Y"), None, None),
    ]
    yy = 162
    for label, text, fname, value in rows2:
        _kv(s, 326, 578, yy, label, text, fname, value, prop=pk, address=addr)
        yy += 12

    s.rect(320, 258, 584, 330)
    s.t(326, 270, f"Year-to-Date ({year})", "Helvetica-Bold", 8.5)
    _kv(s, 326, 578, 284, f"Principal Paid Year-to-Date ({year})", money_cents(snap["principal_ytd"]),
        "mortgage.principal_paid_ytd", snap["principal_ytd"], prop=pk, address=addr)
    _kv(s, 326, 578, 296, f"Interest Paid Year-to-Date ({year})", money_cents(snap["interest_ytd"]),
        "mortgage.interest_paid_ytd", snap["interest_ytd"], prop=pk, address=addr)
    _kv(s, 326, 578, 308, "Escrow Disbursements Year-to-Date", money_cents(escrow * 12), None)
    s.t(326, 322, f"Mortgage interest reported on Form 1098 for {year}: see Box 1.", "Helvetica", 6.4)

    yy = 350
    s.t(40, yy, "Important Messages", "Helvetica-Bold", 8.5)
    msgs = []
    if loan.arm_reset:
        msgs.append(f"Your interest rate is scheduled to adjust on {loan.arm_reset.strftime('%m/%d/%Y')}. The new rate "
                    f"will equal the {loan.index_name} index plus a margin of {Decimal(loan.index_margin) * 100:.2f}%, "
                    "subject to the caps in your note. You will receive a notice 210 days before the first change.")
    if loan.io_end and not heloc:
        msgs.append(f"Your interest-only period ends on {loan.io_end.strftime('%m/%d/%Y')}. After that date your "
                    "payment will include principal and may increase significantly.")
    if heloc:
        msgs.append(f"Your draw period ends {loan.io_end.strftime('%m/%d/%Y')}. This line of credit is secured by a "
                    "second lien on the property address shown above.")
    msgs.append("If you are experiencing financial difficulty, HUD-approved housing counselors are available at "
                "1-800-569-4287.")
    yy += 12
    for m in msgs:
        n = s.wrap(40, yy, m, 530, size=7.2, leading=9)
        yy += 9 * n + 4
    return s.save()


# ============================================================================ closing statement / appraisal


CLOSING_LINES = [
    ("Owner's Title Insurance Policy - Placer Title Company", 1_820),
    ("Escrow / Settlement Fee - Placer Title Company", 1_450),
    ("Recording Fees - Grant Deed and Assumption Agreement", 210),
    ("Loan Assumption Fee - Pacific Crest Bank", 900),
    ("Assumption Processing and Credit Report - Pacific Crest Bank", 1_250),
    ("Appraisal Fee", 650),
    ("Home Inspection - Foothill Home Inspections", 525),
    ("Property Taxes 06/14/2024 - 06/30/2024 (Placer County)", 1_045),
]


def render_closing_statement(h: Household, p: Property, path: str) -> dict:
    s = Sheet(path, "closing_statement", p.purchase_date.year, title="ALTA Settlement Statement - Buyer")
    pk = p.key
    addr = p.address.one_line()
    assert sum(v for _, v in CLOSING_LINES) == p.closing_costs
    loan = p.loans[0]
    s.ct(306, 46, "ALTA Settlement Statement - Buyer", "Helvetica-Bold", 13)
    s.ct(306, 58, "Adopted 05-01-2015", "Helvetica", 6.5)
    s.t(40, 76, "Placer Title Company", "Helvetica-Bold", 9)
    s.t(40, 86, "1550 Eureka Rd, Roseville, CA 95661", "Helvetica", 7)
    s.t(330, 76, "File No.:", "Helvetica", 7.4)
    s.t(400, 76, "PTC-24-061482", "Helvetica-Bold", 7.6)
    s.t(330, 88, "Property:", "Helvetica", 7.4)
    s.val(400, 88, addr, "closing.property_address", addr, "text", prop=pk, address=addr, align="left",
          font="Helvetica-Bold", size=7.6)
    s.t(330, 100, "Buyer:", "Helvetica", 7.4)
    s.t(400, 100, f"{h.taxpayer} and {h.spouse}", "Helvetica-Bold", 7.6)
    s.t(330, 112, "Seller:", "Helvetica", 7.4)
    s.t(400, 112, "Harmon Family Trust", "Helvetica-Bold", 7.6)
    s.t(330, 124, "Settlement Date:", "Helvetica", 7.4)
    s.val(400, 124, p.purchase_date.strftime("%m/%d/%Y"), "closing.settlement_date", p.purchase_date.isoformat(),
          "date", prop=pk, address=addr, align="left", font="Helvetica-Bold", size=7.6)
    s.t(330, 136, "Disbursement Date:", "Helvetica", 7.4)
    s.t(400, 136, p.purchase_date.strftime("%m/%d/%Y"), "Helvetica-Bold", 7.6)
    s.hline(36, 584, 144, gray=0, width=1.0)
    s.t(40, 158, "Description", "Helvetica-Bold", 8)
    s.rt(500, 158, "Buyer Debit", "Helvetica-Bold", 8)
    s.rt(578, 158, "Buyer Credit", "Helvetica-Bold", 8)
    s.hline(36, 584, 162)
    yy = 176
    s.t(40, yy, "Financial", "Helvetica-Bold", 7.6)
    yy += 12

    def line(desc: str, debit: int | None = None, credit: int | None = None, fname: str | None = None,
             value_on: str = "debit") -> None:
        nonlocal yy
        s.t(48, yy, desc, "Helvetica", 7.4)
        for col, v, xr in (("debit", debit, 500), ("credit", credit, 578)):
            if v is None:
                continue
            txt = f"{v:,.2f}"
            if fname and value_on == col:
                s.val(xr, yy, txt, fname, v * 100, "cents", prop=pk, address=addr, font="Helvetica-Bold", size=7.6)
            else:
                s.rt(xr, yy, txt, "Helvetica-Bold", 7.6)
        s.hline(44, 584, yy + 3.5, gray=0.75)
        yy += 12

    line("Contract Sales Price", debit=p.purchase_price, fname="closing.contract_sales_price")
    line("Deposit / Earnest Money", credit=15_000)
    s.t(40, yy, "Loan", "Helvetica-Bold", 7.6)
    yy += 12
    line(f"Assumption of Existing Loan - {loan.lender} ({loan.product})", credit=loan.original,
         fname="closing.loan_amount", value_on="credit")
    s.t(40, yy, "Title Charges, Escrow, Recording and Other", "Helvetica-Bold", 7.6)
    yy += 12
    for desc, amt in CLOSING_LINES:
        line(desc, debit=amt)
    yy += 4
    line("Total Closing Costs (Buyer)", debit=p.closing_costs, fname="closing.total_closing_costs")
    s.hline(36, 584, yy - 6, gray=0, width=0.8)
    debit_total = p.purchase_price + p.closing_costs
    credit_total = 15_000 + loan.original
    line("Subtotals", debit=debit_total, credit=credit_total)
    line("Due From Buyer", credit=debit_total - credit_total)
    yy += 14
    s.wrap(40, yy, "Acknowledgement: We/I have carefully reviewed the ALTA Settlement Statement and find it to be a "
           "true and accurate statement of all receipts and disbursements made on my account or by me in this "
           "transaction and further certify that I have received a copy of the ALTA Settlement Statement.", 530,
           size=7, leading=8.6)
    s.t(40, yy + 40, "Buyer signature ______________________________", "Helvetica", 7.4)
    s.t(330, yy + 40, "Settlement Agent ______________________________", "Helvetica", 7.4)
    return s.save()


def render_appraisal(h: Household, p: Property, path: str) -> dict:
    assert p.appraisal is not None
    as_of, value, printed = p.appraisal
    s = Sheet(path, "appraisal", as_of.year, title="Appraisal letter")
    pk = p.key
    s.t(40, 52, "Sacramento Valley Appraisal Group", "Helvetica-Bold", 13)
    s.t(40, 64, "Certified Residential Appraisers  |  2120 J Street, Suite 300, Sacramento, CA 95816", "Helvetica", 7)
    s.hline(36, 584, 72, gray=0, width=1.0)
    letter_date = date(as_of.year, as_of.month, as_of.day + 4)
    s.t(40, 92, letter_date.strftime("%B %d, %Y").replace(" 0", " "), "Helvetica", 8.5)
    s.t(40, 112, f"{h.taxpayer} and {h.spouse}", "Helvetica", 8.5)
    s.t(40, 123, f"{h.address.line1}, {h.address.city}, {h.address.state} {h.address.zip}", "Helvetica", 8.5)
    s.t(40, 146, "Re: Appraisal Report Summary Letter - Market Value Opinion", "Helvetica-Bold", 8.5)
    s.wrap(40, 166, f"At your request we have appraised the two-unit residential property located at {printed}. The "
           "purpose of this appraisal is to develop an opinion of the market value of the fee simple interest in the "
           "subject property for portfolio planning purposes. The appraisal was prepared in conformance with the "
           "Uniform Standards of Professional Appraisal Practice (USPAP).", 530, size=8.5, leading=11)
    s.wrap(40, 222, "Based on our inspection of the property, analysis of comparable two-to-four unit sales in North "
           "Sacramento, and the income approach using current market rents, it is our opinion that the market value "
           "of the subject property is as stated below.", 530, size=8.5, leading=11)
    s.rect(36, 262, 584, 360)
    s.t(42, 276, "Summary of Appraisal", "Helvetica-Bold", 9)
    s.t(42, 292, "Subject Property:", "Helvetica", 8)
    s.val(200, 292, printed, "appraisal.property_address", printed, "text", prop=pk, address=printed, align="left",
          font="Helvetica-Bold", size=8)
    s.t(42, 306, "Property Type:", "Helvetica", 8)
    s.t(200, 306, "Two-unit residential (duplex)", "Helvetica-Bold", 8)
    s.t(42, 320, "Effective Date of Appraisal:", "Helvetica", 8)
    s.val(200, 320, as_of.strftime("%m/%d/%Y"), "appraisal.effective_date", as_of.isoformat(), "date", prop=pk,
          address=printed, align="left", font="Helvetica-Bold", size=8)
    s.t(42, 334, "Opinion of Market Value:", "Helvetica", 8)
    s.val(200, 334, f"${value:,}", "appraisal.market_value", value * 100, "cents", prop=pk, address=printed,
          align="left", font="Helvetica-Bold", size=8)
    s.t(42, 348, "Approaches Used:", "Helvetica", 8)
    s.t(200, 348, "Sales Comparison and Income", "Helvetica-Bold", 8)
    s.wrap(40, 384, "This letter summarizes the full appraisal report retained in our work file. The opinion of value "
           "is subject to the assumptions and limiting conditions contained in that report.", 530, size=8.5,
           leading=11)
    s.t(40, 430, "Respectfully submitted,", "Helvetica", 8.5)
    s.t(40, 460, "Dana Whitfield, Certified Residential Appraiser, CA License AR 038114", "Helvetica", 8.5)
    return s.save()
