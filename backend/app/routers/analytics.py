"""Dashboard + analytical views: weekly/monthly/cumulative summaries, records, monthly breakdown."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import TIMEZONE
from app.database import get_session
from app.models import DayType, WorkEntry
from app.schemas import (
    DashboardOut,
    MonthlyBreakdownRow,
    PeriodSummaryOut,
    RecordEntry,
    RecordMonth,
    RecordsOut,
)
from app.services.computations import (
    PeriodSummary,
    daily_net_hours,
    iso_week_bounds,
    month_bounds,
    summarize,
)
from app.services.settings import get_cumulative_start_date, get_daily_target_hours

router = APIRouter(tags=["analytics"])


def local_today() -> date:
    return datetime.now(ZoneInfo(TIMEZONE)).date()


def _entries_between(session: Session, start: date, end: date) -> list[WorkEntry]:
    return list(
        session.scalars(
            select(WorkEntry)
            .where(WorkEntry.date >= start, WorkEntry.date <= end)
            .order_by(WorkEntry.date)
        )
    )


def _period_out(s: PeriodSummary) -> PeriodSummaryOut:
    return PeriodSummaryOut(
        net_hours=s.net_hours,
        target_hours=s.target_hours,
        work_days=s.work_days,
        non_work_days=s.non_work_days,
        surplus_hours=s.surplus_hours,
    )


@router.get("/api/dashboard", response_model=DashboardOut)
def dashboard(
    today: date | None = Query(
        None,
        description="Override 'today' for testing/point-in-time views.",
    ),
    session: Session = Depends(get_session),
) -> DashboardOut:
    today = today or local_today()
    daily_target = get_daily_target_hours(session)
    cum_start = get_cumulative_start_date(session)

    week_start, week_end = iso_week_bounds(today)
    month_start, month_end = month_bounds(today)

    return DashboardOut(
        today=today,
        week=_period_out(
            summarize(_entries_between(session, week_start, week_end), daily_target)
        ),
        month=_period_out(
            summarize(_entries_between(session, month_start, month_end), daily_target)
        ),
        cumulative=_period_out(
            summarize(_entries_between(session, cum_start, today), daily_target)
        ),
        cumulative_start_date=cum_start,
        daily_target_hours=daily_target,
    )


@router.get("/api/analytics/cumulative", response_model=PeriodSummaryOut)
def cumulative_as_of(
    as_of: date = Query(..., description="Show cumulative surplus/deficit up to this date."),
    session: Session = Depends(get_session),
) -> PeriodSummaryOut:
    daily_target = get_daily_target_hours(session)
    start = get_cumulative_start_date(session)
    entries = _entries_between(session, start, as_of)
    return _period_out(summarize(entries, daily_target))


@router.get("/api/analytics/monthly", response_model=list[MonthlyBreakdownRow])
def monthly_breakdown(session: Session = Depends(get_session)) -> list[MonthlyBreakdownRow]:
    """Return one row per (year, month) that has any entries, oldest first."""
    daily_target = get_daily_target_hours(session)
    entries = list(session.scalars(select(WorkEntry).order_by(WorkEntry.date)))

    grouped: dict[tuple[int, int], list[WorkEntry]] = defaultdict(list)
    for e in entries:
        grouped[(e.date.year, e.date.month)].append(e)

    rows: list[MonthlyBreakdownRow] = []
    for (y, m) in sorted(grouped):
        s = summarize(grouped[(y, m)], daily_target)
        rows.append(
            MonthlyBreakdownRow(
                year=y,
                month=m,
                label=f"{y:04d}-{m:02d}",
                net_hours=s.net_hours,
                target_hours=s.target_hours,
                surplus_hours=s.surplus_hours,
                work_days=s.work_days,
                non_work_days=s.non_work_days,
            )
        )
    return rows


@router.get("/api/analytics/records", response_model=RecordsOut)
def records(session: Session = Depends(get_session)) -> RecordsOut:
    daily_target = get_daily_target_hours(session)
    entries = list(session.scalars(select(WorkEntry).order_by(WorkEntry.date)))
    work_entries = [e for e in entries if e.day_type == DayType.WORK]

    longest_day = max(work_entries, key=daily_net_hours, default=None)
    shortest_day = min(work_entries, key=daily_net_hours, default=None)

    grouped: dict[tuple[int, int], list[WorkEntry]] = defaultdict(list)
    for e in entries:
        grouped[(e.date.year, e.date.month)].append(e)
    month_summaries = {
        key: summarize(es, daily_target) for key, es in grouped.items()
    }

    longest_month = (
        max(month_summaries.items(), key=lambda kv: kv[1].net_hours, default=None)
        if month_summaries
        else None
    )
    most_surplus = (
        max(month_summaries.items(), key=lambda kv: kv[1].surplus_hours, default=None)
        if month_summaries
        else None
    )
    most_deficit = (
        min(month_summaries.items(), key=lambda kv: kv[1].surplus_hours, default=None)
        if month_summaries
        else None
    )

    def _erec(e: WorkEntry | None) -> RecordEntry | None:
        if e is None:
            return None
        return RecordEntry(date=e.date, net_hours=daily_net_hours(e))

    def _mrec(item: tuple[tuple[int, int], PeriodSummary] | None) -> RecordMonth | None:
        if item is None:
            return None
        (y, m), s = item
        return RecordMonth(
            year=y,
            month=m,
            label=f"{y:04d}-{m:02d}",
            net_hours=s.net_hours,
            surplus_hours=s.surplus_hours,
        )

    return RecordsOut(
        longest_work_day=_erec(longest_day),
        shortest_work_day=_erec(shortest_day),
        longest_month=_mrec(longest_month),
        most_surplus_month=_mrec(most_surplus),
        most_deficit_month=_mrec(most_deficit),
    )
