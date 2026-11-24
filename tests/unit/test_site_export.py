from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from perp_monitor.cli import main
from perp_monitor.http import RetryPolicy
from perp_monitor.insights import live_source
from perp_monitor.models import Venue
from perp_monitor.site_export import export_site, history_to_json
from perp_monitor.store import SnapshotStore
from tests.conftest import mock_client
from tests.factories import T0, T8, snap


def store_with_two_runs(path: Path) -> SnapshotStore:
    store = SnapshotStore(path)
    store.record_run(T0, False, [snap("NVDA", oi=10, price=180.123456789, funding=-0.0001)])
    store.record_run(
        T8,
        False,
        [
            snap("NVDA", oi=12, price=181.0, funding=0.0002),
            snap("TSLA", oi=5, price=400.0, venue=Venue.HYPERLIQUID, funding=0.00001),
        ],
    )
    return store


def test_history_to_json(tmp_path: Path) -> None:
    with store_with_two_runs(tmp_path / "m.db") as store:
        runs, rows = store.history(T0 - timedelta(hours=1))
        later_runs, _ = store.history(T0 + timedelta(hours=1))
    assert len(later_runs) == 1
    data = history_to_json(runs, rows)
    assert data["runs"] == [T0.isoformat(), T8.isoformat()]
    nvda = data["series"]["binance:NVDA"]
    assert nvda["market"] == "NVDAUSDT"
    assert [p[0] for p in nvda["points"]] == [0, 1]
    assert nvda["points"][0][1] == -0.0001
    assert nvda["points"][0][2] == round(10 * 180.123456789)
    assert nvda["points"][0][3] == 180.123
    assert data["series"]["hyperliquid:TSLA"]["points"][0][0] == 1


def test_export_site_keeps_old_insights_when_none(tmp_path: Path) -> None:
    out = tmp_path / "web" / "data"
    (out).mkdir(parents=True)
    (out / "insights.json").write_text('{"old": true}')
    paths = export_site(out, {"generated_at": "g"}, {"runs": []}, None, T8, "boom")
    names = sorted(p.name for p in paths)
    assert names == ["history.json", "meta.json", "report.json"]
    assert json.loads((out / "insights.json").read_text()) == {"old": True}
    meta = json.loads((out / "meta.json").read_text())
    assert meta["insights_error"] == "boom"
    assert meta["report_generated_at"] == "g"


ONE_MARKET = {
    "generated_at": "x",
    "sections": [{"venue": "binance", "error": None, "rankings": {}, "rows": [{"ticker": "NVDA"}]}],
}


def test_cli_site_refuses_a_report_without_markets(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "latest.json").write_text(json.dumps({"generated_at": "x", "sections": []}))

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no network expected")

    assert main(["site"], root=tmp_path, env={}, http=mock_client(handler)) == 1
    assert not (tmp_path / "web" / "data").exists()


def test_cli_site_skip_insights(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "latest.json").write_text(json.dumps(ONE_MARKET))
    with store_with_two_runs(tmp_path / "data" / "monitor.db"):
        pass

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no network expected")

    code = main(["site", "--skip-insights"], root=tmp_path, env={}, http=mock_client(handler))
    assert code == 0
    data = tmp_path / "web" / "data"
    assert json.loads((data / "report.json").read_text())["generated_at"] == "x"
    assert not (data / "insights.json").exists()


def test_cli_site_without_report(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no network expected")

    assert main(["site"], root=tmp_path, env={}, http=mock_client(handler)) == 1


def test_cli_site_with_failing_network_still_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(live_source, "POLICY", RetryPolicy(attempts=1, backoff_seconds=0))
    reports = tmp_path / "reports"
    reports.mkdir()
    report = {
        "generated_at": "x",
        "sections": [
            {
                "venue": "binance",
                "error": None,
                "rankings": {"funding_negative": ["NVDA"], "funding_positive": []},
                "rows": [
                    {
                        "ticker": "NVDA",
                        "market": "NVDAUSDT",
                        "funding_8h": -0.001,
                        "funding_apr": -1.095,
                        "funding_interval_hours": 8.0,
                        "oi_usd": 1e6,
                        "volume_24h_usd": 2e6,
                    }
                ],
            }
        ],
    }
    (reports / "latest.json").write_text(json.dumps(report))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    code = main(["site"], root=tmp_path, env={}, http=mock_client(handler))
    assert code == 0
    insights = json.loads((tmp_path / "web" / "data" / "insights.json").read_text())
    item = insights["items"][0]
    assert item["key"] == "binance:NVDA"
    assert item["errors"]  # every source failed, recorded on the card
    assert item["answers"]["what"] == "暂无公司资料。"
