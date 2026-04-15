"""Read/update app-level settings (daily target, cumulative start date)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_session
from app.schemas import ConfigIn, ConfigOut
from app.services.settings import (
    get_cumulative_start_date,
    get_daily_target_hours,
    set_cumulative_start_date,
    set_daily_target_hours,
)

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("", response_model=ConfigOut)
def read_config(session: Session = Depends(get_session)) -> ConfigOut:
    return ConfigOut(
        daily_target_hours=get_daily_target_hours(session),
        cumulative_start_date=get_cumulative_start_date(session),
    )


@router.put("", response_model=ConfigOut)
def update_config(body: ConfigIn, session: Session = Depends(get_session)) -> ConfigOut:
    if body.daily_target_hours is not None:
        set_daily_target_hours(session, body.daily_target_hours)
    if body.cumulative_start_date is not None:
        set_cumulative_start_date(session, body.cumulative_start_date)
    session.commit()
    return ConfigOut(
        daily_target_hours=get_daily_target_hours(session),
        cumulative_start_date=get_cumulative_start_date(session),
    )
