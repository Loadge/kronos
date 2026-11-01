"""What "now" and "today" mean to Kronos: the wall clock in the configured ``TZ``.

One definition for every router (dashboard, streaks, projection, timesheet, clock
in/out) so a client in another time zone — a phone abroad, a bot in a UTC container —
never gets a different "today" than the app itself.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import TIMEZONE


def local_now() -> datetime:
    return datetime.now(ZoneInfo(TIMEZONE))


def local_today() -> date:
    return local_now().date()


def local_hhmm() -> str:
    """The current wall-clock time as the ``HH:MM`` the entry fields store."""
    return local_now().strftime("%H:%M")
