"""Pure, deterministic engine. No I/O, Decimal math, integer cents out, provenance on every Figure.

Rounding rule (shared with the Go port): all intermediate arithmetic is exact Decimal; a value is rounded
HALF-UP to the cent exactly once, when it becomes the value of a Figure or a schedule row.
"""

from groundplan.engine.figure import Figure, Input, Source, cents, pct, rate_str

__all__ = ["Figure", "Input", "Source", "cents", "pct", "rate_str"]
