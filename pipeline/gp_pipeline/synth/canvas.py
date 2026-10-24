"""A thin top-left-origin wrapper over a reportlab canvas that records gold labels as it draws.

Every value drawn through :meth:`Sheet.val` is written to ``self.fields`` with its page and its
bounding box (PDF points, origin top-left, same convention as the extractor), so the gold file
is produced by the same code that produces the pixels and can never drift from them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reportlab.lib.pagesizes import letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = letter  # 612 x 792


def money(d: int | None, parens: bool = True) -> str:
    """Whole-dollar form style: 12,310 or (7,578)."""
    if d is None:
        return ""
    if d < 0 and parens:
        return f"({abs(d):,})"
    return f"{d:,}"


def money_cents(c: int) -> str:
    """Statement style: $159,293.47."""
    sign = "-" if c < 0 else ""
    return f"{sign}${abs(c) / 100:,.2f}"


@dataclass
class GoldField:
    field: str
    value: Any
    unit: str
    page: int
    bbox: list[float]
    property_key: str | None = None  # gold key p1..p4, or None for household-level
    entity: str = "household"
    address_printed: str | None = None
    text: str = ""

    def as_dict(self) -> dict:
        return {
            "field": self.field,
            "value": self.value,
            "unit": self.unit,
            "page": self.page,
            "bbox": [round(v, 1) for v in self.bbox],
            "property_key": self.property_key,
            "entity": self.entity,
            "address_printed": self.address_printed,
            "text": self.text,
        }


@dataclass
class Sheet:
    path: str
    kind: str
    tax_year: int | None
    title: str = ""
    page: int = 1
    fields: list[GoldField] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.c = canvas.Canvas(self.path, pagesize=letter, invariant=1, pageCompression=1)
        self.c.setTitle(self.title or self.kind)
        self.c.setAuthor("Groundplan synthetic fixture")
        self.c.setCreator("gp_pipeline.synth")

    # ---------------------------------------------------------------- primitives (y = baseline from top)

    def t(self, x: float, y: float, s: str, font: str = "Helvetica", size: float = 7.0, gray: float = 0.0) -> float:
        self.c.setFillGray(gray)
        self.c.setFont(font, size)
        self.c.drawString(x, PAGE_H - y, s)
        self.c.setFillGray(0)
        return stringWidth(s, font, size)

    def rt(self, xr: float, y: float, s: str, font: str = "Helvetica", size: float = 7.0) -> None:
        self.c.setFont(font, size)
        self.c.drawRightString(xr, PAGE_H - y, s)

    def ct(self, xc: float, y: float, s: str, font: str = "Helvetica", size: float = 7.0) -> None:
        self.c.setFont(font, size)
        self.c.drawCentredString(xc, PAGE_H - y, s)

    def wrap(self, x: float, y: float, s: str, width: float, font: str = "Helvetica", size: float = 6.6,
             leading: float = 7.6) -> int:
        """Draw wrapped text; returns the number of lines used."""
        words = s.split()
        lines: list[str] = []
        cur = ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if stringWidth(trial, font, size) <= width:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        for i, ln in enumerate(lines):
            self.t(x, y + i * leading, ln, font, size)
        return len(lines)

    def hline(self, x0: float, x1: float, y: float, gray: float = 0.7, width: float = 0.35) -> None:
        self.c.setStrokeGray(gray)
        self.c.setLineWidth(width)
        self.c.line(x0, PAGE_H - y, x1, PAGE_H - y)
        self.c.setStrokeGray(0)

    def vline(self, x: float, y0: float, y1: float, gray: float = 0.7, width: float = 0.35) -> None:
        self.c.setStrokeGray(gray)
        self.c.setLineWidth(width)
        self.c.line(x, PAGE_H - y0, x, PAGE_H - y1)
        self.c.setStrokeGray(0)

    def rect(self, x0: float, y0: float, x1: float, y1: float, gray: float = 0.0, width: float = 0.6,
             fill: float | None = None) -> None:
        self.c.setStrokeGray(gray)
        self.c.setLineWidth(width)
        if fill is not None:
            self.c.setFillGray(fill)
        self.c.rect(x0, PAGE_H - y1, x1 - x0, y1 - y0, stroke=1, fill=1 if fill is not None else 0)
        self.c.setFillGray(0)
        self.c.setStrokeGray(0)

    def bar(self, y: float, label: str, title: str) -> None:
        """A black 'Part I' bar like the IRS forms."""
        self.rect(36, y - 9, 80, y + 3, fill=0)
        self.c.setFillGray(1)
        self.c.setFont("Helvetica-Bold", 8)
        self.c.drawString(40, PAGE_H - y, label)
        self.c.setFillGray(0)
        self.t(86, y, title, "Helvetica-Bold", 8)
        self.hline(36, 584, y + 3, gray=0, width=0.8)

    def checkbox(self, x: float, y: float, checked: bool) -> None:
        self.rect(x, y - 7, x + 7, y)
        if checked:
            self.t(x + 1.2, y - 0.8, "X", "Courier-Bold", 8)

    # ---------------------------------------------------------------- values with gold

    def val(
        self,
        xr: float,
        y: float,
        text: str,
        fieldname: str,
        value: Any,
        unit: str,
        prop: str | None = None,
        address: str | None = None,
        entity: str | None = None,
        font: str = "Courier-Bold",
        size: float = 8.6,
        align: str = "right",
    ) -> None:
        w = stringWidth(text, font, size)
        x0 = xr - w if align == "right" else xr
        self.c.setFont(font, size)
        self.c.drawString(x0, PAGE_H - y, text)
        bbox = [x0, y - size * 0.75, x0 + w, y + size * 0.22]
        self.fields.append(
            GoldField(
                field=fieldname,
                value=value,
                unit=unit,
                page=self.page,
                bbox=bbox,
                property_key=prop,
                entity=entity or ("property" if prop else "household"),
                address_printed=address,
                text=text,
            )
        )

    def newpage(self) -> None:
        self.c.showPage()
        self.page += 1

    def save(self) -> dict:
        self.c.showPage()
        self.c.save()
        return {"kind": self.kind, "tax_year": self.tax_year, "pages": self.page,
                "fields": [f.as_dict() for f in self.fields]}

    def header_irs(self, form_word: str, form_no: str, title: str, subtitle: list[str], year: int, seq: str,
                   omb: str = "OMB No. 1545-0074") -> float:
        """Common IRS header block; returns the y below it."""
        self.t(36, 46, form_word, "Helvetica-Bold", 11)
        self.t(36, 58, form_no, "Helvetica", 8)
        self.t(36, 72, "Department of the Treasury", "Helvetica", 6)
        self.t(36, 79, "Internal Revenue Service", "Helvetica", 6)
        self.ct(306, 48, title, "Helvetica-Bold", 12)
        for i, s in enumerate(subtitle):
            self.ct(306, 60 + i * 8, s, "Helvetica", 6.5)
        self.t(500, 44, omb, "Helvetica", 6)
        self.t(506, 66, str(year), "Helvetica-Bold", 20)
        self.t(500, 79, seq, "Helvetica", 6)
        self.hline(36, 584, 84, gray=0, width=1.0)
        return 96
