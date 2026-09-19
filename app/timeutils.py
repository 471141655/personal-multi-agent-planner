from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import get_settings


def now_local() -> datetime:
    """Return configured local wall-clock time without tzinfo for DB portability."""
    return datetime.now(ZoneInfo(get_settings().timezone)).replace(tzinfo=None)


def today_local() -> date:
    return now_local().date()

