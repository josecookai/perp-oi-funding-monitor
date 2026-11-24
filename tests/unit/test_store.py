from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from perp_monitor.models import Venue
from perp_monitor.store import SnapshotStore
from tests.factories import T0, T8, snap


def test_record_and_read_back_prior(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    with SnapshotStore(db) as store:
        store.record_run(
            T0, manual=False, snapshots=[snap("NVDA", oi=10, price=150, funding=0.0001)]
        )
    with SnapshotStore(db) as store:  # survives reopening
        found = store.latest_prior(Venue.BINANCE, before=T8)
    assert found is not None
    at, points = found
    assert at == T0
    point = points["NVDAUSDT"]
    assert point.oi_contracts == 10
    assert point.oi_usd == pytest.approx(1500)
    assert point.funding_8h == pytest.approx(0.0001)
    assert point.origin == "store"


def test_latest_prior_picks_most_recent_run_before_cutoff(tmp_path: Path) -> None:
    with SnapshotStore(tmp_path / "m.db") as store:
        store.record_run(T0, manual=False, snapshots=[snap("NVDA", oi=1)])
        store.record_run(T0 + timedelta(hours=4), manual=True, snapshots=[snap("NVDA", oi=2)])
        store.record_run(T8, manual=False, snapshots=[snap("NVDA", oi=3)])
        at, points = store.latest_prior(Venue.BINANCE, before=T8)
    assert at == T0 + timedelta(hours=4)
    assert points["NVDAUSDT"].oi_contracts == 2


def test_latest_prior_is_per_venue(tmp_path: Path) -> None:
    with SnapshotStore(tmp_path / "m.db") as store:
        store.record_run(T0, manual=False, snapshots=[snap("NVDA", venue=Venue.HYPERLIQUID)])
        assert store.latest_prior(Venue.BINANCE, before=T8) is None
        assert store.latest_prior(Venue.HYPERLIQUID, before=T8) is not None


def test_empty_store_has_no_prior(tmp_path: Path) -> None:
    with SnapshotStore(tmp_path / "m.db") as store:
        assert store.latest_prior(Venue.BINANCE, before=T8) is None
        assert store.run_count() == 0


def test_rejects_naive_datetimes(tmp_path: Path) -> None:
    with SnapshotStore(tmp_path / "m.db") as store, pytest.raises(ValueError, match="timezone"):
        store.record_run(T0.replace(tzinfo=None), manual=False, snapshots=[])


def test_creates_parent_directory(tmp_path: Path) -> None:
    db = tmp_path / "nested" / "dir" / "m.db"
    with SnapshotStore(db) as store:
        store.record_run(T0, manual=False, snapshots=[snap("AAPL")])
        assert store.run_count() == 1
    assert db.exists()


def test_latest_prior_prefers_a_run_at_least_min_age_old(tmp_path: Path) -> None:
    with SnapshotStore(tmp_path / "m.db") as store:
        store.record_run(T0, manual=False, snapshots=[snap("NVDA", oi=1)])
        store.record_run(T8 - timedelta(minutes=10), manual=True, snapshots=[snap("NVDA", oi=2)])
        at, points = store.latest_prior(Venue.BINANCE, before=T8, min_age_hours=7)
        assert at == T0 and points["NVDAUSDT"].oi_contracts == 1
        # nothing old enough: fall back to the latest earlier run
        at, _ = store.latest_prior(Venue.BINANCE, before=T0 + timedelta(hours=2), min_age_hours=7)
        assert at == T0
