"""The US market calendar day for a UTC instant.

Earnings dates, filing dates and daily bars are US-Eastern calendar days. The 00:00 UTC
run is 19:00 or 20:00 ET on the previous day, so day offsets must use the ET date.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

MARKET_TZ = ZoneInfo("America/New_York")


def market_date(now: datetime) -> date:
    return now.astimezone(MARKET_TZ).date()
