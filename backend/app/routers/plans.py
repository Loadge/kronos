"""Time-off planner: drafted leave days and the year-end projection.

A draft is a ``Plan`` row — vacation / holiday / flex on a date, optionally partial,
with a note. Drafts never touch the numbers until committed; the projection endpoint
shows what they *would* do to the balance at the end of the year. Committing copies a
draft into a real entry (same skip rule as batch logging: an existing entry wins).
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import DayType, Plan, WorkEntry
from app.routers.analytics import local_today
from app.schemas import (
    PlanBatchIn,
    PlanBatchResultOut,
    PlanCommitIn,
    PlanCommitOut,
    PlanOut,
    PlanUpdate,
    ProjectionOut,
)
from app.services.computations import (
    DailyTargetSchedule,
    project_balance,
    summarize,
)
from app.services.settings import (
    get_daily_target_schedule,
    get_effective_cumulative_start,
    get_vacation_budget_days,
    get_work_week_days,
)

router = APIRouter(prefix="/api/plans", tags=["plans"])


def _plan_out(plan: Plan, schedule: DailyTargetSchedule, exists: bool) -> PlanOut:
    return PlanOut(
        date=plan.date,
        day_type=plan.day_type,
        fraction=plan.fraction,
        leave_hours=round(schedule.for_date(plan.date) * plan.fraction, 4),
        notes=plan.notes,
        exists=exists,
    )


def _plans_between(session: Session, start: date, end: date) -> list[Plan]:
    return list(
        session.scalars(
            select(Plan).where(Plan.date >= start, Plan.date <= end).order_by(Plan.date)
        )
    )


def _entries_between(session: Session, start: date, end: date) -> list[WorkEntry]:
    return list(
        session.scalars(
            select(WorkEntry)
            .where(WorkEntry.date >= start, WorkEntry.date <= end)
            .order_by(WorkEntry.date)
        )
    )


_YearQ = Query(None, ge=2000, le=2100, description="Calendar year; defaults to today's.")


@router.get("", response_model=list[PlanOut])
def list_plans(
    year: int | None = _YearQ,
    session: Session = Depends(get_session),
) -> list[PlanOut]:
    """Drafts, oldest first — the whole table, or one calendar year."""
    stmt = select(Plan).order_by(Plan.date)
    if year is not None:
        stmt = stmt.where(Plan.date >= date(year, 1, 1), Plan.date <= date(year, 12, 31))
    schedule = get_daily_target_schedule(session)
    return [
        _plan_out(p, schedule, session.get(WorkEntry, p.date) is not None)
        for p in session.scalars(stmt)
    ]


@router.post("", response_model=PlanBatchResultOut)
def draft_plans(body: PlanBatchIn, session: Session = Depends(get_session)) -> PlanBatchResultOut:
    """Draft one leave type across dates. Re-drafts existing drafts; skips logged dates."""
    drafted: list[date] = []
    replaced: list[date] = []
    skipped: list[date] = []
    for d in body.dates:
        if session.get(WorkEntry, d):
            skipped.append(d)
            continue
        plan = session.get(Plan, d)
        if plan:
            plan.day_type = body.day_type.value
            plan.fraction = body.fraction
            plan.notes = body.notes
            replaced.append(d)
        else:
            session.add(
                Plan(date=d, day_type=body.day_type.value, fraction=body.fraction, notes=body.notes)
            )
            drafted.append(d)
    session.commit()
    return PlanBatchResultOut(drafted=drafted, replaced=replaced, skipped=skipped)


@router.put("/{plan_date}", response_model=PlanOut)
def update_plan(
    plan_date: date, body: PlanUpdate, session: Session = Depends(get_session)
) -> PlanOut:
    plan = session.get(Plan, plan_date)
    if not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "draft not found")
    if body.day_type is not None:
        plan.day_type = body.day_type.value
    if body.fraction is not None:
        plan.fraction = body.fraction
    if "notes" in body.model_fields_set:
        plan.notes = body.notes
    session.commit()
    return _plan_out(
        plan, get_daily_target_schedule(session), session.get(WorkEntry, plan_date) is not None
    )


@router.delete("/{plan_date}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_date: date, session: Session = Depends(get_session)) -> Response:
    plan = session.get(Plan, plan_date)
    if not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "draft not found")
    session.delete(plan)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/commit", response_model=PlanCommitOut)
def commit_plans(body: PlanCommitIn, session: Session = Depends(get_session)) -> PlanCommitOut:
    """Turn drafts into real entries.

    A date that already has an entry is skipped and its draft dropped (the entry is
    the truth); a date with no draft is reported as missing. Notes carry over.
    """
    created: list[date] = []
    skipped: list[date] = []
    missing: list[date] = []
    for d in body.dates:
        plan = session.get(Plan, d)
        if plan is None:
            missing.append(d)
            continue
        if session.get(WorkEntry, d):
            session.delete(plan)
            skipped.append(d)
            continue
        session.add(
            WorkEntry(date=d, day_type=plan.day_type, fraction=plan.fraction, notes=plan.notes)
        )
        session.delete(plan)
        created.append(d)
    session.commit()
    return PlanCommitOut(created=created, skipped=skipped, missing=missing)


@router.get("/projection", response_model=ProjectionOut)
def projection(
    year: int | None = _YearQ,
    today: date | None = Query(None, description="Override 'today' for testing."),
    session: Session = Depends(get_session),
) -> ProjectionOut:
    """The balance at Dec 31 of ``year`` on target and at pace, and the vacation budget
    after the drafts. Only days after today are projected; real entries on those days
    count as they are and beat any draft on the same date."""
    today = today or local_today()
    year = year or today.year
    horizon = date(year, 12, 31)
    schedule = get_daily_target_schedule(session)
    work_week = get_work_week_days(session)

    # Pace: the dashboard's cumulative (its start as of today). Balance: the same
    # summary, but from the start that applies at the horizon — with an annual reset
    # and a next-year horizon that is Jan 1 of that year, i.e. nothing yet.
    pace_start = get_effective_cumulative_start(session, today)
    pace_summary = summarize(_entries_between(session, pace_start, today), schedule)
    pace = (
        round(pace_summary.surplus_hours / pace_summary.work_days, 4)
        if pace_summary.work_days
        else 0.0
    )
    balance_start = get_effective_cumulative_start(session, horizon)
    if balance_start == pace_start:
        balance_today = pace_summary.surplus_hours
    else:
        balance_today = summarize(
            _entries_between(session, balance_start, today), schedule
        ).surplus_hours

    future_start = max(today + timedelta(days=1), balance_start)
    entries_by_date = {e.date: e for e in _entries_between(session, future_start, horizon)}
    drafts_by_date = {p.date: p for p in _plans_between(session, future_start, horizon)}
    pr = project_balance(
        balance_today=balance_today,
        pace_per_day=pace,
        start=future_start,
        end=horizon,
        work_week_days=work_week,
        entries_by_date=entries_by_date,
        drafts_by_date=drafts_by_date,
        schedule=schedule,
    )

    # Vacation budget for the year: real entries (past and logged ahead) plus drafts
    # that still stand (no real entry on their date).
    y0, y1 = date(year, 1, 1), horizon
    year_entries = _entries_between(session, y0, y1)
    year_plans = _plans_between(session, y0, y1)
    logged_dates = {e.date for e in year_entries}
    used = sum(e.fraction for e in year_entries if e.day_type == DayType.VACATION)
    drafted_vac = sum(
        p.fraction
        for p in year_plans
        if p.day_type == DayType.VACATION and p.date not in logged_dates
    )
    budget = get_vacation_budget_days(session)

    return ProjectionOut(
        year=year,
        today=today,
        horizon=horizon,
        balance_today=round(balance_today, 2),
        pace_per_day=pace,
        on_target=pr.on_target,
        at_pace=pr.at_pace,
        scheduled_days_left=pr.scheduled_days_left,
        open_days_left=pr.open_days_left,
        drafted_days=pr.drafted_days,
        drafted_flex_hours=pr.drafted_flex_hours,
        vacation_budget_days=budget,
        vacation_used_days=round(used, 2),
        vacation_drafted_days=round(drafted_vac, 2),
        vacation_remaining_after_plan=round(budget - used - drafted_vac, 2),
    )
