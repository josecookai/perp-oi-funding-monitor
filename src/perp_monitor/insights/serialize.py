"""Insight bundle -> JSON for the dashboard (schema_version 1)."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from enum import Enum
from typing import Any

from perp_monitor.insights import analysis
from perp_monitor.insights.collect import InsightsBundle
from perp_monitor.insights.models import Fundamentals, ShortInterest, TickerInsight

SCHEMA_VERSION = 1


def _plain(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    if isinstance(obj, ShortInterest):
        return {**_fields(obj), "change_pct": obj.change_pct}
    if isinstance(obj, Fundamentals):
        return {**_fields(obj), "gross_margin": obj.gross_margin}
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _fields(obj)
    if isinstance(obj, tuple | list):
        return [_plain(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    return obj


def _fields(obj: Any) -> dict[str, Any]:
    return {f.name: _plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}


def insight_to_json(item: TickerInsight) -> dict[str, Any]:
    data = _fields(item)
    data["key"] = item.key
    data["answers"] = dict(item.answers)
    return data


def thresholds() -> dict[str, float]:
    return {
        "noise_oi_usd": analysis.NOISE_OI_USD,
        "noise_volume_usd": analysis.NOISE_VOLUME_USD,
        "meaningful_oi_usd": analysis.MEANINGFUL_OI_USD,
        "meaningful_volume_usd": analysis.MEANINGFUL_VOLUME_USD,
        "persistent_share": analysis.PERSISTENT_SHARE,
        "spike_share": analysis.SPIKE_SHARE,
        "short_high": analysis.SHORT_HIGH,
        "short_elevated": analysis.SHORT_ELEVATED,
        "short_moderate": analysis.SHORT_MODERATE,
        "long_days_to_cover": analysis.LONG_DAYS_TO_COVER,
    }


def bundle_to_json(bundle: InsightsBundle) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": bundle.generated_at.isoformat(),
        "market_date": bundle.market_date.isoformat(),
        "report_generated_at": bundle.report_generated_at,
        "thresholds": thresholds(),
        "errors": list(bundle.errors),
        "items": [insight_to_json(i) for i in bundle.items],
    }
