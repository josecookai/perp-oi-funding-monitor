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
from perp_monitor.insights.models import (
    EarningsDate,
    Fundamentals,
    LastEarnings,
    Profile,
    SpotBar,
)

BASE_URL = "https://api.nasdaq.com/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)",
    "Accept": "application/json",
}
HISTORY_DAYS = 45  # calendar days, enough for 20 sessions plus holidays
FINANCIALS_UNIT = 1000.0  # Nasdaq income statements are in thousands of USD
TTM_QUARTERS = 4
TIMING = {"time-pre-market": "bmo", "time-after-hours": "amc"}


def nasdaq_symbol(ticker: str) -> str:
    """Nasdaq displays share classes as BRK/B, but its API paths take the dot form.

    A slash in the path returns 404, so the ticker is passed as is.
    """
    return ticker


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


def _us_date(raw: object) -> date | None:
    try:
        return datetime.strptime(str(raw).strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def parse_financials(payload: Any, market_cap_usd: float | None) -> Fundamentals | None:
    """Trailing revenue and gross profit from the quarterly income statement table."""
    data = payload.get("data") if isinstance(payload, Mapping) else None
    table = data.get("incomeStatementTable") if isinstance(data, Mapping) else None
    if not isinstance(table, Mapping):
        return None
    headers = table.get("headers") or {}
    rows = {str(r.get("value1")): r for r in table.get("rows") or ()}
    columns = [k for k in headers if k != "value1"][:TTM_QUARTERS]
    revenue_row = rows.get("Total Revenue") or {}
    # Newer companies have fewer reported quarters ("--"): use the latest run of them.
    usable = []
    for k in columns:
        if parse_number(revenue_row.get(k)) is None:
            break
        usable.append(k)
    if not usable:
        return None
    columns = usable

    def total(label: str) -> float | None:
        row = rows.get(label)
        if row is None:
            return None
        values = [parse_number(row.get(k)) for k in columns]
        if any(v is None for v in values):
            return None
        return sum(v for v in values if v is not None) * FINANCIALS_UNIT

    revenue = total("Total Revenue")
    if revenue is None:
        return None
    period_end = _us_date(headers.get(columns[0])) if columns else None
    return Fundamentals(
        market_cap_usd=market_cap_usd,
        revenue_ttm_usd=revenue,
        gross_profit_ttm_usd=total("Gross Profit"),
        period_end=period_end,
        quarters=len(columns),
    )


def parse_earnings_surprise(payload: Any) -> LastEarnings | None:
    """The most recent reported quarter: date, EPS, consensus and surprise."""
    data = payload.get("data") if isinstance(payload, Mapping) else None
    table = data.get("earningsSurpriseTable") if isinstance(data, Mapping) else None
    rows = table.get("rows") if isinstance(table, Mapping) else None
    dated = [(d, r) for r in rows or () if (d := _us_date(r.get("dateReported")))]
    if not dated:
        return None
    reported, row = max(dated, key=lambda x: x[0])
    return LastEarnings(
        reported=reported,
        fiscal_quarter=str(row.get("fiscalQtrEnd") or ""),
        eps=parse_number(row.get("eps")),
        consensus=parse_number(row.get("consensusForecast")),
        surprise_pct=parse_number(row.get("percentageSurprise")),
    )


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
) -> tuple[float | None, bool, float | None]:
    """(shares outstanding, multi-class flag, market cap)."""
    symbol = nasdaq_symbol(ticker)
    summary = _get(client, f"/quote/{symbol}/summary", policy, assetClass="stocks")
    info = _get(client, f"/quote/{symbol}/info", policy, assetClass="stocks")
    return parse_shares_outstanding(summary), parse_multi_class(info), parse_market_cap(summary)


def fetch_financials(
    client: httpx.Client,
    ticker: str,
    market_cap_usd: float | None,
    policy: RetryPolicy = DEFAULT_POLICY,
) -> Fundamentals | None:
    payload = _get(client, f"/company/{nasdaq_symbol(ticker)}/financials", policy, frequency=2)
    return parse_financials(payload, market_cap_usd)


def fetch_earnings_surprise(
    client: httpx.Client, ticker: str, policy: RetryPolicy = DEFAULT_POLICY
) -> LastEarnings | None:
    payload = _get(client, f"/company/{nasdaq_symbol(ticker)}/earnings-surprise", policy)
    return parse_earnings_surprise(payload)


def fetch_earnings_day(
    client: httpx.Client, day: date, policy: RetryPolicy = DEFAULT_POLICY
) -> dict[str, EarningsDate]:
    payload = _get(client, "/calendar/earnings", policy, date=day.isoformat())
    return parse_earnings_calendar(payload, day)
