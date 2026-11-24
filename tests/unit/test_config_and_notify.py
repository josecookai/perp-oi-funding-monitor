from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from perp_monitor.config import ConfigError, load_config
from perp_monitor.http import RetryPolicy
from perp_monitor.notify import NotifyError, TelegramNotifier
from tests.conftest import mock_client

TOKEN = "123456:SECRET-token"


def test_defaults_resolve_paths_under_root(tmp_path: Path) -> None:
    cfg = load_config(tmp_path, {})
    assert cfg.db_path == tmp_path / "data" / "monitor.db"
    assert cfg.reports_dir == tmp_path / "reports"
    assert cfg.allowlist_path == tmp_path / "assets" / "stocks_allowlist.txt"
    assert cfg.hl_dexes == ("xyz",)
    assert cfg.expected_window_hours == 8
    assert cfg.top_n == 10
    assert cfg.binance_backfill is True
    assert cfg.telegram_chat_id is None


def test_env_overrides(tmp_path: Path) -> None:
    cfg = load_config(
        tmp_path,
        {
            "HL_DEXES": "xyz, io",
            "TOP_N": "5",
            "BINANCE_BACKFILL": "0",
            "PERP_MONITOR_DB": "/abs/x.db",
            "EXPECTED_WINDOW_HOURS": "24",
        },
    )
    assert cfg.hl_dexes == ("xyz", "io")
    assert cfg.top_n == 5
    assert cfg.binance_backfill is False
    assert cfg.db_path == Path("/abs/x.db")
    assert cfg.expected_window_hours == 24


@pytest.mark.parametrize(
    "env",
    [
        {"TOP_N": "0"},
        {"TOP_N": "ten"},
        {"EXPECTED_WINDOW_HOURS": "-1"},
        {"HL_DEXES": ""},
        {"HL_DEXES": "xyz,Bad Dex"},
        {"BINANCE_BACKFILL": "maybe"},
    ],
)
def test_invalid_env_raises(tmp_path: Path, env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path, env)


def test_telegram_token_from_file_and_hidden_in_repr(tmp_path: Path) -> None:
    token_file = tmp_path / "tg.env"
    token_file.write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\n")
    cfg = load_config(tmp_path, {"TELEGRAM_CHAT_ID": "42", "TELEGRAM_TOKEN_FILE": str(token_file)})
    assert cfg.telegram_bot_token == TOKEN
    assert cfg.telegram_chat_id == "42"
    assert TOKEN not in repr(cfg)


def test_telegram_chat_without_token_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="token"):
        load_config(tmp_path, {"TELEGRAM_CHAT_ID": "42"})


def _telegram(handler) -> TelegramNotifier:
    return TelegramNotifier(
        mock_client(handler),
        TOKEN,
        "42",
        policy=RetryPolicy(attempts=1, backoff_seconds=0),
        api_base="https://tg.test",
    )


def test_send_messages_posts_html() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    _telegram(handler).send_messages(["<b>a</b>", "b"])
    assert [r.url.path for r in sent] == [f"/bot{TOKEN}/sendMessage"] * 2
    body = json.loads(sent[0].content)
    assert body == {
        "chat_id": "42",
        "text": "<b>a</b>",
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }


def test_send_document_uploads_file(tmp_path: Path) -> None:
    doc = tmp_path / "r.md"
    doc.write_text("# report")
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"ok": True})

    _telegram(handler).send_document(doc, "Full report")
    assert sent[0].url.path.endswith("/sendDocument")
    assert b"# report" in sent[0].content
    assert b"Full report" in sent[0].content


def test_errors_redact_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "chat not found"})

    with pytest.raises(NotifyError) as info:
        _telegram(handler).send_messages(["x"])
    assert TOKEN not in str(info.value)
    assert "chat not found" in str(info.value)


def test_ok_false_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "description": "nope"})

    with pytest.raises(NotifyError, match="nope"):
        _telegram(handler).send_messages(["x"])


def test_retry_logs_do_not_contain_token(caplog: pytest.LogCaptureFixture) -> None:
    replies = [httpx.Response(502), httpx.Response(200, json={"ok": True})]

    def handler(request: httpx.Request) -> httpx.Response:
        return replies.pop(0)

    notifier = TelegramNotifier(
        mock_client(handler),
        TOKEN,
        "42",
        policy=RetryPolicy(attempts=2, backoff_seconds=0),
        api_base="https://tg.test",
    )
    notifier.send_messages(["x"])
    assert "attempt 1/2" in caplog.text
    assert TOKEN not in caplog.text
