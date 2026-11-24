from __future__ import annotations

import json
import re
from datetime import timedelta

from perp_monitor.delta import make_window
from perp_monitor.models import Venue
from perp_monitor.render_json import report_to_json
from perp_monitor.render_md import render_markdown
from perp_monitor.render_tg import TELEGRAM_LIMIT, render_telegram
from perp_monitor.report import VenueInput, build_report
from tests.factories import T0, T8, change

STORE_WINDOW = make_window(T0, T8, expected_hours=8, tolerance_hours=1, origin="store")
BASELINE = make_window(None, T8, expected_hours=8, tolerance_hours=1, origin=None)


def binance_changes():
    ladder = [
        change(f"T{i:02d}", 1000 + 100 * (i - 6), 1000, funding=(i - 6) * 0.00001)
        for i in range(13)
    ]
    return (*ladder, change("NVDA", 5000, 4000, funding=0.0001), change("NEWCO", 10, None))


def hl_changes():
    return (
        change("NVDA", 3000, None, funding=0.00002, venue=Venue.HYPERLIQUID),
        change("AAPL", 2000, None, funding=-0.00001, venue=Venue.HYPERLIQUID),
    )


def sample_report(binance_window=STORE_WINDOW, error: str | None = None):
    return build_report(
        generated_at=T8,
        manual=False,
        top_n=10,
        allowlist_size=165,
        inputs=(
            VenueInput(Venue.BINANCE, "Binance", binance_changes(), binance_window, error),
            VenueInput(Venue.HYPERLIQUID, "Hyperliquid (xyz)", hl_changes(), BASELINE, None),
        ),
    )


def test_build_report_rankings() -> None:
    report = sample_report()
    binance, hl = report.sections
    assert len(binance.gainers) == 7  # T07..T12 + NVDA
    assert binance.gainers[0].current.ticker == "NVDA"
    assert len(binance.losers) == 6
    assert len(binance.negative) == 6
    assert len(binance.positive) == 7
    assert hl.gainers == () and hl.losers == ()  # baseline: nothing to compare with
    assert [r.ticker for r in report.cross] == ["NVDA"]


def test_totals_only_count_markets_seen_both_times() -> None:
    binance = sample_report().sections[0]
    assert binance.total_oi_usd == sum(c.current.oi_usd for c in binance.changes)
    matched = [c for c in binance.changes if not c.is_new]
    assert binance.matched_d_oi_usd == sum(c.d_oi_usd for c in matched)


def test_markdown_has_all_sections_and_no_usdt_suffix() -> None:
    text = render_markdown(sample_report())
    for heading in (
        "## 1. OI change",
        "## 2. OI gain",
        "## 3. OI loss",
        "## 4. Funding negative",
        "## 5. Funding positive",
        "## Cross-venue",
    ):
        assert heading in text
    assert "USDT" not in text
    assert "| NVDA |" in text
    assert "baseline" in text.lower()


def test_markdown_flags_out_of_range_window_and_short_lists() -> None:
    late = make_window(
        T0, T8 + timedelta(hours=8), expected_hours=8, tolerance_hours=1, origin="store"
    )
    text = render_markdown(sample_report(binance_window=late))
    assert "expected 8h" in text
    assert re.search(r"only 6 of 10", text)


def test_markdown_shows_venue_error() -> None:
    text = render_markdown(sample_report(error="HTTP 451 restricted location"))
    assert "fetch failed" in text and "451" in text


def test_telegram_messages_fit_and_escape() -> None:
    messages = render_telegram(sample_report())
    assert len(messages) >= 2
    assert all(len(m) <= TELEGRAM_LIMIT for m in messages)
    assert all(m.count("<pre>") == m.count("</pre>") for m in messages)
    assert "USDT" not in "".join(messages)


def test_report_to_json_round_trips() -> None:
    data = report_to_json(sample_report())
    text = json.dumps(data)
    assert json.loads(text)["sections"][0]["venue"] == "binance"
    first = data["sections"][0]
    assert first["window"]["hours"] == 8
    assert {"oi_gain", "oi_loss", "funding_negative", "funding_positive"} <= set(first["rankings"])
    nvda = next(r for r in first["rows"] if r["ticker"] == "NVDA")
    assert nvda["market"] == "NVDAUSDT"
    assert nvda["d_oi_usd"] == 100_000


def test_oversized_telegram_block_is_replaced_not_cut() -> None:
    from perp_monitor.render_tg import _pack

    huge = "<pre>" + "x" * 5000 + "</pre>"
    messages = _pack(["<b>head</b>", huge])
    assert all(len(m) <= TELEGRAM_LIMIT for m in messages)
    assert all(m.count("<pre>") == m.count("</pre>") for m in messages)
    assert "see the attached report" in "".join(messages)
