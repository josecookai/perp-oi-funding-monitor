from __future__ import annotations

from datetime import timedelta

import pytest

from perp_monitor.delta import compute_changes, make_window
from perp_monitor.models import Venue
from perp_monitor.ranking import (
    top_negative_funding,
    top_oi_gainers,
    top_oi_losers,
    top_positive_funding,
)
from tests.factories import T0, T8, change, prior, snap


def test_compute_changes_matches_by_market() -> None:
    current = [snap("NVDA", oi=120, price=100), snap("TSLA", oi=50)]
    changes = compute_changes(current, {"NVDAUSDT": prior(100, price=90)})
    nvda, tsla = changes
    assert nvda.d_oi_usd == pytest.approx(120 * 100 - 100 * 90)
    assert nvda.d_oi_pct == pytest.approx((12000 - 9000) / 9000)
    assert nvda.d_contracts_pct == pytest.approx(0.2)
    assert tsla.is_new and tsla.d_oi_usd is None and tsla.d_oi_pct is None


def test_change_handles_zero_prior_oi() -> None:
    item = compute_changes([snap("NVDA", oi=10)], {"NVDAUSDT": prior(0)})[0]
    assert item.d_oi_usd == pytest.approx(1000)
    assert item.d_oi_pct is None


def test_funding_change_uses_8h_equivalents() -> None:
    current = [snap("NVDA", funding=0.0001, venue=Venue.HYPERLIQUID)]  # hourly
    item = compute_changes(current, {"xyz:NVDA": prior(1000, funding_8h=0.0002)})[0]
    assert item.current.funding_8h == pytest.approx(0.0008)
    assert item.d_funding_8h == pytest.approx(0.0006)


def test_funding_change_unknown_for_backfilled_prior() -> None:
    item = compute_changes([snap("NVDA")], {"NVDAUSDT": prior(1000, funding_8h=None)})[0]
    assert item.d_funding_8h is None


def test_make_window() -> None:
    window = make_window(T0, T8, expected_hours=8, tolerance_hours=1, origin="store")
    assert window.hours == pytest.approx(8)
    assert window.in_range and not window.is_baseline
    late = make_window(
        T0, T8 + timedelta(hours=8), expected_hours=8, tolerance_hours=1, origin="store"
    )
    assert not late.in_range
    baseline = make_window(None, T8, expected_hours=8, tolerance_hours=1, origin=None)
    assert baseline.is_baseline and baseline.in_range


def test_top_oi_gainers_and_losers_rank_by_usd_change() -> None:
    changes = [
        change("AAA", 1500, 1000),  # +50,000
        change("BBB", 1100, 1000),  # +10,000
        change("CCC", 900, 1000),  # -10,000
        change("DDD", 400, 1000),  # -60,000
        change("EEE", 1000, 1000),  # 0
        change("NEW", 5000, None),  # new listing: never ranked
    ]
    assert [c.current.ticker for c in top_oi_gainers(changes, 10)] == ["AAA", "BBB"]
    assert [c.current.ticker for c in top_oi_losers(changes, 10)] == ["DDD", "CCC"]
    assert [c.current.ticker for c in top_oi_gainers(changes, 1)] == ["AAA"]


def test_funding_rankings_skip_zero_and_sort_by_8h_rate() -> None:
    changes = [
        change("AAA", 1, 1, funding=-0.0003),
        change("BBB", 1, 1, funding=-0.0001),
        change("ZER", 1, 1, funding=0.0),
        change("CCC", 1, 1, funding=0.0002),
        # hourly 0.00005 = 0.0004 per 8h, so it outranks CCC
        change("HLX", 1, 1, funding=0.00005, venue=Venue.HYPERLIQUID),
        change("NEW", 1, None, funding=0.001),  # new listings still have a funding rate
    ]
    neg = [c.current.ticker for c in top_negative_funding(changes, 10)]
    pos = [c.current.ticker for c in top_positive_funding(changes, 10)]
    assert neg == ["AAA", "BBB"]
    assert pos == ["NEW", "HLX", "CCC"]


def test_rankings_break_ties_by_ticker() -> None:
    changes = [change("ZZZ", 1, 1, funding=0.0001), change("AAA", 1, 1, funding=0.0001)]
    assert [c.current.ticker for c in top_positive_funding(changes, 10)] == ["AAA", "ZZZ"]
