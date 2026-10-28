"""Dashboard + analytical views: weekly/monthly/cumulative summaries, records, monthly breakdown."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import TIMEZONE
from app.database import get_session
from app.models import DayType, Plan, WorkEntry
from app.schemas import (
    CumulativePointOut,
    CumulativeSeriesOut,
    DashboardOut,
    MonthlyBreakdownRow,
    PeriodSummaryOut,
    RecordEntry,
    RecordMonth,
    RecordsOut,
    RecordYear,
    StreaksOut,
    YearlyBreakdownRow,
    YoYOut,
    YoYPeriod,
)
from app.services.computations import (
    PeriodSummary,
    daily_net_hours,
    daily_target_for,
    iso_week_bounds,
    month_bounds,
    summarize,
)
from app.services.settings import (
    get_cumulative_start_date,
    get_daily_target_schedule,
    get_effective_cumulative_start,
    get_reset_annually,
    get_vacation_budget_days,
    get_work_week_days,
)

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
    schedule = get_daily_target_schedule(session)

    week_start, week_end = iso_week_bounds(today)
    month_start, month_end = month_bounds(today)

    cum_start = get_effective_cumulative_start(session, today)

    # Vacation used this year, in days: partial days count their fraction.
    year_start = date(today.year, 1, 1)
    vacation_days_used = round(
        session.scalar(
            select(func.coalesce(func.sum(WorkEntry.fraction), 0.0)).where(
                WorkEntry.date >= year_start,
                WorkEntry.date <= today,
                WorkEntry.day_type == DayType.VACATION,
            )
        )
        or 0.0,
        2,
    )

    # Drafted time off after today, this year, on dates still free: the forecast uses
    # it instead of assuming the whole remaining vacation budget will be taken.
    year_end = date(today.year, 12, 31)
    planned_days = 0.0
    planned_flex_hours = 0.0
    for plan in session.scalars(select(Plan).where(Plan.date > today, Plan.date <= year_end)):
        if session.get(WorkEntry, plan.date):
            continue
        planned_days += plan.fraction
        if plan.day_type == DayType.FLEX:
            planned_flex_hours += schedule.for_date(plan.date) * plan.fraction

    return DashboardOut(
        today=today,
        week=_period_out(summarize(_entries_between(session, week_start, week_end), schedule)),
        month=_period_out(summarize(_entries_between(session, month_start, month_end), schedule)),
        cumulative=_period_out(summarize(_entries_between(session, cum_start, today), schedule)),
        cumulative_start_date=cum_start,
        daily_target_hours=schedule.for_date(today),
        work_week_days=get_work_week_days(session),
        vacation_budget_days=get_vacation_budget_days(session),
        vacation_days_used=vacation_days_used,
        planned_days_remaining=round(planned_days, 2),
        planned_flex_hours=round(planned_flex_hours, 2),
    )


@router.get("/api/streaks", response_model=StreaksOut)
def streaks(
    today: date | None = Query(
        None,
        description="Override 'today' for testing/point-in-time views.",
    ),
    session: Session = Depends(get_session),
) -> StreaksOut:
    today = today or local_today()
    schedule = get_daily_target_schedule(session)

    entries = list(
        session.scalars(
            select(WorkEntry).where(WorkEntry.date <= today).order_by(WorkEntry.date.desc())
        )
    )
    logged_dates = {e.date for e in entries}

    # Logging streak: consecutive calendar days with any entry, ending at today —
    # or yesterday if today isn't logged yet, so the streak doesn't drop to 0 mid-day.
    anchor = today if today in logged_dates else today - timedelta(days=1)
    logging_streak = 0
    d = anchor
    while d in logged_dates:
        logging_streak += 1
        d -= timedelta(days=1)

    # On-target streak: most recent work days, consecutive, each with surplus >= 0.
    # Each day is compared against the target in effect on its own date.
    on_target_streak = 0
    for e in entries:
        if e.day_type != DayType.WORK:
            continue
        surplus = daily_net_hours(e) - daily_target_for(e, schedule)
        if surplus >= -0.01:
            on_target_streak += 1
        else:
            break

    return StreaksOut(
        logging_streak=logging_streak,
        on_target_streak=on_target_streak,
        total_logged_days=len(entries),
    )


@router.get("/api/analytics/cumulative", response_model=PeriodSummaryOut)
def cumulative_as_of(
    as_of: date = Query(..., description="Show cumulative surplus/deficit up to this date."),
    session: Session = Depends(get_session),
) -> PeriodSummaryOut:
    schedule = get_daily_target_schedule(session)
    start = get_effective_cumulative_start(session, as_of)
    entries = _entries_between(session, start, as_of)
    return _period_out(summarize(entries, schedule))


@router.get("/api/analytics/cumulative-series", response_model=CumulativeSeriesOut)
def cumulative_series(
    year: int | None = Query(None, description="Calendar year; defaults to the current one."),
    all: bool = Query(False, description="The whole history from the cumulative start instead."),
    session: Session = Depends(get_session),
) -> CumulativeSeriesOut:
    """Running balance after each logged day of `year`, from the effective cumulative start.

    Each point equals `GET /api/analytics/cumulative?as_of=<date>` for that date, so the
    last point of the year matches the Dashboard's cumulative card; entries before Jan 1
    fold into `opening`. One call instead of one per day — the trajectory chart's data.
    With `all=true` the series runs from the cumulative start to the last entry, restarting
    at zero each January 1st when the cumulative resets annually (the Analytics chart).
    """
    if all:
        return _whole_history(session)
    year = year or local_today().year
    jan1, dec31 = date(year, 1, 1), date(year, 12, 31)
    start = get_effective_cumulative_start(session, dec31)
    schedule = get_daily_target_schedule(session)
    entries = _entries_between(session, start, dec31)

    before = [e for e in entries if e.date < jan1]
    opening = summarize(before, schedule).surplus_hours if before else 0.0

    running = opening
    points: list[CumulativePointOut] = []
    for e in entries:
        if e.date < jan1:
            continue
        # Summed unrounded, rounded per point: the last point then equals summarize()
        # over the same entries instead of drifting by a cent per step.
        running += daily_net_hours(e) - daily_target_for(e, schedule)
        points.append(CumulativePointOut(date=e.date, surplus_hours=round(running, 2)))

    return CumulativeSeriesOut(year=year, start=start, opening=round(opening, 2), points=points)


def _whole_history(session: Session) -> CumulativeSeriesOut:
    schedule = get_daily_target_schedule(session)
    start = get_cumulative_start_date(session)
    reset = get_reset_annually(session)
    entries = [
        e for e in session.scalars(select(WorkEntry).order_by(WorkEntry.date)) if e.date >= start
    ]
    running = 0.0
    year = None
    points: list[CumulativePointOut] = []
    for e in entries:
        if reset and year is not None and e.date.year != year:
            running = 0.0
        year = e.date.year
        running += daily_net_hours(e) - daily_target_for(e, schedule)
        points.append(CumulativePointOut(date=e.date, surplus_hours=round(running, 2)))
    return CumulativeSeriesOut(year=None, start=start, opening=0.0, points=points)


@router.get("/api/analytics/monthly", response_model=list[MonthlyBreakdownRow])
def monthly_breakdown(session: Session = Depends(get_session)) -> list[MonthlyBreakdownRow]:
    """Return one row per (year, month) that has any entries, oldest first."""
    schedule = get_daily_target_schedule(session)
    entries = list(session.scalars(select(WorkEntry).order_by(WorkEntry.date)))

    grouped: dict[tuple[int, int], list[WorkEntry]] = defaultdict(list)
    for e in entries:
        grouped[(e.date.year, e.date.month)].append(e)

    rows: list[MonthlyBreakdownRow] = []
    for y, m in sorted(grouped):
        s = summarize(grouped[(y, m)], schedule)
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
    schedule = get_daily_target_schedule(session)
    entries = list(session.scalars(select(WorkEntry).order_by(WorkEntry.date)))
    work_entries = [e for e in entries if e.day_type == DayType.WORK]

    longest_day = max(work_entries, key=daily_net_hours, default=None)
    shortest_day = min(work_entries, key=daily_net_hours, default=None)

    # Monthly grouping
    grouped: dict[tuple[int, int], list[WorkEntry]] = defaultdict(list)
    for e in entries:
        grouped[(e.date.year, e.date.month)].append(e)
    month_summaries = {key: summarize(es, schedule) for key, es in grouped.items()}

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

    # Yearly grouping
    year_grouped: dict[int, list[WorkEntry]] = defaultdict(list)
    for e in entries:
        year_grouped[e.date.year].append(e)
    year_summaries = {y: summarize(es, schedule) for y, es in year_grouped.items()}

    best_year_item = (
        max(year_summaries.items(), key=lambda kv: kv[1].surplus_hours, default=None)
        if year_summaries
        else None
    )
    worst_year_item = (
        min(year_summaries.items(), key=lambda kv: kv[1].surplus_hours, default=None)
        if year_summaries
        else None
    )

    # Longest positive cumulative streak (consecutive entries where running total > 0)
    running = 0.0
    cur_streak = 0
    max_streak = 0
    for e in entries:
        running = round(running + daily_net_hours(e) - daily_target_for(e, schedule), 2)
        if running > 0.01:
            cur_streak += 1
        else:
            cur_streak = 0
        max_streak = max(max_streak, cur_streak)

    def _erec(e: WorkEntry | None) -> RecordEntry | None:
        return None if e is None else RecordEntry(date=e.date, net_hours=daily_net_hours(e))

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

    def _yrec(item: tuple[int, PeriodSummary] | None) -> RecordYear | None:
        if item is None:
            return None
        y, s = item
        return RecordYear(
            year=y, label=str(y), net_hours=s.net_hours, surplus_hours=s.surplus_hours
        )

    return RecordsOut(
        longest_work_day=_erec(longest_day),
        shortest_work_day=_erec(shortest_day),
        longest_month=_mrec(longest_month),
        most_surplus_month=_mrec(most_surplus),
        most_deficit_month=_mrec(most_deficit),
        longest_positive_streak=max_streak,
        best_year=_yrec(best_year_item),
        worst_year=_yrec(worst_year_item),
    )


@router.get("/api/analytics/yearly", response_model=list[YearlyBreakdownRow])
def yearly_breakdown(session: Session = Depends(get_session)) -> list[YearlyBreakdownRow]:
    """One row per year that has any entries, oldest first."""
    schedule = get_daily_target_schedule(session)
    entries = list(session.scalars(select(WorkEntry).order_by(WorkEntry.date)))

    grouped: dict[int, list[WorkEntry]] = defaultdict(list)
    for e in entries:
        grouped[e.date.year].append(e)

    rows: list[YearlyBreakdownRow] = []
    for y in sorted(grouped):
        s = summarize(grouped[y], schedule)
        rows.append(
            YearlyBreakdownRow(
                year=y,
                label=str(y),
                net_hours=s.net_hours,
                target_hours=s.target_hours,
                surplus_hours=s.surplus_hours,
                work_days=s.work_days,
                non_work_days=s.non_work_days,
            )
        )
    return rows


@router.get("/api/analytics/yoy", response_model=YoYOut)
def year_over_year(
    today: date | None = Query(None),
    session: Session = Depends(get_session),
) -> YoYOut:
    """Compare year-to-date this year vs the same period last year."""
    today = today or local_today()
    schedule = get_daily_target_schedule(session)

    this_start = date(today.year, 1, 1)
    this_s = summarize(_entries_between(session, this_start, today), schedule)

    try:
        last_same_day = today.replace(year=today.year - 1)
    except ValueError:
        last_same_day = today.replace(year=today.year - 1, day=28)
    last_start = date(today.year - 1, 1, 1)
    last_s = summarize(_entries_between(session, last_start, last_same_day), schedule)

    def _period(label: str, s: PeriodSummary) -> YoYPeriod:
        return YoYPeriod(
            label=label,
            net_hours=s.net_hours,
            target_hours=s.target_hours,
            surplus_hours=s.surplus_hours,
            work_days=s.work_days,
        )

    return YoYOut(
        this_year=_period(f"{today.year} YTD", this_s),
        last_year=_period(f"{today.year - 1} (same period)", last_s),
    )
