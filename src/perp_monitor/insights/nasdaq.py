"""Nasdaq's public quote API: company profile, daily bars, market cap, earnings calendar.

The API covers NYSE and Nasdaq listings alike. It wants a browser-like User-Agent and
returns numbers as display strings ("$27.69", "3,528,787", "N/A").
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from perp_monitor.http import DEFAULT_POLICY, RetryPolicy, request_json
from perp_monitor.insights.models import EarningsDate, Profile, SpotBar

BASE_URL = "https://api.nasdaq.com/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)",
    "Accept": "application/json",
}
HISTORY_DAYS = 45  # calendar days, enough for 20 sessions plus holidays
TIMING = {"time-pre-market": "bmo", "time-after-hours": "amc"}


def nasdaq_symbol(ticker: str) -> str:
    """Nasdaq writes share classes with a slash: BRK.B -> BRK/B."""
    return ticker.replace(".", "/")


def parse_number(raw: object) -> float | None:
    if raw is None:
        return None
    text = str(raw).replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _value(data: Mapping[str, Any], key: str) -> str | None:
    field = data.get(key)
    if not isinstance(field, Mapping):
        return None
    value = field.get("value")
    if value is None:
        return None
    return str(value).strip() or None


def parse_profile(payload: Any) -> Profile | None:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping):
        return None
    name = _value(data, "CompanyName")
    if not name:
        return None
    return Profile(
        name=name,
        sector=_value(data, "Sector"),
        industry=_value(data, "Industry"),
        description=_value(data, "CompanyDescription"),
    )


def parse_historical(payload: Any) -> tuple[SpotBar, ...]:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    table = data.get("tradesTable") if isinstance(data, Mapping) else None
    rows = table.get("rows") if isinstance(table, Mapping) else None
    bars = []
    for row in rows or ():
        close = parse_number(row.get("close"))
        volume = parse_number(row.get("volume"))
        try:
            day = datetime.strptime(str(row.get("date")), "%m/%d/%Y").date()
        except ValueError:
            continue
        if close is None or volume is None or close <= 0:
            continue
        bars.append(SpotBar(day, close, volume))
    return tuple(bars)


def parse_market_cap(payload: Any) -> float | None:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    summary = data.get("summaryData") if isinstance(data, Mapping) else None
    if not isinstance(summary, Mapping):
        return None
    cap = parse_number(_value(summary, "MarketCap"))
    return cap if cap and cap > 0 else None


def parse_shares_outstanding(payload: Any) -> float | None:
    """Market cap / previous close, both from the same summary quote."""
    cap = parse_market_cap(payload)
    data = payload.get("data") if isinstance(payload, Mapping) else None
    summary = data.get("summaryData") if isinstance(data, Mapping) else None
    close = parse_number(_value(summary, "PreviousClose")) if isinstance(summary, Mapping) else None
    if cap is None or not close or close <= 0:
        return None
    return cap / close


def parse_multi_class(payload: Any) -> bool:
    """True when the listed line is one share class ("Class A Common Stock")."""
    data = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(data, Mapping):
        return False
    text = f"{data.get('stockType') or ''} {data.get('companyName') or ''}".lower()
    return "class " in text


def parse_earnings_calendar(payload: Any, day: date) -> dict[str, EarningsDate]:
    data = payload.get("data") if isinstance(payload, Mapping) else None
    rows = data.get("rows") if isinstance(data, Mapping) else None
    out: dict[str, EarningsDate] = {}
    for row in rows or ():
        symbol = str(row.get("symbol") or "").strip().upper()
        if symbol:
            out[symbol.replace("/", ".")] = EarningsDate(day, TIMING.get(str(row.get("time"))))
    return out


def _get(client: httpx.Client, path: str, policy: RetryPolicy, **params: Any) -> Any:
    return request_json(
        client, "GET", f"{BASE_URL}{path}", params=params or None, headers=HEADERS, policy=policy
    )


def fetch_profile(
    client: httpx.Client, ticker: str, policy: RetryPolicy = DEFAULT_POLICY
) -> Profile | None:
    return parse_profile(_get(client, f"/company/{nasdaq_symbol(ticker)}/company-profile", policy))


def fetch_bars(
    client: httpx.Client, ticker: str, today: date, policy: RetryPolicy = DEFAULT_POLICY
) -> tuple[SpotBar, ...]:
    payload = _get(
        client,
        f"/quote/{nasdaq_symbol(ticker)}/historical",
        policy,
        assetclass="stocks",
        fromdate=(today - timedelta(days=HISTORY_DAYS)).isoformat(),
        todate=today.isoformat(),
        limit=60,
    )
    return parse_historical(payload)


def fetch_share_info(
    client: httpx.Client, ticker: str, policy: RetryPolicy = DEFAULT_POLICY
) -> tuple[float | None, bool]:
    """(shares outstanding, multi-class flag)."""
    symbol = nasdaq_symbol(ticker)
    summary = _get(client, f"/quote/{symbol}/summary", policy, assetClass="stocks")
    info = _get(client, f"/quote/{symbol}/info", policy, assetClass="stocks")
    return parse_shares_outstanding(summary), parse_multi_class(info)


def fetch_earnings_day(
    client: httpx.Client, day: date, policy: RetryPolicy = DEFAULT_POLICY
) -> dict[str, EarningsDate]:
    payload = _get(client, "/calendar/earnings", policy, date=day.isoformat())
    return parse_earnings_calendar(payload, day)
