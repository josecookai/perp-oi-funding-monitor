"""Real-data tests against the public Binance and Hyperliquid APIs.

Skipped unless RUN_LIVE=1. Binance refuses US IPs (HTTP 451), so run these from a host
outside the US (they are not part of CI).
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from perp_monitor.allowlist import load_allowlist, load_denylist
from perp_monitor.binance_client import (
    BinanceClient,
    fetch_binance_snapshots,
    select_equity_symbols,
)
from perp_monitor.config import load_config
from perp_monitor.http import build_client
from perp_monitor.hyperliquid_client import HyperliquidClient, fetch_hl_snapshots
from perp_monitor.models import Venue
from perp_monitor.overrides import load_overrides
from perp_monitor.pipeline import run_cycle
from perp_monitor.store import SnapshotStore
from tests.conftest import ASSETS

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1 to hit real APIs"),
]

ALLOW = load_allowlist(ASSETS / "stocks_allowlist.txt")
DENY = load_denylist(ASSETS / "crypto_denylist.txt")
OVERRIDES = load_overrides(ASSETS / "symbol_overrides.toml")
COLLISIONS = ("BB", "CVX", "QNT")  # stock tickers that are also Binance crypto perps


@pytest.fixture(scope="module")
def http():
    with build_client(20) as client:
        yield client


@pytest.fixture(scope="module")
def binance(http) -> BinanceClient:
    return BinanceClient(http, "https://fapi.binance.com")


@pytest.fixture(scope="module")
def hyperliquid(http) -> HyperliquidClient:
    return HyperliquidClient(http, "https://api.hyperliquid.xyz/info")


def test_binance_equity_universe(binance: BinanceClient) -> None:
    info = binance.exchange_info()
    symbols = {s.symbol for s in select_equity_symbols(info)}
    assert len(symbols) > 100
    assert "NVDAUSDT" in symbols
    coins = {s["symbol"] for s in info["symbols"] if s.get("underlyingType") == "COIN"}
    assert "BTCUSDT" in coins and not symbols & coins


def test_binance_snapshots_are_stocks_only(binance: BinanceClient) -> None:
    snaps = fetch_binance_snapshots(binance, ALLOW, OVERRIDES)
    assert len(snaps) > 100
    assert {s.source for s in snaps} == {"binance:EQUITY"}
    tickers = {s.ticker for s in snaps}
    assert {"NVDA", "TSLA", "AAPL", "MSTR"} <= tickers
    assert not tickers & DENY
    assert not tickers & set(COLLISIONS)  # Binance's BB/CVX/QNT are crypto perps
    assert all(s.mark_price > 0 for s in snaps)
    assert {s.funding_interval_hours for s in snaps} <= {1, 2, 4, 8}
    assert sum(s.oi_usd for s in snaps) > 1e8


def test_binance_oi_history(binance: BinanceClient) -> None:
    point = binance.open_interest_at("NVDAUSDT", datetime.now(UTC) - timedelta(hours=8))
    assert point is not None
    assert point.oi_usd > 0
    assert abs((datetime.now(UTC) - timedelta(hours=8) - point.observed_at).total_seconds()) < 900


def test_hyperliquid_xyz_snapshots_are_stocks_only(hyperliquid: HyperliquidClient) -> None:
    assert "xyz" in hyperliquid.perp_dexs()
    snaps = fetch_hl_snapshots(hyperliquid, ("xyz",), ALLOW, OVERRIDES)
    assert len(snaps) > 50
    assert {s.source for s in snaps} == {"hl:xyz"}
    tickers = {s.ticker for s in snaps}
    assert {"NVDA", "TSLA", "AAPL"} <= tickers
    assert not tickers & DENY
    assert not tickers & {"GOLD", "CL", "SILVER", "SP500", "XYZ100"}
    assert all(s.funding_interval_hours == 1 for s in snaps)


def test_full_cycle_live(tmp_path: Path, http) -> None:
    shutil.copytree(ASSETS, tmp_path / "assets")
    config = load_config(tmp_path, {})
    with SnapshotStore(config.db_path) as store:
        outcome = run_cycle(
            config,
            binance=BinanceClient(http, config.binance_base_url),
            hyperliquid=HyperliquidClient(http, config.hl_info_url),
            store=store,
            now=datetime.now(UTC).replace(second=0, microsecond=0),
            manual=True,
            persist=False,
        )
    assert outcome.errors == ()
    for heading in (
        "## 1. OI change",
        "## 2. OI gain",
        "## 3. OI loss",
        "## 4. Funding negative",
        "## 5. Funding positive",
    ):
        assert heading in outcome.markdown
    assert "USDT" not in outcome.markdown
    binance = outcome.report.section(Venue.BINANCE)
    assert binance.window.origin == "binance_oi_hist"
    assert binance.gainers and binance.losers
