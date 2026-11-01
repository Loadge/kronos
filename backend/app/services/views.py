"""Shared converters between the ORM entities and the API shapes, both ways."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Break, WorkEntry
from app.schemas import BreakIn, BreakOut, EntryOut, _EntryBody
from app.services.computations import DailyTargetSchedule, day_figures


def entry_to_out(entry: WorkEntry, daily_target: float | DailyTargetSchedule) -> EntryOut:
    # One schedule lookup for this entry's own date gives target, leave and surplus.
    day = day_figures(entry, daily_target)
    return EntryOut(
        date=entry.date,
        day_type=entry.day_type,
        fraction=entry.fraction,
        leave_hours=day.leave_hours,
        start_time=entry.start_time,
        end_time=entry.end_time,
        notes=entry.notes,
        # A transient entry (a preview) has unsaved breaks with no id yet: number them
        # in order so the shape is the same as a stored day's.
        breaks=[
            BreakOut(
                id=b.id if b.id is not None else i,
                break_minutes=b.break_minutes,
                start_time=b.start_time,
                end_time=b.end_time,
            )
            for i, b in enumerate(entry.breaks, start=1)
        ],
        total_break_minutes=entry.total_break_minutes,
        net_hours=day.net_hours,
        target_hours=day.target_hours,
        surplus_hours=day.surplus_hours,
    )


def breaks_from_body(breaks: Iterable[BreakIn]) -> list[Break]:
    return [
        Break(break_minutes=b.break_minutes, start_time=b.start_time, end_time=b.end_time)
        for b in breaks
    ]


def entry_from_body(on: date, body: _EntryBody) -> WorkEntry:
    """A transient ``WorkEntry`` (with its breaks) from a validated request body."""
    entry = WorkEntry(
        date=on,
        day_type=body.day_type.value,
        fraction=body.fraction,
        start_time=body.start_time,
        end_time=body.end_time,
        notes=body.notes,
    )
    entry.breaks = breaks_from_body(body.breaks)
    return entry


def logged_dates(session: Session, dates: Iterable[date]) -> set[date]:
    """Which of ``dates`` already have an entry — one query, not one per date."""
    wanted = set(dates)
    if not wanted:
        return set()
    return set(session.scalars(select(WorkEntry.date).where(WorkEntry.date.in_(wanted))))
