"""Backup and restore — full data portability.

GET  /api/backup   → download a self-contained JSON snapshot
POST /api/restore  → wipe current entries and reimport from snapshot

The backup format is intentionally simple (version 1):
{
  "version": 1,
  "exported_at": "<ISO-8601 UTC>",
  "settings": { "daily_target_hours": 8.0, "cumulative_start_date": "2025-01-01" },
  "entries": [
    { "date": "2025-03-10", "day_type": "work",
      "start_time": "09:00", "end_time": "17:30",
      "notes": null, "breaks": [{"break_minutes": 60}] },
    ...
  ]
}
"""

from __future__ import annotations

import json
from datetime import date as date_
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Break, WorkEntry  # Break imported for explicit pre-delete
from app.schemas import ConfigOut, RestoreIn
from app.services.settings import (
    get_cumulative_start_date,
    get_daily_target_hours,
    set_cumulative_start_date,
    set_daily_target_hours,
)

router = APIRouter(prefix="/api", tags=["backup"])


@router.get("/backup")
def download_backup(session: Session = Depends(get_session)) -> Response:
    """Return a self-contained JSON snapshot as a file download."""
    settings = ConfigOut(
        daily_target_hours=get_daily_target_hours(session),
        cumulative_start_date=get_cumulative_start_date(session),
    )

    rows = session.scalars(select(WorkEntry).order_by(WorkEntry.date)).all()
    entries = [
        {
            "date": e.date.isoformat(),
            "day_type": e.day_type,
            "start_time": e.start_time,
            "end_time": e.end_time,
            "notes": e.notes,
            "breaks": [{"break_minutes": b.break_minutes} for b in e.breaks],
        }
        for e in rows
    ]

    payload = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "settings": settings.model_dump(mode="json"),
        "entries": entries,
    }

    filename = f"kronos_backup_{date_.today().isoformat()}.json"
    return Response(
        content=json.dumps(payload, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/restore", status_code=200)
def restore_backup(
    payload: RestoreIn,
    session: Session = Depends(get_session),
) -> dict[str, int]:
    """Wipe the current entry set and reimport from a backup payload.

    Settings are also restored when ``payload.settings`` is present.
    Entries are validated by the same rules as the normal create endpoint
    (Pydantic raises 422 before we touch the DB if anything is invalid).
    """
    if payload.version != 1:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unsupported backup version {payload.version!r}; only version 1 is supported",
        )

    # Delete breaks first, then entries.  We do this explicitly rather than
    # relying on the FK ondelete=CASCADE so the operation is correct even in
    # environments where PRAGMA foreign_keys is not set (e.g. the test engine).
    session.execute(delete(Break))
    session.execute(delete(WorkEntry))
    session.flush()

    for entry_in in payload.entries:
        entry = WorkEntry(
            date=entry_in.date,
            day_type=entry_in.day_type.value,
            start_time=entry_in.start_time,
            end_time=entry_in.end_time,
            notes=entry_in.notes,
        )
        entry.breaks = [Break(break_minutes=b.break_minutes) for b in entry_in.breaks]
        session.add(entry)

    if payload.settings:
        set_daily_target_hours(session, payload.settings.daily_target_hours)
        set_cumulative_start_date(session, payload.settings.cumulative_start_date)

    session.commit()
    return {"restored_entries": len(payload.entries)}
