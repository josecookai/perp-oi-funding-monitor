"""Local company database (SQLite): profile, share count, financials, last earnings.

Each group of columns has its own `*_at` timestamp, so slow-changing facts are fetched
rarely (profiles monthly, financials weekly) instead of on every hourly run. A group can
be stored as "known missing" (timestamp set, values NULL), e.g. funds and foreign filers
that Nasdaq has no income statement for, so those are not refetched every hour either.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import Lock
from types import TracebackType

from perp_monitor.insights.models import Fundamentals, LastEarnings, Profile

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    ticker               TEXT PRIMARY KEY,
    name                 TEXT,
    sector               TEXT,
    industry             TEXT,
    description          TEXT,
    profile_at           TEXT,
    shares_outstanding   REAL,
    multi_class          INTEGER,
    market_cap_usd       REAL,
    shares_at            TEXT,
    revenue_ttm_usd      REAL,
    gross_profit_ttm_usd REAL,
    fin_period_end       TEXT,
    fin_quarters         INTEGER,
    financials_at        TEXT,
    last_reported        TEXT,
    last_fiscal_quarter  TEXT,
    last_eps             REAL,
    last_consensus       REAL,
    last_surprise_pct    REAL,
    earnings_at          TEXT
);
"""

GROUPS = {
    "profile": ("name", "sector", "industry", "description"),
    "shares": ("shares_outstanding", "multi_class", "market_cap_usd"),
    "financials": ("revenue_ttm_usd", "gross_profit_ttm_usd", "fin_period_end", "fin_quarters"),
    "earnings": (
        "last_reported",
        "last_fiscal_quarter",
        "last_eps",
        "last_consensus",
        "last_surprise_pct",
    ),
}
STAMP = {"profile": "profile_at", "shares": "shares_at", "financials": "financials_at",
         "earnings": "earnings_at"}  # fmt: skip


@dataclass(frozen=True, slots=True)
class CompanyRow:
    ticker: str
    values: dict[str, object]

    def stamp(self, group: str) -> datetime | None:
        raw = self.values.get(STAMP[group])
        return datetime.fromisoformat(str(raw)) if raw else None

    def fresh(self, group: str, now: datetime, max_age: timedelta) -> bool:
        at = self.stamp(group)
        return at is not None and now - at <= max_age

    def profile(self) -> Profile | None:
        name = self.values.get("name")
        if not name:
            return None
        return Profile(
            name=str(name),
            sector=_str(self.values.get("sector")),
            industry=_str(self.values.get("industry")),
            description=_str(self.values.get("description")),
        )

    def shares(self) -> tuple[float | None, bool, float | None]:
        v = self.values
        return (
            _float(v.get("shares_outstanding")),
            bool(v.get("multi_class")),
            _float(v.get("market_cap_usd")),
        )

    def fundamentals(self) -> Fundamentals | None:
        v = self.values
        revenue = _float(v.get("revenue_ttm_usd"))
        if revenue is None:
            return None
        end = v.get("fin_period_end")
        return Fundamentals(
            market_cap_usd=_float(v.get("market_cap_usd")),
            revenue_ttm_usd=revenue,
            gross_profit_ttm_usd=_float(v.get("gross_profit_ttm_usd")),
            period_end=date.fromisoformat(str(end)) if end else None,
            quarters=int(v.get("fin_quarters") or 0),  # type: ignore[call-overload]
        )

    def last_earnings(self) -> LastEarnings | None:
        v = self.values
        reported = v.get("last_reported")
        if not reported:
            return None
        return LastEarnings(
            reported=date.fromisoformat(str(reported)),
            fiscal_quarter=str(v.get("last_fiscal_quarter") or ""),
            eps=_float(v.get("last_eps")),
            consensus=_float(v.get("last_consensus")),
            surprise_pct=_float(v.get("last_surprise_pct")),
        )


def _str(x: object) -> str | None:
    return None if x is None else str(x)


def _float(x: object) -> float | None:
    return None if x is None else float(x)  # type: ignore[arg-type]


class CompanyDB:
    """Thread-safe: the insight workers share one connection behind a lock."""

    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def __enter__(self) -> CompanyDB:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def get(self, ticker: str) -> CompanyRow | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM companies WHERE ticker = ?", (ticker,)
            ).fetchone()
        return None if row is None else CompanyRow(ticker, dict(row))

    def all(self) -> list[CompanyRow]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM companies ORDER BY ticker").fetchall()
        return [CompanyRow(r["ticker"], dict(r)) for r in rows]

    def _save(self, ticker: str, group: str, values: Mapping[str, object], at: datetime) -> None:
        columns = [*GROUPS[group], STAMP[group]]
        row = [values.get(c) for c in GROUPS[group]] + [at.isoformat()]
        updates = ", ".join(f"{c} = excluded.{c}" for c in columns)
        sql = (
            f"INSERT INTO companies (ticker, {', '.join(columns)}) "
            f"VALUES (?, {', '.join('?' for _ in columns)}) "
            f"ON CONFLICT(ticker) DO UPDATE SET {updates}"
        )
        with self._lock, self._conn:
            self._conn.execute(sql, [ticker, *row])

    def save_profile(self, ticker: str, p: Profile | None, at: datetime) -> None:
        values: dict[str, object] = {}
        if p is not None:
            values = {"name": p.name, "sector": p.sector, "industry": p.industry,
                      "description": p.description}  # fmt: skip
        self._save(ticker, "profile", values, at)

    def save_shares(
        self, ticker: str, shares: float | None, multi: bool, cap: float | None, at: datetime
    ) -> None:
        values = {"shares_outstanding": shares, "multi_class": int(multi), "market_cap_usd": cap}
        self._save(ticker, "shares", values, at)

    def save_financials(self, ticker: str, f: Fundamentals | None, at: datetime) -> None:
        values: dict[str, object] = {}
        if f is not None:
            values = {
                "revenue_ttm_usd": f.revenue_ttm_usd,
                "gross_profit_ttm_usd": f.gross_profit_ttm_usd,
                "fin_period_end": f.period_end.isoformat() if f.period_end else None,
                "fin_quarters": f.quarters,
            }
        self._save(ticker, "financials", values, at)

    def save_last_earnings(self, ticker: str, e: LastEarnings | None, at: datetime) -> None:
        values: dict[str, object] = {}
        if e is not None:
            values = {
                "last_reported": e.reported.isoformat(),
                "last_fiscal_quarter": e.fiscal_quarter,
                "last_eps": e.eps,
                "last_consensus": e.consensus,
                "last_surprise_pct": e.surprise_pct,
            }
        self._save(ticker, "earnings", values, at)
