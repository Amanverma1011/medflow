from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def now() -> datetime:
    """Hospital-local wall-clock time.

    Domain timestamps are stored naive in the hospital's timezone so that
    "today", shift hours and hour-of-day analytics mean the same thing in SQL,
    Python and the browser.
    """
    return datetime.now(ZoneInfo(settings.hospital_tz)).replace(tzinfo=None, microsecond=0)


def today_start() -> datetime:
    return now().replace(hour=0, minute=0, second=0)
