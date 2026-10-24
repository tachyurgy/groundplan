"""Layout helpers shared by the form extractors: rows, anchors, token parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from gp_pipeline.models import Page, Word

MONEY_RE = re.compile(r"^\(?-?\$?\d{1,3}(,\d{3})*(\.\d{2})?\)?$|^\(?-?\$?\d+(\.\d{2})?\)?$")
DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
MONTH_YEAR_RE = re.compile(r"^(\d{1,2})/(\d{4})$")
RATE_RE = re.compile(r"^(\d{1,2}\.\d{1,4})%$")

# OCR confusions that only make sense inside an otherwise-numeric token
OCR_DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "|": "1", "S": "5", "B": "8",
                               "Z": "2", "§": "5", "€": "6"})


@dataclass
class Row:
    words: list[Word]
    top: float
    bottom: float

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    def right_of(self, x: float) -> list[Word]:
        return [w for w in self.words if w.x0 >= x]


def group_rows(words: list[Word], tol: float | None = None) -> list[Row]:
    """Cluster words into visual rows by vertical centre."""
    if not words:
        return []
    heights = sorted(w.bottom - w.top for w in words)
    med = heights[len(heights) // 2] or 6.0
    tol = tol if tol is not None else max(2.5, med * 0.55)
    ws = sorted(words, key=lambda w: ((w.top + w.bottom) / 2, w.x0))
    rows: list[list[Word]] = []
    centers: list[float] = []
    for w in ws:
        c = (w.top + w.bottom) / 2
        if rows and abs(c - centers[-1]) <= tol:
            rows[-1].append(w)
            centers[-1] = sum((x.top + x.bottom) / 2 for x in rows[-1]) / len(rows[-1])
        else:
            rows.append([w])
            centers.append(c)
    out = []
    for r in rows:
        r.sort(key=lambda w: w.x0)
        out.append(Row(r, min(w.top for w in r), max(w.bottom for w in r)))
    return out


def words_in_band(page: Page, cy: float, half: float, x_min: float = 0, x_max: float = 1e9) -> list[Word]:
    return sorted(
        [w for w in page.words if abs((w.top + w.bottom) / 2 - cy) <= half and w.x0 >= x_min and w.x1 <= x_max],
        key=lambda w: w.x0,
    )


def clean_numeric(t: str) -> tuple[str, bool]:
    """Apply OCR digit fixes to tokens that are mostly digits. Returns (text, corrected?)."""
    core = t.strip("$()-.,:;")
    if not core:
        return t, False
    digits = sum(ch.isdigit() for ch in core)
    if digits >= max(1, int(len(core) * 0.6)) and digits < len(core):
        fixed = t.translate(OCR_DIGIT_FIX)
        return fixed, fixed != t
    return t, False


def parse_money(t: str) -> int | None:
    """Return whole cents for '12,310', '(7,578)', '$159,293.47', '-1,021'. None if not money."""
    t = t.strip().rstrip(".,;:")
    t = t.replace("$ ", "$")
    if not t or not MONEY_RE.match(t):
        return None
    neg = t.startswith("(") or t.startswith("-") or t.endswith(")")
    core = t.strip("()$-").replace(",", "")
    if core.startswith("$"):
        core = core[1:]
    try:
        if "." in core:
            whole, frac = core.split(".")
            cents = int(whole) * 100 + int(frac)
        else:
            cents = int(core) * 100
    except ValueError:
        return None
    return -cents if neg else cents


def merge_money_tokens(words: list[Word], gap: float = 4.0) -> list[Word]:
    """Join tokens OCR split inside a number ('12,' '310', '(7,' '578)', '$' '1,234.00')."""
    out: list[Word] = []
    for w in sorted(words, key=lambda w: w.x0):
        if out:
            prev = out[-1]
            g = w.x0 - prev.x1
            joinable = g <= gap and (
                prev.text.endswith(",") or prev.text in ("$", "(", "($") or w.text.startswith(",")
                or (prev.text.startswith("(") and not prev.text.endswith(")"))
            )
            # "49 800": a comma OCR read as a space between a 1-3 digit group and a 3-digit group
            comma_lost = (g <= gap * 2.2 and re.fullmatch(r"\(?\$?\d{1,3}", prev.text)
                          and re.fullmatch(r"\d{3}(\.\d{2})?\)?", w.text))
            if joinable or comma_lost:
                sep = "," if comma_lost and not joinable else ""
                out[-1] = Word(text=prev.text + sep + w.text, x0=prev.x0, top=min(prev.top, w.top), x1=w.x1,
                               bottom=max(prev.bottom, w.bottom), conf=min(prev.conf, w.conf) * (0.9 if sep else 1))
                continue
        out.append(w)
    return out


def parse_date(t: str) -> str | None:
    m = DATE_RE.match(t.strip().rstrip(".,"))
    if not m:
        return None
    mo, d, y = (int(g) for g in m.groups())
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def parse_rate(t: str) -> float | None:
    m = RATE_RE.match(t.strip().rstrip(".,"))
    return round(float(m.group(1)) / 100, 6) if m else None


def bbox_of(words: list[Word]) -> list[float]:
    return [min(w.x0 for w in words), min(w.top for w in words), max(w.x1 for w in words),
            max(w.bottom for w in words)]


def conf_of(words: list[Word], base: float, corrected: bool = False) -> float:
    c = min(w.conf for w in words) if words else 0.0
    c = base * (0.55 + 0.45 * c)
    if corrected:
        c *= 0.8
    return round(min(c, 0.99), 3)
