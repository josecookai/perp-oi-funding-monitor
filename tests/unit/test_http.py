from __future__ import annotations

import httpx
import pytest

from perp_monitor.http import HttpError, RetryPolicy, request_json
from tests.conftest import mock_client

FAST = RetryPolicy(attempts=3, backoff_seconds=0)


def _sequence(*responses: httpx.Response):
    calls: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return queue.pop(0)

    return handler, calls


def test_returns_json_on_success() -> None:
    handler, _ = _sequence(httpx.Response(200, json={"ok": True}))
    assert request_json(mock_client(handler), "GET", "https://x/a", policy=FAST) == {"ok": True}


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retries_retryable_status_then_succeeds(status: int) -> None:
    handler, calls = _sequence(httpx.Response(status), httpx.Response(200, json=[1]))
    assert request_json(mock_client(handler), "GET", "https://x/a", policy=FAST) == [1]
    assert len(calls) == 2


def test_gives_up_after_attempts() -> None:
    handler, calls = _sequence(*[httpx.Response(502)] * 3)
    with pytest.raises(HttpError) as info:
        request_json(mock_client(handler), "GET", "https://x/a", policy=FAST)
    assert info.value.status == 502
    assert len(calls) == 3


def test_does_not_retry_client_errors() -> None:
    handler, calls = _sequence(httpx.Response(451, text="restricted location"))
    with pytest.raises(HttpError) as info:
        request_json(mock_client(handler), "GET", "https://x/a", policy=FAST)
    assert info.value.status == 451
    assert "restricted location" in str(info.value)
    assert len(calls) == 1


def test_retries_transport_errors() -> None:
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={})

    assert request_json(mock_client(handler), "GET", "https://x/a", policy=FAST) == {}


def test_invalid_json_raises_http_error() -> None:
    handler, _ = _sequence(httpx.Response(200, text="<html>"))
    with pytest.raises(HttpError, match="invalid JSON"):
        request_json(mock_client(handler), "GET", "https://x/a", policy=FAST)


def test_post_sends_json_body() -> None:
    handler, calls = _sequence(httpx.Response(200, json=[]))
    request_json(
        mock_client(handler), "POST", "https://x/info", json_body={"type": "meta"}, policy=FAST
    )
    assert calls[0].method == "POST"
    assert calls[0].content == b'{"type":"meta"}'


def test_label_replaces_url_in_logs_and_errors(caplog: pytest.LogCaptureFixture) -> None:
    secret_url = "https://api.test/botSECRET/sendMessage"
    handler, _ = _sequence(httpx.Response(502), httpx.Response(503))
    with pytest.raises(HttpError) as info:
        request_json(
            mock_client(handler),
            "POST",
            secret_url,
            label="telegram sendMessage",
            policy=RetryPolicy(attempts=2, backoff_seconds=0),
        )
    assert "SECRET" not in caplog.text and "SECRET" not in str(info.value)
    assert "telegram sendMessage" in caplog.text


def test_other_httpx_errors_become_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TooManyRedirects("loop", request=request)

    with pytest.raises(HttpError, match="TooManyRedirects"):
        request_json(mock_client(handler), "GET", "https://x/a", policy=FAST)
