from __future__ import annotations

import shutil
from pathlib import Path

import httpx
import pytest

from perp_monitor.cli import main
from tests.conftest import ASSETS, load_fixture
from tests.unit.test_binance_client import binance_handler
from tests.unit.test_hyperliquid_client import hl_handler


@pytest.fixture
def root(tmp_path: Path) -> Path:
    shutil.copytree(ASSETS, tmp_path / "assets")
    return tmp_path


def combined_handler(telegram: list[httpx.Request] | None = None):
    bn, _ = binance_handler()
    hl, _ = hl_handler()
    sec = load_fixture("sec_company_tickers_exchange.json")

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "fapi.binance.com":
            return bn(request)
        if host == "api.hyperliquid.xyz":
            return hl(request)
        if host == "www.sec.gov":
            return httpx.Response(200, json=sec)
        if host == "api.telegram.org" and telegram is not None:
            telegram.append(request)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    return handler


def cli(root: Path, *argv: str, env: dict[str, str] | None = None, telegram=None) -> int:
    http = httpx.Client(transport=httpx.MockTransport(combined_handler(telegram)))
    return main(list(argv), root=root, env=env or {}, http=http)


def test_run_writes_report_and_prints_it(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(root, "run", "--manual") == 0
    out = capsys.readouterr().out
    assert "## 2. OI gain" in out
    assert (root / "reports" / "latest.md").exists()
    assert (root / "data" / "monitor.db").exists()


def test_run_sends_telegram_when_configured(root: Path) -> None:
    token_file = root / "tg.env"
    token_file.write_text("TELEGRAM_BOT_TOKEN=1:abc\n")
    sent: list[httpx.Request] = []
    env = {"TELEGRAM_CHAT_ID": "42", "TELEGRAM_TOKEN_FILE": str(token_file)}
    assert cli(root, "run", env=env, telegram=sent) == 0
    paths = [r.url.path for r in sent]
    assert paths.count("/bot1:abc/sendMessage") >= 2
    assert paths[-1] == "/bot1:abc/sendDocument"


def test_run_no_notify_and_no_store(root: Path) -> None:
    sent: list[httpx.Request] = []
    token_file = root / "tg.env"
    token_file.write_text("TELEGRAM_BOT_TOKEN=1:abc\n")
    env = {"TELEGRAM_CHAT_ID": "42", "TELEGRAM_TOKEN_FILE": str(token_file)}
    assert cli(root, "run", "--no-notify", "--no-store", env=env, telegram=sent) == 0
    assert sent == []
    assert not (root / "reports").exists()


def test_allowlist_add_remove_validate(root: Path) -> None:
    path = root / "assets" / "stocks_allowlist.txt"
    assert cli(root, "allowlist", "add", "ZZZZ") == 0
    assert "ZZZZ\n" in path.read_text()
    assert cli(root, "allowlist", "remove", "ZZZZ") == 0
    assert "ZZZZ" not in path.read_text()
    assert cli(root, "allowlist", "validate") == 0
    assert cli(root, "allowlist", "remove", "NOTTHERE") == 1


def test_allowlist_validate_fails_on_denylisted(root: Path) -> None:
    path = root / "assets" / "stocks_allowlist.txt"
    path.write_text(path.read_text() + "BTC\n")
    assert cli(root, "allowlist", "validate") == 1


def test_allowlist_validate_with_sec(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = root / "assets" / "stocks_allowlist.txt"
    path.write_text("# test\nBRK.B\nNOPE\nNVDA\n")
    assert cli(root, "allowlist", "validate", "--sec") == 0  # SEC misses are warnings
    out = capsys.readouterr().out
    assert "warning: NOPE" in out
    assert "warning: BRK.B" not in out and "warning: NVDA" not in out


def test_allowlist_suggest_lists_unlisted_venue_stocks(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = root / "assets" / "stocks_allowlist.txt"
    path.write_text("# test\nNVDA\n")
    assert cli(root, "allowlist", "suggest") == 0
    out = capsys.readouterr().out
    assert "TSLA" in out and "SPY" in out
    assert "BBUSDT" not in out and "STX" not in out


def _telegram_env(root: Path) -> dict[str, str]:
    token_file = root / "tg.env"
    token_file.write_text("TELEGRAM_BOT_TOKEN=1:abc\n")
    return {"TELEGRAM_CHAT_ID": "42", "TELEGRAM_TOKEN_FILE": str(token_file)}


def test_guard_abort_exits_2_and_alerts(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from perp_monitor import cli as cli_module
    from perp_monitor.guard import CryptoLeakError

    def boom(*args, **kwargs):
        raise CryptoLeakError("BTC found")

    monkeypatch.setattr(cli_module, "run_cycle", boom)
    sent: list[httpx.Request] = []
    assert cli(root, "run", env=_telegram_env(root), telegram=sent) == 2
    assert len(sent) == 1 and b"aborted" in sent[0].content and b"BTC found" in sent[0].content


def test_unexpected_crash_exits_2_and_alerts(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from perp_monitor import cli as cli_module

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(cli_module, "run_cycle", boom)
    sent: list[httpx.Request] = []
    assert cli(root, "run", env=_telegram_env(root), telegram=sent) == 2
    assert len(sent) == 1 and b"disk full" in sent[0].content
