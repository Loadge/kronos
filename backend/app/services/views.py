"""Shared entity → API response converters."""

from __future__ import annotations

from app.models import WorkEntry
from app.schemas import BreakOut, EntryOut
from app.services.computations import daily_net_hours, daily_target_for


def entry_to_out(entry: WorkEntry, daily_target_hours: float) -> EntryOut:
    net = daily_net_hours(entry)
    target = daily_target_for(entry, daily_target_hours)
    return EntryOut(
        date=entry.date,
        day_type=entry.day_type,
        start_time=entry.start_time,
        end_time=entry.end_time,
        notes=entry.notes,
        breaks=[BreakOut.model_validate(b) for b in entry.breaks],
        total_break_minutes=entry.total_break_minutes,
        net_hours=net,
        target_hours=target,
        surplus_hours=round(net - target, 2),
    )
