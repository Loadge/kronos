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
            if not self.start_time:
                raise ValueError("work days require start_time")
            if self.end_time:
                # Complete entry: validate span vs breaks.
                span = minutes_between(self.start_time, self.end_time)
                break_sum = sum(b.break_minutes for b in self.breaks)
                if break_sum > span:
                    raise ValueError(f"total breaks ({break_sum}min) exceed work span ({span}min)")
            elif self.breaks:
                # In-progress entry (no end_time yet): breaks not allowed yet.
                raise ValueError("cannot add breaks without end_time")
        else:
            # vacation / sick / holiday / flex — no time fields, no breaks
            if self.start_time is not None or self.end_time is not None:
                raise ValueError(f"{self.day_type.value} days must not have start_time or end_time")
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


class StreaksOut(BaseModel):
    logging_streak: int
    on_target_streak: int
    total_logged_days: int


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
    default_start_time: str = "09:00"
    default_end_time: str = "17:00"
    holiday_country: str = ""  # ISO 3166-1 alpha-2; "" = none chosen
    holiday_region: str = ""  # ISO 3166-2 subdivision, e.g. "ES-MD"; "" = national only


class ConfigIn(BaseModel):
    daily_target_hours: float | None = Field(default=None, gt=0, le=24)
    cumulative_start_date: date_ | None = None
    reset_annually: bool | None = None
    work_week_days: list[int] | None = None
    vacation_budget_days: int | None = Field(default=None, ge=0)
    default_start_time: HHMM | None = None
    default_end_time: HHMM | None = None
    holiday_country: str | None = None
    holiday_region: str | None = None


class RestoreIn(BaseModel):
    """Body for POST /api/restore.

    ``entries`` are validated with the same rules as EntryIn so bad data
    (e.g. a work day with no times) is rejected before touching the DB.
    ``settings`` is optional — omit to keep the current target / start-date.
    """

    version: int
    settings: ConfigOut | None = None
    entries: list[EntryIn] = Field(default_factory=list)


class CountryOut(BaseModel):
    code: str
    name: str


class HolidayImportOut(BaseModel):
    imported: list[date_]
    skipped: list[date_]


class HolidayPreviewOut(BaseModel):
    date: date_
    name: str
    regional: bool  # False = national (global), True = regional (matched the region)
    exists: bool  # a work/other entry already occupies this date → import will skip it


class CsvImportIn(BaseModel):
    """Body for POST /api/import/csv — the raw text of a Kronos CSV export.

    The file is read client-side (like restore) and posted as a string, so the
    app needs no multipart/form-data dependency.
    """

    content: str


class ImportResultOut(BaseModel):
    imported: list[date_]
    skipped: list[date_]
    errors: list[str]


class BatchEntryIn(BaseModel):
    """Body for POST /api/entries/batch — log the same non-work day type across multiple dates."""

    dates: list[date_] = Field(..., min_length=1)
    day_type: DayType

    @model_validator(mode="after")
    def _no_work(self):
        if self.day_type is DayType.WORK:
            raise ValueError("batch logging only supports non-work day types")
        return self


class BatchResultOut(BaseModel):
    created: list[date_]
    skipped: list[date_]


class TemplateBreakOut(BaseModel):
    break_minutes: int
    start_time: str | None
    end_time: str | None


class TemplateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    start_time: HHMM
    end_time: HHMM
    breaks: list[BreakIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_span(self):
        span = minutes_between(self.start_time, self.end_time)
        break_sum = sum(b.break_minutes for b in self.breaks)
        if break_sum > span:
            raise ValueError(f"total breaks ({break_sum}min) exceed work span ({span}min)")
        return self


class TemplateOut(BaseModel):
    id: int
    name: str
    start_time: str
    end_time: str
    breaks: list[TemplateBreakOut]
