"""Shared JSON-over-HTTP helper with bounded retries."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
USER_AGENT = "perp-oi-funding-monitor/0.1"


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 3
    backoff_seconds: float = 1.0


DEFAULT_POLICY = RetryPolicy()


def build_client(timeout_seconds: float) -> httpx.Client:
    return httpx.Client(timeout=timeout_seconds, headers={"User-Agent": USER_AGENT})


def _decode(response: httpx.Response, where: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise HttpError(f"{where}: invalid JSON in response", response.status_code) from exc


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    json_body: Any = None,
    data: Mapping[str, str] | None = None,
    files: Mapping[str, tuple[str, bytes, str]] | None = None,
    headers: Mapping[str, str] | None = None,
    label: str | None = None,
    policy: RetryPolicy = DEFAULT_POLICY,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Send a request and return decoded JSON.

    Retries transport errors and 429/5xx responses with linear backoff. Other 4xx
    responses fail at once, because retrying them does not help.

    `label` replaces the URL in log lines and errors. Pass it whenever the URL holds a
    secret (the Telegram bot token is part of the URL path).
    """
    where = label or f"{method} {url}"
    last_error: HttpError | None = None
    for attempt in range(1, policy.attempts + 1):
        try:
            response = client.request(
                method, url, params=params, json=json_body, data=data, files=files, headers=headers
            )
        except httpx.HTTPError as exc:
            detail = str(exc) if label is None else "request failed"
            last_error = HttpError(f"{where}: {type(exc).__name__}: {detail}")
        else:
            if response.status_code < 400:
                return _decode(response, where)
            message = f"{where}: HTTP {response.status_code}: {response.text[:200]}"
            last_error = HttpError(message, response.status_code)
            if response.status_code not in RETRYABLE_STATUS:
                raise last_error
        if attempt < policy.attempts:
            log.warning("attempt %d/%d failed: %s", attempt, policy.attempts, last_error)
            sleep(policy.backoff_seconds * attempt)
    assert last_error is not None
    raise last_error
