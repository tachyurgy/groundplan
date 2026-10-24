"""Hand-rolled US address normalization (usaddress-style, no dependency) and fuzzy similarity.

``normalize("1420 MAPLE STREET UNIT A/B, SACRAMENTO, CA 95838")`` ->
``ParsedAddress(number='1420', street='maple st', unit='a/b', city='sacramento', state='ca', zip='95838')``
and ``.key()`` -> ``"1420 maple st, sacramento, ca 95838"``.

The key deliberately drops a multi-dwelling unit range ("A/B", "A-B") because that designates the
whole building, but keeps a single unit ("Unit 204") because a condo unit is its own property.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

SUFFIX = {
    "street": "st", "str": "st", "st": "st", "avenue": "ave", "av": "ave", "ave": "ave", "drive": "dr", "drv": "dr",
    "dr": "dr", "court": "ct", "crt": "ct", "ct": "ct", "road": "rd", "rd": "rd", "lane": "ln", "ln": "ln",
    "boulevard": "blvd", "blvd": "blvd", "place": "pl", "pl": "pl", "circle": "cir", "cir": "cir",
    "terrace": "ter", "ter": "ter", "parkway": "pkwy", "pkwy": "pkwy", "highway": "hwy", "hwy": "hwy",
    "way": "way", "trail": "trl", "trl": "trl", "square": "sq", "sq": "sq", "loop": "loop",
}
DIRECTIONAL = {"north": "n", "south": "s", "east": "e", "west": "w", "northeast": "ne", "northwest": "nw",
               "southeast": "se", "southwest": "sw", "n": "n", "s": "s", "e": "e", "w": "w"}
UNIT_WORDS = {"unit", "apt", "apartment", "ste", "suite", "#", "no", "bldg", "building", "spc", "space"}
STATES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga", "hi", "id", "il", "in", "ia", "ks", "ky", "la",
    "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or",
    "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
}
STATE_NAMES = {"california": "ca", "washington": "wa", "oregon": "or", "nevada": "nv", "texas": "tx"}


@dataclass(frozen=True)
class ParsedAddress:
    number: str
    street: str
    unit: str
    city: str
    state: str
    zip: str
    raw: str

    def key(self) -> str:
        unit = f" unit {self.unit}" if self.unit and not _is_multi_unit(self.unit) else ""
        parts = [f"{self.number} {self.street}".strip() + unit]
        tail = " ".join(x for x in (self.state, self.zip) if x)
        if self.city:
            parts.append(self.city)
        if tail:
            parts.append(tail)
        return ", ".join(p for p in parts if p)

    def street_line(self) -> str:
        return f"{self.number} {self.street}".strip()


def _is_multi_unit(u: str) -> bool:
    return bool(re.search(r"[/&-]|\band\b", u))


def _clean(s: str) -> str:
    s = s.lower().replace("–", "-").replace("—", "-")
    s = re.sub(r"#\s*", " # ", s)
    s = re.sub(r"[^\w\s,/#&-]", " ", s)  # drop periods etc.
    return re.sub(r"\s+", " ", s).strip()


def normalize(raw: str) -> ParsedAddress:
    s = _clean(raw)
    # split off "city, st zip" from the right
    zip_ = ""
    m = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", s)
    if m:
        zip_ = m.group(1)
        s = s[: m.start()].strip(" ,")
    state = ""
    m = re.search(r"(?:,|\s)\s*([a-z]{2}|" + "|".join(STATE_NAMES) + r")\s*$", s)
    if m and (m.group(1) in STATES or m.group(1) in STATE_NAMES):
        state = STATE_NAMES.get(m.group(1), m.group(1))
        s = s[: m.start()].strip(" ,")
    city = ""
    if "," in s:
        s, city = s.rsplit(",", 1)
        # "street, unit x, city" -> keep unit with the street part
        city = city.strip()
        s = s.strip()
    tokens = s.replace(",", " ").split()
    number = ""
    if tokens and re.fullmatch(r"\d+[a-z]?", tokens[0]):
        number = tokens.pop(0)
    unit = ""
    for i, t in enumerate(tokens):
        if t in UNIT_WORDS:
            rest = [x for x in tokens[i + 1 :] if x not in UNIT_WORDS]
            unit = rest[0] if rest else ""
            if not city and len(rest) > 1:  # "Unit 204 Elk Grove CA" with the comma lost
                city = " ".join(rest[1:])
            tokens = tokens[:i]
            break
    out = []
    for i, t in enumerate(tokens):
        if t in DIRECTIONAL and (i == 0 or i == len(tokens) - 1):
            out.append(DIRECTIONAL[t])
        elif i == len(tokens) - 1 and t in SUFFIX:
            out.append(SUFFIX[t])
        else:
            out.append(t)
    return ParsedAddress(number=number, street=" ".join(out), unit=unit.strip(), city=city, state=state,
                         zip=zip_, raw=raw)


def key(raw: str) -> str:
    return normalize(raw).key()


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def token_set_ratio(a: str, b: str) -> float:
    """rapidfuzz-style token_set_ratio in [0, 1] built on difflib."""
    ta, tb = set(a.split()), set(b.split())
    inter = " ".join(sorted(ta & tb))
    da = " ".join(sorted(ta - tb))
    db = " ".join(sorted(tb - ta))
    s1 = inter
    s2 = f"{inter} {da}".strip()
    s3 = f"{inter} {db}".strip()
    if not s2 and not s3:
        return 1.0
    return max(_ratio(s1, s2) if s1 else 0.0, _ratio(s1, s3) if s1 else 0.0, _ratio(s2, s3))


def similarity(a: ParsedAddress, b: ParsedAddress) -> float:
    """Address similarity with hard vetoes: different house numbers, ZIPs (beyond one OCR digit)
    or distinct single units never match."""
    if a.number and b.number and a.number != b.number and _ratio(a.number, b.number) < 0.75:
        return 0.0
    if a.zip and b.zip and a.zip != b.zip and sum(x != y for x, y in zip(a.zip, b.zip, strict=False)) > 1:
        return 0.0
    if a.unit and b.unit and not _is_multi_unit(a.unit) and not _is_multi_unit(b.unit) and a.unit != b.unit:
        return 0.0
    street = token_set_ratio(a.street_line(), b.street_line())
    city = token_set_ratio(a.city, b.city) if a.city and b.city else 0.9
    return round(0.75 * street + 0.25 * city, 4)
