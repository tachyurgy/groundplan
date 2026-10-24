"""Entity resolution: which printed addresses (across years and documents) are the same property.

1. Every address mention (Schedule E line 1a, Form 4562 activity, 8582 worksheet names, mortgage
   statements, the closing statement, the appraisal) is normalized (``address.normalize``).
2. Mentions are clustered greedily, Schedule E first (the return is the spine), oldest year first.
   A mention joins the best cluster when ``similarity >= THRESHOLD`` (token-set ratio on the street
   line, weighted with the city; vetoed on different house numbers, ZIPs or distinct single units).
3. Ties within ``TIE_MARGIN`` are broken by the Schedule E property-type code (line 1b).
4. Each cluster's canonical key is the most common normalized key among its Schedule E mentions.

The result is a :class:`PropertyMatch` per distinct raw address, with the runner-up clusters as
alternative candidates so a reviewer can see why a mention landed where it did.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from gp_pipeline.address import ParsedAddress, normalize, similarity
from gp_pipeline.models import ExtractedField, PropertyMatch

THRESHOLD = 0.85
TIE_MARGIN = 0.03
KIND_PRIORITY = {"schedule_e": 0, "form_4562": 1, "form_8582": 2, "closing_statement": 3, "mortgage_statement": 4,
                 "appraisal": 5}


@dataclass
class Mention:
    raw: str
    parsed: ParsedAddress
    kind: str
    year: int | None
    type_code: int | None = None


@dataclass
class Cluster:
    members: list[Mention] = field(default_factory=list)

    def score(self, m: Mention) -> float:
        return max(similarity(m.parsed, x.parsed) for x in self.members)

    def type_codes(self) -> set[int]:
        return {x.type_code for x in self.members if x.type_code is not None}

    def canonical(self) -> str:
        se = [x.parsed.key() for x in self.members if x.kind == "schedule_e"] or [x.parsed.key() for x in self.members]
        return Counter(se).most_common(1)[0][0]


def mentions_from_fields(fields: list[ExtractedField]) -> list[Mention]:
    types: dict[tuple[str, str], int] = {}
    for f in fields:
        if f.field == "schedule_e.line1b.type" and f.address_raw:
            types[(f.document_key, f.address_raw)] = int(f.value)
    seen: set[tuple[str, str]] = set()
    out: list[Mention] = []
    for f in fields:
        if not f.address_raw or (f.document_key, f.address_raw) in seen:
            continue
        seen.add((f.document_key, f.address_raw))
        out.append(Mention(f.address_raw, normalize(f.address_raw), f.document_kind or "", f.tax_year,
                           types.get((f.document_key, f.address_raw))))
    return out


def resolve(fields: list[ExtractedField]) -> tuple[dict[str, PropertyMatch], list[str]]:
    """Return {raw address -> PropertyMatch} and the canonical keys in first-seen order."""
    mentions = sorted(mentions_from_fields(fields), key=lambda m: (KIND_PRIORITY.get(m.kind, 9), m.year or 0))
    clusters: list[Cluster] = []
    placed: list[tuple[Mention, int, float]] = []
    for m in mentions:
        scored = sorted(((c.score(m), i) for i, c in enumerate(clusters)), reverse=True)
        choice, conf = None, 1.0
        if scored and scored[0][0] >= THRESHOLD:
            choice, conf = scored[0][1], scored[0][0]
            close = [i for s, i in scored if s >= THRESHOLD and scored[0][0] - s <= TIE_MARGIN]
            if len(close) > 1 and m.type_code is not None:
                same_type = [i for i in close if m.type_code in clusters[i].type_codes()]
                if same_type:
                    choice = same_type[0]
        if choice is None:
            clusters.append(Cluster([m]))
            choice = len(clusters) - 1
        else:
            clusters[choice].members.append(m)
        placed.append((m, choice, conf))
    canon = [c.canonical() for c in clusters]
    matches: dict[str, PropertyMatch] = {}
    for m, ci, conf in placed:
        alts = [{"property_key": canon[i], "score": round(clusters[i].score(m), 3)} for i in range(len(clusters))
                if i != ci]
        alts = sorted([a for a in alts if a["score"] > 0.4], key=lambda a: -a["score"])[:3]
        matches[m.raw] = PropertyMatch(raw_address=m.raw, normalized=m.parsed.key(), property_key=canon[ci],
                                       confidence=round(conf, 3), candidates=alts)
    return matches, canon


def apply(fields: list[ExtractedField], matches: dict[str, PropertyMatch]) -> None:
    for f in fields:
        if f.address_raw and f.address_raw in matches:
            f.property_key = matches[f.address_raw].property_key
