"""Machine-readable report (one JSON file per run) for the future dashboard."""

from __future__ import annotations

from typing import Any

from perp_monitor.models import MarketChange
from perp_monitor.report import Report, VenueSection

SCHEMA_VERSION = 1


def _row(c: MarketChange) -> dict[str, Any]:
    s = c.current
    return {
        "ticker": s.ticker,
        "market": s.market,
        "source": s.source,
        "is_new": c.is_new,
        "oi_contracts": s.oi_contracts,
        "mark_price": s.mark_price,
        "oi_usd": s.oi_usd,
        "prior_oi_usd": None if c.prior is None else c.prior.oi_usd,
        "d_oi_usd": c.d_oi_usd,
        "d_oi_pct": c.d_oi_pct,
        "d_contracts_pct": c.d_contracts_pct,
        "funding_rate": s.funding_rate,
        "funding_interval_hours": s.funding_interval_hours,
        "funding_8h": s.funding_8h,
        "funding_apr": s.funding_apr,
        "d_funding_8h": c.d_funding_8h,
        "volume_24h_usd": s.volume_24h_usd,
    }


def _tickers(items: tuple[MarketChange, ...]) -> list[str]:
    return [c.current.ticker for c in items]


def _section(s: VenueSection) -> dict[str, Any]:
    w = s.window
    return {
        "venue": s.venue.value,
        "label": s.label,
        "error": s.error,
        "window": {
            "hours": w.hours,
            "expected_hours": w.expected_hours,
            "in_range": w.in_range,
            "origin": w.origin,
        },
        "total_oi_usd": s.total_oi_usd,
        "matched_d_oi_usd": s.matched_d_oi_usd,
        "rankings": {
            "oi_gain": _tickers(s.gainers),
            "oi_loss": _tickers(s.losers),
            "funding_negative": _tickers(s.negative),
            "funding_positive": _tickers(s.positive),
        },
        "rows": [_row(c) for c in s.changes],
    }


def report_to_json(report: Report) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": report.generated_at.isoformat(),
        "manual": report.manual,
        "top_n": report.top_n,
        "allowlist_size": report.allowlist_size,
        "sections": [_section(s) for s in report.sections],
        "cross_venue": [
            {
                "ticker": r.ticker,
                "binance_funding_8h": r.binance.current.funding_8h,
                "hyperliquid_funding_8h": r.hyperliquid.current.funding_8h,
                "funding_spread_8h": r.funding_spread_8h,
                "binance_oi_usd": r.binance.current.oi_usd,
                "hyperliquid_oi_usd": r.hyperliquid.current.oi_usd,
            }
            for r in report.cross
        ],
    }
