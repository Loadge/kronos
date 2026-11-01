"""CRUD for work_entries + their breaks. Breaks are always managed through the parent."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import WorkEntry
from app.schemas import (
    BatchEntryIn,
    BatchResultOut,
    EntryIn,
    EntryOut,
    EntryPreviewOut,
    EntryUpdate,
)
from app.services.leave import fraction_for_hours, resolve_entry_hours
from app.services.settings import get_daily_target_schedule
from app.services.views import breaks_from_body, entry_from_body, entry_to_out, logged_dates

router = APIRouter(prefix="/api/entries", tags=["entries"])


@router.post("", response_model=EntryOut, status_code=status.HTTP_201_CREATED)
def create_entry(body: EntryIn, session: Session = Depends(get_session)) -> EntryOut:
    if session.get(WorkEntry, body.date):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"entry for {body.date.isoformat()} already exists",
        )
    schedule = get_daily_target_schedule(session)
    body = resolve_entry_hours(body, body.date, schedule)
    entry = entry_from_body(body.date, body)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry_to_out(entry, schedule)


@router.post("/preview", response_model=EntryPreviewOut)
def preview_entry(body: EntryIn, session: Session = Depends(get_session)) -> EntryPreviewOut:
    """The day a create or update with this body would produce — validated and computed
    by the same code, written nowhere. ``exists`` says whether a create would 409.

    What a CLI's ``--dry-run`` shows; what a form could show before saving.
    """
    schedule = get_daily_target_schedule(session)
    body = resolve_entry_hours(body, body.date, schedule)
    out = entry_to_out(entry_from_body(body.date, body), schedule)
    exists = session.get(WorkEntry, body.date) is not None
    return EntryPreviewOut(**out.model_dump(), exists=exists)


@router.post("/batch", response_model=BatchResultOut)
def batch_create_entries(
    body: BatchEntryIn, session: Session = Depends(get_session)
) -> BatchResultOut:
    """Create multiple non-work entries at once. Silently skips dates that already have an entry."""
    created: list[date] = []
    skipped: list[date] = []
    taken = logged_dates(session, body.dates)
    schedule = get_daily_target_schedule(session) if body.hours_pending else None
    for d in body.dates:
        if d in taken:
            skipped.append(d)
            continue
        taken.add(d)  # the same date twice in one request is created once
        fraction = (
            fraction_for_hours(body.leave_hours, d, schedule)
            if schedule is not None
            else body.fraction
        )
        session.add(
            WorkEntry(date=d, day_type=body.day_type.value, fraction=fraction, notes=body.notes)
        )
        created.append(d)
    if created:
        session.commit()
    return BatchResultOut(created=created, skipped=skipped)


@router.get("", response_model=list[EntryOut])
def list_entries(
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    session: Session = Depends(get_session),
) -> list[EntryOut]:
    stmt = select(WorkEntry).order_by(WorkEntry.date)
    if from_:
        stmt = stmt.where(WorkEntry.date >= from_)
    if to:
        stmt = stmt.where(WorkEntry.date <= to)
    schedule = get_daily_target_schedule(session)
    return [entry_to_out(e, schedule) for e in session.scalars(stmt)]


@router.get("/{entry_date}", response_model=EntryOut)
def get_entry(entry_date: date, session: Session = Depends(get_session)) -> EntryOut:
    entry = session.get(WorkEntry, entry_date)
    if not entry:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entry not found")
    return entry_to_out(entry, get_daily_target_schedule(session))


@router.put("/{entry_date}", response_model=EntryOut)
def update_entry(
    entry_date: date, body: EntryUpdate, session: Session = Depends(get_session)
) -> EntryOut:
    entry = session.get(WorkEntry, entry_date)
    if not entry:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entry not found")
    schedule = get_daily_target_schedule(session)
    body = resolve_entry_hours(body, entry_date, schedule)
    entry.day_type = body.day_type.value
    entry.fraction = body.fraction
    entry.start_time = body.start_time
    entry.end_time = body.end_time
    entry.notes = body.notes
    # Replace the break set atomically — cascade='all, delete-orphan' handles cleanup.
    entry.breaks = breaks_from_body(body.breaks)
    session.commit()
    session.refresh(entry)
    return entry_to_out(entry, schedule)


@router.delete("/{entry_date}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(entry_date: date, session: Session = Depends(get_session)) -> Response:
    entry = session.get(WorkEntry, entry_date)
    if not entry:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entry not found")
    session.delete(entry)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
