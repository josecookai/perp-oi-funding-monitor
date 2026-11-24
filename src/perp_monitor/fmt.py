"""Number formatting for human-readable reports."""

from __future__ import annotations

MISSING = "—"
_UNITS = ((1e9, "B"), (1e6, "M"), (1e3, "K"))


def usd(value: float) -> str:
    magnitude = abs(value)
    for size, suffix in _UNITS:
        if magnitude >= size:
            scaled = magnitude / size
            digits = 2 if scaled < 10 else 1 if scaled < 100 else 0
            return f"{'-' if value < 0 else ''}${scaled:.{digits}f}{suffix}"
    return f"{'-' if value < 0 else ''}${magnitude:.0f}"


def signed_usd(value: float | None) -> str:
    if value is None:
        return MISSING
    return ("+" if value >= 0 else "") + usd(value)


def pct(value: float | None, *, signed: bool = True, digits: int = 1) -> str:
    if value is None:
        return MISSING
    sign = "+" if signed and value != 0 else ""
    return f"{value * 100:{sign}.{digits}f}%"


def rate(value: float | None) -> str:
    """A funding rate (e.g. 0.000125) as a signed percent with 4 decimals."""
    return pct(value, digits=4)


def hours(value: float) -> str:
    return f"{value:.1f}h"
