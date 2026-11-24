"""Hyperliquid: stock perps on HIP-3 builder dexes (e.g. `xyz`).

The default `metaAndAssetCtxs` call returns the main dex, which is all crypto. This
client always names a builder dex and refuses to read the main one.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from perp_monitor.allowlist import Allowlist
from perp_monitor.http import DEFAULT_POLICY, HttpError, RetryPolicy, request_json
from perp_monitor.models import MarketSnapshot, Venue
from perp_monitor.overrides import Overrides

log = logging.getLogger(__name__)

FUNDING_INTERVAL_HOURS = 1.0


class HyperliquidError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class HlMarket:
    dex: str
    name: str  # e.g. "xyz:NVDA"
    base: str  # e.g. "NVDA"
    ctx: Mapping[str, Any]


class HyperliquidClient:
    def __init__(self, http: httpx.Client, info_url: str, policy: RetryPolicy = DEFAULT_POLICY):
        self._http = http
        self._url = info_url
        self._policy = policy

    def _post(self, payload: Mapping[str, Any]) -> Any:
        try:
            return request_json(
                self._http, "POST", self._url, json_body=payload, policy=self._policy
            )
        except HttpError as exc:
            raise HyperliquidError(str(exc)) from exc

    def perp_dexs(self) -> tuple[str, ...]:
        return tuple(d["name"] for d in self._post({"type": "perpDexs"}) if d and d.get("name"))

    def markets(self, dex: str) -> tuple[HlMarket, ...]:
        if not dex:
            raise ValueError("refusing to read the main Hyperliquid dex (crypto only)")
        payload = self._post({"type": "metaAndAssetCtxs", "dex": dex})
        return parse_markets(dex, payload)


def parse_markets(dex: str, payload: Any) -> tuple[HlMarket, ...]:
    try:
        meta, ctxs = payload
        universe = meta["universe"]
    except (TypeError, ValueError, KeyError) as exc:
        raise HyperliquidError(f"dex {dex}: unexpected metaAndAssetCtxs shape") from exc
    if len(universe) != len(ctxs):
        raise HyperliquidError(
            f"dex {dex}: universe length {len(universe)} != contexts length {len(ctxs)}"
        )
    markets = []
    for asset, ctx in zip(universe, ctxs, strict=True):
        if asset.get("isDelisted"):
            continue
        name = asset["name"]
        prefix, _, base = name.partition(":")
        if prefix != dex or not base:
            raise HyperliquidError(f"dex {dex}: unexpected market name {name!r}")
        markets.append(HlMarket(dex=dex, name=name, base=base, ctx=ctx))
    return tuple(markets)


def _snapshot(market: HlMarket, ticker: str) -> MarketSnapshot | None:
    ctx = market.ctx
    mark = float(ctx.get("markPx") or 0)
    if mark <= 0:
        log.warning("hyperliquid %s: no mark price, skipped", market.name)
        return None
    return MarketSnapshot(
        venue=Venue.HYPERLIQUID,
        source=f"hl:{market.dex}",
        market=market.name,
        ticker=ticker,
        oi_contracts=float(ctx.get("openInterest") or 0),
        mark_price=mark,
        funding_rate=float(ctx.get("funding") or 0),
        funding_interval_hours=FUNDING_INTERVAL_HOURS,
        volume_24h_usd=float(ctx.get("dayNtlVlm") or 0),
    )


def _checked_dexes(client: HyperliquidClient, dexes: Iterable[str]) -> tuple[str, ...]:
    wanted = tuple(dexes)
    available = set(client.perp_dexs())
    missing = [d for d in wanted if d not in available]
    if missing:
        raise HyperliquidError(f"configured HL dex not found: {', '.join(missing)}")
    return wanted


def fetch_hl_snapshots(
    client: HyperliquidClient, dexes: Iterable[str], allowlist: Allowlist, overrides: Overrides
) -> tuple[MarketSnapshot, ...]:
    snapshots = []
    for dex in _checked_dexes(client, dexes):
        for market in client.markets(dex):
            ticker = overrides.canonical(Venue.HYPERLIQUID, market.base)
            if ticker is None or ticker not in allowlist:
                continue
            snap = _snapshot(market, ticker)
            if snap is not None:
                snapshots.append(snap)
    return tuple(snapshots)


def stock_base_names(
    client: HyperliquidClient, dexes: Iterable[str], overrides: Overrides
) -> frozenset[str]:
    """Canonical names of every market on the configured dexes (for `allowlist suggest`)."""
    names = (
        overrides.canonical(Venue.HYPERLIQUID, m.base)
        for dex in _checked_dexes(client, dexes)
        for m in client.markets(dex)
    )
    return frozenset(n for n in names if n is not None)
