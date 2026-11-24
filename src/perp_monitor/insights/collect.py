"""Build one insight card per ticker in each venue's funding top-N lists.

Every data source is optional: a failure is recorded on the card (or on the bundle for
batched sources) and the card is still built from whatever else came back.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime
from types import MappingProxyType
from typing import Any, Protocol, TypeVar

from perp_monitor.insights.analysis import (
    bucket_8h,
    classify_persistence,
    short_level,
    volume_verdict,
)
from perp_monitor.insights.clock import market_date
from perp_monitor.insights.models import (
    Catalysts,
    EarningsDate,
    Filing,
    FundingPoint,
    NewsItem,
    Profile,
    ShortInterest,
    Side,
    SpotStats,
    TickerInsight,
)
from perp_monitor.insights.narrative import NarrativeInput, answers, headline

log = logging.getLogger(__name__)

T = TypeVar("T")
NO_NEWS: tuple[NewsItem, ...] = ()
NO_FILINGS: tuple[Filing, ...] = ()
NO_HISTORY: tuple[FundingPoint, ...] = ()
NO_EARNINGS: Mapping[str, EarningsDate] = MappingProxyType({})
NO_SHORTS: Mapping[str, ShortInterest] = MappingProxyType({})
RANKINGS = ((Side.NEGATIVE, "funding_negative"), (Side.POSITIVE, "funding_positive"))


class InsightSource(Protocol):
    def warm_up(self) -> None: ...
    def profile(self, ticker: str) -> Profile | None: ...
    def spot(self, ticker: str) -> SpotStats | None: ...
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
    rank: int
    funding_8h: float
    funding_apr: float
    interval_hours: float
    oi_usd: float
    volume_24h_usd: float


@dataclass(frozen=True, slots=True)
class TickerData:
    profile: Profile | None
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


def targets_from_report(report: Mapping[str, Any]) -> tuple[Target, ...]:
    targets: list[Target] = []
    for section in report.get("sections", ()):
        if section.get("error"):
            continue
        rows = {r["ticker"]: r for r in section.get("rows", ())}
        for side, key in RANKINGS:
            for rank, ticker in enumerate(section.get("rankings", {}).get(key, ()), start=1):
                row = rows.get(ticker)
                if row is None:
                    continue
                targets.append(
                    Target(
                        venue=section["venue"],
                        ticker=ticker,
                        market=row["market"],
                        side=side,
                        rank=rank,
                        funding_8h=float(row["funding_8h"]),
                        funding_apr=float(row["funding_apr"]),
                        interval_hours=float(row["funding_interval_hours"]),
                        oi_usd=float(row["oi_usd"]),
                        volume_24h_usd=float(row.get("volume_24h_usd") or 0.0),
                    )
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
    errors = tuple(e for e in (e1, e2, e3, e4) if e)
    return TickerData(profile, spot, news, filings, errors)


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
    catalysts = Catalysts(data.news, data.filings, earnings.get(t.ticker))
    narrative = NarrativeInput(
        ticker=t.ticker,
        side=t.side,
        funding_8h=t.funding_8h,
        funding_apr=t.funding_apr,
        profile=data.profile,
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
        rank=t.rank,
        funding_8h=t.funding_8h,
        funding_apr=t.funding_apr,
        profile=data.profile,
        spot=data.spot,
        catalysts=catalysts,
        short_interest=si,
        short_level=level,
        persistence=persistence,
        volume=volume,
        headline=headline(narrative),
        answers=answers(narrative),
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
