"""The stock-ticker allowlist: load, validate, intersect and edit.

All edit functions take file text and return new text; nothing is modified in place.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{0,9}(\.[A-Z])?$")


class AllowlistError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Allowlist:
    tickers: frozenset[str]

    def __contains__(self, ticker: object) -> bool:
        return ticker in self.tickers

    def __len__(self) -> int:
        return len(self.tickers)


@dataclass(frozen=True, slots=True)
class Issue:
    level: Literal["error", "warning"]
    message: str


def _strip(line: str) -> str:
    return line.split("#", 1)[0].strip()


def _entries(text: str) -> list[tuple[int, str]]:
    return [(n, _strip(line)) for n, line in enumerate(text.splitlines(), 1) if _strip(line)]


def _split(text: str) -> tuple[list[str], list[str]]:
    """Split file text into (comment/blank header lines, ticker entries)."""
    header: list[str] = []
    tickers: list[str] = []
    for line in text.splitlines():
        value = _strip(line)
        if value:
            tickers.append(value)
        elif not tickers:
            header.append(line)
    return header, tickers


def _render(header: list[str], tickers: Iterable[str]) -> str:
    return "".join(f"{line}\n" for line in [*header, *sorted(set(tickers))])


def parse_allowlist(text: str) -> Allowlist:
    seen: set[str] = set()
    for number, value in _entries(text):
        if not TICKER_RE.match(value):
            raise AllowlistError(f"line {number}: invalid ticker {value!r}")
        if value in seen:
            raise AllowlistError(f"line {number}: duplicate ticker {value!r}")
        seen.add(value)
    return Allowlist(frozenset(seen))


def load_allowlist(path: Path) -> Allowlist:
    return parse_allowlist(path.read_text())


def load_denylist(path: Path) -> frozenset[str]:
    return frozenset(value for _, value in _entries(path.read_text()))


def validate_allowlist_text(text: str, denylist: frozenset[str]) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    seen: set[str] = set()
    values = []
    for number, value in _entries(text):
        values.append(value)
        if not TICKER_RE.match(value):
            issues.append(Issue("error", f"line {number}: invalid ticker {value!r}"))
        if value in seen:
            issues.append(Issue("error", f"line {number}: duplicate ticker {value!r}"))
        if value in denylist:
            issues.append(Issue("error", f"line {number}: {value} is on the crypto denylist"))
        seen.add(value)
    if values != sorted(values):
        issues.append(Issue("warning", "tickers are not sorted (add/remove will sort them)"))
    return tuple(issues)


def add_tickers(text: str, tickers: Iterable[str]) -> str:
    new = list(tickers)
    for ticker in new:
        if not TICKER_RE.match(ticker):
            raise AllowlistError(f"invalid ticker {ticker!r}")
    header, existing = _split(text)
    return _render(header, [*existing, *new])


def remove_tickers(text: str, tickers: Iterable[str]) -> str:
    header, existing = _split(text)
    drop = set(tickers)
    unknown = sorted(drop - set(existing))
    if unknown:
        raise AllowlistError(f"not in allowlist: {', '.join(unknown)}")
    return _render(header, [t for t in existing if t not in drop])


def suggest_missing(candidates: Iterable[str], allowlist: Allowlist) -> tuple[str, ...]:
    return tuple(sorted(set(candidates) - allowlist.tickers))
