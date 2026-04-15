"""Pydantic schemas for the HTTP API."""

from __future__ import annotations

from datetime import date as date_
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models import DayType
from app.services.computations import minutes_between

HHMM = Annotated[
    str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", min_length=5, max_length=5)
]


class BreakIn(BaseModel):
    break_minutes: int = Field(ge=1, le=12 * 60)


class BreakOut(BaseModel):
    id: int
    break_minutes: int

    model_config = ConfigDict(from_attributes=True)


class _EntryBody(BaseModel):
    """Shared fields + cross-field validation for create / update payloads."""

    day_type: DayType = DayType.WORK
    start_time: HHMM | None = None
    end_time: HHMM | None = None
    notes: str | None = None
    breaks: list[BreakIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_day_type_rules(self):
        if self.day_type is DayType.WORK:
            if not self.start_time or not self.end_time:
                raise ValueError("work days require start_time and end_time")
            span = minutes_between(self.start_time, self.end_time)
            break_sum = sum(b.break_minutes for b in self.breaks)
            if break_sum > span:
                raise ValueError(
                    f"total breaks ({break_sum}min) exceed work span ({span}min)"
                )
        else:
            if self.start_time is not None or self.end_time is not None:
                raise ValueError(
                    f"{self.day_type.value} days must not have start_time or end_time"
                )
            if self.breaks:
                raise ValueError(f"{self.day_type.value} days must not have breaks")
        return self


class EntryIn(_EntryBody):
    date: date_


class EntryUpdate(_EntryBody):
    """Body for PUT /api/entries/{date} — same shape minus `date` (URL path)."""


class EntryOut(BaseModel):
    date: date_
    day_type: DayType
    start_time: str | None
    end_time: str | None
    notes: str | None
    breaks: list[BreakOut]
    total_break_minutes: int
    net_hours: float
    target_hours: float
    surplus_hours: float


class PeriodSummaryOut(BaseModel):
    net_hours: float
    target_hours: float
    work_days: int
    non_work_days: int
    surplus_hours: float


class DashboardOut(BaseModel):
    today: date_
    week: PeriodSummaryOut
    month: PeriodSummaryOut
    cumulative: PeriodSummaryOut
    cumulative_start_date: date_
    daily_target_hours: float


class MonthlyBreakdownRow(BaseModel):
    year: int
    month: int
    label: str  # "2026-04"
    net_hours: float
    target_hours: float
    surplus_hours: float
    work_days: int
    non_work_days: int


class RecordEntry(BaseModel):
    date: date_
    net_hours: float


class RecordMonth(BaseModel):
    year: int
    month: int
    label: str
    net_hours: float
    surplus_hours: float


class RecordsOut(BaseModel):
    longest_work_day: RecordEntry | None
    shortest_work_day: RecordEntry | None
    longest_month: RecordMonth | None
    most_surplus_month: RecordMonth | None
    most_deficit_month: RecordMonth | None


class ConfigOut(BaseModel):
    daily_target_hours: float
    cumulative_start_date: date_


class ConfigIn(BaseModel):
    daily_target_hours: float | None = Field(default=None, gt=0, le=24)
    cumulative_start_date: date_ | None = None
