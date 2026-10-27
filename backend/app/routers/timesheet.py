"""The printable timesheet: a standalone, server-rendered page for Days → PDF.

No Alpine, no app chrome. The browser's "Save as PDF" is the PDF export — there is no
server-side PDF dependency. Every switch is a query parameter, so a URL *is* a report.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import TEMPLATES_DIR, TIMEZONE
from app.database import get_session
from app.models import WorkEntry
from app.services.settings import (
    get_daily_target_schedule,
    get_profile,
    get_work_week_days,
)
from app.services.timesheet import build_timesheet, fmt_days

router = APIRouter(tags=["timesheet"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["fmtdays"] = fmt_days

MAX_DAYS = 3 * 366  # a custom range longer than three years is a mistake, not a report
_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _local_today() -> date:
    return datetime.now(ZoneInfo(TIMEZONE)).date()


@router.get("/timesheet", response_class=HTMLResponse, include_in_schema=False)
def timesheet(
    request: Request,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    detail: Literal["compact", "full"] = "full",
    hours: Literal["dec", "hm"] = "dec",
    notes: bool = False,
    sign: bool = False,
    theme: Literal["light", "dark"] = "light",
    today: date | None = Query(None, description="Override 'today' for testing."),
    session: Session = Depends(get_session),
):
    today = today or _local_today()
    start = from_ or today.replace(day=1)
    end = to or today
    if end < start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "'to' must not be before 'from'")
    if (end - start).days + 1 > MAX_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"range too long (max {MAX_DAYS} days)"
        )

    schedule = get_daily_target_schedule(session)
    work_week = get_work_week_days(session)
    entries = session.scalars(
        select(WorkEntry).where(WorkEntry.date >= start, WorkEntry.date <= end)
    ).all()
    sheet = build_timesheet(
        entries,
        start=start,
        end=end,
        today=today,
        schedule=schedule,
        work_week_days=work_week,
        hours_style=hours,
    )

    # The target line: one value, or the values in force across the range.
    targets = sorted(
        {schedule.for_date(start + timedelta(days=i)) for i in range((end - start).days + 1)}
    )
    target_label = " / ".join(f"{t:g}h" for t in targets)
    work_week_label = ", ".join(_DOW[d] for d in sorted(work_week))
    if sorted(work_week) == [0, 1, 2, 3, 4]:
        work_week_label = "Mon–Fri"

    profile = get_profile(session)
    return templates.TemplateResponse(
        request,
        "timesheet.html",
        {
            "sheet": sheet,
            "detail": detail,
            "hours": hours,
            "show_notes": notes,
            "show_sign": sign,
            "theme": theme,
            "today": today,
            "target_label": target_label,
            "work_week_label": work_week_label,
            "profile": {k: v for k, v in profile.items() if v},
            "columns": 7 + (3 if detail == "full" else 0) + (1 if notes else 0),
        },
    )
