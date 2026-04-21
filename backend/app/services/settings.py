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
WORK_WEEK_DAYS = "work_week_days"
VACATION_BUDGET_DAYS = "vacation_budget_days"

_DEFAULT_WORK_WEEK_DAYS = "0,1,2,3,4"  # Mon–Fri


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


def get_work_week_days(session: Session) -> list[int]:
    raw = _get(session, WORK_WEEK_DAYS, _DEFAULT_WORK_WEEK_DAYS)
    return [int(d) for d in raw.split(",") if d.strip()]


def set_work_week_days(session: Session, days: list[int]) -> None:
    _set(session, WORK_WEEK_DAYS, ",".join(str(d) for d in sorted(days)))


def get_vacation_budget_days(session: Session) -> int:
    return int(_get(session, VACATION_BUDGET_DAYS, "0"))


def set_vacation_budget_days(session: Session, days: int) -> None:
    _set(session, VACATION_BUDGET_DAYS, str(days))


def get_effective_cumulative_start(session: Session, today: date) -> date:
    """Cumulative start date, auto-advanced to Jan 1 of the current year when reset_annually=True."""
    base = get_cumulative_start_date(session)
    if get_reset_annually(session):
        return max(base, date(today.year, 1, 1))
    return base
