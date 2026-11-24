"""Report model: per-venue sections with rankings, plus a cross-venue comparison."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from perp_monitor.models import MarketChange, Venue, Window
from perp_monitor.ranking import (
    top_negative_funding,
    top_oi_gainers,
    top_oi_losers,
    top_positive_funding,
)


@dataclass(frozen=True, slots=True)
class VenueInput:
    venue: Venue
    label: str
    changes: tuple[MarketChange, ...]
    window: Window
    error: str | None = None


@dataclass(frozen=True, slots=True)
class VenueSection:
    venue: Venue
    label: str
    window: Window
    error: str | None
    changes: tuple[MarketChange, ...]
    gainers: tuple[MarketChange, ...]
    losers: tuple[MarketChange, ...]
    negative: tuple[MarketChange, ...]
    positive: tuple[MarketChange, ...]

    @property
    def total_oi_usd(self) -> float:
        return sum(c.current.oi_usd for c in self.changes)

    @property
    def matched_d_oi_usd(self) -> float | None:
        """Total OI change over markets present in both observations."""
        deltas = [c.d_oi_usd for c in self.changes if c.d_oi_usd is not None]
        return sum(deltas) if deltas else None

    @property
    def matched_prior_oi_usd(self) -> float | None:
        priors = [c.prior.oi_usd for c in self.changes if c.prior is not None]
        return sum(priors) if priors else None


@dataclass(frozen=True, slots=True)
class CrossRow:
    ticker: str
    binance: MarketChange
    hyperliquid: MarketChange

    @property
    def funding_spread_8h(self) -> float:
        """Hyperliquid minus Binance, both as 8h-equivalent rates."""
        return self.hyperliquid.current.funding_8h - self.binance.current.funding_8h


@dataclass(frozen=True, slots=True)
class Report:
    generated_at: datetime
    manual: bool
    top_n: int
    allowlist_size: int
    sections: tuple[VenueSection, ...]
    cross: tuple[CrossRow, ...]

    def section(self, venue: Venue) -> VenueSection | None:
        return next((s for s in self.sections if s.venue is venue), None)


def _section(item: VenueInput, top_n: int) -> VenueSection:
    changes = item.changes
    return VenueSection(
        venue=item.venue,
        label=item.label,
        window=item.window,
        error=item.error,
        changes=changes,
        gainers=top_oi_gainers(changes, top_n),
        losers=top_oi_losers(changes, top_n),
        negative=top_negative_funding(changes, top_n),
        positive=top_positive_funding(changes, top_n),
    )


def _largest_by_ticker(changes: Sequence[MarketChange]) -> dict[str, MarketChange]:
    best: dict[str, MarketChange] = {}
    for c in changes:
        held = best.get(c.current.ticker)
        if held is None or c.current.oi_usd > held.current.oi_usd:
            best[c.current.ticker] = c
    return best


def _cross(sections: Sequence[VenueSection]) -> tuple[CrossRow, ...]:
    by_venue = {s.venue: _largest_by_ticker(s.changes) for s in sections}
    binance = by_venue.get(Venue.BINANCE, {})
    hyperliquid = by_venue.get(Venue.HYPERLIQUID, {})
    rows = [CrossRow(t, binance[t], hyperliquid[t]) for t in binance.keys() & hyperliquid.keys()]
    total = lambda r: r.binance.current.oi_usd + r.hyperliquid.current.oi_usd  # noqa: E731
    return tuple(sorted(rows, key=lambda r: (-total(r), r.ticker)))


def build_report(
    *,
    generated_at: datetime,
    manual: bool,
    top_n: int,
    allowlist_size: int,
    inputs: Sequence[VenueInput],
) -> Report:
    sections = tuple(_section(item, top_n) for item in inputs)
    return Report(
        generated_at=generated_at,
        manual=manual,
        top_n=top_n,
        allowlist_size=allowlist_size,
        sections=sections,
        cross=_cross(sections),
    )
