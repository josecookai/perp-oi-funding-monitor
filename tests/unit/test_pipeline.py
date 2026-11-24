"""End-to-end runs on recorded API responses: fetch → guard → store → report → files."""

from __future__ import annotations

import copy
import json
import shutil
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from perp_monitor.binance_client import BinanceClient
from perp_monitor.config import load_config
from perp_monitor.guard import CryptoLeakError
from perp_monitor.http import RetryPolicy
from perp_monitor.hyperliquid_client import HyperliquidClient
from perp_monitor.models import Venue
from perp_monitor.pipeline import run_cycle
from perp_monitor.store import SnapshotStore
from tests.conftest import ASSETS, load_fixture, mock_client
from tests.factories import T0, T8
from tests.unit.test_binance_client import binance_handler
from tests.unit.test_hyperliquid_client import hl_handler

FAST = RetryPolicy(attempts=1, backoff_seconds=0)
CRYPTO = ("BTC", "ETH", "SOL", "XRP", "DOGE", "STX")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    shutil.copytree(ASSETS, tmp_path / "assets")
    return tmp_path


def clients(binance_routes=None, xyz_payload=None):
    bn_handler, _ = binance_handler(binance_routes)
    hl, _ = hl_handler(xyz_payload)
    return (
        BinanceClient(mock_client(bn_handler), "https://fapi.test", policy=FAST),
        HyperliquidClient(mock_client(hl), "https://hl.test/info", policy=FAST),
    )


def run(root: Path, now=T8, binance_routes=None, xyz_payload=None, persist=True):
    cfg = load_config(root, {})
    bn, hl = clients(binance_routes, xyz_payload)
    with SnapshotStore(cfg.db_path) as store:
        return run_cycle(
            cfg, binance=bn, hyperliquid=hl, store=store, now=now, manual=False, persist=persist
        )


def test_first_run_backfills_binance_and_baselines_hyperliquid(root: Path) -> None:
    outcome = run(root)
    binance = outcome.report.section(Venue.BINANCE)
    hl = outcome.report.section(Venue.HYPERLIQUID)
    assert binance.window.origin == "binance_oi_hist"
    assert not binance.window.is_baseline
    assert hl.window.is_baseline
    assert {c.current.ticker for c in binance.changes} == {"NVDA", "TSLA", "AAPL", "MSTR", "BRK.B"}
    assert {"BB", "CVX", "QNT"} <= {c.current.ticker for c in hl.changes}
    assert outcome.errors == ()
    assert outcome.run_id == 1


def test_outputs_written_and_stock_only(root: Path) -> None:
    outcome = run(root)
    assert outcome.md_path == root / "reports" / "2026-11-24" / "0800Z.md"
    assert outcome.json_path.exists()
    assert (root / "reports" / "latest.md").read_text() == outcome.markdown
    data = json.loads(outcome.json_path.read_text())
    texts = [outcome.markdown, *outcome.telegram, json.dumps(data)]
    for text in texts:
        for symbol in CRYPTO:
            assert f'"{symbol}"' not in text and f"| {symbol} |" not in text
    sources = {row["source"] for s in data["sections"] for row in s["rows"]}
    assert sources == {"binance:EQUITY", "hl:xyz"}


def test_second_run_compares_with_stored_snapshot(root: Path) -> None:
    run(root, now=T0)
    payload = copy.deepcopy(load_fixture("hl_meta_and_asset_ctxs_xyz.json"))
    names = [a["name"] for a in payload[0]["universe"]]
    ctx = payload[1][names.index("xyz:NVDA")]
    before = float(ctx["openInterest"])
    ctx["openInterest"] = str(before * 1.5)
    outcome = run(root, now=T8, xyz_payload=payload)
    hl = outcome.report.section(Venue.HYPERLIQUID)
    assert hl.window.origin == "store"
    assert hl.window.hours == pytest.approx(8)
    nvda = next(c for c in hl.changes if c.current.ticker == "NVDA")
    assert nvda.d_contracts_pct == pytest.approx(0.5)
    assert hl.gainers[0].current.ticker == "NVDA"


def test_binance_failure_still_reports_hyperliquid(root: Path) -> None:
    blocked = httpx.Response(451, text="Service unavailable from a restricted location")
    outcome = run(root, binance_routes={"/fapi/v1/exchangeInfo": blocked})
    binance = outcome.report.section(Venue.BINANCE)
    assert binance.error and "451" in binance.error
    assert outcome.report.section(Venue.HYPERLIQUID).changes
    assert len(outcome.errors) == 1
    assert "fetch failed" in outcome.markdown


def test_denylisted_ticker_in_allowlist_aborts_before_storing(root: Path) -> None:
    allowlist = root / "assets" / "stocks_allowlist.txt"
    allowlist.write_text(allowlist.read_text() + "BTC\n")
    payload = copy.deepcopy(load_fixture("hl_meta_and_asset_ctxs_xyz.json"))
    payload[0]["universe"][0]["name"] = "xyz:BTC"
    with pytest.raises(CryptoLeakError):
        run(root, xyz_payload=payload)
    with SnapshotStore(root / "data" / "monitor.db") as store:
        assert store.run_count() == 0
    assert not (root / "reports" / "latest.md").exists()


def test_persist_false_writes_nothing(root: Path) -> None:
    outcome = run(root, persist=False)
    assert outcome.run_id is None and outcome.md_path is None
    assert not (root / "reports").exists()


def test_backfill_disabled_gives_binance_baseline(root: Path) -> None:
    cfg = load_config(root, {"BINANCE_BACKFILL": "0"})
    bn, hl = clients()
    with SnapshotStore(cfg.db_path) as store:
        outcome = run_cycle(cfg, binance=bn, hyperliquid=hl, store=store, now=T8, manual=True)
    assert outcome.report.section(Venue.BINANCE).window.is_baseline
    assert outcome.report.manual


def test_window_uses_actual_gap(root: Path) -> None:
    run(root, now=T0)
    outcome = run(root, now=T0 + timedelta(hours=20))
    window = outcome.report.section(Venue.HYPERLIQUID).window
    assert window.hours == pytest.approx(20)
    assert not window.in_range


def test_unexpected_payload_error_fails_only_that_venue(root: Path) -> None:
    outcome = run(root, xyz_payload=[{"universe": [{"name": "xyz:NVDA"}]}, [{"markPx": "abc"}]])
    hl = outcome.report.section(Venue.HYPERLIQUID)
    assert hl.error and "ValueError" in hl.error
    assert outcome.report.section(Venue.BINANCE).changes
    assert len(outcome.errors) == 1


def test_all_venues_failing_persists_nothing(root: Path) -> None:
    blocked = httpx.Response(451, text="restricted location")
    outcome = run(
        root,
        binance_routes={"/fapi/v1/exchangeInfo": blocked},
        xyz_payload=[{"universe": []}, [{}]],
    )
    assert len(outcome.errors) == 2
    assert outcome.run_id is None and outcome.md_path is None
    assert not (root / "reports" / "latest.md").exists()


def test_hourly_runs_compare_with_the_run_a_full_window_ago(root: Path) -> None:
    # Runs every hour from T0; the T8 run must compare with T0 (8h), not T1 (7h).
    for hour in range(8):
        run(root, now=T0 + timedelta(hours=hour))
    outcome = run(root, now=T8)
    hl = outcome.report.section(Venue.HYPERLIQUID)
    assert hl.window.hours == pytest.approx(8)
    assert hl.window.in_range


def test_no_archive_writes_only_latest(root: Path) -> None:
    cfg = load_config(root, {})
    bn, hl = clients()
    with SnapshotStore(cfg.db_path) as store:
        outcome = run_cycle(
            cfg, binance=bn, hyperliquid=hl, store=store, now=T8, manual=False, archive=False
        )
    assert outcome.run_id == 1
    assert outcome.md_path == root / "reports" / "latest.md"
    assert not (root / "reports" / "2026-11-24").exists()


def test_prior_min_age_uses_small_slack() -> None:
    from perp_monitor.pipeline import prior_min_age

    assert prior_min_age(load_config(Path("/tmp"), {})) == pytest.approx(7.75)
    tight = load_config(Path("/tmp"), {"WINDOW_TOLERANCE_HOURS": "0.1"})
    assert prior_min_age(tight) == pytest.approx(7.9)
