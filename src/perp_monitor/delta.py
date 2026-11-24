"""Compare a run's snapshots with the previous observation of each market."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from perp_monitor.models import MarketChange, MarketSnapshot, PriorPoint, Window


def compute_changes(
    current: Sequence[MarketSnapshot], prior_points: Mapping[str, PriorPoint]
) -> tuple[MarketChange, ...]:
    """One MarketChange per current snapshot, matched to its prior point by market."""
    return tuple(MarketChange(snap, prior_points.get(snap.market)) for snap in current)


def make_window(
    prior_at: datetime | None,
    now: datetime,
    *,
    expected_hours: float,
    tolerance_hours: float,
    origin: str | None,
) -> Window:
    hours = None if prior_at is None else (now - prior_at).total_seconds() / 3600
    return Window(
        hours=hours, expected_hours=expected_hours, tolerance_hours=tolerance_hours, origin=origin
    )
