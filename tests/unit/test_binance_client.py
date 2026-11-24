from __future__ import annotations

import copy
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest

from perp_monitor.allowlist import parse_allowlist
from perp_monitor.binance_client import (
    BinanceClient,
    BinanceError,
    fetch_binance_snapshots,
    select_equity_symbols,
)
from perp_monitor.http import RetryPolicy
from perp_monitor.models import Venue
from perp_monitor.overrides import load_overrides
from tests.conftest import ASSETS, load_fixture, mock_client

BASE = "https://fapi.test"
ALLOW = parse_allowlist("AAPL\nBB\nBRK.B\nCVX\nMSTR\nNVDA\nQNT\nTSLA\n")
OVERRIDES = load_overrides(ASSETS / "symbol_overrides.toml")
FAST = RetryPolicy(attempts=2, backoff_seconds=0)


def binance_handler(overrides: dict[str, object] | None = None):
    routes: dict[str, object] = {
        "/fapi/v1/exchangeInfo": load_fixture("binance_exchange_info.json"),
        "/fapi/v1/premiumIndex": load_fixture("binance_premium_index.json"),
        "/fapi/v1/ticker/24hr": load_fixture("binance_ticker_24hr.json"),
        "/fapi/v1/fundingInfo": load_fixture("binance_funding_info.json"),
        "/futures/data/openInterestHist": load_fixture("binance_oi_hist_nvda.json"),
        **(overrides or {}),
    }
    oi = load_fixture("binance_open_interest.json")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path + "?" + request.url.query.decode())
        if request.url.path == "/fapi/v1/openInterest":
            symbol = parse_qs(request.url.query.decode())["symbol"][0]
            return httpx.Response(200, json=oi[symbol])
        body = routes[request.url.path]
        if isinstance(body, httpx.Response):
            return body
        return httpx.Response(200, json=body)

    return handler, seen


def make_client(handler) -> BinanceClient:
    return BinanceClient(mock_client(handler), BASE, policy=FAST)


def test_select_equity_symbols_keeps_only_usdt_equity_perps() -> None:
    symbols = select_equity_symbols(load_fixture("binance_exchange_info.json"))
    names = {s.symbol for s in symbols}
    assert names == {"NVDAUSDT", "TSLAUSDT", "AAPLUSDT", "MSTRUSDT", "BRKBUSDT", "SPYUSDT"}
    # crypto perps that share a name with a stock, KR stocks, commodities, USD1-margined
    for excluded in (
        "BBUSDT",
        "CVXUSDT",
        "QNTUSDT",
        "STXUSDT",
        "BTCUSDT",
        "SKHYNIXUSDT",
        "XAUUSDT",
        "SPCXUSD1",
    ):
        assert excluded not in names


def test_select_equity_symbols_skips_non_trading_status() -> None:
    info = copy.deepcopy(load_fixture("binance_exchange_info.json"))
    for symbol in info["symbols"]:
        if symbol["symbol"] == "TSLAUSDT":
            symbol["status"] = "SETTLING"
    assert "TSLAUSDT" not in {s.symbol for s in select_equity_symbols(info)}


def test_fetch_snapshots_builds_stock_rows_only() -> None:
    handler, seen = binance_handler()
    snaps = fetch_binance_snapshots(make_client(handler), ALLOW, OVERRIDES)
    by_ticker = {s.ticker: s for s in snaps}
    assert set(by_ticker) == {"NVDA", "TSLA", "AAPL", "MSTR", "BRK.B"}
    nvda = by_ticker["NVDA"]
    premium = {p["symbol"]: p for p in load_fixture("binance_premium_index.json")}["NVDAUSDT"]
    oi = load_fixture("binance_open_interest.json")["NVDAUSDT"]
    assert nvda.venue is Venue.BINANCE
    assert nvda.source == "binance:EQUITY"
    assert nvda.market == "NVDAUSDT"
    assert nvda.oi_contracts == pytest.approx(float(oi["openInterest"]))
    assert nvda.mark_price == pytest.approx(float(premium["markPrice"]))
    assert nvda.funding_rate == pytest.approx(float(premium["lastFundingRate"]))
    assert nvda.funding_interval_hours == 8
    assert nvda.volume_24h_usd > 0
    # OI is only requested for allowlisted stock symbols
    oi_calls = [s for s in seen if s.startswith("/fapi/v1/openInterest")]
    assert len(oi_calls) == 5
    assert not any("BBUSDT" in s or "SPYUSDT" in s for s in oi_calls)


def test_missing_funding_info_defaults_to_8h() -> None:
    handler, _ = binance_handler({"/fapi/v1/fundingInfo": []})
    snaps = fetch_binance_snapshots(make_client(handler), ALLOW, OVERRIDES)
    assert {s.funding_interval_hours for s in snaps} == {8}


def test_symbol_without_mark_price_is_skipped() -> None:
    premium = [p for p in load_fixture("binance_premium_index.json") if p["symbol"] != "AAPLUSDT"]
    handler, _ = binance_handler({"/fapi/v1/premiumIndex": premium})
    tickers = {s.ticker for s in fetch_binance_snapshots(make_client(handler), ALLOW, OVERRIDES)}
    assert "AAPL" not in tickers
    assert "NVDA" in tickers


def test_region_block_raises_clear_error() -> None:
    blocked = httpx.Response(451, text="Service unavailable from a restricted location")
    handler, _ = binance_handler({"/fapi/v1/exchangeInfo": blocked})
    with pytest.raises(BinanceError, match="451"):
        fetch_binance_snapshots(make_client(handler), ALLOW, OVERRIDES)


def test_open_interest_at_picks_closest_record() -> None:
    hist = load_fixture("binance_oi_hist_nvda.json")
    target_ms = hist[2]["timestamp"] + 60_000
    handler, seen = binance_handler()
    at = datetime.fromtimestamp(target_ms / 1000, tz=UTC)
    point = make_client(handler).open_interest_at("NVDAUSDT", at)
    assert point is not None
    assert point.oi_contracts == pytest.approx(float(hist[2]["sumOpenInterest"]))
    assert point.oi_usd == pytest.approx(float(hist[2]["sumOpenInterestValue"]))
    assert point.origin == "binance_oi_hist"
    assert point.funding_8h is None
    assert "period=5m" in seen[-1]


def test_open_interest_at_returns_none_without_history() -> None:
    handler, _ = binance_handler({"/futures/data/openInterestHist": []})
    assert make_client(handler).open_interest_at("NVDAUSDT", datetime.now(UTC)) is None


def _oi_failing(symbols: set[str]):
    handler, _ = binance_handler()

    def wrapped(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/fapi/v1/openInterest":
            symbol = parse_qs(request.url.query.decode())["symbol"][0]
            if symbol in symbols:
                return httpx.Response(500)
        return handler(request)

    return wrapped


def test_one_symbol_oi_failure_skips_only_that_symbol() -> None:
    client = make_client(_oi_failing({"TSLAUSDT"}))
    tickers = {s.ticker for s in fetch_binance_snapshots(client, ALLOW, OVERRIDES)}
    assert "TSLA" not in tickers
    assert "NVDA" in tickers


def test_all_symbols_failing_raises() -> None:
    every = {"NVDAUSDT", "TSLAUSDT", "AAPLUSDT", "MSTRUSDT", "BRKBUSDT"}
    with pytest.raises(BinanceError, match="open interest failed"):
        fetch_binance_snapshots(make_client(_oi_failing(every)), ALLOW, OVERRIDES)
