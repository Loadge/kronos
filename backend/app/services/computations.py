"""Pure computation helpers for hours math.

No DB, no HTTP — everything here is trivially unit-testable. The API/analytics
routers lift data out of SQLAlchemy and feed it into these functions.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

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


def leave_fraction(entry: WorkEntry) -> float:
    """The share of the day that is leave: 0 for a work day, 1 for whole-day leave,
    in between for partial leave. Work days ignore the stored value."""
    if is_work_day(entry):
        return 0.0
    return float(entry.fraction)


def daily_target_for(entry: WorkEntry, daily_target: float | DailyTargetSchedule) -> float:
    """Hours the day is measured against.

    * work: the full target in force on that date.
    * flex: the full target too — flex rests on banked surplus, so the whole day still
      charges the pool; on a partial flex day the hours actually worked offset it.
    * vacation / sick / holiday: the target for the part of the day that was *not*
      leave — zero for a whole day, ``T * (1 - fraction)`` for a partial one.
    """
    target = _as_schedule(daily_target).for_date(entry.date)
    if entry.day_type in (DayType.WORK, DayType.FLEX):
        return target
    return round(target * (1.0 - leave_fraction(entry)), 4)


def leave_hours_for(entry: WorkEntry, daily_target: float | DailyTargetSchedule) -> float:
    """Hours of leave on the day: ``fraction * T(date)``; 0 for a work day."""
    f = leave_fraction(entry)
    if f == 0.0:
        return 0.0
    return round(_as_schedule(daily_target).for_date(entry.date) * f, 4)


def daily_net_hours(entry: WorkEntry) -> float:
    """Hours worked: the span minus breaks, for work days and for the worked part of a
    partial leave day. Whole-day leave is always 0."""
    if not is_work_day(entry) and not entry.is_partial:
        return 0.0
    return net_hours(entry.start_time, entry.end_time, entry.total_break_minutes)


@dataclass(frozen=True)
class PeriodSummary:
    net_hours: float
    target_hours: float
    # Fractional: a day with 3h of leave on an 8h target counts as
    # 0.625 work + 0.375 off, so a week still adds up to its number of entries.
    work_days: float
    non_work_days: float

    @property
    def surplus_hours(self) -> float:
        return round(self.net_hours - self.target_hours, 2)


def summarize(
    entries: Iterable[WorkEntry], daily_target: float | DailyTargetSchedule
) -> PeriodSummary:
    schedule = _as_schedule(daily_target)
    net = 0.0
    target = 0.0
    work_days = 0.0
    non_work_days = 0.0
    for entry in entries:
        # Target is resolved per entry-date so a range spanning a contract change
        # (e.g. 8h → 6h) bills each day at the rate in effect that day. Flex days
        # charge the full target (they rest on banked surplus); other leave charges
        # only the worked share of the day — see daily_target_for.
        off = leave_fraction(entry)
        non_work_days += off
        work_days += 1.0 - off
        target += daily_target_for(entry, schedule)
        net += daily_net_hours(entry)
    return PeriodSummary(
        net_hours=round(net, 2),
        target_hours=round(target, 2),
        work_days=round(work_days, 2),
        non_work_days=round(non_work_days, 2),
    )


# ---------- time-off projection -------------------------------------------


class _Leave(Protocol):
    """What the projection needs from a drafted day (a Plan row, or any stand-in)."""

    date: date
    day_type: str
    fraction: float


@dataclass(frozen=True)
class Projection:
    """Cumulative balance carried to a horizon under two assumptions.

    ``on_target``: every undrafted scheduled day lands exactly on target, so only
    leave moves the number (flex drains, vacation / holiday are neutral). ``at_pace``:
    each undrafted scheduled day (and the worked share of a partial draft) adds the
    average surplus per work day so far. Real entries after today — imported
    holidays, days logged ahead — count as they are under both.
    """

    on_target: float
    at_pace: float
    scheduled_days_left: float  # work-week days after today with no real entry
    open_days_left: float  # ... minus the drafted share of them
    drafted_days: float  # sum of draft fractions after today, all types
    drafted_flex_hours: float  # what the flex drafts will take from the pool


def project_balance(
    *,
    balance_today: float,
    pace_per_day: float,
    start: date,
    end: date,
    work_week_days: Iterable[int],
    entries_by_date: dict[date, WorkEntry],
    drafts_by_date: dict[date, _Leave],
    schedule: DailyTargetSchedule,
) -> Projection:
    """Walk the days in ``[start, end]`` (the future) and carry ``balance_today``.

    A real entry on a day wins over a draft. Drafts on non-scheduled days (a weekend)
    still count as drafted, and a flex one still drains — the model never looks at the
    weekday for flex — but they add no worked share.
    """
    week = set(work_week_days)
    on_target = balance_today
    at_pace = balance_today
    scheduled = open_days = drafted = flex_hours = 0.0
    d = start
    while d <= end:
        entry = entries_by_date.get(d)
        if entry is not None:
            delta = daily_net_hours(entry) - daily_target_for(entry, schedule)
            on_target += delta
            at_pace += delta
            d += timedelta(days=1)
            continue
        is_scheduled = d.weekday() in week
        if is_scheduled:
            scheduled += 1
        draft = drafts_by_date.get(d)
        if draft is None:
            if is_scheduled:
                open_days += 1
                at_pace += pace_per_day
        else:
            f = float(draft.fraction)
            drafted += f
            if draft.day_type == DayType.FLEX:
                cost = schedule.for_date(d) * f
                flex_hours += cost
                on_target -= cost
                at_pace -= cost
            if is_scheduled:
                open_days += 1.0 - f
                at_pace += pace_per_day * (1.0 - f)
        d += timedelta(days=1)
    return Projection(
        on_target=round(on_target, 2),
        at_pace=round(at_pace, 2),
        scheduled_days_left=round(scheduled, 2),
        open_days_left=round(open_days, 2),
        drafted_days=round(drafted, 2),
        drafted_flex_hours=round(flex_hours, 2),
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
