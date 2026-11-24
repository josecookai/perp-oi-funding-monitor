"""Command line: `perp-monitor run` and `perp-monitor allowlist ...`."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from html import escape
from pathlib import Path

import httpx
from dotenv import dotenv_values

from perp_monitor.allowlist import (
    AllowlistError,
    add_tickers,
    load_allowlist,
    load_denylist,
    remove_tickers,
    suggest_missing,
    validate_allowlist_text,
)
from perp_monitor.binance_client import BinanceClient, BinanceError, equity_base_names
from perp_monitor.config import Config, ConfigError, load_config
from perp_monitor.guard import CryptoLeakError
from perp_monitor.http import HttpError, build_client
from perp_monitor.hyperliquid_client import HyperliquidClient, HyperliquidError, stock_base_names
from perp_monitor.notify import NotifyError, TelegramNotifier
from perp_monitor.overrides import OverridesError, load_overrides
from perp_monitor.pipeline import RunOutcome, run_cycle
from perp_monitor.sec import fetch_listings, sec_issues
from perp_monitor.store import SnapshotStore

log = logging.getLogger("perp_monitor")

EXIT_OK, EXIT_PARTIAL, EXIT_ABORTED = 0, 1, 2
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="perp-monitor", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="collect one snapshot, compare, report")
    run.add_argument("--manual", action="store_true", help="mark this as an ad-hoc run")
    run.add_argument("--no-notify", action="store_true", help="skip Telegram")
    run.add_argument(
        "--no-store", action="store_true", help="dry run: print the report, write and store nothing"
    )
    allow = sub.add_parser("allowlist", help="maintain assets/stocks_allowlist.txt")
    allow_sub = allow.add_subparsers(dest="action", required=True)
    validate = allow_sub.add_parser("validate", help="check the allowlist file")
    validate.add_argument("--sec", action="store_true", help="also check SEC listings (online)")
    allow_sub.add_parser("suggest", help="venue stock perps not yet on the allowlist")
    for action in ("add", "remove"):
        cmd = allow_sub.add_parser(action, help=f"{action} tickers")
        cmd.add_argument("tickers", nargs="+", type=str.upper)
    return parser


def _env(root: Path) -> dict[str, str]:
    file_values = {k: v for k, v in dotenv_values(root / ".env").items() if v is not None}
    return {**file_values, **os.environ}


def _out(text: str) -> None:
    sys.stdout.write(text if text.endswith("\n") else text + "\n")


def _notifier(config: Config, http: httpx.Client) -> TelegramNotifier | None:
    if not (config.telegram_chat_id and config.telegram_bot_token):
        return None
    return TelegramNotifier(http, config.telegram_bot_token, config.telegram_chat_id)


def _alert(notifier: TelegramNotifier | None, text: str) -> None:
    if notifier is None:
        return
    try:
        notifier.send_messages([f"<b>perp-monitor</b>: {escape(text)}"])
    except NotifyError as exc:
        log.error("%s", exc)


def _deliver(notifier: TelegramNotifier, outcome: RunOutcome) -> bool:
    try:
        notifier.send_messages(outcome.telegram)
        if outcome.md_path is not None:
            notifier.send_document(outcome.md_path, "Full report")
    except NotifyError as exc:
        log.error("%s", exc)
        return False
    return True


def _run(args: argparse.Namespace, config: Config, http: httpx.Client) -> int:
    notify = not args.no_notify and not args.no_store
    notifier = _notifier(config, http) if notify else None
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    try:
        with SnapshotStore(config.db_path) as store:
            outcome = run_cycle(
                config,
                binance=BinanceClient(http, config.binance_base_url),
                hyperliquid=HyperliquidClient(http, config.hl_info_url),
                store=store,
                now=now,
                manual=args.manual,
                persist=not args.no_store,
            )
    except CryptoLeakError as exc:
        log.critical("run aborted, nothing stored or sent: %s", exc)
        _alert(notifier, f"run aborted by the stock-only check, nothing stored: {exc}")
        return EXIT_ABORTED
    except Exception as exc:
        log.exception("run crashed")
        _alert(notifier, f"run crashed, nothing stored: {type(exc).__name__}: {exc}")
        return EXIT_ABORTED

    _out(outcome.markdown)
    for error in outcome.errors:
        log.error("venue failed: %s", error)
    status = EXIT_PARTIAL if outcome.errors else EXIT_OK
    if notifier is not None:
        if outcome.run_id is None and outcome.errors:
            _alert(notifier, "every venue failed, nothing stored: " + "; ".join(outcome.errors))
        elif not _deliver(notifier, outcome):
            status = EXIT_PARTIAL
    if outcome.md_path:
        log.info("report written to %s", outcome.md_path)
    return status


def _validate(args: argparse.Namespace, config: Config, http: httpx.Client) -> int:
    text = config.allowlist_path.read_text()
    issues = list(validate_allowlist_text(text, load_denylist(config.denylist_path)))
    if args.sec and not any(i.level == "error" for i in issues):
        listings = fetch_listings(http, config.sec_user_agent)
        issues += sec_issues(load_allowlist(config.allowlist_path).tickers, listings)
    for issue in issues:
        _out(f"{issue.level}: {issue.message}")
    errors = sum(1 for i in issues if i.level == "error")
    _out(f"{config.allowlist_path.name}: {errors} error(s), {len(issues) - errors} warning(s)")
    return EXIT_PARTIAL if errors else EXIT_OK


def _suggest(config: Config, http: httpx.Client) -> int:
    overrides = load_overrides(config.overrides_path)
    allowlist = load_allowlist(config.allowlist_path)
    binance = equity_base_names(BinanceClient(http, config.binance_base_url), overrides)
    hl = stock_base_names(HyperliquidClient(http, config.hl_info_url), config.hl_dexes, overrides)
    missing = suggest_missing(binance | hl, allowlist)
    for name in missing:
        venues = ", ".join(
            v for v, names in (("Binance", binance), ("Hyperliquid", hl)) if name in names
        )
        _out(f"{name:10} {venues}")
    _out(
        f"{len(missing)} venue stock perps are not on the allowlist. Review each one "
        "(ETF? non-US? commodity?) before adding it."
    )
    return EXIT_OK


def _edit(args: argparse.Namespace, config: Config) -> int:
    path = config.allowlist_path
    text = path.read_text()
    updated = (
        add_tickers(text, args.tickers)
        if args.action == "add"
        else remove_tickers(text, args.tickers)
    )
    path.write_text(updated)
    _out(f"{args.action}: {', '.join(args.tickers)} -> {path}")
    return EXIT_OK


def _dispatch(args: argparse.Namespace, config: Config, http: httpx.Client) -> int:
    if args.command == "run":
        return _run(args, config, http)
    if args.action == "validate":
        return _validate(args, config, http)
    if args.action == "suggest":
        return _suggest(config, http)
    return _edit(args, config)


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    env: Mapping[str, str] | None = None,
    http: httpx.Client | None = None,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs full request URLs at INFO; the Telegram URL contains the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = _parser().parse_args(argv)
    root = root or PROJECT_ROOT
    try:
        config = load_config(root, env if env is not None else _env(root))
        client = http or build_client(config.http_timeout_seconds)
        with client:
            return _dispatch(args, config, client)
    except (ConfigError, AllowlistError, OverridesError) as exc:
        log.error("%s", exc)
        return EXIT_PARTIAL if args.command == "allowlist" else EXIT_ABORTED
    except CryptoLeakError as exc:
        log.critical("run aborted, nothing stored or sent: %s", exc)
        return EXIT_ABORTED
    except (BinanceError, HyperliquidError, HttpError) as exc:
        log.error("%s", exc)
        return EXIT_PARTIAL
    except Exception:
        log.exception("unexpected error")
        return EXIT_ABORTED
