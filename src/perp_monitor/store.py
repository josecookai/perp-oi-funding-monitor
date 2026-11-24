"""SQLite persistence: one row per run, one row per (run, venue, market) snapshot."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Literal

from perp_monitor.models import MarketSnapshot, PriorPoint, Venue

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT    NOT NULL,
    manual      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs (started_at);
CREATE TABLE IF NOT EXISTS snapshots (
    run_id                 INTEGER NOT NULL REFERENCES runs (id),
    venue                  TEXT    NOT NULL,
    market                 TEXT    NOT NULL,
    ticker                 TEXT    NOT NULL,
    source                 TEXT    NOT NULL,
    oi_contracts           REAL    NOT NULL,
    mark_price             REAL    NOT NULL,
    oi_usd                 REAL    NOT NULL,
    funding_rate           REAL    NOT NULL,
    funding_interval_hours REAL    NOT NULL,
    funding_8h             REAL    NOT NULL,
    volume_24h_usd         REAL    NOT NULL,
    PRIMARY KEY (run_id, venue, market)
);
"""

INSERT_SNAPSHOT = """
INSERT INTO snapshots (run_id, venue, market, ticker, source, oi_contracts, mark_price, oi_usd,
                       funding_rate, funding_interval_hours, funding_8h, volume_24h_usd)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# {op} is "<" (strictly before) or "<=" (at or before); never user input.
LATEST_RUN_TEMPLATE = """
SELECT r.id, r.started_at FROM runs r
WHERE r.started_at {op} ?
  AND EXISTS (SELECT 1 FROM snapshots s WHERE s.run_id = r.id AND s.venue = ?)
ORDER BY r.started_at DESC LIMIT 1
"""
LATEST_RUN_BEFORE = LATEST_RUN_TEMPLATE.format(op="<")
LATEST_RUN_AT_OR_BEFORE = LATEST_RUN_TEMPLATE.format(op="<=")
OLDEST_RUN_BEFORE = LATEST_RUN_BEFORE.replace("DESC", "ASC")


def _iso(moment: datetime) -> str:
    offset = moment.utcoffset()
    if offset is None:
        raise ValueError("datetimes must carry a timezone (use UTC)")
    if offset.total_seconds() != 0:
        raise ValueError("datetimes must be in UTC")
    return moment.isoformat()


class SnapshotStore:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)

    def __enter__(self) -> SnapshotStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def record_run(
        self, started_at: datetime, manual: bool, snapshots: Sequence[MarketSnapshot]
    ) -> int:
        stamp = _iso(started_at)
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO runs (started_at, manual) VALUES (?, ?)", (stamp, int(manual))
            )
            run_id = cursor.lastrowid
            assert run_id is not None
            self._conn.executemany(
                INSERT_SNAPSHOT,
                [
                    (
                        run_id,
                        s.venue.value,
                        s.market,
                        s.ticker,
                        s.source,
                        s.oi_contracts,
                        s.mark_price,
                        s.oi_usd,
                        s.funding_rate,
                        s.funding_interval_hours,
                        s.funding_8h,
                        s.volume_24h_usd,
                    )
                    for s in snapshots
                ],
            )
        return run_id

    def _latest_run(self, query: str, venue: Venue, cutoff: datetime) -> tuple[int, str] | None:
        return self._conn.execute(query, (_iso(cutoff), venue.value)).fetchone()

    def latest_prior(
        self,
        venue: Venue,
        before: datetime,
        min_age_hours: float = 0.0,
        fallback: Literal["latest", "oldest", "none"] = "latest",
    ) -> tuple[datetime, dict[str, PriorPoint]] | None:
        """The run to compare against for `venue`, with its rows keyed by market.

        Prefers the latest run at least `min_age_hours` older than `before`, so an ad-hoc
        run a few minutes before a scheduled one does not shrink the scheduled window.
        If none is that old, `fallback` picks the latest earlier run, the oldest earlier
        run (the widest window available), or nothing.
        """
        row = None
        if min_age_hours > 0:
            old_enough = before - timedelta(hours=min_age_hours)
            row = self._latest_run(LATEST_RUN_AT_OR_BEFORE, venue, old_enough)
        if row is None and fallback == "latest":
            row = self._latest_run(LATEST_RUN_BEFORE, venue, before)
        elif row is None and fallback == "oldest":
            row = self._latest_run(OLDEST_RUN_BEFORE, venue, before)
        if row is None:
            return None
        run_id, started_at = row
        observed_at = datetime.fromisoformat(started_at)
        rows = self._conn.execute(
            "SELECT market, oi_contracts, oi_usd, funding_8h FROM snapshots "
            "WHERE run_id = ? AND venue = ?",
            (run_id, venue.value),
        ).fetchall()
        points = {
            market: PriorPoint(
                oi_contracts=oi,
                oi_usd=oi_usd,
                funding_8h=f8h,
                observed_at=observed_at,
                origin="store",
            )
            for market, oi, oi_usd, f8h in rows
        }
        return observed_at, points

    def run_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

    def history(self, since: datetime) -> tuple[tuple[HistoryRun, ...], tuple[HistoryRow, ...]]:
        """Runs started at or after `since` (oldest first) and their snapshot rows."""
        runs = tuple(
            HistoryRun(run_id, datetime.fromisoformat(started_at))
            for run_id, started_at in self._conn.execute(
                "SELECT id, started_at FROM runs WHERE started_at >= ? ORDER BY started_at",
                (_iso(since),),
            )
        )
        rows = tuple(
            HistoryRow(*row)
            for row in self._conn.execute(
                "SELECT s.run_id, s.venue, s.ticker, s.market, s.funding_8h, s.oi_usd, "
                "s.mark_price, s.volume_24h_usd FROM snapshots s JOIN runs r ON r.id = s.run_id "
                "WHERE r.started_at >= ? ORDER BY r.started_at",
                (_iso(since),),
            )
        )
        return runs, rows


@dataclass(frozen=True, slots=True)
class HistoryRun:
    run_id: int
    started_at: datetime


@dataclass(frozen=True, slots=True)
class HistoryRow:
    run_id: int
    venue: str
    ticker: str
    market: str
    funding_8h: float
    oi_usd: float
    mark_price: float
    volume_24h_usd: float
