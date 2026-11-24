"""Build insight cards: funding top-N per venue, side and volume bucket.

Every data source is optional: a failure is recorded on the card (or on the bundle for
batched sources) and the card is still built from whatever else came back.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from types import MappingProxyType
from typing import Any, Protocol, TypeVar

from perp_monitor.insights.analysis import (
    bucket_8h,
    bucket_for,
    classify_persistence,
    short_level,
    volume_tier,
    volume_verdict,
)
from perp_monitor.insights.clock import market_date
from perp_monitor.insights.models import (
    Bucket,
    Catalysts,
    EarningsDate,
    Filing,
    Fundamentals,
    FundingPoint,
    LastEarnings,
    NewsItem,
    Profile,
    ShortInterest,
    Side,
    SpotStats,
    TickerInsight,
)
from perp_monitor.insights.narrative import NarrativeInput, answers, english_summary, headline

log = logging.getLogger(__name__)

T = TypeVar("T")
NO_NEWS: tuple[NewsItem, ...] = ()
NO_FILINGS: tuple[Filing, ...] = ()
NO_HISTORY: tuple[FundingPoint, ...] = ()
NO_EARNINGS: Mapping[str, EarningsDate] = MappingProxyType({})
NO_SHORTS: Mapping[str, ShortInterest] = MappingProxyType({})
DEFAULT_TOP_N = 10
QUARTER = timedelta(days=91)


class InsightSource(Protocol):
    def warm_up(self) -> None: ...
    def profile(self, ticker: str) -> Profile | None: ...
    def spot(self, ticker: str) -> SpotStats | None: ...
    def fundamentals(self, ticker: str) -> Fundamentals | None: ...
    def last_earnings(self, ticker: str) -> LastEarnings | None: ...
    def news(self, ticker: str) -> tuple[NewsItem, ...]: ...
    def filings(self, ticker: str) -> tuple[Filing, ...]: ...
    def earnings(self, tickers: Sequence[str]) -> Mapping[str, EarningsDate]: ...
    def short_interest(self, tickers: Iterable[str]) -> Mapping[str, ShortInterest]: ...
    def funding_history(
        self, venue: str, market: str, interval_hours: float
    ) -> tuple[FundingPoint, ...]: ...


@dataclass(frozen=True, slots=True)
class Target:
    venue: str
    ticker: str
    market: str
    side: Side
    bucket: Bucket
    rank: int
    funding_8h: float
    funding_apr: float
    interval_hours: float
    oi_usd: float
    volume_24h_usd: float


@dataclass(frozen=True, slots=True)
class TickerData:
    profile: Profile | None
    fundamentals: Fundamentals | None
    last_earnings: LastEarnings | None
    spot: SpotStats | None
    news: tuple[NewsItem, ...]
    filings: tuple[Filing, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InsightsBundle:
    generated_at: datetime
    market_date: date  # US-Eastern calendar day the day offsets are counted from
    report_generated_at: str
    items: tuple[TickerInsight, ...]
    errors: tuple[str, ...]


def _row_sign_ok(row: Mapping[str, Any], side: Side) -> bool:
    f = float(row["funding_8h"])
    return f < 0 if side is Side.NEGATIVE else f > 0


def targets_from_report(report: Mapping[str, Any], top_n: int | None = None) -> tuple[Target, ...]:
    """Top-N funding per (venue, side, volume bucket), most extreme first.

    Ranking inside each bucket means the liquid page shows the most extreme funding among
    markets big enough to matter, instead of the same thinly traded names that lead the
    overall ranking.
    """
    n = top_n or int(report.get("top_n") or DEFAULT_TOP_N)
    targets: list[Target] = []
    for section in report.get("sections", ()):
        if section.get("error"):
            continue
        rows = section.get("rows", ())
        for side in (Side.NEGATIVE, Side.POSITIVE):
            ordered = sorted(
                (r for r in rows if _row_sign_ok(r, side)),
                key=lambda r: (-abs(float(r["funding_8h"])), r["ticker"]),
            )
            for bucket in (Bucket.LIQUID, Bucket.ILLIQUID):
                picked = [
                    r
                    for r in ordered
                    if bucket_for(
                        volume_tier(float(r["oi_usd"]), float(r.get("volume_24h_usd") or 0))
                    )
                    is bucket
                ][:n]
                targets.extend(
                    Target(
                        venue=section["venue"],
                        ticker=row["ticker"],
                        market=row["market"],
                        side=side,
                        bucket=bucket,
                        rank=rank,
                        funding_8h=float(row["funding_8h"]),
                        funding_apr=float(row["funding_apr"]),
                        interval_hours=float(row["funding_interval_hours"]),
                        oi_usd=float(row["oi_usd"]),
                        volume_24h_usd=float(row.get("volume_24h_usd") or 0.0),
                    )
                    for rank, row in enumerate(picked, start=1)
                )
    return tuple(targets)


def _describe(label: str, exc: Exception) -> str:
    """Short error for the committed JSON: no upstream response bodies, no URLs."""
    status = getattr(exc, "status", None)
    return f"{label}: {type(exc).__name__}" + (f" (HTTP {status})" if status else "")


def _attempt(label: str, fn: Callable[[], T], default: T) -> tuple[T, str | None]:
    try:
        return fn(), None
    except Exception as exc:  # each source is optional; record and move on
        log.warning("%s failed: %s: %s", label, type(exc).__name__, exc)
        return default, _describe(label, exc)


def _ticker_data(source: InsightSource, ticker: str) -> TickerData:
    profile, e1 = _attempt(f"{ticker} profile", lambda: source.profile(ticker), None)
    spot, e2 = _attempt(f"{ticker} spot", lambda: source.spot(ticker), None)
    news, e3 = _attempt(f"{ticker} news", lambda: source.news(ticker), NO_NEWS)
    filings, e4 = _attempt(f"{ticker} filings", lambda: source.filings(ticker), NO_FILINGS)
    funds, e5 = _attempt(f"{ticker} financials", lambda: source.fundamentals(ticker), None)
    last, e6 = _attempt(f"{ticker} last earnings", lambda: source.last_earnings(ticker), None)
    errors = tuple(e for e in (e1, e2, e3, e4, e5, e6) if e)
    return TickerData(profile, funds, last, spot, news, filings, errors)


def next_earnings(
    listed: EarningsDate | None, last: LastEarnings | None, today: date
) -> EarningsDate | None:
    """The calendar's date when Nasdaq lists one (about five weeks ahead), else an estimate:
    the last report date plus one quarter, rolled forward past dates more than a week old.
    """
    if listed is not None:
        return listed
    if last is None:
        return None
    day = last.reported + QUARTER
    while day < today - timedelta(days=7):
        day += QUARTER
    return EarningsDate(day, None, confirmed=False)


def _with_pct(si: ShortInterest | None, spot: SpotStats | None) -> ShortInterest | None:
    if si is None or spot is None or not spot.shares_outstanding:
        return si
    return replace(si, pct_of_shares=si.shares / spot.shares_outstanding)


def _assemble(
    t: Target,
    data: TickerData,
    history: tuple[FundingPoint, ...],
    history_error: str | None,
    earnings: Mapping[str, EarningsDate],
    shorts: Mapping[str, ShortInterest],
    today: date,
) -> TickerInsight:
    persistence = classify_persistence(t.funding_8h, bucket_8h(history))
    adv = data.spot.adv_usd_20d if data.spot else None
    volume = volume_verdict(t.oi_usd, t.volume_24h_usd, adv)
    si = _with_pct(shorts.get(t.ticker), data.spot)
    level = short_level(si)
    catalysts = Catalysts(
        data.news,
        data.filings,
        next_earnings(earnings.get(t.ticker), data.last_earnings, today),
        data.last_earnings,
    )
    narrative = NarrativeInput(
        ticker=t.ticker,
        side=t.side,
        funding_8h=t.funding_8h,
        funding_apr=t.funding_apr,
        profile=data.profile,
        fundamentals=data.fundamentals,
        spot=data.spot,
        catalysts=catalysts,
        short_interest=si,
        short_level=level,
        persistence=persistence,
        volume=volume,
        today=today,
    )
    errors = data.errors + ((history_error,) if history_error else ())
    return TickerInsight(
        venue=t.venue,
        ticker=t.ticker,
        market=t.market,
        side=t.side,
        bucket=t.bucket,
        rank=t.rank,
        funding_8h=t.funding_8h,
        funding_apr=t.funding_apr,
        profile=data.profile,
        fundamentals=data.fundamentals,
        spot=data.spot,
        catalysts=catalysts,
        short_interest=si,
        short_level=level,
        persistence=persistence,
        volume=volume,
        headline=headline(narrative),
        answers=answers(narrative),
        summary_en=english_summary(data.profile),
        errors=errors,
    )


def build_insights(
    report: Mapping[str, Any], source: InsightSource, now: datetime, workers: int = 4
) -> InsightsBundle:
    targets = targets_from_report(report)
    tickers = sorted({t.ticker for t in targets})
    _, warm_error = _attempt("warm-up", source.warm_up, None)

    def history(t: Target) -> tuple[tuple[FundingPoint, ...], str | None]:
        return _attempt(
            f"{t.venue}:{t.ticker} funding history",
            lambda: source.funding_history(t.venue, t.market, t.interval_hours),
            NO_HISTORY,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        per_ticker = dict(
            zip(tickers, pool.map(lambda x: _ticker_data(source, x), tickers), strict=True)
        )
        histories = list(pool.map(history, targets))
    earnings, earnings_error = _attempt("earnings", lambda: source.earnings(tickers), NO_EARNINGS)
    shorts, shorts_error = _attempt(
        "short interest", lambda: source.short_interest(tickers), NO_SHORTS
    )

    today = market_date(now)

    def card(
        t: Target, hist: tuple[FundingPoint, ...], err: str | None
    ) -> tuple[TickerInsight | None, str | None]:
        def build() -> TickerInsight | None:
            return _assemble(t, per_ticker[t.ticker], hist, err, earnings, shorts, today)

        return _attempt(f"{t.venue}:{t.ticker} card", build, None)

    cards = [card(t, hist, err) for t, (hist, err) in zip(targets, histories, strict=True)]
    items = tuple(card for card, _ in cards if card is not None)
    card_errors = tuple(e for _, e in cards if e)
    errors = tuple(e for e in (warm_error, earnings_error, shorts_error) if e) + card_errors
    return InsightsBundle(now, today, str(report.get("generated_at", "")), items, errors)
