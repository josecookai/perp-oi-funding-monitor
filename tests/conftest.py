"""Shared test helpers: fixture loading and fake HTTP transports."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
ASSETS = ROOT / "assets"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


Handler = Callable[[httpx.Request], httpx.Response]


def mock_client(handler: Handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def fixture_loader() -> Callable[[str], Any]:
    return load_fixture
