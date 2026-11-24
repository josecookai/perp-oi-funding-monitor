"""Pure rules behind the insight cards: volume tier, funding persistence, short level.

Thresholds are module constants so the dashboard's method page can quote them.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from perp_monitor.insights.models import (
    Bucket,
    FundingPattern,
    FundingPersistence,
    FundingPoint,
    ShortInterest,
    ShortLevel,
    SpotBar,
    SpotStats,
    VolumeTier,
    VolumeVerdict,
)

# Volume tiers. Calibrated on 2026-11-24: Binance stock perps have median OI ~$0.65M and
# median 24h volume ~$1.9M; Hyperliquid xyz has median OI ~$3.7M.
NOISE_OI_USD = 250_000.0
NOISE_VOLUME_USD = 100_000.0
MEANINGFUL_OI_USD = 1_000_000.0
MEANINGFUL_VOLUME_USD = 1_000_000.0

# Funding persistence over the lookback (8h buckets).
MIN_BUCKETS = 3
PERSISTENT_SHARE = 0.6
SPIKE_SHARE = 0.25

# Short interest as a share of shares outstanding.
SHORT_HIGH = 0.15
SHORT_ELEVATED = 0.08
SHORT_MODERATE = 0.04
LONG_DAYS_TO_COVER = 7.0

BUCKET_SECONDS = 8 * 3600
ADV_SESSIONS = 20


def volume_tier(oi_usd: float, volume_24h_usd: float) -> VolumeTier:
    if oi_usd < NOISE_OI_USD or volume_24h_usd < NOISE_VOLUME_USD:
        return VolumeTier.NOISE
    if oi_usd >= MEANINGFUL_OI_USD and volume_24h_usd >= MEANINGFUL_VOLUME_USD:
        return VolumeTier.MEANINGFUL
    return VolumeTier.THIN


def bucket_for(tier: VolumeTier) -> Bucket:
    return Bucket.LIQUID if tier is VolumeTier.MEANINGFUL else Bucket.ILLIQUID


def volume_verdict(
    oi_usd: float, volume_24h_usd: float, spot_adv_usd: float | None
) -> VolumeVerdict:
    ratio = oi_usd / spot_adv_usd if spot_adv_usd else None
    return VolumeVerdict(volume_tier(oi_usd, volume_24h_usd), oi_usd, volume_24h_usd, ratio)


def bucket_8h(points: Iterable[FundingPoint]) -> tuple[FundingPoint, ...]:
    """Average 8h-equivalent rates into UTC-aligned 8h buckets (00/08/16), oldest first."""
    groups: dict[int, list[float]] = {}
    for p in points:
        start = int(p.time.timestamp()) // BUCKET_SECONDS * BUCKET_SECONDS
        groups.setdefault(start, []).append(p.rate_8h)
    return tuple(
        FundingPoint(datetime.fromtimestamp(start, UTC), sum(rates) / len(rates))
        for start, rates in sorted(groups.items())
    )


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def classify_persistence(current_8h: float, buckets: Sequence[FundingPoint]) -> FundingPersistence:
    """Compare the current rate with the lookback buckets (which exclude nothing)."""
    if len(buckets) < MIN_BUCKETS:
        return FundingPersistence(FundingPattern.INSUFFICIENT, tuple(buckets), None, None, None)
    rates = [b.rate_8h for b in buckets]
    sign = _sign(current_8h)
    share = sum(1 for r in rates if _sign(r) == sign and sign != 0) / len(rates)
    mean = sum(rates) / len(rates)
    mean_abs = sum(abs(r) for r in rates) / len(rates)
    multiple = abs(current_8h) / mean_abs if mean_abs > 0 else None
    if share >= PERSISTENT_SHARE:
        pattern = FundingPattern.PERSISTENT
    elif share <= SPIKE_SHARE:
        pattern = FundingPattern.SPIKE
    else:
        pattern = FundingPattern.MIXED
    return FundingPersistence(pattern, tuple(buckets), share, mean, multiple)


def short_level(si: ShortInterest | None) -> ShortLevel:
    if si is None or si.pct_of_shares is None:
        return ShortLevel.UNKNOWN
    pct = si.pct_of_shares
    if pct >= SHORT_HIGH:
        return ShortLevel.HIGH
    if pct >= SHORT_ELEVATED:
        return ShortLevel.ELEVATED
    if pct >= SHORT_MODERATE:
        return ShortLevel.MODERATE
    # A small short position can still be hard to cover when the free float is tiny.
    if si.days_to_cover is not None and si.days_to_cover >= LONG_DAYS_TO_COVER:
        return ShortLevel.MODERATE
    return ShortLevel.LOW


def _ret(closes: Sequence[float], sessions: int) -> float | None:
    if len(closes) <= sessions or closes[-1 - sessions] == 0:
        return None
    return closes[-1] / closes[-1 - sessions] - 1


def spot_stats(
    bars: Iterable[SpotBar], shares_outstanding: float | None, multi_class: bool = False
) -> SpotStats | None:
    ordered = sorted(bars, key=lambda b: b.day)
    if not ordered:
        return None
    closes = [b.close for b in ordered]
    recent = ordered[-ADV_SESSIONS:]
    adv = sum(b.close * b.volume for b in recent) / len(recent)
    return SpotStats(
        as_of=ordered[-1].day,
        close=closes[-1],
        ret_1d=_ret(closes, 1),
        ret_5d=_ret(closes, 5),
        ret_20d=_ret(closes, 20),
        adv_usd_20d=adv,
        shares_outstanding=shares_outstanding,
        multi_class=multi_class,
    )
