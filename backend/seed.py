"""Populate the DB with ~3 months of realistic sample data.

Usage:
    python backend/seed.py             # from repo root
    python -m seed                      # from inside backend/
    make seed                           # Makefile wrapper

Drops existing work_entries + breaks rows first, so it's idempotent.
Preserves the `settings` table.
"""

from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

# Make `app.*` importable whether run as a script or module.
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Break, DayType, Plan, WorkEntry  # noqa: E402

# Reproducible "realistic" seed — fixed seed so every fresh seed run looks the same.
RNG = random.Random(42)


def _is_in_any_range(d: date, ranges: list[tuple[date, date]]) -> bool:
    return any(a <= d <= b for a, b in ranges)


def _weekday_on_or_before(d: date) -> date:
    """Pull a Saturday/Sunday back to the Friday so anchored days are never skipped."""
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _workday_times(d: date) -> tuple[str, str, list[int]]:
    """Return (start, end, breaks) for a work day, with natural variation."""
    # Start between 08:00 and 09:30
    start_min = RNG.randrange(8 * 60, 9 * 60 + 30 + 1, 15)
    # Work length between 7.5h and 9.5h
    work_min = RNG.randrange(int(7.5 * 60), int(9.5 * 60) + 1, 15)
    # 1–2 breaks totaling 30–90 minutes
    breaks = [RNG.choice([30, 45, 60])]
    if RNG.random() < 0.25:
        breaks.append(RNG.choice([10, 15, 20]))
    total_breaks = sum(breaks)
    # End = start + work_min + total_breaks (breaks are time OFF inside the span)
    end_min = start_min + work_min + total_breaks
    # Clamp so we don't spill past 22:00
    if end_min >= 22 * 60:
        end_min = 22 * 60 - 15
    return _fmt(start_min), _fmt(end_min), breaks


def _fmt(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


def build_entries(today: date | None = None) -> list[WorkEntry]:
    """Build ~3 months of realistic sample entries ending on *today*.

    Passing an explicit *today* makes the output deterministic for tests and
    avoids stale data when the endpoint is called long after server start-up.
    """
    today = today or date.today()
    start = today - timedelta(days=90)

    # Anchors for non-work days — spread across the window so the dashboard
    # math is interesting.
    vacation_ranges: list[tuple[date, date]] = [
        (today - timedelta(days=70), today - timedelta(days=66)),  # 5-day block
        (today - timedelta(days=25), today - timedelta(days=23)),  # 3-day block
    ]
    sick_days: list[date] = [today - timedelta(days=50), today - timedelta(days=14)]
    holidays: list[date] = [today - timedelta(days=78), today - timedelta(days=40)]
    # Partial leave: the day's fraction that was leave, and the hours worked
    # in the rest of it. Tuned for an 8h target: half a vacation day with its 4h
    # worked, and a 2h sick leave (left at 15:00 after a 6h shift).
    partial_days: dict[date, tuple[DayType, float, str, str, list[int]]] = {
        _weekday_on_or_before(today - timedelta(days=33)): (
            DayType.VACATION,
            0.5,
            "09:00",
            "13:00",
            [],
        ),
        _weekday_on_or_before(today - timedelta(days=9)): (
            DayType.SICK,
            0.25,
            "08:30",
            "15:00",
            [30],
        ),
    }

    # Reset the RNG so every seed run produces identical data regardless of
    # how many times the function has been called in this process.
    RNG.seed(42)

    entries: list[WorkEntry] = []
    d = start
    while d <= today:
        # Skip weekends by default (Saturday = 5, Sunday = 6)
        if d.weekday() >= 5:
            d += timedelta(days=1)
            continue

        if d in partial_days:
            day_type, fraction, start, end, breaks_min = partial_days[d]
            entry = WorkEntry(
                date=d, day_type=day_type.value, fraction=fraction, start_time=start, end_time=end
            )
            entry.breaks = [Break(break_minutes=m) for m in breaks_min]
            entries.append(entry)
            d += timedelta(days=1)
            continue

        if _is_in_any_range(d, vacation_ranges):
            day_type = DayType.VACATION
        elif d in sick_days:
            day_type = DayType.SICK
        elif d in holidays:
            day_type = DayType.HOLIDAY
        else:
            day_type = DayType.WORK

        if day_type is DayType.WORK:
            start, end, breaks_min = _workday_times(d)
            entry = WorkEntry(
                date=d,
                day_type=day_type.value,
                start_time=start,
                end_time=end,
            )
            entry.breaks = [Break(break_minutes=m) for m in breaks_min]
        else:
            entry = WorkEntry(date=d, day_type=day_type.value)

        entries.append(entry)
        d += timedelta(days=1)

    return entries


def build_plans(today: date | None = None) -> list[Plan]:
    """A few drafted days ahead of *today* so the planner has something to show:
    a long weekend of vacation in three weeks and a flex Friday in two."""
    today = today or date.today()
    plans: list[Plan] = []
    monday = _weekday_on_or_before(today + timedelta(days=21))
    monday -= timedelta(days=monday.weekday())  # back to that week's Monday
    for i in range(3):
        plans.append(
            Plan(
                date=monday + timedelta(days=i),
                day_type=DayType.VACATION.value,
                notes="long weekend",
            )
        )
    friday = today + timedelta(days=14)
    friday += timedelta(days=(4 - friday.weekday()) % 7)  # next Friday on/after
    plans.append(Plan(date=friday, day_type=DayType.FLEX.value))
    return plans


def main() -> None:
    # Ensure tables exist (in case the user runs seed on a fresh volume before migrations).
    Base.metadata.create_all(engine)

    with SessionLocal() as session:
        # Wipe existing entries + breaks (cascade handles breaks).
        existing = session.query(WorkEntry).all()
        for e in existing:
            session.delete(e)
        session.flush()

        for p in session.query(Plan).all():
            session.delete(p)
        entries = build_entries()
        plans = build_plans()
        session.add_all(entries)
        session.add_all(plans)
        session.commit()

        work = sum(1 for e in entries if e.day_type == DayType.WORK.value)
        vac = sum(1 for e in entries if e.day_type == DayType.VACATION.value)
        sick = sum(1 for e in entries if e.day_type == DayType.SICK.value)
        hol = sum(1 for e in entries if e.day_type == DayType.HOLIDAY.value)

    date_range = (
        f"{entries[0].date.isoformat()} → {entries[-1].date.isoformat()}"
        if entries
        else "no entries"
    )
    print(
        f"seeded {len(entries)} entries: "
        f"{work} work, {vac} vacation, {sick} sick, {hol} holiday "
        f"({date_range}); {len(plans)} planner drafts"
    )


if __name__ == "__main__":
    main()
