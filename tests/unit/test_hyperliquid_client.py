from __future__ import annotations

import copy
import json

import httpx
import pytest

from perp_monitor.allowlist import parse_allowlist
from perp_monitor.http import RetryPolicy
from perp_monitor.hyperliquid_client import (
    HyperliquidClient,
    HyperliquidError,
    fetch_hl_snapshots,
)
from perp_monitor.models import Venue
from perp_monitor.overrides import load_overrides
from tests.conftest import ASSETS, load_fixture, mock_client

URL = "https://hl.test/info"
ALLOW = parse_allowlist("AAPL\nBB\nCL\nCVX\nGOLD\nMSTR\nNVDA\nQNT\nTSLA\n")
OVERRIDES = load_overrides(ASSETS / "symbol_overrides.toml")
FAST = RetryPolicy(attempts=2, backoff_seconds=0)


def hl_handler(xyz_payload: object | None = None):
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if body["type"] == "perpDexs":
            return httpx.Response(200, json=load_fixture("hl_perp_dexs.json"))
        if body["type"] == "metaAndAssetCtxs" and body.get("dex") == "xyz":
            payload = xyz_payload or load_fixture("hl_meta_and_asset_ctxs_xyz.json")
            return httpx.Response(200, json=payload)
        if body["type"] == "metaAndAssetCtxs":
            # The main (crypto) dex. The client must never ask for it.
            return httpx.Response(200, json=load_fixture("hl_meta_and_asset_ctxs_main.json"))
        return httpx.Response(400)

    return handler, bodies


def make_client(handler) -> HyperliquidClient:
    return HyperliquidClient(mock_client(handler), URL, policy=FAST)


def test_perp_dexs_lists_builder_dex_names() -> None:
    handler, _ = hl_handler()
    names = make_client(handler).perp_dexs()
    assert "xyz" in names
    assert "" not in names


def test_markets_refuses_main_dex() -> None:
    handler, bodies = hl_handler()
    with pytest.raises(ValueError, match="main"):
        make_client(handler).markets("")
    assert bodies == []


def test_fetch_snapshots_reads_stock_markets_from_xyz_only() -> None:
    handler, bodies = hl_handler()
    snaps = fetch_hl_snapshots(make_client(handler), ("xyz",), ALLOW, OVERRIDES)
    by_ticker = {s.ticker: s for s in snaps}
    # CL (crude oil) and GOLD (gold) are excluded by the overrides even though both
    # are in this test allowlist; SP500 and XYZ100 are not allowlisted.
    assert set(by_ticker) == {"NVDA", "TSLA", "AAPL", "MSTR", "BB", "CVX", "QNT"}
    assert all(b.get("dex") for b in bodies if b["type"] == "metaAndAssetCtxs")

    meta, ctxs = load_fixture("hl_meta_and_asset_ctxs_xyz.json")
    raw = dict(zip((a["name"] for a in meta["universe"]), ctxs, strict=True))["xyz:NVDA"]
    nvda = by_ticker["NVDA"]
    assert nvda.venue is Venue.HYPERLIQUID
    assert nvda.source == "hl:xyz"
    assert nvda.market == "xyz:NVDA"
    assert nvda.oi_contracts == pytest.approx(float(raw["openInterest"]))
    assert nvda.mark_price == pytest.approx(float(raw["markPx"]))
    assert nvda.funding_rate == pytest.approx(float(raw["funding"]))
    assert nvda.funding_interval_hours == 1
    assert nvda.volume_24h_usd == pytest.approx(float(raw["dayNtlVlm"]))


def test_unknown_dex_raises() -> None:
    handler, _ = hl_handler()
    with pytest.raises(HyperliquidError, match="nope"):
        fetch_hl_snapshots(make_client(handler), ("nope",), ALLOW, OVERRIDES)


def test_delisted_markets_are_skipped() -> None:
    payload = copy.deepcopy(load_fixture("hl_meta_and_asset_ctxs_xyz.json"))
    for asset in payload[0]["universe"]:
        if asset["name"] == "xyz:TSLA":
            asset["isDelisted"] = True
    handler, _ = hl_handler(payload)
    tickers = {
        s.ticker for s in fetch_hl_snapshots(make_client(handler), ("xyz",), ALLOW, OVERRIDES)
    }
    assert "TSLA" not in tickers


def test_mismatched_payload_raises() -> None:
    payload = copy.deepcopy(load_fixture("hl_meta_and_asset_ctxs_xyz.json"))
    payload[1] = payload[1][:-1]
    handler, _ = hl_handler(payload)
    with pytest.raises(HyperliquidError, match="length"):
        fetch_hl_snapshots(make_client(handler), ("xyz",), ALLOW, OVERRIDES)


def test_market_without_mark_price_is_skipped() -> None:
    payload = copy.deepcopy(load_fixture("hl_meta_and_asset_ctxs_xyz.json"))
    names = [a["name"] for a in payload[0]["universe"]]
    payload[1][names.index("xyz:AAPL")]["markPx"] = None
    handler, _ = hl_handler(payload)
    tickers = {
        s.ticker for s in fetch_hl_snapshots(make_client(handler), ("xyz",), ALLOW, OVERRIDES)
    }
    assert "AAPL" not in tickers
