from __future__ import annotations

import pytest

from perp_monitor.allowlist import parse_allowlist
from perp_monitor.fmt import pct, rate, signed_usd, usd
from perp_monitor.guard import CryptoLeakError, check_report_text, check_stock_only
from perp_monitor.models import MarketSnapshot, Venue
from tests.factories import snap

ALLOW = parse_allowlist("AAPL\nNVDA\n")
DENY = frozenset({"BTC", "ETH", "SOL"})
SOURCES = frozenset({"binance:EQUITY", "hl:xyz"})


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1.234e9, "$1.23B"), (45.6e6, "$45.6M"), (789_000, "$789K"), (12.4, "$12"), (0, "$0")],
)
def test_usd(value: float, expected: str) -> None:
    assert usd(value) == expected


def test_signed_usd_and_missing_values() -> None:
    assert signed_usd(1.2e6) == "+$1.20M"
    assert signed_usd(-3.4e6) == "-$3.40M"
    assert signed_usd(None) == "—"
    assert pct(None) == "—"


def test_pct_and_rate() -> None:
    assert pct(0.1234) == "+12.3%"
    assert pct(-0.05) == "-5.0%"
    assert pct(0.5, signed=False) == "50.0%"
    assert rate(0.000125) == "+0.0125%"
    assert rate(-0.0003) == "-0.0300%"
    assert rate(0.0) == "0.0000%"
    assert pct(0.0) == "0.0%"


def test_check_stock_only_accepts_clean_rows() -> None:
    rows = [snap("NVDA"), snap("AAPL", venue=Venue.HYPERLIQUID)]
    check_stock_only(rows, allowlist=ALLOW, denylist=DENY, allowed_sources=SOURCES)


def _with(base: MarketSnapshot, **changes: object) -> MarketSnapshot:
    fields = {name: getattr(base, name) for name in base.__dataclass_fields__}
    return MarketSnapshot(**{**fields, **changes})


@pytest.mark.parametrize(
    "bad",
    [
        _with(snap("NVDA"), source="binance:COIN"),
        _with(snap("NVDA", venue=Venue.HYPERLIQUID), source="hl:"),
        snap("TSLA"),  # not allowlisted
    ],
)
def test_check_stock_only_rejects_leaks(bad: MarketSnapshot) -> None:
    with pytest.raises(CryptoLeakError):
        check_stock_only([bad], allowlist=ALLOW, denylist=DENY, allowed_sources=SOURCES)


def test_check_stock_only_rejects_denylisted_even_if_allowlisted() -> None:
    allow = parse_allowlist("BTC\n")
    with pytest.raises(CryptoLeakError, match="BTC"):
        check_stock_only([snap("BTC")], allowlist=allow, denylist=DENY, allowed_sources=SOURCES)


def test_check_report_text() -> None:
    check_report_text("| NVDA | $1.2M |\n| BTCX | ok |", DENY)
    with pytest.raises(CryptoLeakError, match="ETH"):
        check_report_text("| NVDA | 1 |\n| ETH | 2 |", DENY)


def test_check_report_text_scans_telegram_pre_blocks() -> None:
    with pytest.raises(CryptoLeakError, match="SOL"):
        check_report_text("<b>Funding</b>\n<pre>NVDA  +0.01%\nSOL   +0.02%</pre>", DENY)


def test_check_report_text_ignores_prose() -> None:
    check_report_text("_fetch failed: ETH node down_\n\n| NVDA | 1 |", DENY)
