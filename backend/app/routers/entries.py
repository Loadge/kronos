"""CRUD for work_entries + their breaks. Breaks are always managed through the parent."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Break, WorkEntry
from app.schemas import EntryIn, EntryOut, EntryUpdate
from app.services.settings import get_daily_target_hours
from app.services.views import entry_to_out

router = APIRouter(prefix="/api/entries", tags=["entries"])


@router.post("", response_model=EntryOut, status_code=status.HTTP_201_CREATED)
def create_entry(body: EntryIn, session: Session = Depends(get_session)) -> EntryOut:
    if session.get(WorkEntry, body.date):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"entry for {body.date.isoformat()} already exists",
        )
    entry = WorkEntry(
        date=body.date,
        day_type=body.day_type.value,
        start_time=body.start_time,
        end_time=body.end_time,
        notes=body.notes,
    )
    entry.breaks = [Break(break_minutes=b.break_minutes, start_time=b.start_time, end_time=b.end_time) for b in body.breaks]
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry_to_out(entry, get_daily_target_hours(session))


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
    daily_target = get_daily_target_hours(session)
    return [entry_to_out(e, daily_target) for e in session.scalars(stmt)]


@router.get("/{entry_date}", response_model=EntryOut)
def get_entry(entry_date: date, session: Session = Depends(get_session)) -> EntryOut:
    entry = session.get(WorkEntry, entry_date)
    if not entry:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entry not found")
    return entry_to_out(entry, get_daily_target_hours(session))


@router.put("/{entry_date}", response_model=EntryOut)
def update_entry(
    entry_date: date, body: EntryUpdate, session: Session = Depends(get_session)
) -> EntryOut:
    entry = session.get(WorkEntry, entry_date)
    if not entry:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entry not found")
    entry.day_type = body.day_type.value
    entry.start_time = body.start_time
    entry.end_time = body.end_time
    entry.notes = body.notes
    # Replace the break set atomically — cascade='all, delete-orphan' handles cleanup.
    entry.breaks = [Break(break_minutes=b.break_minutes, start_time=b.start_time, end_time=b.end_time) for b in body.breaks]
    session.commit()
    session.refresh(entry)
    return entry_to_out(entry, get_daily_target_hours(session))


@router.delete("/{entry_date}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(entry_date: date, session: Session = Depends(get_session)) -> Response:
    entry = session.get(WorkEntry, entry_date)
    if not entry:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entry not found")
    session.delete(entry)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
