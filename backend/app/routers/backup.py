"""Backup and restore — full data portability.

GET  /api/backup   → download a self-contained JSON snapshot
POST /api/restore  → wipe current entries and reimport from snapshot

The backup format is intentionally simple (version 2):
{
  "version": 2,
  "exported_at": "<ISO-8601 UTC>",
  "settings": { "daily_target_hours": 8.0, "cumulative_start_date": "2025-01-01" },
  "entries": [
    { "date": "2025-03-10", "day_type": "work", "fraction": 1.0,
      "start_time": "09:00", "end_time": "17:30",
      "notes": null, "breaks": [{"break_minutes": 60, "start_time": null, "end_time": null}] },
    ...
  ],
  "plans": [
    { "date": "2025-12-24", "day_type": "vacation", "fraction": 1.0, "notes": "Christmas" },
    ...
  ]
}

Version 2 adds ``fraction`` to every entry — partial leave days also carry
the hours worked. Version 1 files still restore (no fraction → whole day); an older
Kronos refuses a version 2 file rather than silently turning partial days into whole
ones.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from datetime import date as date_

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Break, Plan, WorkEntry  # Break imported for explicit pre-delete
from app.schemas import (
    BACKUP_VERSION,
    SUPPORTED_BACKUP_VERSIONS,
    ConfigOut,
    DailyTargetRow,
    RestoreIn,
)
from app.services.computations import DailyTargetSchedule
from app.services.settings import (
    PROFILE_EMPLOYER,
    PROFILE_EXTRA,
    PROFILE_NAME,
    get_cumulative_start_date,
    get_daily_target_hours,
    get_daily_target_schedule,
    get_profile,
    set_cumulative_start_date,
    set_daily_target_hours,
    set_daily_target_schedule,
    set_profile_field,
)

router = APIRouter(prefix="/api", tags=["backup"])


@router.get("/backup")
def download_backup(session: Session = Depends(get_session)) -> Response:
    """Return a self-contained JSON snapshot as a file download."""
    settings = ConfigOut(
        daily_target_hours=get_daily_target_hours(session),
        daily_target_schedule=[
            DailyTargetRow(effective_from=eff, hours=hours)
            for eff, hours in get_daily_target_schedule(session).rows
        ],
        cumulative_start_date=get_cumulative_start_date(session),
        **get_profile(session),
    )

    rows = session.scalars(select(WorkEntry).order_by(WorkEntry.date)).all()
    entries = [
        {
            "date": e.date.isoformat(),
            "day_type": e.day_type,
            "fraction": e.fraction,
            "start_time": e.start_time,
            "end_time": e.end_time,
            "notes": e.notes,
            # A break keeps its time range when it was entered as one (older files only
            # have the minutes; they restore as untimed breaks).
            "breaks": [
                {
                    "break_minutes": b.break_minutes,
                    "start_time": b.start_time,
                    "end_time": b.end_time,
                }
                for b in e.breaks
            ],
        }
        for e in rows
    ]

    plans = [
        {
            "date": p.date.isoformat(),
            "day_type": p.day_type,
            "fraction": p.fraction,
            "notes": p.notes,
        }
        for p in session.scalars(select(Plan).order_by(Plan.date))
    ]

    payload = {
        "version": BACKUP_VERSION,
        "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "settings": settings.model_dump(mode="json"),
        "entries": entries,
        "plans": plans,
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
    if payload.version not in SUPPORTED_BACKUP_VERSIONS:
        supported = ", ".join(str(v) for v in SUPPORTED_BACKUP_VERSIONS)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"unsupported backup version {payload.version!r}; supported: {supported}",
        )

    # Delete breaks first, then entries.  We do this explicitly rather than
    # relying on the FK ondelete=CASCADE so the operation is correct even in
    # environments where PRAGMA foreign_keys is not set (e.g. the test engine).
    session.execute(delete(Break))
    session.execute(delete(WorkEntry))
    session.execute(delete(Plan))
    session.flush()

    for entry_in in payload.entries:
        entry = WorkEntry(
            date=entry_in.date,
            day_type=entry_in.day_type.value,
            fraction=entry_in.fraction,
            start_time=entry_in.start_time,
            end_time=entry_in.end_time,
            notes=entry_in.notes,
        )
        entry.breaks = [
            Break(break_minutes=b.break_minutes, start_time=b.start_time, end_time=b.end_time)
            for b in entry_in.breaks
        ]
        session.add(entry)

    for plan_in in payload.plans:
        session.add(
            Plan(
                date=plan_in.date,
                day_type=plan_in.day_type.value,
                fraction=plan_in.fraction,
                notes=plan_in.notes,
            )
        )

    if payload.settings:
        set_cumulative_start_date(session, payload.settings.cumulative_start_date)
        # Prefer the full date-effective timeline; older backups without one fall back
        # to the single value (restored non-destructively via set_daily_target_hours).
        if payload.settings.daily_target_schedule:
            set_daily_target_schedule(
                session,
                DailyTargetSchedule.from_rows(
                    [(r.effective_from, r.hours) for r in payload.settings.daily_target_schedule]
                ),
            )
        else:
            set_daily_target_hours(session, payload.settings.daily_target_hours)
        # Profile lines ride in the settings too; older files simply have none.
        set_profile_field(session, PROFILE_NAME, payload.settings.profile_name)
        set_profile_field(session, PROFILE_EMPLOYER, payload.settings.profile_employer)
        set_profile_field(session, PROFILE_EXTRA, payload.settings.profile_extra)

    session.commit()
    return {"restored_entries": len(payload.entries)}
