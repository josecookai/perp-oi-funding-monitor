"""Small builders for synthetic snapshots used across unit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from perp_monitor.models import MarketChange, MarketSnapshot, PriorPoint, Venue

T0 = datetime(2026, 11, 24, 0, 0, tzinfo=UTC)
T8 = T0 + timedelta(hours=8)


def snap(
    ticker: str,
    oi: float = 1000.0,
    price: float = 100.0,
    funding: float = 0.0,
    venue: Venue = Venue.BINANCE,
    interval: float | None = None,
    volume: float = 5e6,
) -> MarketSnapshot:
    binance = venue is Venue.BINANCE
    return MarketSnapshot(
        venue=venue,
        source="binance:EQUITY" if binance else "hl:xyz",
        market=f"{ticker}USDT" if binance else f"xyz:{ticker}",
        ticker=ticker,
        oi_contracts=oi,
        mark_price=price,
        funding_rate=funding,
        funding_interval_hours=interval if interval is not None else (8.0 if binance else 1.0),
        volume_24h_usd=volume,
    )


def prior(
    oi: float, price: float = 100.0, funding_8h: float | None = 0.0, at: datetime = T0
) -> PriorPoint:
    return PriorPoint(
        oi_contracts=oi, oi_usd=oi * price, funding_8h=funding_8h, observed_at=at, origin="store"
    )


def change(
    ticker: str,
    oi_now: float,
    oi_before: float | None,
    price: float = 100.0,
    funding: float = 0.0,
    venue: Venue = Venue.BINANCE,
) -> MarketChange:
    before = None if oi_before is None else prior(oi_before, price)
    return MarketChange(snap(ticker, oi_now, price, funding, venue), before)
