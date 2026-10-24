"""Figure: the API shape for any computed number, with provenance.

A Figure is confirmed only if every input came from a document or manual entry, estimated if any input is
public_data or default, and blocked if an open blocking Finding touches an input. Child Figures propagate the
worst status upward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

SOURCE_TYPES = ("document", "manual", "public_data", "default", "figure")
STATUS_ORDER = {"confirmed": 0, "estimated": 1, "blocked": 2}

ONE_CENT = Decimal("1")


def cents(x: Decimal | int | float | str) -> int:
    """Round a Decimal amount of cents half-up to an integer number of cents (the only rounding point)."""
    if isinstance(x, int):
        return x
    d = x if isinstance(x, Decimal) else Decimal(repr(x) if isinstance(x, float) else str(x))
    return int(d.quantize(ONE_CENT, rounding=ROUND_HALF_UP))


def D(x: Any) -> Decimal:  # noqa: N802 - short constructor name on purpose
    """Exact Decimal from ints, strings and floats (floats go through repr, never binary expansion)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(repr(x))
    return Decimal(x)


def pct(x: Decimal | str | float) -> Decimal:
    """A percentage expressed as a fraction, e.g. pct('3.485') -> Decimal('0.03485')."""
    return D(x) / Decimal(100)


def rate_str(x: Decimal | float | None, places: int = 6) -> str | None:
    if x is None:
        return None
    q = Decimal(1).scaleb(-places)
    return str(D(x).quantize(q, rounding=ROUND_HALF_UP))


@dataclass
class Source:
    type: str = "manual"  # document | manual | public_data | default | figure
    ref: str | None = None  # document id / "Schedule E line 3" / figure key / rule name
    page: int | None = None
    document_id: str | None = None
    bbox: list[float] | None = None

    def __post_init__(self) -> None:
        if self.type not in SOURCE_TYPES:
            raise ValueError(f"unknown source type {self.type!r}")


@dataclass
class Input:
    key: str
    value: Any
    source: Source = field(default_factory=Source)
    status: str | None = None  # only set when the input is itself a Figure
    child: Figure | None = field(default=None, repr=False, compare=False)  # the child Figure (inputs tree)
    label: str | None = None

    def to_dict(self, depth: int = 1) -> dict[str, Any]:
        src = {"type": self.source.type, "ref": self.source.ref, "page": self.source.page}
        if self.source.document_id:
            src["document_id"] = self.source.document_id
        if self.source.bbox:
            src["bbox"] = self.source.bbox
        d: dict[str, Any] = {"key": self.key, "value": self.value, "source": src}
        if self.status is not None:
            d["status"] = self.status
        if self.label:
            d["label"] = self.label
        if self.child is not None and depth > 0:
            d["figure"] = self.child.to_dict(depth - 1)
        return d

    @classmethod
    def of(cls, key: str, value: Any, src: str = "manual", ref: str | None = None, page: int | None = None) -> Input:
        return cls(key=key, value=_jsonable(value), source=Source(type=src, ref=ref, page=page))

    @classmethod
    def figure(cls, fig: Figure) -> Input:
        return cls(
            key=fig.key,
            value=fig.value_cents if fig.value_cents is not None else fig.value,
            source=Source(type="figure", ref=fig.key),
            status=fig.status,
            child=fig,
        )


@dataclass
class Figure:
    key: str
    value_cents: int | None = None
    status: str = "confirmed"
    inputs: list[Input] = field(default_factory=list)
    formula: str = ""
    notes: list[str] = field(default_factory=list)
    value: str | None = None  # for non-money figures (rates, ratios, years) as a decimal string
    unit: str = "cents"  # cents | rate | ratio | years | count

    def __post_init__(self) -> None:
        if self.status not in STATUS_ORDER:
            raise ValueError(f"unknown status {self.status!r}")

    @property
    def dec(self) -> Decimal:
        """Value as a Decimal (cents for money figures, the raw value otherwise)."""
        if self.value_cents is not None:
            return Decimal(self.value_cents)
        return D(self.value) if self.value is not None else Decimal(0)

    def to_dict(self, depth: int = 1) -> dict[str, Any]:
        """JSON shape. `depth` = how many levels of child Figures to inline under inputs[].figure."""
        d: dict[str, Any] = {"key": self.key, "value_cents": self.value_cents, "status": self.status,
                             "inputs": [i.to_dict(depth) for i in self.inputs], "formula": self.formula,
                             "notes": list(self.notes), "unit": self.unit}
        if self.unit != "cents":
            d["value"] = self.value
        return d

    def walk(self):
        """Yield this Figure and every descendant Figure (depth-first)."""
        yield self
        for i in self.inputs:
            if i.child is not None:
                yield from i.child.walk()


def derive_status(inputs: list[Input], blocked_keys: set[str] | frozenset[str] | None = None) -> str:
    """Confirmed unless any input is public_data/default (estimated) or touches a blocking Finding (blocked)."""
    worst = "confirmed"
    for inp in inputs:
        s = "confirmed"
        if blocked_keys and inp.key in blocked_keys:
            s = "blocked"
        elif inp.source.type == "figure":
            s = inp.status or "confirmed"
        elif inp.source.type in ("public_data", "default"):
            s = "estimated"
        if STATUS_ORDER[s] > STATUS_ORDER[worst]:
            worst = s
    return worst


def money(
    key: str,
    amount: Decimal | int,
    inputs: list[Input],
    formula: str,
    notes: list[str] | None = None,
    blocked_keys: set[str] | None = None,
) -> Figure:
    """Build a money Figure: rounds once, derives status from inputs."""
    return Figure(
        key=key,
        value_cents=cents(amount),
        status=derive_status(inputs, blocked_keys),
        inputs=inputs,
        formula=formula,
        notes=list(notes or []),
    )


def ratio(
    key: str,
    value: Decimal | None,
    inputs: list[Input],
    formula: str,
    unit: str = "rate",
    notes: list[str] | None = None,
    places: int = 6,
) -> Figure:
    return Figure(
        key=key,
        value_cents=None,
        value=rate_str(value, places),
        unit=unit,
        status=derive_status(inputs),
        inputs=inputs,
        formula=formula,
        notes=list(notes or []),
    )


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v
