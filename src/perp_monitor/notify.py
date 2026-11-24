"""Telegram Bot API sender. The bot token is redacted from every error it raises."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from perp_monitor.http import DEFAULT_POLICY, HttpError, RetryPolicy, request_json

API_BASE = "https://api.telegram.org"


class NotifyError(RuntimeError):
    pass


class TelegramNotifier:
    def __init__(
        self,
        http: httpx.Client,
        token: str,
        chat_id: str,
        policy: RetryPolicy = DEFAULT_POLICY,
        api_base: str = API_BASE,
    ) -> None:
        self._http = http
        self._token = token
        self._chat_id = chat_id
        self._policy = policy
        self._base = api_base.rstrip("/")

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "***")

    def _call(
        self,
        method: str,
        *,
        json_body: Any = None,
        data: Mapping[str, str] | None = None,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
    ) -> None:
        url = f"{self._base}/bot{self._token}/{method}"
        try:
            result = request_json(
                self._http,
                "POST",
                url,
                json_body=json_body,
                data=data,
                files=files,
                label=f"telegram {method}",
                policy=self._policy,
            )
        except HttpError as exc:
            raise NotifyError(f"telegram {method} failed: {self._redact(str(exc))}") from None
        if not isinstance(result, dict) or not result.get("ok"):
            detail = result.get("description") if isinstance(result, dict) else result
            raise NotifyError(f"telegram {method} failed: {self._redact(str(detail))}")

    def send_messages(self, messages: Sequence[str]) -> None:
        for text in messages:
            self._call(
                "sendMessage",
                json_body={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )

    def send_document(self, path: Path, caption: str) -> None:
        files = {"document": (path.name, path.read_bytes(), "text/markdown")}
        self._call("sendDocument", data={"chat_id": self._chat_id, "caption": caption}, files=files)
