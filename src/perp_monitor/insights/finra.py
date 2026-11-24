"""Exchange-reported short interest from FINRA's public consolidated dataset.

Short interest is published twice a month (mid-month and month-end settlement dates),
about two weeks after the settlement date.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

import httpx

from perp_monitor.http import DEFAULT_POLICY, RetryPolicy, request_json
from perp_monitor.insights.models import ShortInterest

URL = "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
LOOKBACK_DAYS = 60
FIELDS = [
    "symbolCode",
    "settlementDate",
    "currentShortPositionQuantity",
    "previousShortPositionQuantity",
    "daysToCoverQuantity",
]


def finra_symbol(ticker: str) -> str:
    return ticker.replace(".", " ")


def _number(raw: Any) -> float | None:
    try:
        return None if raw is None else float(raw)
    except (TypeError, ValueError):
        return None


def parse_short_interest(payload: Any) -> dict[str, ShortInterest]:
    """Latest settlement per symbol. pct_of_shares is filled in later from market cap."""
    latest: dict[str, ShortInterest] = {}
    for row in payload if isinstance(payload, list) else ():
        symbol = str(row.get("symbolCode") or "").replace(" ", ".")
        shares = _number(row.get("currentShortPositionQuantity"))
        try:
            settled = date.fromisoformat(str(row.get("settlementDate")))
        except ValueError:
            continue
        if not symbol or shares is None:
            continue
        current = latest.get(symbol)
        if current is not None and current.settlement_date >= settled:
            continue
        latest[symbol] = ShortInterest(
            settlement_date=settled,
            shares=shares,
            prev_shares=_number(row.get("previousShortPositionQuantity")),
            days_to_cover=_number(row.get("daysToCoverQuantity")),
            pct_of_shares=None,
        )
    return latest


def fetch_short_interest(
    client: httpx.Client,
    tickers: Iterable[str],
    today: date,
    policy: RetryPolicy = DEFAULT_POLICY,
) -> dict[str, ShortInterest]:
    symbols = sorted({finra_symbol(t) for t in tickers})
    if not symbols:
        return {}
    body = {
        "limit": 5000,
        "fields": FIELDS,
        "compareFilters": [
            {
                "compareType": "GREATER",
                "fieldName": "settlementDate",
                "fieldValue": (today - timedelta(days=LOOKBACK_DAYS)).isoformat(),
            }
        ],
        "domainFilters": [{"fieldName": "symbolCode", "values": symbols}],
    }
    payload = request_json(
        client, "POST", URL, json_body=body, headers={"Accept": "application/json"}, policy=policy
    )
    return parse_short_interest(payload)
