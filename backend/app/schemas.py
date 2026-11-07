"""Pydantic schemas for the HTTP API."""

from __future__ import annotations

from datetime import date as date_
from datetime import datetime as datetime_
from datetime import timedelta
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models import DayType
from app.services.computations import minutes_between
from app.services.currencies import CODES as CURRENCY_CODES

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


class _LeaveHoursMixin(BaseModel):
    """``leave_hours`` as the human alternative to ``fraction``.

    People say "3h of vacation", not "0.375 of the day". A request may carry either;
    the server turns hours into the fraction using the target in force on that date
    (see ``services.leave``), so callers never need the schedule.
    Both at once is ambiguous and rejected; on a work day hours mean nothing.
    """

    leave_hours: float | None = Field(default=None, gt=0, le=24)

    @model_validator(mode="after")
    def _one_or_the_other(self):
        if self.leave_hours is not None:
            if "fraction" in self.model_fields_set:
                raise ValueError("give either fraction or leave_hours, not both")
            if getattr(self, "day_type", None) is DayType.WORK:
                raise ValueError("work days have no leave_hours")
        return self

    @property
    def hours_pending(self) -> bool:
        """True while ``leave_hours`` still has to be turned into a fraction."""
        return self.leave_hours is not None


class _EntryBody(_LeaveHoursMixin):
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
        # With hours still unresolved the day is treated as partial: the times it may
        # carry are checked now, and the whole-day rules again once the fraction is known.
        return self.day_type is not DayType.WORK and (self.fraction < 1.0 or self.hours_pending)

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


class ClockInIn(BaseModel):
    """Body for POST /api/clock/in — start today's work day now.

    Everything is optional: the server stamps its own wall clock (in ``TZ``) unless
    ``at`` is given, on ``date`` (default today). ``dry_run`` returns the entry it
    would create without writing it.
    """

    date: date_ | None = None
    at: HHMM | None = None
    notes: str | None = None
    dry_run: bool = False


class ClockOutIn(BaseModel):
    """Body for POST /api/clock/out — finish the started day with the end time now.

    ``breaks`` are set on the way out (a started day cannot carry them yet); ``notes``
    replaces the note only when present in the body.
    """

    date: date_ | None = None
    at: HHMM | None = None
    breaks: list[BreakIn] = Field(default_factory=list)
    notes: str | None = None
    dry_run: bool = False


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


class EntryPreviewOut(EntryOut):
    """What POST /api/entries/preview would have written: the day as the API would
    return it, plus whether the date is already taken (a create would 409)."""

    exists: bool


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


class CumulativePointOut(BaseModel):
    date: date_
    surplus_hours: float  # running balance after this day's entry


class CumulativeSeriesOut(BaseModel):
    """The cumulative balance day by day within one year — the dashboard's trajectory."""

    year: int | None  # None for the whole history (`all=true`)
    start: date_  # effective cumulative start for that year (Jan 1 when reset_annually)
    opening: float  # balance carried into the year from `start`; 0 when `start` is in the year
    points: list[CumulativePointOut]  # one per logged day, ascending


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
    # Freelance projection (Freelance tab): planned hours a week, days off a year.
    freelance_hours_per_week: float = 0
    freelance_days_off: float = 0


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
    freelance_hours_per_week: float | None = Field(default=None, ge=0, le=168)
    freelance_days_off: float | None = Field(default=None, ge=0, le=366)


# 4: freelance payouts; 3: freelance (income sources, hour blocks, tax years);
# 2: entries carry `fraction`; 1: whole days only
BACKUP_VERSION = 4
SUPPORTED_BACKUP_VERSIONS = (1, 2, 3, 4)


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
    # Version 3 (payouts: 4; accounts are optional keys of a version 4 file). Older files
    # simply have none; sources and accounts
    # keep their ids so blocks and payouts find them.
    accounts: list[AccountBackup] = Field(default_factory=list)
    income_sources: list[IncomeSourceBackup] = Field(default_factory=list)
    freelance_blocks: list[FreelanceBlockBackup] = Field(default_factory=list)
    freelance_tax_years: list[FreelanceTaxYearIn] = Field(default_factory=list)
    freelance_payouts: list[FreelancePayoutBackup] = Field(default_factory=list)


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


class BatchEntryIn(_LeaveHoursMixin):
    """Body for POST /api/entries/batch — log the same non-work day type across multiple dates.

    ``fraction`` (default 1.0, whole days) applies to every date; the batch UI doesn't
    expose it, but the time-off planner and API users can pencil in partial days.
    ``leave_hours`` instead resolves per date against that date's target. ``notes``
    goes on every created day.
    """

    dates: list[date_] = Field(..., min_length=1)
    day_type: DayType
    fraction: float = Field(default=1.0, gt=0, le=1)
    notes: str | None = None

    @model_validator(mode="after")
    def _no_work(self):
        if self.day_type is DayType.WORK:
            raise ValueError("batch logging only supports non-work day types")
        return self


class BatchResultOut(BaseModel):
    created: list[date_]
    skipped: list[date_]


# ---------- time-off planner ----------------------------------------------


class PlanBatchIn(_LeaveHoursMixin):
    """Body for POST /api/plans — draft the same leave across many dates.

    A date that already has a draft is re-drafted (type / fraction / notes replaced);
    a date with a real entry is skipped, like batch logging. ``leave_hours`` resolves
    per date like it does for entries.
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


# ---------- freelance -------------------------------------------------------

Currency = Annotated[str, StringConstraints(pattern=r"^(" + "|".join(CURRENCY_CODES) + r")$")]
ACCOUNT_KINDS = ("bank", "wallet", "cash", "other")
AccountKind = Annotated[str, StringConstraints(pattern=r"^(" + "|".join(ACCOUNT_KINDS) + r")$")]


def _clean_account_name(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 60:
        raise ValueError("name must be 1 to 60 characters")
    return value


class AccountIn(BaseModel):
    """Where the money lands: a name, a currency and a kind."""

    name: str
    currency: Currency
    kind: AccountKind = "bank"
    is_default: bool = False
    archived: bool = False

    _name = field_validator("name")(_clean_account_name)


class AccountUpdate(BaseModel):
    name: str | None = None
    currency: Currency | None = None
    kind: AccountKind | None = None
    is_default: bool | None = None
    archived: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_account_name(value)


class AccountOut(BaseModel):
    id: int
    name: str
    currency: str
    kind: str
    is_default: bool
    archived: bool
    created_at: datetime_
    payouts: int  # how many payouts went into it (one with payouts is archived, not deleted)


class AccountBackup(AccountIn):
    """An account as the backup carries it: with its id, which the payouts reference."""

    id: int
    created_at: datetime_ | None = None


class IncomeSourceIn(BaseModel):
    """A client or activity: its name, hourly rate and currency. One source is the default."""

    name: str = Field(..., min_length=1, max_length=100)
    hourly_rate: float = Field(..., gt=0, le=100000)
    currency: Currency = "EUR"
    is_default: bool = False
    archived: bool = False
    default_account_id: int | None = None


class IncomeSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    hourly_rate: float | None = Field(default=None, gt=0, le=100000)
    currency: Currency | None = None
    is_default: bool | None = None
    archived: bool | None = None
    default_account_id: int | None = None  # null clears it; leave it out to keep it


class IncomeSourceOut(BaseModel):
    id: int
    name: str
    hourly_rate: float
    currency: str
    is_default: bool
    archived: bool
    default_account_id: int | None
    blocks: int  # how many blocks bill to it (a source with blocks is archived, not deleted)


class IncomeSourceBackup(BaseModel):
    """A source as the backup carries it: with its id, which the blocks reference."""

    id: int
    name: str = Field(..., min_length=1, max_length=100)
    hourly_rate: float = Field(..., gt=0)
    currency: Currency = "EUR"
    is_default: bool = False
    archived: bool = False
    default_account_id: int | None = None


class _BlockDuration(BaseModel):
    """``hours`` or a start and an end (which also fix the hours); not neither, not a
    contradiction."""

    hours: float | None = Field(default=None, gt=0, le=24)
    start_time: HHMM | None = None
    end_time: HHMM | None = None

    @model_validator(mode="after")
    def _resolve(self):
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("give both start_time and end_time, or neither")
        if self.start_time and self.end_time:
            span = minutes_between(self.start_time, self.end_time)
            if span <= 0:
                raise ValueError("end_time must be after start_time")
            from_times = span / 60.0
            if self.hours is not None and abs(self.hours - from_times) > 1 / 60:
                raise ValueError("hours do not match the start and end times")
            self.hours = from_times
        elif self.hours is None:
            raise ValueError("give hours, or a start and an end")
        return self

    @property
    def minutes(self) -> int:
        return int(round(self.hours * 60))


class FreelanceBlockIn(_BlockDuration):
    """Body for POST /api/freelance/blocks.

    The rate and currency are the source's unless ``rate`` is given (a one-off price). A USD
    block takes the ECB rate of its date unless ``fx_rate`` is given; ``fx_rate`` on a EUR
    block is ignored.
    """

    date: date_
    source_id: int
    notes: str | None = None
    rate: float | None = Field(default=None, gt=0, le=100000)
    fx_rate: float | None = Field(default=None, gt=0)


class FreelanceBlockUpdate(_BlockDuration):
    """Body for PUT /api/freelance/blocks/{id}: the same, the date included.

    The stored rate and currency stay unless ``rate`` is given or the source changes (then
    the new source's rate applies); the stored ``fx_rate`` stays unless given.
    """

    date: date_
    source_id: int
    notes: str | None = None
    rate: float | None = Field(default=None, gt=0, le=100000)
    fx_rate: float | None = Field(default=None, gt=0)


class FreelanceBlockOut(BaseModel):
    id: int
    date: date_
    source_id: int
    source_name: str
    minutes: int
    hours: float
    start_time: str | None
    end_time: str | None
    notes: str | None
    rate: float
    currency: str
    fx_rate: float | None  # USD per EUR on the block's date; None for EUR or when unknown
    amount: float  # in the block's currency, to the cent
    amount_eur: float | None  # None for a USD block without a rate
    effective_eur: float | None  # what counts: its share of the week's payout, else amount_eur
    payout_id: int | None  # the payout of its source and week, when there is one


class FreelanceBlockBackup(BaseModel):
    date: date_
    source_id: int
    minutes: int = Field(..., gt=0, le=24 * 60)
    start_time: HHMM | None = None
    end_time: HHMM | None = None
    notes: str | None = None
    rate: float = Field(..., gt=0)
    currency: Currency = "EUR"
    fx_rate: float | None = Field(default=None, gt=0)


def _must_be_monday(value: date_) -> date_:
    if value.weekday() != 0:
        raise ValueError("week_start must be a Monday")
    return value


class FreelancePayoutIn(BaseModel):
    """Body for POST / PUT /api/freelance/payouts: what a source paid for one week.

    ``amount`` is in the account's currency when ``account_id`` is given, else in the source's.
    ``paid_on`` is the day the money landed (default: the week's Sunday); its rate is the ECB's
    or CoinGecko's of that day. ``eur_amount`` is what it was worth in euros, typed by hand:
    it beats any rate. ``fx_rate`` (units per EUR) is the older way to give a rate by hand;
    on a EUR payout it is ignored.
    """

    source_id: int
    week_start: date_
    amount: float = Field(..., gt=0)
    fx_rate: float | None = Field(default=None, gt=0)
    note: str | None = None
    account_id: int | None = None
    paid_on: date_ | None = None
    eur_amount: float | None = Field(default=None, gt=0)

    _monday = field_validator("week_start")(_must_be_monday)


class FreelancePayoutOut(BaseModel):
    id: int
    source_id: int
    week_start: date_
    week_end: date_  # the Sunday
    amount: float
    currency: str
    fx_rate: float | None  # units of `currency` per EUR; None for EUR or when unknown
    note: str | None
    amount_eur: float | None  # to the cent; None for a payout without a rate
    blocks: int  # the source's blocks in that week
    minutes: int
    estimate_eur: float | None  # their estimates added up; None when one has no rate
    estimate_amount: float  # the same in the source's currency
    account_id: int | None
    account_name: str | None
    rate_source: str | None  # ECB, CoinGecko or manual; None for EUR
    rate_date: date_ | None
    billed_amount: float  # the week's estimate in the source's currency
    billed_currency: str
    billed_eur: float | None  # that estimate at the ECB rate of rate_date
    fx_cost_eur: float | None  # billed_eur - amount_eur: lost to the exchange and fees
    effective_rate: float | None  # source units per EUR actually obtained


class FreelancePayoutBackup(BaseModel):
    source_id: int
    week_start: date_
    amount: float = Field(..., gt=0)
    currency: Currency = "EUR"
    fx_rate: float | None = Field(default=None, gt=0)
    note: str | None = None
    account_id: int | None = None
    rate_source: str | None = None
    rate_date: date_ | None = None

    _monday = field_validator("week_start")(_must_be_monday)


def week_end_of(week_start: date_) -> date_:
    return week_start + timedelta(days=6)


class FreelanceTaxYearIn(BaseModel):
    """The tax inputs of one year (PUT /api/freelance/tax-years/{year}; the backup)."""

    year: int = Field(..., ge=2000, le=2100)
    salary_annual: float = Field(default=0, ge=0)
    tarifa_plana: bool = False
    inicio_actividad: bool = False
    set_aside_share: float = Field(default=0.4, ge=0, le=1)
    gestoria_annual: float = Field(default=0, ge=0)
    other_expenses: float = Field(default=0, ge=0)


class FreelanceTaxYearOut(FreelanceTaxYearIn):
    inherited_from: int | None  # the row's year when the year has no row of its own
    is_default: bool  # no row applies at all: the defaults
    fiscal_year: int  # the year of fiscal_es.json used for this year's figures
    region: str


class FreelanceCalcIn(BaseModel):
    """Body for POST /api/freelance/calc — the calculator's inputs, one field driving.

    Every assumption is on view in the calculator, so every one rides in the request; the
    server only adds the fiscal rules of the year.
    """

    year: int = Field(..., ge=2000, le=2100)
    mode: Annotated[str, StringConstraints(pattern=r"^(hourly|daily|net)$")]
    value: float = Field(..., ge=0, le=1e9)
    currency: Currency = "EUR"
    fx_rate: float | None = Field(default=None, gt=0)
    billable_days: int = Field(default=220, ge=0, le=366)
    hours_per_day: float = Field(default=8, gt=0, le=24)
    salary_annual: float = Field(default=0, ge=0)
    gestoria_annual: float = Field(default=0, ge=0)
    other_expenses: float = Field(default=0, ge=0)
    tarifa_plana: bool = False
    inicio_actividad: bool = False

    @model_validator(mode="after")
    def _foreign_needs_a_rate(self):
        if self.currency != "EUR" and not self.fx_rate:
            raise ValueError(f"a {self.currency} rate needs fx_rate ({self.currency} per EUR)")
        return self
