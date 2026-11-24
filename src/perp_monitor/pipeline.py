"""One full cycle: fetch both venues, check, compare with the last run, report, store."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from perp_monitor.allowlist import Allowlist, load_allowlist, load_denylist
from perp_monitor.binance_client import BinanceClient, BinanceError, fetch_binance_snapshots
from perp_monitor.config import Config
from perp_monitor.delta import compute_changes, make_window
from perp_monitor.guard import check_report_text, check_stock_only
from perp_monitor.hyperliquid_client import (
    HyperliquidClient,
    HyperliquidError,
    fetch_hl_snapshots,
)
from perp_monitor.models import MarketSnapshot, PriorPoint, Venue
from perp_monitor.overrides import Overrides, load_overrides
from perp_monitor.render_json import report_to_json
from perp_monitor.render_md import render_markdown
from perp_monitor.render_tg import render_telegram
from perp_monitor.report import Report, VenueInput, build_report
from perp_monitor.store import SnapshotStore

log = logging.getLogger(__name__)

PRIOR_SLACK_HOURS = 0.25


@dataclass(frozen=True, slots=True)
class Universe:
    allowlist: Allowlist
    overrides: Overrides
    denylist: frozenset[str]
    allowed_sources: frozenset[str]


@dataclass(frozen=True, slots=True)
class VenueFetch:
    venue: Venue
    label: str
    snapshots: tuple[MarketSnapshot, ...]
    error: str | None


@dataclass(frozen=True, slots=True)
class RunOutcome:
    report: Report
    markdown: str
    telegram: tuple[str, ...]
    md_path: Path | None
    json_path: Path | None
    run_id: int | None
    errors: tuple[str, ...]


def load_universe(config: Config) -> Universe:
    sources = frozenset({"binance:EQUITY", *(f"hl:{dex}" for dex in config.hl_dexes)})
    return Universe(
        allowlist=load_allowlist(config.allowlist_path),
        overrides=load_overrides(config.overrides_path),
        denylist=load_denylist(config.denylist_path),
        allowed_sources=sources,
    )


def _fetch_venue(
    venue: Venue, label: str, fetch: Callable[[], tuple[MarketSnapshot, ...]]
) -> VenueFetch:
    """Run one venue's fetch; any failure becomes that venue's error, not a crash."""
    try:
        return VenueFetch(venue, label, fetch(), None)
    except (BinanceError, HyperliquidError) as exc:
        log.error("%s fetch failed: %s", venue.value, exc)
        return VenueFetch(venue, label, (), _short(str(exc)))
    except Exception as exc:  # unexpected payload shape, parse error, ...
        log.exception("%s fetch failed unexpectedly", venue.value)
        return VenueFetch(venue, label, (), _short(f"{type(exc).__name__}: {exc}"))


def _fetch_all(
    config: Config, universe: Universe, binance: BinanceClient, hyperliquid: HyperliquidClient
) -> tuple[VenueFetch, VenueFetch]:
    allow, overrides = universe.allowlist, universe.overrides
    bn = _fetch_venue(
        Venue.BINANCE, "Binance", lambda: fetch_binance_snapshots(binance, allow, overrides)
    )
    hl = _fetch_venue(
        Venue.HYPERLIQUID,
        f"Hyperliquid ({', '.join(config.hl_dexes)})",
        lambda: fetch_hl_snapshots(hyperliquid, config.hl_dexes, allow, overrides),
    )
    return bn, hl


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _backfill(
    binance: BinanceClient, snapshots: tuple[MarketSnapshot, ...], at: datetime
) -> dict[str, PriorPoint]:
    points: dict[str, PriorPoint] = {}
    for snap in snapshots:
        try:
            point = binance.open_interest_at(snap.market, at)
        except BinanceError as exc:
            log.warning("binance backfill %s failed: %s", snap.market, exc)
            continue
        if point is not None:
            points[snap.market] = point
    return points


def _venue_input(
    config: Config, fetch: VenueFetch, store: SnapshotStore, binance: BinanceClient, now: datetime
) -> VenueInput:
    def window(prior_at: datetime | None, origin: str | None):
        return make_window(
            prior_at,
            now,
            expected_hours=config.expected_window_hours,
            tolerance_hours=config.window_tolerance_hours,
            origin=origin,
        )

    if fetch.error:
        return VenueInput(fetch.venue, fetch.label, (), window(None, None), fetch.error)
    # 1) a stored run about one window old; 2) Binance's own OI history at now - window;
    # 3) the oldest stored run (the widest window there is, in the first hours of data).
    stored = store.latest_prior(
        fetch.venue, before=now, min_age_hours=prior_min_age(config), fallback="none"
    )
    if stored is not None:
        prior_at, points = stored
        return VenueInput(
            fetch.venue,
            fetch.label,
            compute_changes(fetch.snapshots, points),
            window(prior_at, "store"),
        )
    if fetch.venue is Venue.BINANCE and config.binance_backfill:
        target = now - timedelta(hours=config.expected_window_hours)
        points = _backfill(binance, fetch.snapshots, target)
        if points:
            prior_at = min(p.observed_at for p in points.values())
            return VenueInput(
                fetch.venue,
                fetch.label,
                compute_changes(fetch.snapshots, points),
                window(prior_at, "binance_oi_hist"),
            )
    stored = store.latest_prior(fetch.venue, before=now, fallback="oldest")
    if stored is not None:
        prior_at, points = stored
        return VenueInput(
            fetch.venue,
            fetch.label,
            compute_changes(fetch.snapshots, points),
            window(prior_at, "store"),
        )
    return VenueInput(
        fetch.venue, fetch.label, compute_changes(fetch.snapshots, {}), window(None, None)
    )


def prior_min_age(config: Config) -> float:
    """How old the comparison run must be.

    Runs happen hourly, so "at least EXPECTED - TOLERANCE old" would pick a 7h-old run.
    A 15-minute slack picks the run closest to a full window while still letting a
    manual run just before a scheduled one keep the scheduled run's window intact.
    """
    slack = min(config.window_tolerance_hours, PRIOR_SLACK_HOURS)
    return max(config.expected_window_hours - slack, 0.0)


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def write_outputs(
    reports_dir: Path, now: datetime, markdown: str, data: dict, archive: bool = True
) -> tuple[Path, Path]:
    """Write latest.md/json, plus a dated copy under reports/YYYY-MM-DD/ when archiving."""
    latest_md, latest_json = reports_dir / "latest.md", reports_dir / "latest.json"
    payload = json.dumps(data, indent=1) + "\n"
    outputs = [(latest_md, markdown), (latest_json, payload)]
    md_path, json_path = latest_md, latest_json
    if archive:
        stem = reports_dir / now.strftime("%Y-%m-%d") / now.strftime("%H%MZ")
        md_path, json_path = stem.with_suffix(".md"), stem.with_suffix(".json")
        outputs = [(md_path, markdown), (json_path, payload), *outputs]
    for path, text in outputs:
        _write_atomic(path, text)
    return md_path, json_path


def run_cycle(
    config: Config,
    *,
    binance: BinanceClient,
    hyperliquid: HyperliquidClient,
    store: SnapshotStore,
    now: datetime,
    manual: bool,
    persist: bool = True,
    archive: bool = True,
) -> RunOutcome:
    universe = load_universe(config)
    fetches = _fetch_all(config, universe, binance, hyperliquid)
    snapshots = tuple(s for f in fetches for s in f.snapshots)
    check_stock_only(
        snapshots,
        allowlist=universe.allowlist,
        denylist=universe.denylist,
        allowed_sources=universe.allowed_sources,
    )

    inputs = [_venue_input(config, f, store, binance, now) for f in fetches]
    report = build_report(
        generated_at=now,
        manual=manual,
        top_n=config.top_n,
        allowlist_size=len(universe.allowlist),
        inputs=inputs,
    )
    markdown = render_markdown(report)
    telegram = tuple(render_telegram(report))
    check_report_text(markdown, universe.denylist)
    check_report_text("\n".join(telegram), universe.denylist)

    md_path = json_path = None
    run_id = None
    all_failed = all(f.error for f in fetches)
    if all_failed:
        log.error("every venue failed; nothing stored, latest report left unchanged")
    if persist and not all_failed:
        # Store first: a stored run with a failed file write only loses one report,
        # while a written report without a stored run would widen the next window.
        run_id = store.record_run(now, manual, snapshots)
        md_path, json_path = write_outputs(
            config.reports_dir, now, markdown, report_to_json(report), archive=archive
        )
    errors = tuple(f"{f.label}: {f.error}" for f in fetches if f.error)
    return RunOutcome(report, markdown, telegram, md_path, json_path, run_id, errors)
