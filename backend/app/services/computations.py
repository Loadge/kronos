"""Pure computation helpers for hours math.

No DB, no HTTP — everything here is trivially unit-testable. The API/analytics
routers lift data out of SQLAlchemy and feed it into these functions.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from app.models import DayType, WorkEntry


# ---------- time parsing ---------------------------------------------------


def parse_hhmm(value: str) -> tuple[int, int]:
    """Parse 'HH:MM' into (hours, minutes). Raises ValueError on malformed input."""
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise ValueError(f"expected HH:MM, got {value!r}")
    h_str, m_str = value[:2], value[3:]
    if not (h_str.isdigit() and m_str.isdigit()):
        raise ValueError(f"expected HH:MM, got {value!r}")
    hh, mm = int(h_str), int(m_str)
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise ValueError(f"time out of range: {value!r}")
    return hh, mm


def minutes_of(value: str) -> int:
    hh, mm = parse_hhmm(value)
    return hh * 60 + mm


def minutes_between(start: str, end: str) -> int:
    """Minutes from `start` to `end` on the same day. End must be strictly after start."""
    start_m = minutes_of(start)
    end_m = minutes_of(end)
    if end_m <= start_m:
        raise ValueError(f"end {end!r} must be after start {start!r}")
    return end_m - start_m


# ---------- break calculator ----------------------------------------------


def minutes_to_hours_label(minutes: int) -> str:
    """80 -> '1h 20min', 60 -> '1h', 45 -> '45min', 0 -> '0min'."""
    if minutes < 0:
        raise ValueError("minutes cannot be negative")
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}min"
    if hours:
        return f"{hours}h"
    return f"{mins}min"


# ---------- net hours ------------------------------------------------------


def net_minutes(
    start_time: str | None, end_time: str | None, total_break_minutes: int
) -> int:
    """Net worked minutes: (end - start) - breaks. Returns 0 if start/end missing.

    Clamped at 0 so a pathological break sum larger than the span doesn't go negative
    (validation in the API prevents this in practice).
    """
    if not start_time or not end_time:
        return 0
    gross = minutes_between(start_time, end_time)
    return max(gross - total_break_minutes, 0)


def net_hours(
    start_time: str | None, end_time: str | None, total_break_minutes: int
) -> float:
    return round(net_minutes(start_time, end_time, total_break_minutes) / 60.0, 4)


# ---------- per-entry & period summaries -----------------------------------


def is_work_day(entry: WorkEntry) -> bool:
    return entry.day_type == DayType.WORK


def daily_target_for(entry: WorkEntry, daily_target_hours: float) -> float:
    return daily_target_hours if is_work_day(entry) else 0.0


def daily_net_hours(entry: WorkEntry) -> float:
    if not is_work_day(entry):
        return 0.0
    return net_hours(entry.start_time, entry.end_time, entry.total_break_minutes)


@dataclass(frozen=True)
class PeriodSummary:
    net_hours: float
    target_hours: float
    work_days: int
    non_work_days: int

    @property
    def surplus_hours(self) -> float:
        return round(self.net_hours - self.target_hours, 2)


def summarize(
    entries: Iterable[WorkEntry], daily_target_hours: float
) -> PeriodSummary:
    net = 0.0
    target = 0.0
    work_days = 0
    non_work_days = 0
    for entry in entries:
        if is_work_day(entry):
            work_days += 1
            target += daily_target_hours
            net += daily_net_hours(entry)
        else:
            non_work_days += 1
    return PeriodSummary(
        net_hours=round(net, 2),
        target_hours=round(target, 2),
        work_days=work_days,
        non_work_days=non_work_days,
    )


# ---------- calendar helpers ----------------------------------------------


def iso_week_bounds(d: date) -> tuple[date, date]:
    """Return (Monday, Sunday) of the ISO week containing `d`."""
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


def month_bounds(d: date) -> tuple[date, date]:
    first = d.replace(day=1)
    next_first = (
        date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)
    )
    return first, next_first - timedelta(days=1)


def month_range(start: date, end: date) -> list[tuple[int, int]]:
    """List of (year, month) tuples from start to end inclusive."""
    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    end_y, end_m = end.year, end.month
    while (y, m) <= (end_y, end_m):
        out.append((y, m))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return out
