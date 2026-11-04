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
from app.models import DayType, FreelanceBlock, FreelancePayout, Plan, WorkEntry

router = APIRouter(tags=["admin"])


@router.delete("/api/data", status_code=200)
def wipe_all_data(session: Session = Depends(get_session)) -> dict[str, int]:
    """Delete every work-entry row (breaks cascade), every planner draft and every
    freelance block and payout. Settings — the income sources and the tax years among them — are
    preserved.

    The frontend requires the user to type a confirmation phrase before
    calling this endpoint.  The endpoint itself has no soft-delete or
    dry-run mode — it is immediate and irreversible.
    """
    result = session.execute(delete(WorkEntry))
    plans = session.execute(delete(Plan))
    blocks = session.execute(delete(FreelanceBlock))
    session.execute(delete(FreelancePayout))
    session.commit()
    return {
        "deleted_entries": result.rowcount,
        "deleted_plans": plans.rowcount,
        "deleted_blocks": blocks.rowcount,
    }


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
    from seed import build_entries, build_freelance, build_plans  # noqa: PLC0415

    # Wipe first so re-seeding doesn't hit duplicate-PK errors.
    session.execute(delete(WorkEntry))
    session.execute(delete(Plan))
    session.execute(delete(FreelancePayout))
    session.execute(delete(FreelanceBlock))
    session.flush()

    today = date.today()
    entries = build_entries(today=today)
    plans = build_plans(today=today)
    session.add_all(entries)
    session.add_all(plans)
    blocks = build_freelance(session, today=today)
    session.commit()

    return {
        "seeded": len(entries),
        "plans": len(plans),
        "freelance_blocks": len(blocks),
        "work": sum(1 for e in entries if e.day_type == DayType.WORK.value),
        "vacation": sum(1 for e in entries if e.day_type == DayType.VACATION.value),
        "sick": sum(1 for e in entries if e.day_type == DayType.SICK.value),
        "holiday": sum(1 for e in entries if e.day_type == DayType.HOLIDAY.value),
    }
