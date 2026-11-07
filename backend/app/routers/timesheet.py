"""The printable timesheet: a standalone, server-rendered page for Days → PDF.

No Alpine, no app chrome. The browser's "Save as PDF" is the PDF export — there is no
server-side PDF dependency. Every switch is a query parameter, so a URL *is* a report.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from sqlalchemy import false, select
from sqlalchemy.orm import Session

from app.config import TEMPLATES_DIR
from app.database import get_session
from app.models import FreelanceBlock, FreelancePayout, IncomeSource, WorkEntry
from app.services import numbers
from app.services.clock import local_today
from app.services.freelance import money_lines
from app.services.settings import (
    get_daily_target_schedule,
    get_number_format,
    get_profile,
    get_work_week_days,
)
from app.services.timesheet import (
    build_freelance_timesheet,
    build_timesheet,
    fmt_days,
    fmt_money,
)

router = APIRouter(tags=["timesheet"])
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["fmtdays"] = fmt_days
templates.env.filters["money"] = fmt_money


@pass_context
def _fmtdec(_ctx, x: float) -> str:
    """A number with two decimals in the sheet's format. It takes the context only so that Jinja
    does not fold `{{ 7.5|fmtdec }}` into a constant when it compiles the template, once, for
    the first format."""
    return numbers.format_number(x, 2, grouping=False)


templates.env.filters["fmtdec"] = _fmtdec

MAX_DAYS = 3 * 366  # a custom range longer than three years is a mistake, not a report
_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


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
    today = today or local_today()
    start = from_ or today.replace(day=1)
    end = to or today
    if end < start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "'to' must not be before 'from'")
    if (end - start).days + 1 > MAX_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"range too long (max {MAX_DAYS} days)"
        )

    numbers.activate(get_number_format(session))
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
    target_label = " / ".join(numbers.localize(f"{t:g}h") for t in targets)
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


def _period(from_: date | None, to: date | None, today: date) -> tuple[date, date]:
    start = from_ or today.replace(day=1)
    end = to or today
    if end < start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "'to' must not be before 'from'")
    if (end - start).days + 1 > MAX_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"range too long (max {MAX_DAYS} days)"
        )
    return start, end


@router.get("/timesheet/freelance", response_class=HTMLResponse, include_in_schema=False)
def freelance_timesheet(
    request: Request,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    sources: str | None = Query(
        None, description="Comma-separated source ids to include; every source when absent."
    ),
    hours: Literal["dec", "hm"] = "dec",
    notes: bool = False,
    sign: bool = False,
    theme: Literal["light", "dark"] = "light",
    today: date | None = Query(None, description="Override 'today' for testing."),
    session: Session = Depends(get_session),
):
    """The freelance side of Days → PDF: the blocks of a range, by month, for the sources
    ticked in the toolbar. Same page conventions as /timesheet: a GET form, the browser's
    print as the PDF, nothing on the employee's sheet touched."""
    today = today or local_today()
    numbers.activate(get_number_format(session))
    start, end = _period(from_, to, today)
    all_sources = list(session.scalars(select(IncomeSource).order_by(IncomeSource.id)))
    if sources is None:
        wanted = {s.id for s in all_sources}
    else:
        try:
            wanted = {int(x) for x in sources.split(",") if x.strip()}
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "sources must be ids separated by commas"
            ) from exc
    blocks = session.scalars(
        select(FreelanceBlock).where(
            FreelanceBlock.date >= start,
            FreelanceBlock.date <= end,
            FreelanceBlock.source_id.in_(wanted) if wanted else false(),
        )
    ).all()
    lines = [ln for ln in money_lines(session, start, end) if ln.source_id in wanted]
    payout_ids = {ln.payout_id for ln in lines if ln.payout_id is not None}
    sheet = build_freelance_timesheet(
        blocks,
        start=start,
        end=end,
        sources=[s.name for s in all_sources if s.id in wanted],
        work_week_days=get_work_week_days(session),
        hours_style=hours,
        lines=lines,
        payouts=session.scalars(
            select(FreelancePayout).where(FreelancePayout.id.in_(payout_ids))
        ).all(),
    )
    profile = get_profile(session)
    return templates.TemplateResponse(
        request,
        "timesheet_freelance.html",
        {
            "sheet": sheet,
            "all_sources": all_sources,
            "wanted": wanted,
            "hours": hours,
            "show_notes": notes,
            "show_sign": sign,
            "theme": theme,
            "today": today,
            "profile": {k: v for k, v in profile.items() if v},
            "columns": 9 + (1 if notes else 0),
        },
    )
