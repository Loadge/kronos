"""Unit tests for the settings read/write service (app.services.settings).

Each function is tested in isolation using the db_session fixture (in-memory
SQLite, no HTTP layer involved).
"""

from __future__ import annotations

from datetime import date

from app.config import DEFAULT_CUMULATIVE_START_DATE, DEFAULT_DAILY_TARGET_HOURS
from app.models import Setting
from app.services.computations import DailyTargetSchedule
from app.services.settings import (
    CUMULATIVE_START_DATE,
    DAILY_TARGET_HOURS,
    DAILY_TARGET_TIMELINE,
    get_cumulative_start_date,
    get_daily_target_hours,
    get_daily_target_schedule,
    set_cumulative_start_date,
    set_daily_target_hours,
    set_daily_target_schedule,
)
from sqlalchemy import func, select

# ── get_daily_target_hours ─────────────────────────────────────────────────


class TestGetDailyTargetHours:
    def test_returns_default_when_no_row(self, db_session):
        assert get_daily_target_hours(db_session) == DEFAULT_DAILY_TARGET_HOURS

    def test_returns_float_type(self, db_session):
        assert isinstance(get_daily_target_hours(db_session), float)

    def test_returns_stored_value(self, db_session):
        db_session.add(Setting(key=DAILY_TARGET_HOURS, value="7.5"))
        db_session.flush()
        assert get_daily_target_hours(db_session) == 7.5

    def test_stored_integer_string_coerces_to_float(self, db_session):
        db_session.add(Setting(key=DAILY_TARGET_HOURS, value="6"))
        db_session.flush()
        result = get_daily_target_hours(db_session)
        assert result == 6.0
        assert isinstance(result, float)


# ── set_daily_target_hours ─────────────────────────────────────────────────


class TestSetDailyTargetHours:
    def test_creates_row_and_can_be_read_back(self, db_session):
        set_daily_target_hours(db_session, 7.5)
        db_session.flush()
        assert get_daily_target_hours(db_session) == 7.5

    def test_updates_existing_row(self, db_session):
        set_daily_target_hours(db_session, 6.0)
        db_session.flush()
        set_daily_target_hours(db_session, 7.5)
        db_session.flush()
        assert get_daily_target_hours(db_session) == 7.5

    def test_exactly_one_timeline_row_setting_after_multiple_sets(self, db_session):
        # The single-field write is non-destructive but must not accumulate DB rows:
        # storage stays a single `daily_target_timeline` KV row, holding a one-row schedule.
        for hours in [4.0, 6.0, 8.0, 7.5]:
            set_daily_target_hours(db_session, hours)
            db_session.flush()
        count = db_session.scalar(
            select(func.count()).select_from(Setting).where(Setting.key == DAILY_TARGET_TIMELINE)
        )
        assert count == 1
        assert len(get_daily_target_schedule(db_session).rows) == 1

    def test_fractional_hours_preserved(self, db_session):
        set_daily_target_hours(db_session, 7.75)
        db_session.flush()
        assert get_daily_target_hours(db_session) == 7.75


# ── daily-target schedule (date-effective target) ──────────────────────────


class TestDailyTargetSchedule:
    def test_falls_back_to_legacy_single_value_before_any_timeline(self, db_session):
        db_session.add(Setting(key=DAILY_TARGET_HOURS, value="6"))
        db_session.flush()
        sched = get_daily_target_schedule(db_session)
        assert sched.for_date(date(2026, 1, 1)) == 6.0

    def test_set_and_get_schedule_round_trip(self, db_session):
        sched = DailyTargetSchedule.from_rows([(date(2025, 1, 1), 8.0), (date(2026, 7, 1), 6.0)])
        set_daily_target_schedule(db_session, sched)
        db_session.flush()
        loaded = get_daily_target_schedule(db_session)
        assert loaded.rows == ((date(2025, 1, 1), 8.0), (date(2026, 7, 1), 6.0))

    def test_get_hours_on_date_resolves_from_schedule(self, db_session):
        set_daily_target_schedule(
            db_session,
            DailyTargetSchedule.from_rows([(date(2025, 1, 1), 8.0), (date(2026, 7, 1), 6.0)]),
        )
        db_session.flush()
        assert get_daily_target_hours(db_session, on=date(2026, 6, 30)) == 8.0
        assert get_daily_target_hours(db_session, on=date(2026, 7, 15)) == 6.0

    def test_get_hours_without_date_returns_current_latest_row(self, db_session):
        set_daily_target_schedule(
            db_session,
            DailyTargetSchedule.from_rows([(date(2025, 1, 1), 8.0), (date(2026, 7, 1), 6.0)]),
        )
        db_session.flush()
        assert get_daily_target_hours(db_session) == 6.0  # the current contracted target

    def test_single_field_write_updates_latest_row_non_destructively(self, db_session):
        # A timeline with a real contract change; setting the single field must only
        # touch the current (latest) row, preserving earlier history.
        set_daily_target_schedule(
            db_session,
            DailyTargetSchedule.from_rows([(date(2025, 1, 1), 8.0), (date(2026, 7, 1), 6.0)]),
        )
        db_session.flush()
        set_daily_target_hours(db_session, 5.0)
        db_session.flush()
        assert get_daily_target_schedule(db_session).rows == (
            (date(2025, 1, 1), 8.0),  # earlier row untouched
            (date(2026, 7, 1), 5.0),  # only the current row changed
        )


# ── get_cumulative_start_date ──────────────────────────────────────────────


class TestGetCumulativeStartDate:
    def test_returns_default_when_no_row(self, db_session):
        assert get_cumulative_start_date(db_session) == date.fromisoformat(
            DEFAULT_CUMULATIVE_START_DATE
        )

    def test_returns_date_type(self, db_session):
        assert isinstance(get_cumulative_start_date(db_session), date)

    def test_returns_stored_value(self, db_session):
        db_session.add(Setting(key=CUMULATIVE_START_DATE, value="2024-06-15"))
        db_session.flush()
        assert get_cumulative_start_date(db_session) == date(2024, 6, 15)

    def test_year_boundary_date(self, db_session):
        db_session.add(Setting(key=CUMULATIVE_START_DATE, value="2023-12-31"))
        db_session.flush()
        assert get_cumulative_start_date(db_session) == date(2023, 12, 31)

    def test_leap_day(self, db_session):
        db_session.add(Setting(key=CUMULATIVE_START_DATE, value="2024-02-29"))
        db_session.flush()
        assert get_cumulative_start_date(db_session) == date(2024, 2, 29)


# ── set_cumulative_start_date ──────────────────────────────────────────────


class TestSetCumulativeStartDate:
    def test_creates_row_and_can_be_read_back(self, db_session):
        set_cumulative_start_date(db_session, date(2024, 6, 1))
        db_session.flush()
        assert get_cumulative_start_date(db_session) == date(2024, 6, 1)

    def test_updates_existing_row(self, db_session):
        set_cumulative_start_date(db_session, date(2024, 1, 1))
        db_session.flush()
        set_cumulative_start_date(db_session, date(2025, 6, 1))
        db_session.flush()
        assert get_cumulative_start_date(db_session) == date(2025, 6, 1)

    def test_exactly_one_row_after_multiple_sets(self, db_session):
        for d in [date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1)]:
            set_cumulative_start_date(db_session, d)
            db_session.flush()  # flush each write so identity map sees the row
        count = db_session.scalar(
            select(func.count()).select_from(Setting).where(Setting.key == CUMULATIVE_START_DATE)
        )
        assert count == 1
