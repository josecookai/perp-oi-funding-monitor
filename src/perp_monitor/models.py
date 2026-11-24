"""Immutable data model shared by the clients, store, delta and report modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from perp_monitor.funding import to_8h, to_apr


class Venue(StrEnum):
    BINANCE = "binance"
    HYPERLIQUID = "hyperliquid"

    @property
    def label(self) -> str:
        return "Binance" if self is Venue.BINANCE else "Hyperliquid"


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """One stock perp market at one point in time.

    `source` records where the row came from (e.g. "binance:EQUITY", "hl:xyz") so the
    report guard can prove every row came from a stock market, not a crypto one.
    """

    venue: Venue
    source: str
    market: str
    ticker: str
    oi_contracts: float
    mark_price: float
    funding_rate: float
    funding_interval_hours: float
    volume_24h_usd: float

    @property
    def oi_usd(self) -> float:
        return self.oi_contracts * self.mark_price

    @property
    def funding_8h(self) -> float:
        return to_8h(self.funding_rate, self.funding_interval_hours)

    @property
    def funding_apr(self) -> float:
        return to_apr(self.funding_rate, self.funding_interval_hours)


@dataclass(frozen=True, slots=True)
class PriorPoint:
    """The previous observation a market is compared against."""

    oi_contracts: float
    oi_usd: float
    funding_8h: float | None
    observed_at: datetime
    origin: str  # "store" or "binance_oi_hist"


@dataclass(frozen=True, slots=True)
class MarketChange:
    current: MarketSnapshot
    prior: PriorPoint | None

    @property
    def is_new(self) -> bool:
        return self.prior is None

    @property
    def d_oi_usd(self) -> float | None:
        return None if self.prior is None else self.current.oi_usd - self.prior.oi_usd

    @property
    def d_oi_pct(self) -> float | None:
        return _pct_change(self.current.oi_usd, None if self.prior is None else self.prior.oi_usd)

    @property
    def d_contracts_pct(self) -> float | None:
        previous = None if self.prior is None else self.prior.oi_contracts
        return _pct_change(self.current.oi_contracts, previous)

    @property
    def d_funding_8h(self) -> float | None:
        if self.prior is None or self.prior.funding_8h is None:
            return None
        return self.current.funding_8h - self.prior.funding_8h


@dataclass(frozen=True, slots=True)
class Window:
    """How far apart the current and previous observations are."""

    hours: float | None
    expected_hours: float
    tolerance_hours: float
    origin: str | None  # "store", "binance_oi_hist", or None for a baseline run

    @property
    def is_baseline(self) -> bool:
        return self.hours is None

    @property
    def in_range(self) -> bool:
        if self.hours is None:
            return True
        return abs(self.hours - self.expected_hours) <= self.tolerance_hours


def _pct_change(current: float, previous: float | None) -> float | None:
    if previous is None or previous == 0:
        return None
    return (current - previous) / previous
