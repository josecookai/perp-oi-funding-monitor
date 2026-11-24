from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from perp_monitor.http import RetryPolicy
from perp_monitor.insights import live_source
from perp_monitor.insights.cache import JsonCache
from perp_monitor.insights.company_db import CompanyDB
from perp_monitor.insights.live_source import LiveSource
from tests.conftest import FIXTURES, load_fixture, mock_client

NOW = datetime(2026, 11, 24, 4, 0, tzinfo=UTC)
INS = FIXTURES / "insights"


def route(request: httpx.Request) -> httpx.Response:
    host, path = request.url.host, request.url.path
    if host == "api.nasdaq.com":
        if path.endswith("/company-profile"):
            return httpx.Response(200, json=load_fixture("insights/nasdaq_profile_fwdi.json"))
        if path.endswith("/historical"):
            return httpx.Response(200, json=load_fixture("insights/nasdaq_historical_vktx.json"))
        if path.endswith("/summary"):
            return httpx.Response(200, json=load_fixture("insights/nasdaq_summary_cvna.json"))
        if path.endswith("/info"):
            return httpx.Response(200, json=load_fixture("insights/nasdaq_info_cvna.json"))
        if path.endswith("/financials"):
            return httpx.Response(200, json=load_fixture("insights/nasdaq_financials_mdt.json"))
        if path.endswith("/earnings-surprise"):
            return httpx.Response(
                200, json=load_fixture("insights/nasdaq_earnings_surprise_mdt.json")
            )
        if path == "/api/calendar/earnings":
            if request.url.params["date"] == "2026-11-24":
                return httpx.Response(
                    200, json=load_fixture("insights/nasdaq_earnings_20261124.json")
                )
            if request.url.params["date"] == "2026-11-25":
                return httpx.Response(503)
            return httpx.Response(200, json={"data": {"rows": []}})
    if host == "feeds.finance.yahoo.com":
        return httpx.Response(200, text=(INS / "yahoo_rss_fwdi.xml").read_text())
    if host == "www.sec.gov":
        return httpx.Response(200, json=load_fixture("insights/sec_company_tickers.json"))
    if host == "data.sec.gov":
        return httpx.Response(200, json=load_fixture("insights/sec_submissions_fwdi.json"))
    if host == "api.finra.org":
        return httpx.Response(200, json=load_fixture("insights/finra_short_interest.json"))
    if host == "fapi.binance.com":
        return httpx.Response(200, json=load_fixture("insights/binance_funding_history_fwdi.json"))
    if host == "api.hyperliquid.xyz":
        return httpx.Response(200, json=load_fixture("insights/hl_funding_history_bot.json"))
    raise AssertionError(f"unexpected {request.url}")


def weekdays_in_window(today: date) -> int:
    start, end = live_source.EARNINGS_WINDOW
    days = (today + timedelta(days=d) for d in range(start, end + 1))
    return sum(1 for d in days if d.weekday() < 5)


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> Counter[str]:
    monkeypatch.setattr(live_source, "POLICY", RetryPolicy(attempts=1, backoff_seconds=0))
    return Counter()


def make(tmp_path: Path, counter: Counter[str]) -> tuple[LiveSource, JsonCache]:
    def handler(request: httpx.Request) -> httpx.Response:
        counter[f"{request.url.host}{request.url.path}"] += 1
        return route(request)

    cache = JsonCache(tmp_path / "cache.json", NOW)
    source = LiveSource(
        mock_client(handler),
        cache,
        NOW,
        companies=CompanyDB(tmp_path / "companies.db"),
        binance_base_url="https://fapi.binance.com",
        hl_info_url="https://api.hyperliquid.xyz/info",
        sec_user_agent="test agent@example.com",
    )
    return source, cache


def test_profile_is_cached(tmp_path: Path, counted: Counter[str]) -> None:
    source, cache = make(tmp_path, counted)
    assert source.profile("FWDI") is not None
    assert source.profile("FWDI") is not None
    assert counted["api.nasdaq.com/api/company/FWDI/company-profile"] == 1
    cache.save()
    again, _ = make(tmp_path, counted)
    assert again.profile("FWDI") is not None
    assert counted["api.nasdaq.com/api/company/FWDI/company-profile"] == 1


def test_spot_combines_bars_and_cached_share_info(tmp_path: Path, counted: Counter[str]) -> None:
    source, _ = make(tmp_path, counted)
    spot = source.spot("VKTX")
    assert spot is not None and spot.as_of == date(2026, 11, 23)
    # CVNA summary: $70.45B cap / $68.00 previous close; info says Class A -> multi-class.
    assert spot.shares_outstanding == pytest.approx(70_454_253_846 / 68.0)
    assert spot.multi_class is True
    source.spot("VKTX")
    assert counted["api.nasdaq.com/api/quote/VKTX/summary"] == 1


def test_news_filings_and_unknown_cik(tmp_path: Path, counted: Counter[str]) -> None:
    source, _ = make(tmp_path, counted)
    source.warm_up()
    source.profile("FWDI")
    items = source.news("FWDI")  # reads the cached profile name; never fetches it again
    assert all(
        "FWDI" in i.title + i.summary or "forward" in (i.title + i.summary).lower() for i in items
    )
    assert counted["api.nasdaq.com/api/company/FWDI/company-profile"] == 1
    assert any(f.form == "8-K" for f in source.filings("FWDI"))
    assert source.filings("ZZZZ") == ()
    assert counted["www.sec.gov/files/company_tickers.json"] == 1


def test_earnings_scans_weekdays_and_skips_failed_days(
    tmp_path: Path, counted: Counter[str]
) -> None:
    source, _ = make(tmp_path, counted)
    found = source.earnings(["MDT", "DELL", "NVDA"])
    assert set(found) == {"MDT", "DELL"}
    assert counted["api.nasdaq.com/api/calendar/earnings"] == weekdays_in_window(source.today)


def test_short_interest_and_funding_history(tmp_path: Path, counted: Counter[str]) -> None:
    source, _ = make(tmp_path, counted)
    assert "CVNA" in source.short_interest(["CVNA"])
    binance = source.funding_history("binance", "FWDIUSDT", 8.0)
    hl = source.funding_history("hyperliquid", "xyz:BOT", 1.0)
    assert binance and hl
    assert all(p.time > NOW - timedelta(days=30) for p in hl)


def test_failed_cik_lookup_is_not_retried_per_ticker(tmp_path: Path, counted: Counter[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        counted[request.url.host] += 1
        return httpx.Response(503)

    source = LiveSource(
        mock_client(handler),
        JsonCache(tmp_path / "c.json", NOW),
        NOW,
        companies=CompanyDB(tmp_path / "companies.db"),
        binance_base_url="https://fapi.binance.com",
        hl_info_url="https://api.hyperliquid.xyz/info",
        sec_user_agent="test agent@example.com",
    )
    with pytest.raises(Exception, match="503"):
        source.warm_up()
    assert source.filings("FWDI") == ()
    assert source.filings("CVNA") == ()
    assert counted["www.sec.gov"] == 1


def test_missing_profile_is_cached(tmp_path: Path, counted: Counter[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        counted[request.url.path] += 1
        return httpx.Response(200, json={"data": None})

    source = LiveSource(
        mock_client(handler),
        JsonCache(tmp_path / "c.json", NOW),
        NOW,
        companies=CompanyDB(tmp_path / "companies.db"),
        binance_base_url="https://fapi.binance.com",
        hl_info_url="https://api.hyperliquid.xyz/info",
        sec_user_agent="test agent@example.com",
    )
    assert source.profile("ZZZZ") is None
    assert source.profile("ZZZZ") is None
    assert counted["/api/company/ZZZZ/company-profile"] == 1


def test_today_is_the_us_eastern_date(tmp_path: Path, counted: Counter[str]) -> None:
    # 00:30 UTC on Nov 25 is still Nov 24 in New York.
    late = datetime(2026, 11, 25, 0, 30, tzinfo=UTC)
    source = LiveSource(
        mock_client(route),
        JsonCache(tmp_path / "c.json", late),
        late,
        companies=CompanyDB(tmp_path / "companies.db"),
        binance_base_url="https://fapi.binance.com",
        hl_info_url="https://api.hyperliquid.xyz/info",
        sec_user_agent="test agent@example.com",
    )
    assert source.today == date(2026, 11, 24)


def test_earnings_and_short_interest_are_cached(tmp_path: Path, counted: Counter[str]) -> None:
    source, cache = make(tmp_path, counted)
    first = source.earnings(["MDT"])
    source.short_interest(["CVNA", "BOT"])
    cache.save()
    again, _ = make(tmp_path, counted)
    assert again.earnings(["MDT"]) == first
    si = again.short_interest(["BOT", "CVNA"])
    assert si["BOT"].shares == 1_298_082
    # Every weekday the first time; only the day that failed (503) is fetched again.
    assert counted["api.nasdaq.com/api/calendar/earnings"] == weekdays_in_window(source.today) + 1
    assert counted["api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"] == 1


def test_fundamentals_and_last_earnings_come_from_the_database(
    tmp_path: Path, counted: Counter[str]
) -> None:
    source, _ = make(tmp_path, counted)
    f = source.fundamentals("MDT")
    assert f is not None and f.revenue_ttm_usd == pytest.approx(37_542_000_000)
    assert f.gross_margin == pytest.approx(24_406 / 37_542)
    assert f.market_cap_usd == pytest.approx(70_454_253_846)  # from the summary quote
    last = source.last_earnings("MDT")
    assert last is not None and last.reported == date(2026, 9, 1)
    again, _ = make(tmp_path, counted)
    assert again.fundamentals("MDT") == f
    assert again.last_earnings("MDT") == last
    assert counted["api.nasdaq.com/api/company/MDT/financials"] == 1
    assert counted["api.nasdaq.com/api/company/MDT/earnings-surprise"] == 1


def test_profile_merges_the_chinese_entry(tmp_path: Path, counted: Counter[str]) -> None:
    from perp_monitor.insights.company_zh import ZhEntry

    def handler(request: httpx.Request) -> httpx.Response:
        return route(request)

    source = LiveSource(
        mock_client(handler),
        JsonCache(tmp_path / "c.json", NOW),
        NOW,
        companies=CompanyDB(tmp_path / "companies.db"),
        zh={"FWDI": ZhEntry("Forward Industries", "Solana 财库公司")},
        binance_base_url="https://fapi.binance.com",
        hl_info_url="https://api.hyperliquid.xyz/info",
        sec_user_agent="test agent@example.com",
    )
    p = source.profile("FWDI")
    assert p is not None and p.description_zh == "Solana 财库公司"
    assert p.name == "Forward Industries, Inc."
