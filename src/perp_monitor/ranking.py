"""Top-N rankings for the report.

OI rankings skip new listings (nothing to compare with). Funding rankings skip rates of
exactly zero, which are common on Binance stock perps, so a list can be shorter than N.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from perp_monitor.models import MarketChange

Key = Callable[[MarketChange], float]


def _top(
    changes: Iterable[MarketChange], keep: Callable[[MarketChange], bool], key: Key, n: int
) -> tuple[MarketChange, ...]:
    picked = [c for c in changes if keep(c)]
    return tuple(sorted(picked, key=lambda c: (key(c), c.current.ticker))[:n])


def _d_oi(change: MarketChange) -> float:
    return change.d_oi_usd or 0.0


def top_oi_gainers(changes: Iterable[MarketChange], n: int) -> tuple[MarketChange, ...]:
    return _top(changes, lambda c: _d_oi(c) > 0, lambda c: -_d_oi(c), n)


def top_oi_losers(changes: Iterable[MarketChange], n: int) -> tuple[MarketChange, ...]:
    return _top(changes, lambda c: _d_oi(c) < 0, _d_oi, n)


def top_negative_funding(changes: Iterable[MarketChange], n: int) -> tuple[MarketChange, ...]:
    return _top(changes, lambda c: c.current.funding_8h < 0, lambda c: c.current.funding_8h, n)


def top_positive_funding(changes: Iterable[MarketChange], n: int) -> tuple[MarketChange, ...]:
    return _top(changes, lambda c: c.current.funding_8h > 0, lambda c: -c.current.funding_8h, n)
