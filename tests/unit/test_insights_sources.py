from __future__ import annotations

import json
from datetime import UTC, date, datetime

import httpx
import pytest

from perp_monitor.http import RetryPolicy
from perp_monitor.insights import finra, funding_history, nasdaq, news, sec_filings
from tests.conftest import FIXTURES, load_fixture, mock_client

INS = FIXTURES / "insights"
NO_RETRY = RetryPolicy(attempts=1, backoff_seconds=0)


def fx(name: str) -> object:
    return load_fixture(f"insights/{name}")


class TestNasdaq:
    def test_profile(self) -> None:
        p = nasdaq.parse_profile(fx("nasdaq_profile_fwdi.json"))
        assert p is not None
        assert p.name == "Forward Industries, Inc."
        assert p.sector == "Finance"
        assert p.industry == "Finance: Consumer Services"
        assert p.description is not None and "Solana" in p.description

    def test_profile_missing_data(self) -> None:
        assert nasdaq.parse_profile({"data": None}) is None

    def test_historical(self) -> None:
        bars = nasdaq.parse_historical(fx("nasdaq_historical_vktx.json"))
        assert len(bars) == 25
        latest = max(bars, key=lambda b: b.day)
        assert latest.day == date(2026, 11, 23)
        assert latest.close == pytest.approx(27.69)
        assert latest.volume == pytest.approx(3_528_787)

    def test_historical_skips_bad_rows(self) -> None:
        payload = {
            "data": {
                "tradesTable": {
                    "rows": [
                        {"date": "11/23/2026", "close": "N/A", "volume": "1"},
                        {"date": "11/20/2026", "close": "$1.50", "volume": "2,000"},
                    ]
                }
            }
        }
        bars = nasdaq.parse_historical(payload)
        assert [(b.close, b.volume) for b in bars] == [(1.5, 2000.0)]

    def test_market_cap(self) -> None:
        assert nasdaq.parse_market_cap(fx("nasdaq_summary_cvna.json")) == pytest.approx(
            70_454_253_846
        )
        assert (
            nasdaq.parse_market_cap({"data": {"summaryData": {"MarketCap": {"value": "N/A"}}}})
            is None
        )

    def test_earnings_calendar(self) -> None:
        events = nasdaq.parse_earnings_calendar(
            fx("nasdaq_earnings_20261124.json"), date(2026, 11, 24)
        )
        assert events["DELL"].timing == "amc"
        assert events["MDT"].timing == "bmo"
        assert events["BHP"].timing is None
        assert events["MDT"].day == date(2026, 11, 24)

    def test_earnings_calendar_empty_rows(self) -> None:
        assert nasdaq.parse_earnings_calendar({"data": {"rows": None}}, date(2026, 11, 28)) == {}

    def test_fetch_profile_uses_symbol_path(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            return httpx.Response(200, json=fx("nasdaq_profile_fwdi.json"))

        with mock_client(handler) as client:
            p = nasdaq.fetch_profile(client, "FWDI", policy=NO_RETRY)
        assert p is not None and seen == ["/api/company/FWDI/company-profile"]

    def test_share_class_keeps_the_dot(self) -> None:
        # /api/quote/BRK/B/... is a 404; /api/quote/BRK.B/... works (checked 2026-11-24).
        assert nasdaq.nasdaq_symbol("BRK.B") == "BRK.B"


class TestYahooNews:
    def test_parse_recent_items(self) -> None:
        xml = (INS / "yahoo_rss_fwdi.xml").read_text()
        items = news.parse_rss(xml, since=datetime(2026, 11, 1, tzinfo=UTC), limit=5)
        assert 1 <= len(items) <= 5
        assert all(i.published_at >= datetime(2026, 11, 1, tzinfo=UTC) for i in items)
        assert items == tuple(sorted(items, key=lambda i: i.published_at, reverse=True))
        first = items[0]
        assert first.url.startswith("https://")
        assert first.source and "." in first.source
        assert first.title

    def test_rejects_non_http_links(self) -> None:
        xml = """<rss><channel>
          <item><title>bad</title><link>javascript:alert(1)</link>
            <pubDate>Fri, 13 Nov 2026 01:09:00 +0000</pubDate></item>
          <item><title>good</title><link>https://example.com/a</link>
            <pubDate>Fri, 13 Nov 2026 02:09:00 +0000</pubDate></item>
        </channel></rss>"""
        items = news.parse_rss(xml, since=datetime(2026, 11, 1, tzinfo=UTC), limit=5)
        assert [i.title for i in items] == ["good"]
        assert items[0].source == "example.com"

    def test_bad_xml_returns_empty(self) -> None:
        assert news.parse_rss("<not-xml", since=datetime(2026, 1, 1, tzinfo=UTC), limit=5) == ()

    def test_dedupes_titles(self) -> None:
        item = """<item><title>Same</title><link>https://a.com/{n}</link>
            <pubDate>Fri, 13 Nov 2026 0{n}:00:00 +0000</pubDate></item>"""
        xml = f"<rss><channel>{item.format(n=1)}{item.format(n=2)}</channel></rss>"
        assert len(news.parse_rss(xml, since=datetime(2026, 1, 1, tzinfo=UTC), limit=5)) == 1


class TestSecFilings:
    def test_cik_map_uses_dash_for_classes(self) -> None:
        ciks = sec_filings.parse_cik_map(fx("sec_company_tickers.json"))
        assert ciks["FWDI"] == 38264
        assert ciks["BRK.B"] == 1067983

    def test_recent_filings(self) -> None:
        filings = sec_filings.parse_filings(
            fx("sec_submissions_fwdi.json"), since=date(2026, 11, 1)
        )
        forms = [f.form for f in filings]
        assert "8-K" in forms and "424B5" in forms
        assert "4" not in forms  # insider forms are left out
        eight_k = next(f for f in filings if f.form == "8-K")
        assert eight_k.filed == date(2026, 11, 19)
        assert eight_k.items == ("1.01", "2.03", "9.01")
        assert "签订重大协议" in eight_k.labels_zh
        assert "财务报表与附件" not in eight_k.labels_zh  # 9.01 is boilerplate
        assert eight_k.url.startswith("https://www.sec.gov/Archives/edgar/data/38264/")
        assert all(f.filed >= date(2026, 11, 1) for f in filings)

    def test_labels_for_offering(self) -> None:
        assert sec_filings.form_labels("424B5", ()) == ("发行说明书（增发或发债）",)


class TestFinra:
    def test_latest_per_symbol(self) -> None:
        out = finra.parse_short_interest(fx("finra_short_interest.json"))
        assert set(out) == {"CVNA", "BOT", "FWDI"}
        bot = out["BOT"]
        assert bot.settlement_date == date(2026, 10, 30)
        assert bot.shares == 1_298_082
        assert bot.prev_shares == 898_372
        assert bot.days_to_cover == pytest.approx(3.14)
        assert bot.pct_of_shares is None

    def test_fetch_posts_symbols(self) -> None:
        bodies: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json=fx("finra_short_interest.json"))

        with mock_client(handler) as client:
            out = finra.fetch_short_interest(
                client, ["CVNA", "BOT"], today=date(2026, 11, 24), policy=NO_RETRY
            )
        assert "CVNA" in out
        domain = bodies[0]["domainFilters"]
        assert isinstance(domain, list) and domain[0]["values"] == ["BOT", "CVNA"]

    def test_fetch_empty_symbols_skips_call(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("no call expected")

        with mock_client(handler) as client:
            assert finra.fetch_short_interest(client, [], today=date(2026, 11, 24)) == {}


class TestFundingHistory:
    def test_binance(self) -> None:
        pts = funding_history.parse_binance(fx("binance_funding_history_fwdi.json"), 8.0)
        assert len(pts) == 21
        assert pts == tuple(sorted(pts, key=lambda p: p.time))
        assert pts[0].time.tzinfo is not None

    def test_binance_4h_interval_doubles(self) -> None:
        payload = [{"fundingTime": 1795363200001, "fundingRate": "0.0001"}]
        assert funding_history.parse_binance(payload, 4.0)[0].rate_8h == pytest.approx(0.0002)

    def test_hyperliquid_hourly_to_8h(self) -> None:
        pts = funding_history.parse_hyperliquid(fx("hl_funding_history_bot.json"))
        raw = fx("hl_funding_history_bot.json")
        assert isinstance(raw, list)
        assert pts[0].rate_8h == pytest.approx(float(raw[0]["fundingRate"]) * 8)


class TestNewsRelevance:
    XML = """<rss><channel>
      <item><title>Agilent Tops Q4 Earnings</title><link>https://a.com/1</link>
        <description>Also mentions Medtronic in passing.</description>
        <pubDate>Fri, 13 Nov 2026 01:00:00 +0000</pubDate></item>
      <item><title>Medtronic beats estimates</title><link>https://a.com/2</link>
        <pubDate>Fri, 13 Nov 2026 02:00:00 +0000</pubDate></item>
      <item><title>Stocks to watch</title><link>https://a.com/3</link>
        <description>Shares of Medtronic (MDT) rose.</description>
        <pubDate>Fri, 13 Nov 2026 03:00:00 +0000</pubDate></item>
      <item><title>Exxon raises dividend</title><link>https://a.com/4</link>
        <pubDate>Fri, 13 Nov 2026 04:00:00 +0000</pubDate></item>
      <item><title>General market wrap</title><link>https://a.com/5</link>
        <pubDate>Fri, 13 Nov 2026 05:00:00 +0000</pubDate></item>
      <item><title>General Motors recalls trucks</title><link>https://a.com/6</link>
        <pubDate>Fri, 13 Nov 2026 06:00:00 +0000</pubDate></item>
    </channel></rss>"""
    SINCE = datetime(2026, 11, 1, tzinfo=UTC)

    def titles(self, ticker: str, company: str | None) -> list[str]:
        rel = news.relevance_for(ticker, company)
        return [i.title for i in news.parse_rss(self.XML, self.SINCE, 10, rel)]

    def test_name_in_title_or_strong_ticker_anywhere(self) -> None:
        # A passing mention of the name in a summary does not count; "(MDT)" does.
        assert self.titles("MDT", "Medtronic plc") == [
            "Stocks to watch",
            "Medtronic beats estimates",
        ]

    def test_long_name_prefix(self) -> None:
        assert self.titles("XOM", "ExxonMobil Holdings Corporation") == ["Exxon raises dividend"]

    def test_generic_first_word_needs_two_words(self) -> None:
        assert self.titles("GM", "General Motors Company") == ["General Motors recalls trucks"]

    def test_short_ticker_needs_strong_form(self) -> None:
        rel = news.relevance_for("ON", None)
        assert not rel.matches("ON the move: chip stocks", "")
        assert rel.matches("Chip stocks", "onsemi (ON) gains")
        assert rel.matches("Chip stocks", "NASDAQ: ON jumps")

    def test_bare_ticker_counts_in_title_only(self) -> None:
        rel = news.relevance_for("NOW", None)
        assert rel.matches("ServiceNow NOW jumps", "")
        assert not rel.matches("buy now", "")
        assert not rel.matches("Tech wrap", "NOW and others")

    def test_doctype_is_refused(self) -> None:
        xml = '<!DOCTYPE rss [<!ENTITY a "b">]><rss><channel></channel></rss>'
        assert news.parse_rss(xml, self.SINCE, 10) == ()


def test_filings_dedupe_same_day_supplements() -> None:
    payload = {
        "cik": "1",
        "filings": {
            "recent": {
                "form": ["424B3", "424B3", "8-K"],
                "filingDate": ["2026-11-17", "2026-11-17", "2026-11-17"],
                "items": ["", "", "9.01"],
                "accessionNumber": ["a-1", "a-2", "a-3"],
                "primaryDocument": ["x.htm", "y.htm", "z.htm"],
            }
        },
    }
    filings = sec_filings.parse_filings(payload, since=date(2026, 11, 1))
    assert [f.form for f in filings] == ["424B3"]  # 8-K with only 9.01 is dropped too


def test_bank_structured_notes_are_skipped_and_8k_ranked_first() -> None:
    forms = ["424B2"] * 5 + ["424B5", "424B3", "424B5", "424B3", "S-3", "10-Q", "8-K"]
    n = len(forms)
    payload = {
        "cik": "1",
        "filings": {
            "recent": {
                "form": forms,
                "filingDate": [f"2026-11-{20 - i:02d}" for i in range(n)],
                "items": [""] * (n - 1) + ["2.02,9.01"],
                "accessionNumber": [f"a-{i}" for i in range(n)],
                "primaryDocument": [f"d{i}.htm" for i in range(n)],
            }
        },
    }
    filings = sec_filings.parse_filings(payload, since=date(2026, 11, 1))
    kinds = [f.form for f in filings]
    assert "424B2" not in kinds
    assert "8-K" in kinds and "10-Q" in kinds  # oldest, but ranked in over offerings
    assert len(filings) == sec_filings.MAX_FILINGS
    assert [f.filed for f in filings] == sorted((f.filed for f in filings), reverse=True)
    assert sec_filings.form_labels("SCHEDULE 13D", ()) == ("持股超 5%（主动型股东）",)


def test_shares_and_multi_class_parsers() -> None:
    assert nasdaq.parse_shares_outstanding(fx("nasdaq_summary_cvna.json")) == pytest.approx(
        70_454_253_846 / 68.0
    )
    assert nasdaq.parse_multi_class(fx("nasdaq_info_cvna.json")) is True
    plain = {"data": {"stockType": "Common Stock", "companyName": "Medtronic plc Ordinary Shares"}}
    assert nasdaq.parse_multi_class(plain) is False
    assert nasdaq.parse_shares_outstanding({"data": None}) is None
