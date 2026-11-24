"""SEC listing lookup used by `allowlist validate --sec`.

SEC's company_tickers_exchange.json lists operating companies (including foreign ADR
issuers) with their exchange. It does not list most ETFs, so a miss is a warning for a
human to check, not proof either way.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import httpx

from perp_monitor.allowlist import Issue
from perp_monitor.http import DEFAULT_POLICY, RetryPolicy, request_json

SEC_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
US_EXCHANGES = frozenset({"Nasdaq", "NYSE", "CBOE"})


@dataclass(frozen=True, slots=True)
class Listing:
    name: str
    exchange: str | None


def sec_ticker(ticker: str) -> str:
    """SEC writes share classes with a dash: BRK.B -> BRK-B."""
    return ticker.replace(".", "-")


def fetch_listings(
    http: httpx.Client, user_agent: str, policy: RetryPolicy = DEFAULT_POLICY
) -> Mapping[str, Listing]:
    payload = request_json(http, "GET", SEC_URL, headers={"User-Agent": user_agent}, policy=policy)
    index = payload["fields"]
    col = {name: index.index(name) for name in ("name", "ticker", "exchange")}
    listings: dict[str, Listing] = {}
    for row in payload["data"]:
        listings.setdefault(row[col["ticker"]], Listing(row[col["name"]], row[col["exchange"]]))
    return listings


def sec_issues(tickers: Iterable[str], listings: Mapping[str, Listing]) -> tuple[Issue, ...]:
    issues = []
    for ticker in sorted(tickers):
        listing = listings.get(sec_ticker(ticker))
        if listing is None:
            issues.append(Issue("warning", f"{ticker}: not found in SEC company list"))
        elif listing.exchange not in US_EXCHANGES:
            issues.append(
                Issue(
                    "warning",
                    f"{ticker}: {listing.name} is listed on {listing.exchange or 'no exchange'}",
                )
            )
    return tuple(issues)
