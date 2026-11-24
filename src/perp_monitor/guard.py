"""Last line of defence: prove a run contains stock markets only.

The venue clients already filter by market type and the allowlist. These checks run
again on the final data and the rendered text; any failure aborts the run before
anything is stored or sent.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from perp_monitor.allowlist import Allowlist
from perp_monitor.models import MarketSnapshot


class CryptoLeakError(RuntimeError):
    pass


def check_stock_only(
    snapshots: Iterable[MarketSnapshot],
    *,
    allowlist: Allowlist,
    denylist: frozenset[str],
    allowed_sources: frozenset[str],
) -> None:
    for snap in snapshots:
        where = f"{snap.venue.value} {snap.market}"
        if snap.source not in allowed_sources:
            raise CryptoLeakError(f"{where}: source {snap.source!r} is not a stock market")
        if snap.ticker in denylist:
            raise CryptoLeakError(f"{where}: {snap.ticker} is on the crypto denylist")
        if snap.ticker not in allowlist:
            raise CryptoLeakError(f"{where}: {snap.ticker} is not on the stock allowlist")


PRE_BLOCK = re.compile(r"<pre>(.*?)</pre>", re.DOTALL)


def _data_text(text: str) -> str:
    """The parts of a report that hold tickers: markdown table rows and <pre> blocks.

    Prose (notes, error messages) is skipped so a word like "USDT" in an error detail
    cannot abort a run.
    """
    rows = [line for line in text.splitlines() if line.lstrip().startswith("|")]
    return "\n".join([*rows, *PRE_BLOCK.findall(text)])


def check_report_text(text: str, denylist: frozenset[str]) -> None:
    if not denylist:
        return
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, sorted(denylist))) + r")\b")
    match = pattern.search(_data_text(text))
    if match:
        raise CryptoLeakError(f"crypto symbol {match.group(1)} found in report text")
