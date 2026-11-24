"""Immutable data model for the per-ticker insight cards on the dashboard.

Each card answers the questions asked about every extreme-funding ticker:
what is the company, what happened recently (catalysts), is the perp volume big
enough to mean anything, and is the stock a crowded short.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class Side(StrEnum):
    NEGATIVE = "negative"  # shorts pay longs
    POSITIVE = "positive"  # longs pay shorts


class VolumeTier(StrEnum):
    MEANINGFUL = "meaningful"
    THIN = "thin"
    NOISE = "noise"


class FundingPattern(StrEnum):
    PERSISTENT = "persistent"  # most recent periods had the same sign
    SPIKE = "spike"  # the current sign is new or rare in the lookback
    MIXED = "mixed"
    INSUFFICIENT = "insufficient"  # too little history to say


class ShortLevel(StrEnum):
    HIGH = "high"
    ELEVATED = "elevated"
    MODERATE = "moderate"
    LOW = "low"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    sector: str | None
    industry: str | None
    description: str | None


@dataclass(frozen=True, slots=True)
class SpotBar:
    day: date
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class SpotStats:
    as_of: date
    close: float
    ret_1d: float | None
    ret_5d: float | None
    ret_20d: float | None
    adv_usd_20d: float | None  # average daily dollar volume, last 20 sessions
    shares_outstanding: float | None  # market cap / close, both from the same quote
    multi_class: bool = False  # the listed line is one class of several (GOOGL, BRK.B)


@dataclass(frozen=True, slots=True)
class NewsItem:
    title: str
    url: str
    published_at: datetime
    source: str
    summary: str


@dataclass(frozen=True, slots=True)
class Filing:
    form: str
    filed: date
    items: tuple[str, ...]
    labels_zh: tuple[str, ...]
    url: str


@dataclass(frozen=True, slots=True)
class EarningsDate:
    day: date
    timing: str | None  # "bmo" (before open), "amc" (after close) or None


@dataclass(frozen=True, slots=True)
class ShortInterest:
    settlement_date: date
    shares: float
    prev_shares: float | None
    days_to_cover: float | None
    pct_of_shares: float | None  # short shares / shares outstanding, if known

    @property
    def change_pct(self) -> float | None:
        if not self.prev_shares:
            return None
        return (self.shares - self.prev_shares) / self.prev_shares


@dataclass(frozen=True, slots=True)
class FundingPoint:
    time: datetime
    rate_8h: float


@dataclass(frozen=True, slots=True)
class FundingPersistence:
    pattern: FundingPattern
    buckets: tuple[FundingPoint, ...]  # 8h buckets over the lookback, oldest first
    same_sign_share: float | None
    mean_8h: float | None
    multiple_of_mean: float | None  # |current| / mean |history|


@dataclass(frozen=True, slots=True)
class VolumeVerdict:
    tier: VolumeTier
    oi_usd: float
    volume_24h_usd: float
    oi_to_spot_adv: float | None  # perp OI / spot average dollar volume


@dataclass(frozen=True, slots=True)
class Catalysts:
    news: tuple[NewsItem, ...] = ()
    filings: tuple[Filing, ...] = ()
    earnings: EarningsDate | None = None


@dataclass(frozen=True, slots=True)
class TickerInsight:
    venue: str
    ticker: str
    market: str
    side: Side
    rank: int
    funding_8h: float
    funding_apr: float
    profile: Profile | None
    spot: SpotStats | None
    catalysts: Catalysts
    short_interest: ShortInterest | None
    short_level: ShortLevel
    persistence: FundingPersistence
    volume: VolumeVerdict
    headline: str
    answers: tuple[tuple[str, str], ...]  # (question key, one-line answer), display order
    errors: tuple[str, ...] = field(default=())

    @property
    def key(self) -> str:
        return f"{self.venue}:{self.ticker}"
