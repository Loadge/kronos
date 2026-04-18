"""Read/write configuration values stored in the `settings` key-value table.

Falls back to the defaults from `app.config` if a key is absent — the app keeps working
on a fresh DB even before the initial migration's seed rows are inserted.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.config import DEFAULT_CUMULATIVE_START_DATE, DEFAULT_DAILY_TARGET_HOURS
from app.models import Setting

DAILY_TARGET_HOURS = "daily_target_hours"
CUMULATIVE_START_DATE = "cumulative_start_date"
RESET_ANNUALLY = "reset_annually"


def _get(session: Session, key: str, default: str) -> str:
    row = session.get(Setting, key)
    return row.value if row else default


def _set(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))


def get_daily_target_hours(session: Session) -> float:
    return float(_get(session, DAILY_TARGET_HOURS, str(DEFAULT_DAILY_TARGET_HOURS)))


def set_daily_target_hours(session: Session, hours: float) -> None:
    _set(session, DAILY_TARGET_HOURS, f"{hours:g}")


def get_cumulative_start_date(session: Session) -> date:
    return date.fromisoformat(
        _get(session, CUMULATIVE_START_DATE, DEFAULT_CUMULATIVE_START_DATE)
    )


def set_cumulative_start_date(session: Session, d: date) -> None:
    _set(session, CUMULATIVE_START_DATE, d.isoformat())


def get_reset_annually(session: Session) -> bool:
    return _get(session, RESET_ANNUALLY, "false") == "true"


def set_reset_annually(session: Session, value: bool) -> None:
    _set(session, RESET_ANNUALLY, "true" if value else "false")


def get_effective_cumulative_start(session: Session, today: date) -> date:
    """Cumulative start date, auto-advanced to Jan 1 of the current year when reset_annually=True."""
    base = get_cumulative_start_date(session)
    if get_reset_annually(session):
        return max(base, date(today.year, 1, 1))
    return base
