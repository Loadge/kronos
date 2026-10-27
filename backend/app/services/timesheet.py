"""The printable timesheet as data: every calendar day of a range, by month, with totals.

Pure — the router fetches entries and settings, this turns them into rows the Jinja
template can print without thinking. Hours are formatted here too (decimal or h:mm)
so the template has no arithmetic.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.models import DayType, WorkEntry
from app.services.computations import (
    DailyTargetSchedule,
    daily_net_hours,
    daily_target_for,
    leave_fraction,
    leave_hours_for,
)

# ---------- hour formatting --------------------------------------------------


def fmt_hours(hours: float, style: str) -> str:
    """7.5 → "7.50" (decimal) or "7:30" (hm). Negative values keep a leading minus."""
    sign = "−" if hours < -1e-9 else ""
    h = abs(hours)
    if style == "hm":
        minutes = round(h * 60)
        return f"{sign}{minutes // 60}:{minutes % 60:02d}"
    return f"{sign}{h:.2f}"


def fmt_signed(hours: float, style: str) -> str:
    """Like fmt_hours but always signed: +1:30, −0:15, ±0:00."""
    if hours > 0.005:
        return "+" + fmt_hours(hours, style)
    if hours < -0.005:
        return "−" + fmt_hours(-hours, style)
    return "±" + fmt_hours(0.0, style)


def fmt_days(n: float) -> str:
    """19.5 → "19.5", 20.0 → "20"."""
    return f"{round(n, 2):g}"


# ---------- rows --------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    date: date
    day: str  # "01"
    weekday: str  # "Mon"
    weekend: bool
    entry: WorkEntry | None
    kind: str  # "work" | "leave" | "partial" | "empty" | "gap" (past work-week day, unlogged)
    day_type: str  # "" for no entry
    type_label: str  # "vacation · 3h" for partial leave
    start: str
    end: str
    breaks: str  # formatted, "" when none
    net: str  # "" on whole-day leave and empty days
    target: str  # "" on whole-day leave / empty
    delta: str  # signed, "" likewise
    delta_sign: int  # -1 / 0 / 1 for colouring
    running: str  # running balance within the sheet, "" on empty days
    running_sign: int
    notes: str


@dataclass
class Totals:
    net: float = 0.0
    target: float = 0.0
    work_days: float = 0.0
    off_days: float = 0.0
    vacation: float = 0.0
    sick: float = 0.0
    holiday: float = 0.0
    flex: float = 0.0
    gaps: int = 0

    @property
    def balance(self) -> float:
        return round(self.net - self.target, 2)

    def add(self, other: Totals) -> None:
        for k in ("net", "target", "work_days", "off_days", "vacation", "sick", "holiday", "flex"):
            setattr(self, k, round(getattr(self, k) + getattr(other, k), 2))
        self.gaps += other.gaps


@dataclass
class MonthSection:
    year: int
    month: int
    label: str  # "September 2026"
    abbr: str  # "Sep"
    rows: list[Row] = field(default_factory=list)
    totals: Totals = field(default_factory=Totals)


@dataclass
class Timesheet:
    start: date
    end: date
    period_label: str
    hours_style: str
    months: list[MonthSection]
    totals: Totals
    multi_month: bool

    def fmt(self, hours: float) -> str:
        return fmt_hours(hours, self.hours_style)

    def fmt_signed(self, hours: float) -> str:
        return fmt_signed(hours, self.hours_style)


def period_label(start: date, end: date) -> str:
    """ "September 2026", "August – September 2026", "2026", or "3 Mar – 14 Apr 2026"."""
    whole_month = start.day == 1 and end == _month_end(end)
    if whole_month and (start.year, start.month) == (end.year, end.month):
        return f"{calendar.month_name[start.month]} {start.year}"
    if start == date(start.year, 1, 1) and end == date(start.year, 12, 31):
        return str(start.year)
    if whole_month and start.year == end.year:
        return f"{calendar.month_name[start.month]} – {calendar.month_name[end.month]} {start.year}"
    if start.year == end.year:
        a = f"{start.day} {calendar.month_abbr[start.month]}"
        b = f"{end.day} {calendar.month_abbr[end.month]}"
        return f"{a} – {b} {start.year}"
    return f"{start.isoformat()} – {end.isoformat()}"


def _month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _sign(h: float) -> int:
    return 1 if h > 0.005 else -1 if h < -0.005 else 0


def build_timesheet(
    entries: Iterable[WorkEntry],
    *,
    start: date,
    end: date,
    today: date,
    schedule: DailyTargetSchedule,
    work_week_days: Iterable[int],
    hours_style: str = "dec",
) -> Timesheet:
    """Every calendar day from ``start`` to ``end`` inclusive, grouped by month.

    Whole-day leave prints blank net / target / Δ (only its type and the running
    balance); a past work-week day without an entry is a ``gap`` ("not logged").
    Future days print empty, never as gaps. The running balance is the sheet's own,
    starting at zero on ``start``.
    """
    if end < start:
        raise ValueError("end before start")
    by_date = {e.date: e for e in entries}
    week = set(work_week_days)
    months: list[MonthSection] = []
    grand = Totals()
    running = 0.0
    d = start
    section: MonthSection | None = None
    while d <= end:
        if section is None or (section.year, section.month) != (d.year, d.month):
            section = MonthSection(
                d.year,
                d.month,
                f"{calendar.month_name[d.month]} {d.year}",
                calendar.month_abbr[d.month],
            )
            months.append(section)
        e = by_date.get(d)
        weekend = d.weekday() not in week
        row, delta = _row(e, d, weekend, today, schedule, hours_style, running)
        running = round(running + delta, 2)
        section.rows.append(row)
        _count(section.totals, e, row.kind, schedule)
        d += timedelta(days=1)
    for m in months:
        grand.add(m.totals)
    return Timesheet(
        start=start,
        end=end,
        period_label=period_label(start, end),
        hours_style=hours_style,
        months=months,
        totals=grand,
        multi_month=len(months) > 1,
    )


def _row(e, d, weekend, today, schedule, style, running_before) -> tuple[Row, float]:
    base = dict(date=d, day=f"{d.day:02d}", weekday=d.strftime("%a"), weekend=weekend, entry=e)
    if e is None:
        gap = (not weekend) and d <= today
        row = Row(
            **base,
            kind="gap" if gap else "empty",
            day_type="",
            type_label="",
            start="",
            end="",
            breaks="",
            net="",
            target="",
            delta="",
            delta_sign=0,
            running="",
            running_sign=0,
            notes="",
        )
        return row, 0.0
    net = daily_net_hours(e)
    target = daily_target_for(e, schedule)
    delta = round(net - target, 2)
    running = round(running_before + delta, 2)
    whole_leave = e.day_type != DayType.WORK and not e.is_partial
    kind = "work" if e.day_type == DayType.WORK else ("partial" if e.is_partial else "leave")
    label = e.day_type
    if kind == "partial":
        label = f"{e.day_type} · {fmt_days(leave_hours_for(e, schedule))}h"
    brk = e.total_break_minutes
    row = Row(
        **base,
        kind=kind,
        day_type=e.day_type,
        type_label=label,
        start=e.start_time or "",
        end=e.end_time or "",
        breaks=fmt_hours(brk / 60, style) if brk else "",
        net="" if whole_leave else fmt_hours(net, style),
        target="" if whole_leave else fmt_hours(target, style),
        delta="" if whole_leave else fmt_signed(delta, style),
        delta_sign=0 if whole_leave else _sign(delta),
        running=fmt_signed(running, style),
        running_sign=_sign(running),
        notes=(e.notes or "").strip(),
    )
    return row, delta


def _count(t: Totals, e: WorkEntry | None, kind: str, schedule: DailyTargetSchedule) -> None:
    if e is None:
        if kind == "gap":
            t.gaps += 1
        return
    off = leave_fraction(e)
    t.net = round(t.net + daily_net_hours(e), 2)
    t.target = round(t.target + daily_target_for(e, schedule), 2)
    t.work_days = round(t.work_days + 1 - off, 2)
    t.off_days = round(t.off_days + off, 2)
    if e.day_type == DayType.VACATION:
        t.vacation = round(t.vacation + off, 2)
    elif e.day_type == DayType.SICK:
        t.sick = round(t.sick + off, 2)
    elif e.day_type == DayType.HOLIDAY:
        t.holiday = round(t.holiday + off, 2)
    elif e.day_type == DayType.FLEX:
        t.flex = round(t.flex + off, 2)
