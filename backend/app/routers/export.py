"""CSV + JSON export of all entries, plus CSV import."""

from __future__ import annotations

import csv
import io
from datetime import date as date_

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Break, WorkEntry
from app.schemas import CsvImportIn, EntryIn, EntryOut, ImportResultOut
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


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    loc = ".".join(str(x) for x in err.get("loc", ()) if x != "body")
    msg = err.get("msg", "invalid value")
    return f"{loc}: {msg}" if loc else msg


def _row_to_entry_in(row: dict[str, str | None]) -> EntryIn:
    """Turn one CSV row into a validated EntryIn.

    Mirrors the export format (CSV_COLUMNS). The derived columns
    (net/target/surplus) are ignored — they are recomputed on read. A work day's
    individual breaks aren't stored in the CSV, so ``total_break_minutes`` is
    reconstructed as a single break.
    """
    date_str = (row.get("date") or "").strip()
    if not date_str:
        raise ValueError("missing date")
    day_type = (row.get("day_type") or "").strip().lower()
    notes = (row.get("notes") or "").strip() or None

    data: dict = {"date": date_str, "day_type": day_type, "notes": notes}
    if day_type == "work":
        data["start_time"] = (row.get("start_time") or "").strip() or None
        data["end_time"] = (row.get("end_time") or "").strip() or None
        brk = (row.get("total_break_minutes") or "").strip()
        if brk:
            try:
                minutes = int(float(brk))
            except ValueError:
                raise ValueError(f"invalid total_break_minutes {brk!r}") from None
            if minutes > 0:
                data["breaks"] = [{"break_minutes": minutes}]
    return EntryIn(**data)


@router.post("/import/csv", response_model=ImportResultOut)
def import_csv(payload: CsvImportIn, session: Session = Depends(get_session)) -> ImportResultOut:
    """Import entries from a Kronos CSV export.

    Adds rows to the existing data — nothing is wiped. Dates that already exist
    (or repeat within the file) are skipped, matching the batch endpoint's rule.
    Invalid rows are collected in ``errors`` and don't abort the import.
    """
    reader = csv.DictReader(io.StringIO(payload.content))
    fields = reader.fieldnames
    if not fields or "date" not in fields or "day_type" not in fields:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "CSV must have at least 'date' and 'day_type' columns",
        )

    imported: list[date_] = []
    skipped: list[date_] = []
    errors: list[str] = []
    seen: set[date_] = set()

    # Header is line 1; first data row is line 2.
    for i, row in enumerate(reader, start=2):
        if not any((v or "").strip() for v in row.values()):
            continue  # skip fully blank rows
        try:
            entry_in = _row_to_entry_in(row)
        except ValidationError as exc:
            errors.append(f"row {i}: {_first_error(exc)}")
            continue
        except ValueError as exc:
            errors.append(f"row {i}: {exc}")
            continue

        d = entry_in.date
        if d in seen or session.get(WorkEntry, d):
            skipped.append(d)
            continue
        seen.add(d)

        entry = WorkEntry(
            date=d,
            day_type=entry_in.day_type.value,
            start_time=entry_in.start_time,
            end_time=entry_in.end_time,
            notes=entry_in.notes,
        )
        entry.breaks = [Break(break_minutes=b.break_minutes) for b in entry_in.breaks]
        session.add(entry)
        imported.append(d)

    if imported:
        session.commit()
    return ImportResultOut(imported=imported, skipped=skipped, errors=errors)
