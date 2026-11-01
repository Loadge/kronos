"""Clock in / clock out with the server's clock.

The Log tab stamps the browser's time into the form; a CLI or a bot has no browser and
may not even share the app's time zone (a container runs in UTC). These two endpoints
stamp ``now`` as the app sees it — the wall clock in ``TZ``, the same clock that decides
"today" everywhere else — so every client agrees on when the day started and ended.

POST /api/clock/in   → create today's work day with start_time = now (or ``at``)
POST /api/clock/out  → set end_time = now (or ``at``) and the breaks on the started day

Both accept ``dry_run``: the entry comes back as it would be written, and nothing is.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import DayType, WorkEntry
from app.schemas import ClockInIn, ClockOutIn, EntryPreviewOut, EntryUpdate
from app.services.clock import local_hhmm, local_today
from app.services.settings import get_daily_target_schedule
from app.services.views import breaks_from_body, entry_from_body, entry_to_out

router = APIRouter(prefix="/api/clock", tags=["clock"])


def _stamp(on: date, at: str | None) -> str:
    """The time to write: ``at`` when given, else now — but only on today.

    "Now" means nothing on another day: without an explicit time, clocking on a past
    or future date would stamp the current wall clock onto it (a 07:55 → 22:41 day
    logged at night for last Tuesday). The request has to say the time.
    """
    if at:
        return at
    today = local_today()
    if on != today:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{on.isoformat()} is not today ({today.isoformat()}) — give `at` (HH:MM) "
            "to clock in or out on another day",
        )
    return local_hhmm()


def _preview(entry: WorkEntry, session: Session, exists: bool) -> EntryPreviewOut:
    out = entry_to_out(entry, get_daily_target_schedule(session))
    return EntryPreviewOut(**out.model_dump(), exists=exists)


@router.post("/in", response_model=EntryPreviewOut, status_code=status.HTTP_201_CREATED)
def clock_in(body: ClockInIn, session: Session = Depends(get_session)) -> EntryPreviewOut:
    """Start a work day: an entry with a start time and no end yet.

    A day that already has an entry is not touched (409) — finish it with clock-out,
    or edit it; a started day is never silently restarted. Another day than today
    needs ``at``: there is no "now" on it.
    """
    on = body.date or local_today()
    start = _stamp(on, body.at)
    existing = session.get(WorkEntry, on)
    if existing is not None:
        since = f" (started {existing.start_time})" if existing.start_time else ""
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"entry for {on.isoformat()} already exists{since}",
        )
    entry = WorkEntry(
        date=on,
        day_type=DayType.WORK.value,
        start_time=start,
        notes=body.notes,
    )
    if body.dry_run:
        return _preview(entry, session, exists=False)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return _preview(entry, session, exists=False)


@router.post("/out", response_model=EntryPreviewOut)
def clock_out(body: ClockOutIn, session: Session = Depends(get_session)) -> EntryPreviewOut:
    """Finish the started day: end time now, breaks and (optionally) a note.

    Needs a work day that was clocked in and not yet out: no entry is a 404, a finished
    day or a leave day is a 409. The end must come after the start, and the breaks must
    fit in the span — the same rules as saving the day in the Log tab.
    """
    on = body.date or local_today()
    end = _stamp(on, body.at)
    entry = session.get(WorkEntry, on)
    if entry is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"no entry for {on.isoformat()} — clock in first"
        )
    if entry.day_type != DayType.WORK.value or not entry.start_time:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{on.isoformat()} is a {entry.day_type} day, not a started one",
        )
    if entry.end_time:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{on.isoformat()} already ended at {entry.end_time}",
        )
    notes = body.notes if "notes" in body.model_fields_set else entry.notes
    try:
        update = EntryUpdate(
            day_type=DayType.WORK,
            start_time=entry.start_time,
            end_time=end,
            notes=notes,
            breaks=body.breaks,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _first_message(exc)) from exc
    if body.dry_run:
        return _preview(entry_from_body(on, update), session, exists=True)
    entry.end_time = update.end_time
    entry.notes = update.notes
    entry.breaks = breaks_from_body(update.breaks)
    session.commit()
    session.refresh(entry)
    return _preview(entry, session, exists=True)


def _first_message(exc: ValueError) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        first = errors()
        if first:
            return first[0].get("msg", str(exc))
    return str(exc)
