"""Curated Chinese company names and one-line descriptions (assets/company_zh.json).

Written once per ticker and kept in the repo, so cards never depend on a translation
service. `perp-monitor companies status` lists allowlisted tickers without an entry.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from perp_monitor.insights.models import Profile

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ZhEntry:
    name: str
    description: str


def load_company_zh(path: Path) -> dict[str, ZhEntry]:
    if not path.is_file():
        log.warning("no Chinese company file at %s", path)
        return {}
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        log.warning("ignoring unreadable %s: %s", path, exc)
        return {}
    out: dict[str, ZhEntry] = {}
    for ticker, entry in raw.items() if isinstance(raw, dict) else ():
        if not isinstance(entry, dict):
            continue
        name, desc = str(entry.get("name") or "").strip(), str(entry.get("desc") or "").strip()
        if name and desc:
            out[ticker.upper()] = ZhEntry(name, desc)
    return out


def with_zh(profile: Profile | None, entry: ZhEntry | None) -> Profile | None:
    if profile is None or entry is None:
        return profile
    return replace(profile, name_zh=entry.name, description_zh=entry.description)


def missing(tickers: Mapping[str, object] | list[str], zh: Mapping[str, ZhEntry]) -> list[str]:
    return sorted(t for t in tickers if t not in zh)
