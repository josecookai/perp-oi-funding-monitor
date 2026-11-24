from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from perp_monitor.insights.cache import JsonCache
from perp_monitor.insights.collect import build_insights, targets_from_report
from perp_monitor.insights.models import (
    EarningsDate,
    Filing,
    FundingPattern,
    FundingPoint,
    NewsItem,
    Profile,
    ShortInterest,
    ShortLevel,
    Side,
    SpotStats,
    VolumeTier,
)
from perp_monitor.insights.serialize import bundle_to_json

NOW = datetime(2026, 11, 24, 4, 0, tzinfo=UTC)


def row(
    ticker: str, market: str, funding: float, oi: float, vol: float, interval: float
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "market": market,
        "funding_8h": funding,
        "funding_apr": funding * 1095,
        "funding_interval_hours": interval,
        "oi_usd": oi,
        "volume_24h_usd": vol,
    }


REPORT: dict[str, Any] = {
    "generated_at": "2026-11-24T03:26:00+00:00",
    "sections": [
        {
            "venue": "binance",
            "error": None,
            "rankings": {"funding_negative": ["FWDI", "MDT"], "funding_positive": ["WDC"]},
            "rows": [
                row("FWDI", "FWDIUSDT", -0.0034, 362_000, 2_746_000, 8.0),
                row("MDT", "MDTUSDT", -0.0032, 67_000, 358_000, 8.0),
                row("WDC", "WDCUSDT", 0.0004, 4_182_000, 37_070_000, 8.0),
            ],
        },
        {
            "venue": "hyperliquid",
            "error": None,
            "rankings": {"funding_negative": ["FWDI", "GONE"], "funding_positive": []},
            "rows": [row("FWDI", "xyz:FWDI", -0.0007, 1_500_000, 1_200_000, 1.0)],
        },
        {"venue": "broken", "error": "boom", "rankings": {}, "rows": []},
    ],
}


class FakeSource:
    def __init__(self, fail: Iterable[str] = ()) -> None:
        self.fail = set(fail)
        self.history_calls: list[tuple[str, str, float]] = []

    def _maybe_fail(self, what: str) -> None:
        if what in self.fail:
            raise RuntimeError(f"{what} down")

    def warm_up(self) -> None:
        self._maybe_fail("warm_up")

    def profile(self, ticker: str) -> Profile | None:
        self._maybe_fail("profile")
        return Profile(
            f"{ticker} Inc.", "Tech", None, f"{ticker} makes things for many customers. More."
        )

    def spot(self, ticker: str) -> SpotStats | None:
        self._maybe_fail("spot")
        return SpotStats(date(2026, 11, 23), 10.0, 0.01, 0.02, 0.03, 5e6, 1e8)

    def news(self, ticker: str) -> tuple[NewsItem, ...]:
        self._maybe_fail("news")
        return (
            NewsItem(f"{ticker} news", "https://a.com/n", NOW - timedelta(hours=5), "a.com", ""),
        )

    def filings(self, ticker: str) -> tuple[Filing, ...]:
        self._maybe_fail("filings")
        return ()

    def earnings(self, tickers: Sequence[str]) -> Mapping[str, EarningsDate]:
        self._maybe_fail("earnings")
        return {"MDT": EarningsDate(date(2026, 11, 24), "bmo")}

    def short_interest(self, tickers: Iterable[str]) -> Mapping[str, ShortInterest]:
        self._maybe_fail("short_interest")
        return {"FWDI": ShortInterest(date(2026, 10, 30), 5_207_169, 4_071_587, 3.9, None)}

    def funding_history(
        self, venue: str, market: str, interval_hours: float
    ) -> tuple[FundingPoint, ...]:
        self.history_calls.append((venue, market, interval_hours))
        self._maybe_fail("history")
        return tuple(FundingPoint(NOW - timedelta(hours=8 * i), 0.0) for i in range(6))


def test_targets_skip_failed_sections_and_missing_rows() -> None:
    targets = targets_from_report(REPORT)
    keys = [(t.venue, t.ticker, t.side, t.rank) for t in targets]
    assert keys == [
        ("binance", "FWDI", Side.NEGATIVE, 1),
        ("binance", "MDT", Side.NEGATIVE, 2),
        ("binance", "WDC", Side.POSITIVE, 1),
        ("hyperliquid", "FWDI", Side.NEGATIVE, 1),
    ]


def test_build_insights_happy_path() -> None:
    source = FakeSource()
    bundle = build_insights(REPORT, source, NOW, workers=2)
    assert bundle.errors == ()
    items = {i.key: i for i in bundle.items if i.side is Side.NEGATIVE}
    fwdi = items["binance:FWDI"]
    assert fwdi.persistence.pattern is FundingPattern.SPIKE
    assert fwdi.volume.tier is VolumeTier.THIN
    assert fwdi.volume.oi_to_spot_adv == pytest.approx(362_000 / 5e6)
    # 100M shares outstanding -> 5.2M short = 5.2%.
    assert fwdi.short_interest is not None
    assert fwdi.short_interest.pct_of_shares == pytest.approx(0.0520717)
    assert fwdi.short_level is ShortLevel.MODERATE
    assert items["binance:MDT"].volume.tier is VolumeTier.NOISE
    assert "财报 11/24" in items["binance:MDT"].headline
    assert ("hyperliquid", "xyz:FWDI", 1.0) in source.history_calls


def test_failures_are_recorded_not_raised() -> None:
    source = FakeSource(fail={"news", "history", "earnings", "warm_up"})
    bundle = build_insights(REPORT, source, NOW, workers=2)
    assert any(e.startswith("earnings") for e in bundle.errors)
    assert any(e.startswith("warm-up") for e in bundle.errors)
    item = bundle.items[0]
    assert item.catalysts.news == ()
    assert item.persistence.pattern is FundingPattern.INSUFFICIENT
    assert any("news" in e for e in item.errors)
    assert any("funding history" in e for e in item.errors)


def test_serialized_bundle_is_json() -> None:
    data = bundle_to_json(build_insights(REPORT, FakeSource(), NOW, workers=1))
    text = json.dumps(data, ensure_ascii=False)
    back = json.loads(text)
    first = back["items"][0]
    assert first["key"] == "binance:FWDI"
    assert first["side"] == "negative"
    assert set(first["answers"]) == {"what", "funding", "catalyst", "volume", "short"}
    assert first["short_interest"]["change_pct"] == pytest.approx(5_207_169 / 4_071_587 - 1)
    assert first["persistence"]["buckets"][0]["time"].endswith("+00:00")
    assert back["thresholds"]["noise_oi_usd"] == 250_000


class TestJsonCache:
    def test_round_trip_and_expiry(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        cache = JsonCache(path, NOW)
        cache.put("a", {"x": 1})
        cache.save()
        later = JsonCache(path, NOW + timedelta(days=2))
        assert later.get("a", timedelta(days=3)) == {"x": 1}
        assert later.get("a", timedelta(days=1)) is None
        assert later.get("missing", timedelta(days=1)) is None

    def test_corrupt_file_is_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        path.write_text("{not json")
        assert JsonCache(path, NOW).get("a", timedelta(days=1)) is None

    def test_bad_timestamp_is_a_miss(self, tmp_path: Path) -> None:
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"a": {"at": "yesterday", "value": 1}}))
        assert JsonCache(path, NOW).get("a", timedelta(days=1)) is None


def test_one_bad_card_does_not_lose_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    from perp_monitor.insights import collect

    real = collect._assemble

    def flaky(t: Any, *args: Any) -> Any:
        if t.ticker == "MDT":
            raise ValueError("bad data")
        return real(t, *args)

    monkeypatch.setattr(collect, "_assemble", flaky)
    bundle = build_insights(REPORT, FakeSource(), NOW, workers=1)
    assert "binance:MDT" not in {i.key for i in bundle.items}
    assert len(bundle.items) == 3
    assert any(e == "binance:MDT card: ValueError" for e in bundle.errors)


def test_error_text_has_no_upstream_body() -> None:
    from perp_monitor.http import HttpError
    from perp_monitor.insights.collect import _describe

    exc = HttpError("GET https://x: HTTP 503: <html>secret page</html>", 503)
    assert _describe("NVDA news", exc) == "NVDA news: HttpError (HTTP 503)"


def test_market_date_in_bundle() -> None:
    late = datetime(2026, 11, 25, 0, 30, tzinfo=UTC)
    bundle = build_insights(REPORT, FakeSource(), late, workers=1)
    assert bundle.market_date == date(2026, 11, 24)
    assert bundle_to_json(bundle)["market_date"] == "2026-11-24"
