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
    # Share of the day covered by ``day_type``. Always 1.0 for work days;
    # 0 < fraction < 1 is partial leave, whose start/end/breaks are the hours worked
    # in the rest of the day.
    fraction: float = Field(default=1.0, gt=0, le=1)
    start_time: HHMM | None = None
    end_time: HHMM | None = None
    notes: str | None = None
    breaks: list[BreakIn] = Field(default_factory=list)

    @property
    def is_partial(self) -> bool:
        return self.day_type is not DayType.WORK and self.fraction < 1.0

    def _check_times(self, *, required: bool) -> None:
        """Start/end/break rules shared by work days and the worked part of a partial
        leave day. ``required`` — a work day must at least have started."""
        if not self.start_time:
            if required:
                raise ValueError("work days require start_time")
            if self.end_time:
                raise ValueError("end_time requires start_time")
            if self.breaks:
                raise ValueError("cannot add breaks without start_time and end_time")
            return
        if self.end_time:
            # Complete entry: validate span vs breaks.
            span = minutes_between(self.start_time, self.end_time)
            break_sum = sum(b.break_minutes for b in self.breaks)
            if break_sum > span:
                raise ValueError(f"total breaks ({break_sum}min) exceed work span ({span}min)")
        elif self.breaks:
            # In-progress entry (no end_time yet): breaks not allowed yet.
            raise ValueError("cannot add breaks without end_time")

    @model_validator(mode="after")
    def _check_day_type_rules(self):
        if self.day_type is DayType.WORK:
            if self.fraction != 1.0:
                raise ValueError("work days have no fraction (it is always 1.0)")
            self._check_times(required=True)
        elif self.is_partial:
            # Partial leave: the hours worked in the rest of the day are optional
            # (net 0 without them, like an in-progress work day).
            self._check_times(required=False)
        else:
            # Whole-day vacation / sick / holiday / flex — no time fields, no breaks
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
    fraction: float  # share of the day that is `day_type`; 1.0 for work and whole-day leave
    leave_hours: float  # fraction × that date's target; 0 for work days
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
    work_days: float  # fractional: a 3h-off day is 0.62 work + 0.38 off
    non_work_days: float
    surplus_hours: float


class DashboardOut(BaseModel):
    today: date_
    week: PeriodSummaryOut
    month: PeriodSummaryOut
    cumulative: PeriodSummaryOut
    cumulative_start_date: date_
    daily_target_hours: float
    work_week_days: list[int]
    vacation_budget_days: float
    vacation_days_used: float  # sum of vacation fractions this year
    # Time-off drafts after today, this year (dates without a real entry): the forecast
    # subtracts these instead of assuming the whole remaining budget will be taken.
    planned_days_remaining: float = 0.0
    planned_flex_hours: float = 0.0


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
    work_days: float
    non_work_days: float


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
    work_days: float
    non_work_days: float


class YoYPeriod(BaseModel):
    label: str
    net_hours: float
    target_hours: float
    surplus_hours: float
    work_days: float


class YoYOut(BaseModel):
    this_year: YoYPeriod
    last_year: YoYPeriod


class DailyTargetRow(BaseModel):
    effective_from: date_
    hours: float = Field(..., gt=0, le=24)


class DailyTargetScheduleOut(BaseModel):
    rows: list[DailyTargetRow]


class DailyTargetScheduleIn(BaseModel):
    rows: list[DailyTargetRow] = Field(..., min_length=1)


class ConfigOut(BaseModel):
    daily_target_hours: float  # the CURRENT effective target (latest schedule row)
    # Full date-effective timeline; empty in old backups → derive from daily_target_hours.
    daily_target_schedule: list[DailyTargetRow] = Field(default_factory=list)
    cumulative_start_date: date_
    reset_annually: bool = False  # default keeps old backup files valid
    work_week_days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    vacation_budget_days: float = 0  # contracts come in halves (22.5); any multiple of 0.5
    default_start_time: str = "09:00"
    default_end_time: str = "17:00"
    holiday_country: str = ""  # ISO 3166-1 alpha-2; "" = none chosen
    holiday_region: str = ""  # ISO 3166-2 subdivision, e.g. "ES-MD"; "" = national only
    # Profile printed on the timesheet; all optional.
    profile_name: str = ""
    profile_employer: str = ""
    profile_extra: str = ""  # employee number, team, contract… one free line


class ConfigIn(BaseModel):
    daily_target_hours: float | None = Field(default=None, gt=0, le=24)
    cumulative_start_date: date_ | None = None
    reset_annually: bool | None = None
    work_week_days: list[int] | None = None
    vacation_budget_days: float | None = Field(default=None, ge=0, multiple_of=0.5)
    default_start_time: HHMM | None = None
    default_end_time: HHMM | None = None
    holiday_country: str | None = None
    holiday_region: str | None = None
    profile_name: str | None = Field(default=None, max_length=120)
    profile_employer: str | None = Field(default=None, max_length=120)
    profile_extra: str | None = Field(default=None, max_length=160)


class DashboardLayoutOut(BaseModel):
    hero: list[str]
    tiles: list[str]
    aux: list[str]


class DashboardLayoutIn(BaseModel):
    hero: list[str] = Field(..., min_length=1)
    tiles: list[str] = Field(..., min_length=1)
    aux: list[str] = Field(..., min_length=1)


BACKUP_VERSION = 2  # 2: entries carry `fraction`; 1: whole days only
SUPPORTED_BACKUP_VERSIONS = (1, 2)


class PlanIn(BaseModel):
    """One drafted leave day (backup format, and the shape PlanBatchIn expands to)."""

    date: date_
    day_type: DayType
    fraction: float = Field(default=1.0, gt=0, le=1)
    notes: str | None = None

    @model_validator(mode="after")
    def _plannable(self):
        if not self.day_type.is_plannable:
            raise ValueError("only vacation, holiday and flex can be planned")
        return self


class RestoreIn(BaseModel):
    """Body for POST /api/restore.

    ``entries`` are validated with the same rules as EntryIn so bad data
    (e.g. a work day with no times) is rejected before touching the DB.
    ``settings`` is optional — omit to keep the current target / start-date.
    Version 1 files (no ``fraction``) load as whole days; files without ``plans``
    simply restore none.
    """

    version: int
    settings: ConfigOut | None = None
    entries: list[EntryIn] = Field(default_factory=list)
    plans: list[PlanIn] = Field(default_factory=list)


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
    """Body for POST /api/entries/batch — log the same non-work day type across multiple dates.

    ``fraction`` (default 1.0, whole days) applies to every date; the batch UI doesn't
    expose it, but the time-off planner and API users can pencil in partial days.
    """

    dates: list[date_] = Field(..., min_length=1)
    day_type: DayType
    fraction: float = Field(default=1.0, gt=0, le=1)

    @model_validator(mode="after")
    def _no_work(self):
        if self.day_type is DayType.WORK:
            raise ValueError("batch logging only supports non-work day types")
        return self


class BatchResultOut(BaseModel):
    created: list[date_]
    skipped: list[date_]


# ---------- time-off planner ----------------------------------------------


class PlanBatchIn(BaseModel):
    """Body for POST /api/plans — draft the same leave across many dates.

    A date that already has a draft is re-drafted (type / fraction / notes replaced);
    a date with a real entry is skipped, like batch logging.
    """

    dates: list[date_] = Field(..., min_length=1)
    day_type: DayType
    fraction: float = Field(default=1.0, gt=0, le=1)
    notes: str | None = None

    @model_validator(mode="after")
    def _plannable(self):
        if not self.day_type.is_plannable:
            raise ValueError("only vacation, holiday and flex can be planned")
        return self


class PlanBatchResultOut(BaseModel):
    drafted: list[date_]
    replaced: list[date_]
    skipped: list[date_]  # a real entry occupies the date


class PlanUpdate(BaseModel):
    """Body for PUT /api/plans/{date} — change a draft's type, share or note."""

    day_type: DayType | None = None
    fraction: float | None = Field(default=None, gt=0, le=1)
    notes: str | None = None

    @model_validator(mode="after")
    def _plannable(self):
        if self.day_type is not None and not self.day_type.is_plannable:
            raise ValueError("only vacation, holiday and flex can be planned")
        return self


class PlanOut(BaseModel):
    date: date_
    day_type: DayType
    fraction: float
    leave_hours: float  # fraction × that date's target
    notes: str | None
    exists: bool  # a real entry now occupies the date — commit will skip it


class PlanCommitIn(BaseModel):
    dates: list[date_] = Field(..., min_length=1)


class PlanCommitOut(BaseModel):
    created: list[date_]
    skipped: list[date_]  # had a real entry already; the draft is dropped
    missing: list[date_]  # no draft on that date


class ProjectionOut(BaseModel):
    """Where the cumulative balance lands at the end of ``year`` given the drafts."""

    year: int
    today: date_
    horizon: date_  # Dec 31 of the year
    balance_today: (
        float  # cumulative surplus as of today, from the start that applies to the horizon
    )
    pace_per_day: float  # average surplus per work day so far (what "at my pace" assumes)
    on_target: float  # balance at the horizon if every open day lands on target
    at_pace: float  # ... if every open day adds pace_per_day
    scheduled_days_left: float
    open_days_left: float
    drafted_days: float
    drafted_flex_hours: float
    vacation_budget_days: float
    vacation_used_days: float  # real vacation entries in the year, past and future
    vacation_drafted_days: float  # vacation drafts in the year without a real entry
    vacation_remaining_after_plan: float


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
