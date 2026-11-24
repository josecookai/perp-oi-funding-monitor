"""Write the dashboard's data files (web/data/*.json) after each run.

The Next.js app in web/ reads these at build time; each git push redeploys it.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from math import floor, log10
from pathlib import Path
from typing import Any

from perp_monitor.store import HistoryRow, HistoryRun

SCHEMA_VERSION = 1
HISTORY_DAYS = 14  # hourly runs: 336 points per market
HISTORY_FIELDS = ("run", "funding_8h", "oi_usd", "price", "volume_24h_usd")


def _sig(x: float, digits: int = 6) -> float:
    if x == 0:
        return 0.0
    return round(x, digits - 1 - floor(log10(abs(x))))


def history_to_json(runs: Sequence[HistoryRun], rows: Sequence[HistoryRow]) -> dict[str, Any]:
    index = {r.run_id: i for i, r in enumerate(runs)}
    series: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.run_id not in index:
            continue
        key = f"{row.venue}:{row.ticker}"
        entry = series.setdefault(key, {"market": row.market, "points": []})
        entry["points"].append(
            [
                index[row.run_id],
                round(row.funding_8h, 8),
                round(row.oi_usd),
                _sig(row.mark_price),
                round(row.volume_24h_usd),
            ]
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "runs": [r.started_at.isoformat() for r in runs],
        "fields": list(HISTORY_FIELDS),
        "series": series,
    }


def write_json(path: Path, data: Any) -> None:
    """Write atomically so a deploy never picks up a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
            fh.write("\n")
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise


def export_site(
    out_dir: Path,
    report: Mapping[str, Any],
    history: Mapping[str, Any],
    insights: Mapping[str, Any] | None,
    now: datetime,
    insights_error: str | None = None,
) -> tuple[Path, ...]:
    """Write report/history/insights/meta JSON. With insights=None the old file is kept."""
    written = []
    for name, data in (("report", report), ("history", history), ("insights", insights)):
        if data is None:
            continue
        path = out_dir / f"{name}.json"
        write_json(path, data)
        written.append(path)
    meta = {
        "schema_version": SCHEMA_VERSION,
        "built_at": now.isoformat(),
        "report_generated_at": report.get("generated_at"),
        "insights_generated_at": None if insights is None else insights.get("generated_at"),
        "insights_error": insights_error,
        "history_days": HISTORY_DAYS,
    }
    meta_path = out_dir / "meta.json"
    write_json(meta_path, meta)
    return (*written, meta_path)
