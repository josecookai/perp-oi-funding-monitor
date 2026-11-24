"""Binance USDT-M futures: public REST reads for stock (EQUITY) perps only."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from perp_monitor.allowlist import Allowlist
from perp_monitor.http import DEFAULT_POLICY, HttpError, RetryPolicy, request_json
from perp_monitor.models import MarketSnapshot, PriorPoint, Venue
from perp_monitor.overrides import Overrides

log = logging.getLogger(__name__)

SOURCE = "binance:EQUITY"
DEFAULT_FUNDING_INTERVAL_HOURS = 8.0
HIST_SEARCH_MINUTES = 10


class BinanceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BinanceSymbol:
    symbol: str
    base_asset: str


def select_equity_symbols(exchange_info: Mapping[str, Any]) -> tuple[BinanceSymbol, ...]:
    """Stock perps: underlyingType EQUITY, TRADIFI_PERPETUAL, USDT-margined, trading.

    Filtering on the venue's own market type (not on the name) is what keeps crypto
    perps such as BBUSDT or CVXUSDT out, even though BB and CVX are also stock tickers.
    """
    return tuple(
        BinanceSymbol(s["symbol"], s["baseAsset"])
        for s in exchange_info.get("symbols", [])
        if s.get("underlyingType") == "EQUITY"
        and s.get("contractType") == "TRADIFI_PERPETUAL"
        and s.get("quoteAsset") == "USDT"
        and s.get("marginAsset", "USDT") == "USDT"
        and s.get("status") == "TRADING"
    )


class BinanceClient:
    def __init__(self, http: httpx.Client, base_url: str, policy: RetryPolicy = DEFAULT_POLICY):
        self._http = http
        self._base = base_url.rstrip("/")
        self._policy = policy

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        try:
            return request_json(
                self._http, "GET", self._base + path, params=params, policy=self._policy
            )
        except HttpError as exc:
            if exc.status == 451:
                raise BinanceError(
                    f"Binance refused this server's region (HTTP 451). Run from a "
                    f"non-US host. Detail: {exc}"
                ) from exc
            raise BinanceError(str(exc)) from exc

    def exchange_info(self) -> Mapping[str, Any]:
        return self._get("/fapi/v1/exchangeInfo")

    def premium_index(self) -> dict[str, Mapping[str, Any]]:
        return {row["symbol"]: row for row in self._get("/fapi/v1/premiumIndex")}

    def volumes_24h(self) -> dict[str, float]:
        return {
            row["symbol"]: float(row["quoteVolume"]) for row in self._get("/fapi/v1/ticker/24hr")
        }

    def funding_intervals(self) -> dict[str, float]:
        rows = self._get("/fapi/v1/fundingInfo")
        return {row["symbol"]: float(row["fundingIntervalHours"]) for row in rows}

    def open_interest(self, symbol: str) -> float:
        return float(self._get("/fapi/v1/openInterest", {"symbol": symbol})["openInterest"])

    def open_interest_at(self, symbol: str, at: datetime) -> PriorPoint | None:
        """Historical OI closest to `at` (Binance keeps about 30 days of 5m history)."""
        span = timedelta(minutes=HIST_SEARCH_MINUTES)
        params = {
            "symbol": symbol,
            "period": "5m",
            "startTime": int((at - span).timestamp() * 1000),
            "endTime": int((at + span).timestamp() * 1000),
            "limit": 10,
        }
        rows = self._get("/futures/data/openInterestHist", params)
        if not rows:
            return None
        target_ms = at.timestamp() * 1000
        row = min(rows, key=lambda r: abs(r["timestamp"] - target_ms))
        return PriorPoint(
            oi_contracts=float(row["sumOpenInterest"]),
            oi_usd=float(row["sumOpenInterestValue"]),
            funding_8h=None,
            observed_at=datetime.fromtimestamp(row["timestamp"] / 1000, tz=UTC),
            origin="binance_oi_hist",
        )


def fetch_binance_snapshots(
    client: BinanceClient, allowlist: Allowlist, overrides: Overrides
) -> tuple[MarketSnapshot, ...]:
    candidates = []
    for sym in select_equity_symbols(client.exchange_info()):
        ticker = overrides.canonical(Venue.BINANCE, sym.base_asset)
        if ticker is not None and ticker in allowlist:
            candidates.append((sym, ticker))

    premium = client.premium_index()
    volumes = client.volumes_24h()
    intervals = client.funding_intervals()
    snapshots = []
    oi_failures = []
    for sym, ticker in candidates:
        row = premium.get(sym.symbol) or {}
        mark = float(row.get("markPrice") or 0)
        if mark <= 0:
            log.warning("binance %s: no mark price, skipped", sym.symbol)
            continue
        try:
            oi_contracts = client.open_interest(sym.symbol)
        except BinanceError as exc:
            log.warning("binance %s: open interest failed, skipped: %s", sym.symbol, exc)
            oi_failures.append(sym.symbol)
            continue
        snapshots.append(
            MarketSnapshot(
                venue=Venue.BINANCE,
                source=SOURCE,
                market=sym.symbol,
                ticker=ticker,
                oi_contracts=oi_contracts,
                mark_price=mark,
                funding_rate=float(row.get("lastFundingRate") or 0),
                funding_interval_hours=intervals.get(sym.symbol, DEFAULT_FUNDING_INTERVAL_HOURS),
                volume_24h_usd=volumes.get(sym.symbol, 0.0),
            )
        )
    if oi_failures and not snapshots:
        raise BinanceError(f"open interest failed for all {len(oi_failures)} symbols")
    return tuple(snapshots)


def equity_base_names(client: BinanceClient, overrides: Overrides) -> frozenset[str]:
    """Canonical names of every Binance stock perp (for `allowlist suggest`)."""
    names = (
        overrides.canonical(Venue.BINANCE, s.base_asset)
        for s in select_equity_symbols(client.exchange_info())
    )
    return frozenset(n for n in names if n is not None)
