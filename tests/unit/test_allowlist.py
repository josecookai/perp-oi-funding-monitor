from __future__ import annotations

import pytest

from perp_monitor.allowlist import (
    AllowlistError,
    add_tickers,
    load_allowlist,
    load_denylist,
    parse_allowlist,
    remove_tickers,
    suggest_missing,
    validate_allowlist_text,
)
from tests.conftest import ASSETS

HEADER = "# header line\n# second\n"


def test_parse_skips_comments_and_blank_lines() -> None:
    allow = parse_allowlist(HEADER + "\nAAPL\nNVDA  # inline note\n\nBRK.B\n")
    assert allow.tickers == frozenset({"AAPL", "NVDA", "BRK.B"})
    assert "NVDA" in allow
    assert "BTC" not in allow
    assert len(allow) == 3


@pytest.mark.parametrize("bad", ["nvda", "NV DA", "BTC/USDT", "1ABC", "TOOLONGTICKERX", "BRK.BB"])
def test_parse_rejects_invalid_ticker_with_line_number(bad: str) -> None:
    with pytest.raises(AllowlistError, match="line 2"):
        parse_allowlist(f"AAPL\n{bad}\n")


def test_parse_rejects_duplicates() -> None:
    with pytest.raises(AllowlistError, match="duplicate"):
        parse_allowlist("AAPL\nNVDA\nAAPL\n")


def test_validate_reports_problems_without_raising() -> None:
    text = "NVDA\nAAPL\nBTC\nAAPL\nbad ticker\n"
    issues = validate_allowlist_text(text, denylist=frozenset({"BTC", "ETH"}))
    messages = " | ".join(issue.message for issue in issues)
    assert "BTC" in messages and "crypto denylist" in messages
    assert "duplicate" in messages
    assert "invalid" in messages
    assert "not sorted" in messages
    assert all(issue.level == "error" for issue in issues if "denylist" in issue.message)


def test_validate_clean_file_has_no_issues() -> None:
    assert validate_allowlist_text(HEADER + "AAPL\nNVDA\n", denylist=frozenset({"BTC"})) == ()


def test_add_keeps_header_sorts_and_does_not_mutate_input() -> None:
    original = HEADER + "NVDA\nAAPL\n"
    updated = add_tickers(original, ["TSLA", "AMD", "NVDA"])
    assert original == HEADER + "NVDA\nAAPL\n"
    assert updated == HEADER + "AAPL\nAMD\nNVDA\nTSLA\n"


def test_add_rejects_invalid_ticker() -> None:
    with pytest.raises(AllowlistError):
        add_tickers("AAPL\n", ["not valid"])


def test_remove_drops_tickers_and_reports_unknown() -> None:
    updated = remove_tickers(HEADER + "AAPL\nNVDA\nTSLA\n", ["NVDA"])
    assert updated == HEADER + "AAPL\nTSLA\n"
    with pytest.raises(AllowlistError, match="not in allowlist"):
        remove_tickers("AAPL\n", ["MSFT"])


def test_suggest_missing_returns_sorted_new_names() -> None:
    allow = parse_allowlist("AAPL\nNVDA\n")
    assert suggest_missing({"NVDA", "TSLA", "AMD"}, allow) == ("AMD", "TSLA")


def test_shipped_allowlist_is_valid_and_stock_only() -> None:
    text = (ASSETS / "stocks_allowlist.txt").read_text()
    denylist = load_denylist(ASSETS / "crypto_denylist.txt")
    assert validate_allowlist_text(text, denylist) == ()
    allow = load_allowlist(ASSETS / "stocks_allowlist.txt")
    assert len(allow) > 100
    for stock in ("NVDA", "AAPL", "TSLA", "MSTR", "MSFT", "AMZN", "META", "BRK.B", "TSM"):
        assert stock in allow
    for excluded in ("SPY", "QQQ", "IBIT", "ZCSH", "BTC", "ETH", "SOL", "GOLD", "CL"):
        assert excluded not in allow


def test_denylist_loads_symbols() -> None:
    denylist = load_denylist(ASSETS / "crypto_denylist.txt")
    assert {"BTC", "ETH", "SOL", "XRP", "DOGE"} <= denylist
