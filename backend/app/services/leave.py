"""Turning ``leave_hours`` into the ``fraction`` the rows store.

The fraction is what survives a later change of the target timeline (a whole day stays
whole); hours are what people and the CLI say. The conversion needs the target in force
on the date, so it lives here, next to the schedule, and every router calls the same
function instead of each client guessing the rate.
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.schemas import _EntryBody
from app.services.computations import DailyTargetSchedule


def fraction_for_hours(hours: float, on: date, schedule: DailyTargetSchedule) -> float:
    """``hours`` of leave on ``on`` as a share of that date's target.

    Exactly the target is a whole day (1.0); more than the target cannot be taken off
    and is a 422. The quotient is not rounded: 3h of 8h is 0.375 exactly, and any other
    value round-trips through JSON and the backup unchanged.
    """
    target = schedule.for_date(on)
    if hours > target + 1e-9:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"leave_hours {hours:g} exceed the {target:g}h target on {on.isoformat()}",
        )
    fraction = hours / target
    return 1.0 if fraction > 1.0 - 1e-9 else fraction


def resolve_entry_hours(body: _EntryBody, on: date, schedule: DailyTargetSchedule) -> _EntryBody:
    """The body with ``leave_hours`` folded into ``fraction`` — re-validated, because
    the whole-day rules (no times, no breaks) only apply once the share is known."""
    if not body.hours_pending:
        return body
    data = body.model_dump()
    data["fraction"] = fraction_for_hours(body.leave_hours, on, schedule)
    data["leave_hours"] = None
    try:
        return type(body).model_validate(data)
    except ValidationError as exc:
        msg = exc.errors()[0].get("msg", "invalid entry")
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg) from exc
