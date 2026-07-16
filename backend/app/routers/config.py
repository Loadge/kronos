"""Read/update app-level settings (daily target, cumulative start date)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas import (
    ConfigIn,
    ConfigOut,
    DailyTargetRow,
    DailyTargetScheduleIn,
    DailyTargetScheduleOut,
    DashboardLayoutIn,
    DashboardLayoutOut,
)
from app.services.computations import DailyTargetSchedule
from app.services.settings import (
    get_cumulative_start_date,
    get_daily_target_hours,
    get_daily_target_schedule,
    get_dashboard_layout,
    get_default_end_time,
    get_default_start_time,
    get_holiday_country,
    get_holiday_region,
    get_reset_annually,
    get_vacation_budget_days,
    get_work_week_days,
    set_cumulative_start_date,
    set_daily_target_hours,
    set_daily_target_schedule,
    set_dashboard_layout,
    set_default_end_time,
    set_default_start_time,
    set_holiday_country,
    set_holiday_region,
    set_reset_annually,
    set_vacation_budget_days,
    set_work_week_days,
)

router = APIRouter(prefix="/api/config", tags=["config"])


def _schedule_rows(session: Session) -> list[DailyTargetRow]:
    return [
        DailyTargetRow(effective_from=eff, hours=hours)
        for eff, hours in get_daily_target_schedule(session).rows
    ]


def _config_out(session: Session) -> ConfigOut:
    return ConfigOut(
        daily_target_hours=get_daily_target_hours(session),
        daily_target_schedule=_schedule_rows(session),
        cumulative_start_date=get_cumulative_start_date(session),
        reset_annually=get_reset_annually(session),
        work_week_days=get_work_week_days(session),
        vacation_budget_days=get_vacation_budget_days(session),
        default_start_time=get_default_start_time(session),
        default_end_time=get_default_end_time(session),
        holiday_country=get_holiday_country(session),
        holiday_region=get_holiday_region(session),
    )


@router.get("", response_model=ConfigOut)
def read_config(session: Session = Depends(get_session)) -> ConfigOut:
    return _config_out(session)


@router.put("", response_model=ConfigOut)
def update_config(body: ConfigIn, session: Session = Depends(get_session)) -> ConfigOut:
    if body.daily_target_hours is not None:
        set_daily_target_hours(session, body.daily_target_hours)
    if body.cumulative_start_date is not None:
        set_cumulative_start_date(session, body.cumulative_start_date)
    if body.reset_annually is not None:
        set_reset_annually(session, body.reset_annually)
    if body.work_week_days is not None:
        set_work_week_days(session, body.work_week_days)
    if body.vacation_budget_days is not None:
        set_vacation_budget_days(session, body.vacation_budget_days)
    if body.default_start_time is not None:
        set_default_start_time(session, body.default_start_time)
    if body.default_end_time is not None:
        set_default_end_time(session, body.default_end_time)
    if body.holiday_country is not None:
        set_holiday_country(session, body.holiday_country)
    if body.holiday_region is not None:
        set_holiday_region(session, body.holiday_region)
    session.commit()
    return _config_out(session)


@router.get("/daily-target-schedule", response_model=DailyTargetScheduleOut)
def read_daily_target_schedule(
    session: Session = Depends(get_session),
) -> DailyTargetScheduleOut:
    return DailyTargetScheduleOut(rows=_schedule_rows(session))


@router.put("/daily-target-schedule", response_model=DailyTargetScheduleOut)
def update_daily_target_schedule(
    body: DailyTargetScheduleIn, session: Session = Depends(get_session)
) -> DailyTargetScheduleOut:
    # from_rows sorts ascending and dedupes by date, so the client can send rows in any order.
    schedule = DailyTargetSchedule.from_rows([(r.effective_from, r.hours) for r in body.rows])
    set_daily_target_schedule(session, schedule)
    session.commit()
    return DailyTargetScheduleOut(rows=_schedule_rows(session))


@router.get("/dashboard-layout", response_model=DashboardLayoutOut)
def read_dashboard_layout(session: Session = Depends(get_session)) -> DashboardLayoutOut:
    return DashboardLayoutOut(**get_dashboard_layout(session))


@router.put("/dashboard-layout", response_model=DashboardLayoutOut)
def update_dashboard_layout(
    body: DashboardLayoutIn, session: Session = Depends(get_session)
) -> DashboardLayoutOut:
    layout = body.model_dump()
    set_dashboard_layout(session, layout)
    session.commit()
    return DashboardLayoutOut(**layout)
