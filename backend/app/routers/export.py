"""CSV + JSON export of all entries."""

from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import WorkEntry
from app.schemas import EntryOut
from app.services.computations import daily_net_hours, daily_target_for
from app.services.settings import get_daily_target_hours
from app.services.views import entry_to_out

router = APIRouter(prefix="/api", tags=["export"])

CSV_COLUMNS = [
    "date",
    "day_type",
    "start_time",
    "end_time",
    "total_break_minutes",
    "net_hours",
    "target_hours",
    "surplus_hours",
    "notes",
]


@router.get("/export.csv")
def export_csv(session: Session = Depends(get_session)) -> Response:
    daily_target = get_daily_target_hours(session)
    entries = list(session.scalars(select(WorkEntry).order_by(WorkEntry.date)))

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for e in entries:
        net = daily_net_hours(e)
        target = daily_target_for(e, daily_target)
        writer.writerow(
            [
                e.date.isoformat(),
                e.day_type,
                e.start_time or "",
                e.end_time or "",
                e.total_break_minutes,
                f"{net:.2f}",
                f"{target:.2f}",
                f"{net - target:.2f}",
                (e.notes or "").replace("\n", " "),
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="kronos_export.csv"'},
    )


@router.get("/export.json", response_model=list[EntryOut])
def export_json(session: Session = Depends(get_session)) -> list[EntryOut]:
    daily_target = get_daily_target_hours(session)
    entries = list(session.scalars(select(WorkEntry).order_by(WorkEntry.date)))
    return [entry_to_out(e, daily_target) for e in entries]
