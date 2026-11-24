from __future__ import annotations

import pytest

from perp_monitor.funding import to_8h, to_apr
from perp_monitor.models import Venue
from perp_monitor.overrides import OverridesError, load_overrides, parse_overrides
from tests.conftest import ASSETS


def test_shipped_overrides_alias_and_exclude() -> None:
    overrides = load_overrides(ASSETS / "symbol_overrides.toml")
    assert overrides.canonical(Venue.BINANCE, "BRKB") == "BRK.B"
    assert overrides.canonical(Venue.BINANCE, "NVDA") == "NVDA"
    assert overrides.canonical(Venue.HYPERLIQUID, "CL") is None
    assert overrides.canonical(Venue.HYPERLIQUID, "GOLD") is None
    assert overrides.canonical(Venue.HYPERLIQUID, "NVDA") == "NVDA"


def test_overrides_reject_non_string_values() -> None:
    with pytest.raises(OverridesError):
        parse_overrides("[binance.aliases]\nBRKB = 5\n")


def test_overrides_missing_sections_default_to_empty() -> None:
    overrides = parse_overrides("")
    assert overrides.canonical(Venue.BINANCE, "AAPL") == "AAPL"


def test_overrides_are_read_only() -> None:
    overrides = parse_overrides('[binance.aliases]\nBRKB = "BRK.B"\n')
    with pytest.raises(TypeError):
        overrides.binance.aliases["X"] = "Y"  # type: ignore[index]


@pytest.mark.parametrize(
    ("rate", "interval", "expected"),
    [(0.0001, 1, 0.0008), (0.0001, 8, 0.0001), (0.0001, 4, 0.0002), (-0.0003, 8, -0.0003)],
)
def test_to_8h(rate: float, interval: float, expected: float) -> None:
    assert to_8h(rate, interval) == pytest.approx(expected)


def test_to_apr() -> None:
    assert to_apr(0.0001, 8) == pytest.approx(0.0001 * 3 * 365)
    assert to_apr(0.0001, 1) == pytest.approx(0.0001 * 24 * 365)


@pytest.mark.parametrize("interval", [0, -1])
def test_funding_rejects_bad_interval(interval: float) -> None:
    with pytest.raises(ValueError):
        to_8h(0.0001, interval)
