"""Destructive / administrative operations.

Kept separate from config.py so the danger-zone endpoints are never
accidentally included by a partial router include.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import DayType, WorkEntry

router = APIRouter(tags=["admin"])


@router.delete("/api/data", status_code=200)
def wipe_all_data(session: Session = Depends(get_session)) -> dict[str, int]:
    """Delete every work-entry row (breaks cascade).  Settings are preserved.

    The frontend requires the user to type a confirmation phrase before
    calling this endpoint.  The endpoint itself has no soft-delete or
    dry-run mode — it is immediate and irreversible.
    """
    result = session.execute(delete(WorkEntry))
    session.commit()
    return {"deleted_entries": result.rowcount}


@router.post("/api/data/seed", status_code=200)
def seed_data(session: Session = Depends(get_session)) -> dict[str, int]:
    """Wipe all entries and repopulate with ~3 months of realistic sample data.

    Delegates to seed.build_entries() so the generated dataset is identical
    to what `python backend/seed.py` produces from the CLI.  Settings are
    preserved.  The endpoint is idempotent — calling it twice yields the same
    result.
    """
    # Import here to avoid a circular dependency at module load time; seed.py
    # lives in backend/ (same PYTHONPATH root as app/) rather than in app/.
    from seed import build_entries  # noqa: PLC0415

    # Wipe first so re-seeding doesn't hit duplicate-PK errors.
    session.execute(delete(WorkEntry))
    session.flush()

    today = date.today()
    entries = build_entries(today=today)
    session.add_all(entries)
    session.commit()

    return {
        "seeded":   len(entries),
        "work":     sum(1 for e in entries if e.day_type == DayType.WORK.value),
        "vacation": sum(1 for e in entries if e.day_type == DayType.VACATION.value),
        "sick":     sum(1 for e in entries if e.day_type == DayType.SICK.value),
        "holiday":  sum(1 for e in entries if e.day_type == DayType.HOLIDAY.value),
    }
