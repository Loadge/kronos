"""Read/update app-level settings (daily target, cumulative start date)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas import ConfigIn, ConfigOut
from app.services.settings import (
    get_cumulative_start_date,
    get_daily_target_hours,
    get_default_end_time,
    get_default_start_time,
    get_holiday_country,
    get_holiday_region,
    get_reset_annually,
    get_vacation_budget_days,
    get_work_week_days,
    set_cumulative_start_date,
    set_daily_target_hours,
    set_default_end_time,
    set_default_start_time,
    set_holiday_country,
    set_holiday_region,
    set_reset_annually,
    set_vacation_budget_days,
    set_work_week_days,
)

router = APIRouter(prefix="/api/config", tags=["config"])


def _config_out(session: Session) -> ConfigOut:
    return ConfigOut(
        daily_target_hours=get_daily_target_hours(session),
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
