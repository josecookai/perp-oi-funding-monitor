"""Funding-rate normalization.

Venues settle funding on different intervals (Hyperliquid hourly, Binance 4h or 8h per
symbol), so every rate is converted to an 8h-equivalent before ranking or comparison.
"""

from __future__ import annotations

HOURS_PER_YEAR = 24 * 365
REFERENCE_HOURS = 8


def _check_interval(interval_hours: float) -> None:
    if interval_hours <= 0:
        raise ValueError(f"funding interval must be positive, got {interval_hours}")


def to_8h(rate: float, interval_hours: float) -> float:
    """Rate paid per `interval_hours` -> equivalent rate per 8 hours."""
    _check_interval(interval_hours)
    return rate * REFERENCE_HOURS / interval_hours


def to_apr(rate: float, interval_hours: float) -> float:
    """Rate paid per `interval_hours` -> simple (non-compounded) annual rate."""
    _check_interval(interval_hours)
    return rate * HOURS_PER_YEAR / interval_hours
