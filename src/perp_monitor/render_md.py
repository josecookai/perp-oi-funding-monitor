"""Markdown report: the dated file written each run and printed to stdout."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from perp_monitor.fmt import MISSING, hours, pct, rate, signed_usd, usd
from perp_monitor.models import MarketChange
from perp_monitor.report import Report, VenueSection

Row = list[str]


def table(headers: Sequence[str], rows: Sequence[Row], right_from: int = 1) -> str:
    align = ["---" if i < right_from else "---:" for i in range(len(headers))]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(align) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def window_text(section: VenueSection) -> str:
    w = section.window
    if section.error:
        return f"fetch failed: {section.error}"
    if w.is_baseline:
        return "baseline run: changes start next run"
    assert w.hours is not None
    text = hours(w.hours)
    if w.origin == "binance_oi_hist":
        text += " (first run: previous OI from Binance OI history)"
    if not w.in_range:
        text += f" ⚠ outside expected {w.expected_hours:g}h ± {w.tolerance_hours:g}h"
    return text


def _total_change(section: VenueSection) -> str:
    delta, prior = section.matched_d_oi_usd, section.matched_prior_oi_usd
    if delta is None:
        return MISSING
    share = pct(delta / prior) if prior else MISSING
    return f"{signed_usd(delta)} ({share})"


def _summary(report: Report) -> str:
    rows = [
        [s.label, str(len(s.changes)), usd(s.total_oi_usd), _total_change(s), window_text(s)]
        for s in report.sections
    ]
    return table(["Venue", "Markets", "Total OI", "OI change*", "Window"], rows, right_from=1)


def _oi_row(c: MarketChange) -> Row:
    return [
        c.current.ticker,
        usd(c.current.oi_usd),
        "new" if c.is_new else signed_usd(c.d_oi_usd),
        pct(c.d_oi_pct),
        pct(c.d_contracts_pct),
        usd(c.current.volume_24h_usd),
        rate(c.current.funding_8h),
    ]


OI_HEADERS = ["Ticker", "OI", "ΔOI", "ΔOI %", "Δ contracts %", "24h volume", "Funding 8h"]
FUNDING_HEADERS = ["#", "Ticker", "Funding 8h", "APR", "Δ vs last run", "OI", "24h volume"]


def _ranked_oi_row(i: int, c: MarketChange) -> Row:
    return [str(i), *_oi_row(c)]


def _funding_row(i: int, c: MarketChange) -> Row:
    return [
        str(i),
        c.current.ticker,
        rate(c.current.funding_8h),
        pct(c.current.funding_apr),
        rate(c.d_funding_8h),
        usd(c.current.oi_usd),
        usd(c.current.volume_24h_usd),
    ]


def _short_note(count: int, top_n: int, reason: str) -> str:
    if count == 0:
        return f"\n\n_None this run ({reason})._"
    if count < top_n:
        return f"\n\n_(only {count} of {top_n} qualify; {reason})_"
    return ""


def _ranked(
    section: VenueSection,
    items: Sequence[MarketChange],
    top_n: int,
    headers: Sequence[str],
    row: Callable[[int, MarketChange], Row],
    reason: str,
    needs_prior: bool,
) -> str:
    if section.error:
        return f"_fetch failed: {section.error}_"
    if needs_prior and section.window.is_baseline:
        return "_Baseline run: no previous snapshot to compare with yet._"
    rows = [row(i, c) for i, c in enumerate(items, 1)]
    body = table(headers, rows, right_from=2) if rows else ""
    return (body + _short_note(len(rows), top_n, reason)).strip()


def _all_tickers(section: VenueSection) -> str:
    if section.error:
        return f"_fetch failed: {section.error}_"
    ordered = sorted(section.changes, key=lambda c: (-c.current.oi_usd, c.current.ticker))
    return table(OI_HEADERS, [_oi_row(c) for c in ordered])


def _cross(report: Report) -> str:
    if not report.cross:
        return "_No ticker is listed on both venues this run._"
    rows = [
        [
            r.ticker,
            usd(r.binance.current.oi_usd),
            usd(r.hyperliquid.current.oi_usd),
            rate(r.binance.current.funding_8h),
            rate(r.hyperliquid.current.funding_8h),
            rate(r.funding_spread_8h),
        ]
        for r in report.cross
    ]
    headers = [
        "Ticker",
        "OI Binance",
        "OI Hyperliquid",
        "Funding 8h Binance",
        "Funding 8h Hyperliquid",
        "Hyperliquid − Binance",
    ]
    return table(headers, rows)


NOTES = """## Notes

- OI in USD = contracts × mark price. Rankings use the USD change; "Δ contracts %" leaves
  out the effect of the price move.
- *OI change in the summary counts only markets present in both observations.
- Funding is converted to an 8h equivalent before ranking. Binance: `premiumIndex`
  `lastFundingRate` with each symbol's own interval. Hyperliquid: the market's current
  hourly `funding` rate. APR is simple, not compounded.
- Funding rates of exactly zero are left out of the funding rankings.
- Universe: allowlisted US single stocks and ADRs only. Crypto perps are filtered out by
  venue market type, the allowlist, and a final check on this text."""


def render_markdown(report: Report) -> str:
    n = report.top_n
    stamp = report.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    kind = "Manual run" if report.manual else "Scheduled run"
    parts = [
        f"# Stock perp OI & funding — {stamp}",
        f"{kind} · allowlist of {report.allowlist_size} US stocks/ADRs · "
        "funding shown as 8h-equivalent",
        _summary(report),
        "## 1. OI change — all tickers",
    ]
    for s in report.sections:
        parts += [f"### {s.label}", _all_tickers(s)]
    ranked_specs = [
        (
            f"## 2. OI gain — top {n}",
            "gainers",
            OI_HEADERS,
            _ranked_oi_row,
            "the rest had no increase",
            True,
        ),
        (
            f"## 3. OI loss — top {n}",
            "losers",
            OI_HEADERS,
            _ranked_oi_row,
            "the rest had no decrease",
            True,
        ),
        (
            f"## 4. Funding negative — top {n}",
            "negative",
            FUNDING_HEADERS,
            _funding_row,
            "the rest are zero or positive",
            False,
        ),
        (
            f"## 5. Funding positive — top {n}",
            "positive",
            FUNDING_HEADERS,
            _funding_row,
            "the rest are zero or negative",
            False,
        ),
    ]
    for title, attr, headers, row, reason, needs_prior in ranked_specs:
        parts.append(title)
        hdrs = ["#", *headers] if row is _ranked_oi_row else headers
        for s in report.sections:
            parts += [
                f"### {s.label}",
                _ranked(s, getattr(s, attr), n, hdrs, row, reason, needs_prior),
            ]
    parts += ["## Cross-venue (tickers on both)", _cross(report), NOTES]
    return "\n\n".join(parts) + "\n"
