"""Unit tests for the settings read/write service (app.services.settings).

Each function is tested in isolation using the db_session fixture (in-memory
SQLite, no HTTP layer involved).
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from app.config import DEFAULT_CUMULATIVE_START_DATE, DEFAULT_DAILY_TARGET_HOURS
from app.models import Setting
from app.services.settings import (
    CUMULATIVE_START_DATE,
    DAILY_TARGET_HOURS,
    get_cumulative_start_date,
    get_daily_target_hours,
    set_cumulative_start_date,
    set_daily_target_hours,
)


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

    def test_exactly_one_row_exists_after_multiple_sets(self, db_session):
        for hours in [4.0, 6.0, 8.0, 7.5]:
            set_daily_target_hours(db_session, hours)
            db_session.flush()  # flush each write so identity map sees the row
        count = db_session.scalar(
            select(func.count()).select_from(Setting).where(Setting.key == DAILY_TARGET_HOURS)
        )
        assert count == 1

    def test_fractional_hours_preserved(self, db_session):
        set_daily_target_hours(db_session, 7.75)
        db_session.flush()
        assert get_daily_target_hours(db_session) == 7.75


# ── get_cumulative_start_date ──────────────────────────────────────────────


class TestGetCumulativeStartDate:
    def test_returns_default_when_no_row(self, db_session):
        assert get_cumulative_start_date(db_session) == date.fromisoformat(DEFAULT_CUMULATIVE_START_DATE)

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
