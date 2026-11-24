"""Settled funding history from each venue, normalized to 8h-equivalent rates.

This lets the dashboard tell a one-period spike from a persistent skew on the first run,
without waiting for the scanner's own history to build up.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from perp_monitor.funding import to_8h
from perp_monitor.http import DEFAULT_POLICY, RetryPolicy, request_json
from perp_monitor.insights.models import FundingPoint

LOOKBACK = timedelta(days=7)
HL_INTERVAL_HOURS = 1.0


def _moment(ms: Any) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, UTC)


def parse_binance(payload: Any, interval_hours: float) -> tuple[FundingPoint, ...]:
    if not isinstance(payload, list):
        return ()
    points = [
        FundingPoint(_moment(row["fundingTime"]), to_8h(float(row["fundingRate"]), interval_hours))
        for row in payload
    ]
    return tuple(sorted(points, key=lambda p: p.time))


def parse_hyperliquid(payload: Any) -> tuple[FundingPoint, ...]:
    if not isinstance(payload, list):
        return ()
    points = [
        FundingPoint(_moment(row["time"]), to_8h(float(row["fundingRate"]), HL_INTERVAL_HOURS))
        for row in payload
    ]
    return tuple(sorted(points, key=lambda p: p.time))


def fetch_binance(
    client: httpx.Client,
    base_url: str,
    symbol: str,
    interval_hours: float,
    now: datetime,
    policy: RetryPolicy = DEFAULT_POLICY,
) -> tuple[FundingPoint, ...]:
    payload = request_json(
        client,
        "GET",
        f"{base_url}/fapi/v1/fundingRate",
        params={
            "symbol": symbol,
            "startTime": int((now - LOOKBACK).timestamp() * 1000),
            "limit": 200,
        },
        policy=policy,
    )
    return parse_binance(payload, interval_hours)


def fetch_hyperliquid(
    client: httpx.Client,
    info_url: str,
    coin: str,
    now: datetime,
    policy: RetryPolicy = DEFAULT_POLICY,
) -> tuple[FundingPoint, ...]:
    payload = request_json(
        client,
        "POST",
        info_url,
        json_body={
            "type": "fundingHistory",
            "coin": coin,
            "startTime": int((now - LOOKBACK).timestamp() * 1000),
        },
        policy=policy,
    )
    return parse_hyperliquid(payload)
