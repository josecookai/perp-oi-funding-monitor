"""The real data source behind the insight cards.

Company facts live in the local company database (company_db.py); short-lived API
results (CIK map, earnings calendar days, FINRA) in the JSON cache.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta

import httpx

from perp_monitor.http import HttpError, RetryPolicy
from perp_monitor.insights import finra, funding_history, nasdaq, news, sec_filings
from perp_monitor.insights.analysis import spot_stats
from perp_monitor.insights.cache import JsonCache
from perp_monitor.insights.clock import market_date
from perp_monitor.insights.company_db import CompanyDB
from perp_monitor.insights.company_zh import ZhEntry, with_zh
from perp_monitor.insights.models import (
    EarningsDate,
    Filing,
    Fundamentals,
    FundingPoint,
    LastEarnings,
    NewsItem,
    Profile,
    ShortInterest,
    SpotStats,
)

log = logging.getLogger(__name__)

PROFILE_TTL = timedelta(days=30)
MISSING_PROFILE_TTL = timedelta(days=1)
CIK_TTL = timedelta(days=7)
SHARES_TTL = timedelta(days=3)
FINANCIALS_TTL = timedelta(days=7)
LAST_EARNINGS_TTL = timedelta(days=1)
EARNINGS_DAY_TTL = timedelta(hours=6)
SHORT_INTEREST_TTL = timedelta(hours=12)
NEWS_LOOKBACK = timedelta(days=7)
FILINGS_LOOKBACK_DAYS = 14
EARNINGS_WINDOW = (-7, 35)  # calendar days around today; Nasdaq lists ~5 weeks ahead
POLICY = RetryPolicy(attempts=2, backoff_seconds=1.0)


class LiveSource:
    def __init__(
        self,
        http: httpx.Client,
        cache: JsonCache,
        now: datetime,
        *,
        companies: CompanyDB,
        zh: Mapping[str, ZhEntry] | None = None,
        binance_base_url: str,
        hl_info_url: str,
        sec_user_agent: str,
    ) -> None:
        self._http = http
        self._cache = cache
        self._now = now
        self._db = companies
        self._zh = zh or {}
        self._binance = binance_base_url
        self._hl = hl_info_url
        self._sec_ua = sec_user_agent
        self._ciks: Mapping[str, int] | None = None

    @property
    def today(self) -> date:
        """US-Eastern calendar day (earnings, filings and bars are ET days)."""
        return market_date(self._now)

    def _db_profile(self, ticker: str) -> tuple[bool, Profile | None]:
        """(known, profile) from the database: known means a fresh entry, even an empty one."""
        row = self._db.get(ticker)
        if row is None:
            return False, None
        found = row.profile()
        ttl = PROFILE_TTL if found is not None else MISSING_PROFILE_TTL
        return row.fresh("profile", self._now, ttl), found

    def profile(self, ticker: str) -> Profile | None:
        known, found = self._db_profile(ticker)
        if not known:
            found = nasdaq.fetch_profile(self._http, ticker, policy=POLICY)
            self._db.save_profile(ticker, found, self._now)
        return with_zh(found, self._zh.get(ticker))

    def _share_info(self, ticker: str) -> tuple[float | None, bool, float | None]:
        row = self._db.get(ticker)
        if row is not None and row.fresh("shares", self._now, SHARES_TTL):
            return row.shares()
        shares, multi, cap = nasdaq.fetch_share_info(self._http, ticker, policy=POLICY)
        self._db.save_shares(ticker, shares, multi, cap, self._now)
        return shares, multi, cap

    def spot(self, ticker: str) -> SpotStats | None:
        bars = nasdaq.fetch_bars(self._http, ticker, self.today, policy=POLICY)
        try:
            shares, multi, _ = self._share_info(ticker)
        except HttpError as exc:
            log.warning("%s share count: %s", ticker, exc)
            shares, multi = None, False
        return spot_stats(bars, shares, multi)

    def fundamentals(self, ticker: str) -> Fundamentals | None:
        row = self._db.get(ticker)
        if row is not None and row.fresh("financials", self._now, FINANCIALS_TTL):
            found = row.fundamentals()
        else:
            found = nasdaq.fetch_financials(self._http, ticker, None, policy=POLICY)
            self._db.save_financials(ticker, found, self._now)
        try:
            _, _, cap = self._share_info(ticker)
        except HttpError:
            cap = None
        if found is None:
            return None if cap is None else Fundamentals(cap, None, None, None, 0)
        return Fundamentals(
            cap, found.revenue_ttm_usd, found.gross_profit_ttm_usd, found.period_end, found.quarters
        )

    def last_earnings(self, ticker: str) -> LastEarnings | None:
        row = self._db.get(ticker)
        if row is not None and row.fresh("earnings", self._now, LAST_EARNINGS_TTL):
            return row.last_earnings()
        found = nasdaq.fetch_earnings_surprise(self._http, ticker, policy=POLICY)
        self._db.save_last_earnings(ticker, found, self._now)
        return found

    def news(self, ticker: str) -> tuple[NewsItem, ...]:
        # profile() already ran for this ticker in the same worker; only read the database.
        _, company = self._db_profile(ticker)
        return news.fetch_news(
            self._http,
            ticker,
            self._now - NEWS_LOOKBACK,
            company=company.name if company else None,
            policy=POLICY,
        )

    def _cik_map(self) -> Mapping[str, int]:
        if self._ciks is None:
            cached = self._cache.get("sec:ciks", CIK_TTL)
            if isinstance(cached, dict):
                self._ciks = {k: int(v) for k, v in cached.items()}
                return self._ciks
            try:
                fetched = sec_filings.fetch_cik_map(self._http, self._sec_ua, policy=POLICY)
            except Exception:
                self._ciks = {}  # don't refetch from every worker; filings() returns ()
                raise
            self._ciks = fetched
            self._cache.put("sec:ciks", dict(fetched))
        return self._ciks

    def warm_up(self) -> None:
        """Load shared lookups once, before worker threads start."""
        self._cik_map()

    def filings(self, ticker: str) -> tuple[Filing, ...]:
        cik = self._cik_map().get(ticker)
        if cik is None:
            return ()
        since = self.today - timedelta(days=FILINGS_LOOKBACK_DAYS)
        return sec_filings.fetch_filings(self._http, cik, since, self._sec_ua, policy=POLICY)

    def earnings(self, tickers: Sequence[str]) -> Mapping[str, EarningsDate]:
        wanted = set(tickers)
        found: dict[str, EarningsDate] = {}
        start, end = EARNINGS_WINDOW
        for offset in range(start, end + 1):
            day = self.today + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            try:
                calendar = self._earnings_day(day)
            except HttpError as exc:
                log.warning("earnings calendar %s: %s", day, exc)
                continue
            for symbol, event in calendar.items():
                if symbol in wanted and _closer(event.day, found.get(symbol), self.today):
                    found[symbol] = event
        return found

    def _earnings_day(self, day: date) -> dict[str, EarningsDate]:
        key = f"earnings:{day.isoformat()}"
        cached = self._cache.get(key, EARNINGS_DAY_TTL)
        if isinstance(cached, dict):
            return {
                s: EarningsDate(date.fromisoformat(v["day"]), v.get("timing"))
                for s, v in cached.items()
            }
        calendar = nasdaq.fetch_earnings_day(self._http, day, policy=POLICY)
        self._cache.put(
            key, {s: {"day": e.day.isoformat(), "timing": e.timing} for s, e in calendar.items()}
        )
        return calendar

    def short_interest(self, tickers: Iterable[str]) -> Mapping[str, ShortInterest]:
        wanted = sorted(set(tickers))
        key = "finra:" + ",".join(wanted)
        cached = self._cache.get(key, SHORT_INTEREST_TTL)
        if isinstance(cached, dict):
            return {
                s: ShortInterest(
                    date.fromisoformat(v["settlement_date"]),
                    v["shares"],
                    v["prev_shares"],
                    v["days_to_cover"],
                    None,
                )
                for s, v in cached.items()
            }
        found = finra.fetch_short_interest(self._http, wanted, self.today, policy=POLICY)
        self._cache.put(
            key,
            {
                s: {
                    "settlement_date": si.settlement_date.isoformat(),
                    "shares": si.shares,
                    "prev_shares": si.prev_shares,
                    "days_to_cover": si.days_to_cover,
                }
                for s, si in found.items()
            },
        )
        return found

    def funding_history(
        self, venue: str, market: str, interval_hours: float
    ) -> tuple[FundingPoint, ...]:
        if venue == "binance":
            return funding_history.fetch_binance(
                self._http, self._binance, market, interval_hours, self._now, policy=POLICY
            )
        return funding_history.fetch_hyperliquid(
            self._http, self._hl, market, self._now, policy=POLICY
        )


def _closer(day: date, current: EarningsDate | None, today: date) -> bool:
    """Keep whichever earnings date is nearest to today."""
    if current is None:
        return True
    return abs((day - today).days) < abs((current.day - today).days)
