"""Telegram summary: one HTML message per venue plus a cross-venue message."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from html import escape

from perp_monitor.fmt import pct, rate, signed_usd, usd
from perp_monitor.models import MarketChange
from perp_monitor.render_md import window_text
from perp_monitor.report import Report, VenueSection

TELEGRAM_LIMIT = 4096
CROSS_ROWS = 10
OVERSIZED = "<i>Table too long for one message; see the attached report.</i>"


def _pre(rows: Sequence[Sequence[str]]) -> str:
    """Fixed-width table: first column left-aligned, the rest right-aligned."""
    if not rows:
        return "<i>none this run</i>"
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = [
        "  ".join(
            cell.ljust(w) if i == 0 else cell.rjust(w)
            for i, (cell, w) in enumerate(zip(row, widths, strict=True))
        )
        for row in rows
    ]
    return "<pre>" + escape("\n".join(lines)) + "</pre>"


def _oi_cells(c: MarketChange) -> list[str]:
    return [c.current.ticker, signed_usd(c.d_oi_usd), pct(c.d_oi_pct), usd(c.current.oi_usd)]


def _funding_cells(c: MarketChange) -> list[str]:
    return [
        c.current.ticker,
        rate(c.current.funding_8h),
        pct(c.current.funding_apr),
        usd(c.current.oi_usd),
    ]


def _block(
    title: str, items: Sequence[MarketChange], cells: Callable[[MarketChange], list[str]]
) -> str:
    return f"<b>{escape(title)}</b>\n{_pre([cells(c) for c in items])}"


def _header(report: Report, section: VenueSection) -> str:
    stamp = report.generated_at.strftime("%Y-%m-%d %H:%M UTC")
    total = usd(section.total_oi_usd)
    change = signed_usd(section.matched_d_oi_usd)
    return (
        f"<b>Stock perps · {escape(section.label)}</b> · {stamp}\n"
        f"{len(section.changes)} markets · OI {total} · Δ {change}\n"
        f"Window: {escape(window_text(section))}"
    )


def _venue_blocks(report: Report, section: VenueSection) -> list[str]:
    n = report.top_n
    blocks = [_header(report, section)]
    if section.error:
        return blocks
    if section.window.is_baseline:
        blocks.append("<i>OI rankings start next run.</i>")
    else:
        blocks += [
            _block(f"OI gain · top {n}", section.gainers, _oi_cells),
            _block(f"OI loss · top {n}", section.losers, _oi_cells),
        ]
    blocks += [
        _block(f"Funding negative · top {n} (8h, APR)", section.negative, _funding_cells),
        _block(f"Funding positive · top {n} (8h, APR)", section.positive, _funding_cells),
    ]
    return blocks


def _cross_blocks(report: Report) -> list[str]:
    rows = [
        [
            r.ticker,
            rate(r.binance.current.funding_8h),
            rate(r.hyperliquid.current.funding_8h),
            rate(r.funding_spread_8h),
        ]
        for r in report.cross[:CROSS_ROWS]
    ]
    title = f"Cross-venue funding 8h · top {CROSS_ROWS} by OI (Binance, HL, HL−Binance)"
    return [f"<b>{escape(title)}</b>\n{_pre(rows)}"]


def _pack(blocks: Sequence[str]) -> list[str]:
    """Join blocks into messages that each stay under Telegram's length limit."""
    messages: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= TELEGRAM_LIMIT:
            current = candidate
            continue
        if current:
            messages.append(current)
        current = block if len(block) <= TELEGRAM_LIMIT else OVERSIZED
    if current:
        messages.append(current)
    return messages


def render_telegram(report: Report) -> list[str]:
    messages: list[str] = []
    for section in report.sections:
        messages += _pack(_venue_blocks(report, section))
    if report.cross:
        messages += _pack(_cross_blocks(report))
    return messages
