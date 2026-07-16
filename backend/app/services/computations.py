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


def net_minutes(start_time: str | None, end_time: str | None, total_break_minutes: int) -> int:
    """Net worked minutes: (end - start) - breaks. Returns 0 if start/end missing.

    Clamped at 0 so a pathological break sum larger than the span doesn't go negative
    (validation in the API prevents this in practice).
    """
    if not start_time or not end_time:
        return 0
    gross = minutes_between(start_time, end_time)
    return max(gross - total_break_minutes, 0)


def net_hours(start_time: str | None, end_time: str | None, total_break_minutes: int) -> float:
    return round(net_minutes(start_time, end_time, total_break_minutes) / 60.0, 4)


# ---------- per-entry & period summaries -----------------------------------


def is_work_day(entry: WorkEntry) -> bool:
    return entry.day_type == DayType.WORK


@dataclass(frozen=True)
class DailyTargetSchedule:
    """The contracted daily target over time.

    Real contracts change (8h → 6h on a start date), so a single flat number makes
    every cumulative total spanning the change wrong. A schedule is a list of
    ``(effective_from, hours)`` rows; the target for any date is the most recent row
    on or before that date. There is always at least one row.
    """

    # Ascending by effective_from, deduped by date. Never empty.
    rows: tuple[tuple[date, float], ...]

    @classmethod
    def constant(cls, hours: float) -> DailyTargetSchedule:
        """A schedule that is ``hours`` for all of time — the common single-target case."""
        return cls(((date.min, float(hours)),))

    @classmethod
    def from_rows(cls, rows: Iterable[tuple[date, float]]) -> DailyTargetSchedule:
        """Build from arbitrary rows: sort ascending, and if two share a date keep the last."""
        by_date: dict[date, float] = {}
        for eff, hours in rows:
            by_date[eff] = float(hours)
        if not by_date:
            raise ValueError("a daily-target schedule needs at least one row")
        ordered = tuple(sorted(by_date.items()))
        return cls(ordered)

    def for_date(self, d: date) -> float:
        """Target hours in effect on ``d`` — the last row whose effective_from is ≤ d.

        A date earlier than the first row falls back to the first row's hours (entries
        predating the earliest known contract use the earliest known target).
        """
        hours = self.rows[0][1]
        for eff, h in self.rows:
            if eff <= d:
                hours = h
            else:
                break
        return hours


def _as_schedule(target: float | DailyTargetSchedule) -> DailyTargetSchedule:
    """Coerce a bare float to a constant schedule so simple callers can pass a number."""
    if isinstance(target, DailyTargetSchedule):
        return target
    return DailyTargetSchedule.constant(target)


def daily_target_for(entry: WorkEntry, daily_target: float | DailyTargetSchedule) -> float:
    # Flex days charge the full daily target against the surplus pool.
    if entry.day_type in (DayType.WORK, DayType.FLEX):
        return _as_schedule(daily_target).for_date(entry.date)
    return 0.0


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
    entries: Iterable[WorkEntry], daily_target: float | DailyTargetSchedule
) -> PeriodSummary:
    schedule = _as_schedule(daily_target)
    net = 0.0
    target = 0.0
    work_days = 0
    non_work_days = 0
    for entry in entries:
        # Target is resolved per entry-date so a range spanning a contract change
        # (e.g. 8h → 6h) bills each day at the rate in effect that day.
        if is_work_day(entry):
            work_days += 1
            target += schedule.for_date(entry.date)
            net += daily_net_hours(entry)
        elif entry.day_type == DayType.FLEX:
            # Flex day: employee rests but the daily target drains the surplus pool.
            non_work_days += 1
            target += schedule.for_date(entry.date)
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
    next_first = date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)
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
