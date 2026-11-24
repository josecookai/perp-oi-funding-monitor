from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from perp_monitor.insights.analysis import (
    bucket_8h,
    classify_persistence,
    short_level,
    spot_stats,
    volume_verdict,
)
from perp_monitor.insights.models import (
    FundingPattern,
    FundingPoint,
    ShortInterest,
    ShortLevel,
    SpotBar,
    VolumeTier,
)

T0 = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)


def points(rates: list[float], step_hours: float = 8.0) -> tuple[FundingPoint, ...]:
    return tuple(FundingPoint(T0 + timedelta(hours=step_hours * i), r) for i, r in enumerate(rates))


class TestVolumeVerdict:
    def test_small_oi_is_noise(self) -> None:
        v = volume_verdict(oi_usd=67_000, volume_24h_usd=358_000, spot_adv_usd=1e9)
        assert v.tier is VolumeTier.NOISE

    def test_tiny_volume_is_noise_even_with_oi(self) -> None:
        v = volume_verdict(oi_usd=900_000, volume_24h_usd=15_000, spot_adv_usd=None)
        assert v.tier is VolumeTier.NOISE

    def test_mid_size_is_thin(self) -> None:
        v = volume_verdict(oi_usd=362_000, volume_24h_usd=2_746_000, spot_adv_usd=None)
        assert v.tier is VolumeTier.THIN

    def test_large_oi_and_volume_is_meaningful(self) -> None:
        v = volume_verdict(oi_usd=5_144_000, volume_24h_usd=4_258_000, spot_adv_usd=2e8)
        assert v.tier is VolumeTier.MEANINGFUL
        assert v.oi_to_spot_adv == pytest.approx(5_144_000 / 2e8)

    def test_spot_ratio_none_without_spot(self) -> None:
        v = volume_verdict(oi_usd=1e6, volume_24h_usd=1e6, spot_adv_usd=0)
        assert v.oi_to_spot_adv is None


class TestBucket8h:
    def test_hourly_points_average_into_8h_buckets(self) -> None:
        hourly = points([0.001] * 8 + [-0.002] * 8, step_hours=1)
        buckets = bucket_8h(hourly)
        assert [b.rate_8h for b in buckets] == pytest.approx([0.001, -0.002])
        assert buckets[0].time == T0

    def test_8h_points_stay_as_is(self) -> None:
        buckets = bucket_8h(points([0.0, 0.0001, -0.005]))
        assert [b.rate_8h for b in buckets] == pytest.approx([0.0, 0.0001, -0.005])

    def test_empty(self) -> None:
        assert bucket_8h(()) == ()


class TestPersistence:
    def test_persistent_negative(self) -> None:
        p = classify_persistence(-0.001, bucket_8h(points([-0.001, -0.002, -0.0005, -0.001])))
        assert p.pattern is FundingPattern.PERSISTENT
        assert p.same_sign_share == pytest.approx(1.0)

    def test_spike_after_flat_history(self) -> None:
        # FWDI on 2026-11-24: zero or slightly positive, then a sudden -0.54%.
        history = bucket_8h(points([0.0, 0.00009, 0.0, 0.00034, 0.0, 0.0]))
        p = classify_persistence(-0.0034, history)
        assert p.pattern is FundingPattern.SPIKE
        assert p.same_sign_share == pytest.approx(0.0)

    def test_mixed(self) -> None:
        p = classify_persistence(-0.001, bucket_8h(points([-0.001, 0.001, -0.001, 0.001])))
        assert p.pattern is FundingPattern.MIXED

    def test_insufficient_history(self) -> None:
        p = classify_persistence(-0.001, bucket_8h(points([-0.001])))
        assert p.pattern is FundingPattern.INSUFFICIENT
        assert p.same_sign_share is None

    def test_multiple_of_mean(self) -> None:
        p = classify_persistence(-0.004, bucket_8h(points([-0.001, -0.001, -0.001])))
        assert p.multiple_of_mean == pytest.approx(4.0)
        assert p.mean_8h == pytest.approx(-0.001)

    def test_multiple_none_when_history_is_all_zero(self) -> None:
        p = classify_persistence(-0.004, bucket_8h(points([0.0, 0.0, 0.0])))
        assert p.multiple_of_mean is None


class TestShortLevel:
    def si(self, pct: float | None, dtc: float | None = 2.0) -> ShortInterest:
        return ShortInterest(date(2026, 10, 30), 1e6, 9e5, dtc, pct)

    @pytest.mark.parametrize(
        ("pct", "level"),
        [
            (0.19, ShortLevel.HIGH),
            (0.09, ShortLevel.ELEVATED),
            (0.05, ShortLevel.MODERATE),
            (0.011, ShortLevel.LOW),
        ],
    )
    def test_levels(self, pct: float, level: ShortLevel) -> None:
        assert short_level(self.si(pct)) is level

    def test_unknown_without_data(self) -> None:
        assert short_level(None) is ShortLevel.UNKNOWN
        assert short_level(self.si(None)) is ShortLevel.UNKNOWN

    def test_long_days_to_cover_raises_low_to_moderate(self) -> None:
        # FRHC: 1.6% of shares but 9.8 days to cover (tiny free float).
        assert short_level(self.si(0.016, dtc=9.8)) is ShortLevel.MODERATE


class TestSpotStats:
    def bars(self, closes: list[float], volume: float = 1000.0) -> list[SpotBar]:
        start = date(2026, 10, 1)
        return [SpotBar(start + timedelta(days=i), c, volume) for i, c in enumerate(closes)]

    def test_returns_and_adv(self) -> None:
        closes = [100.0] * 15 + [100.0, 101.0, 102.0, 103.0, 104.0, 110.0]
        s = spot_stats(self.bars(closes), shares_outstanding=5e8, multi_class=True)
        assert s is not None
        assert s.close == 110.0
        assert s.ret_1d == pytest.approx(110 / 104 - 1)
        assert s.ret_5d == pytest.approx(110 / 100 - 1)
        assert s.ret_20d == pytest.approx(110 / 100 - 1)
        last20 = closes[-20:]
        assert s.adv_usd_20d == pytest.approx(sum(c * 1000 for c in last20) / 20)
        assert s.shares_outstanding == 5e8
        assert s.multi_class is True

    def test_short_history(self) -> None:
        s = spot_stats(self.bars([10.0, 11.0]), shares_outstanding=None)
        assert s is not None
        assert s.ret_1d == pytest.approx(0.1)
        assert s.ret_5d is None and s.ret_20d is None

    def test_unordered_input_is_sorted(self) -> None:
        bars = self.bars([10.0, 11.0, 12.0])
        s = spot_stats(list(reversed(bars)), shares_outstanding=None)
        assert s is not None and s.close == 12.0

    def test_empty(self) -> None:
        assert spot_stats([], shares_outstanding=None) is None
