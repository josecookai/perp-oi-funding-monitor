"""Venue-specific symbol aliases and exclusions (assets/symbol_overrides.toml)."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from perp_monitor.models import Venue


class OverridesError(ValueError):
    pass


def _frozen(mapping: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True, slots=True)
class VenueOverrides:
    aliases: Mapping[str, str] = field(default_factory=lambda: _frozen({}))
    exclude: Mapping[str, str] = field(default_factory=lambda: _frozen({}))


@dataclass(frozen=True, slots=True)
class Overrides:
    binance: VenueOverrides
    hyperliquid: VenueOverrides

    def for_venue(self, venue: Venue) -> VenueOverrides:
        return self.binance if venue is Venue.BINANCE else self.hyperliquid

    def canonical(self, venue: Venue, name: str) -> str | None:
        """Canonical ticker for a venue's base name, or None if the name is excluded."""
        rules = self.for_venue(venue)
        if name in rules.exclude:
            return None
        return rules.aliases.get(name, name)


def _string_table(raw: Any, where: str) -> Mapping[str, str]:
    if raw is None:
        return _frozen({})
    if not isinstance(raw, dict):
        raise OverridesError(f"[{where}] must be a table")
    for key, value in raw.items():
        if not isinstance(value, str):
            raise OverridesError(f"[{where}] {key}: value must be a string")
    return _frozen(raw)


def _venue(raw: dict[str, Any], name: str) -> VenueOverrides:
    section = raw.get(name, {})
    return VenueOverrides(
        aliases=_string_table(section.get("aliases"), f"{name}.aliases"),
        exclude=_string_table(section.get("exclude"), f"{name}.exclude"),
    )


def parse_overrides(text: str) -> Overrides:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise OverridesError(f"invalid TOML: {exc}") from exc
    return Overrides(binance=_venue(raw, "binance"), hyperliquid=_venue(raw, "hyperliquid"))


def load_overrides(path: Path) -> Overrides:
    return parse_overrides(path.read_text())
