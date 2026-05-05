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
    break_minutes: int | None = Field(default=None, ge=1, le=12 * 60)
    start_time: HHMM | None = None
    end_time: HHMM | None = None

    @model_validator(mode="after")
    def _resolve_minutes(self):
        if self.start_time and self.end_time:
            computed = minutes_between(self.start_time, self.end_time)
            if computed <= 0:
                raise ValueError("break end_time must be after start_time")
            self.break_minutes = computed
        elif self.break_minutes is None:
            raise ValueError("provide break_minutes or both start_time and end_time")
        return self


class BreakOut(BaseModel):
    id: int
    break_minutes: int
    start_time: str | None
    end_time: str | None

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
            # vacation / sick / holiday / flex — no time fields, no breaks
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
    work_week_days: list[int]
    vacation_budget_days: int
    vacation_days_used: int


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


class RecordYear(BaseModel):
    year: int
    label: str
    net_hours: float
    surplus_hours: float


class RecordsOut(BaseModel):
    longest_work_day: RecordEntry | None
    shortest_work_day: RecordEntry | None
    longest_month: RecordMonth | None
    most_surplus_month: RecordMonth | None
    most_deficit_month: RecordMonth | None
    longest_positive_streak: int
    best_year: RecordYear | None
    worst_year: RecordYear | None


class YearlyBreakdownRow(BaseModel):
    year: int
    label: str
    net_hours: float
    target_hours: float
    surplus_hours: float
    work_days: int
    non_work_days: int


class YoYPeriod(BaseModel):
    label: str
    net_hours: float
    target_hours: float
    surplus_hours: float
    work_days: int


class YoYOut(BaseModel):
    this_year: YoYPeriod
    last_year: YoYPeriod


class ConfigOut(BaseModel):
    daily_target_hours: float
    cumulative_start_date: date_
    reset_annually: bool = False  # default keeps old backup files valid
    work_week_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    vacation_budget_days: int = 0


class ConfigIn(BaseModel):
    daily_target_hours: float | None = Field(default=None, gt=0, le=24)
    cumulative_start_date: date_ | None = None
    reset_annually: bool | None = None
    work_week_days: list[int] | None = None
    vacation_budget_days: int | None = Field(default=None, ge=0)


class RestoreIn(BaseModel):
    """Body for POST /api/restore.

    ``entries`` are validated with the same rules as EntryIn so bad data
    (e.g. a work day with no times) is rejected before touching the DB.
    ``settings`` is optional — omit to keep the current target / start-date.
    """

    version: int
    settings: ConfigOut | None = None
    entries: list[EntryIn] = Field(default_factory=list)
