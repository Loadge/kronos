"""Unit tests for ORM model properties and the DayType enum."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import Break, DayType, WorkEntry
from app.services.computations import is_work_day


# ── DayType ────────────────────────────────────────────────────────────────


class TestDayType:
    def test_work_is_work(self):
        assert DayType.WORK.is_work is True

    @pytest.mark.parametrize("dt", [DayType.VACATION, DayType.SICK, DayType.HOLIDAY, DayType.FLEX])
    def test_non_work_types_are_not_work(self, dt):
        assert dt.is_work is False

    def test_values_are_lowercase_strings(self):
        assert DayType.WORK.value == "work"
        assert DayType.VACATION.value == "vacation"
        assert DayType.SICK.value == "sick"
        assert DayType.HOLIDAY.value == "holiday"
        assert DayType.FLEX.value == "flex"

    def test_is_str_subclass(self):
        # DayType(str, Enum) means the value IS the string
        assert DayType.WORK == "work"
        assert DayType.VACATION == "vacation"

    def test_all_five_variants_exist(self):
        assert len(DayType) == 5

    def test_from_string_value(self):
        assert DayType("work") is DayType.WORK
        assert DayType("vacation") is DayType.VACATION
        assert DayType("flex") is DayType.FLEX


# ── WorkEntry.total_break_minutes ──────────────────────────────────────────


def _work_entry(breaks_min=()):
    e = WorkEntry(
        date=date(2026, 4, 14),
        day_type=DayType.WORK.value,
        start_time="09:00",
        end_time="17:00",
    )
    e.breaks = [Break(break_minutes=m) for m in breaks_min]
    return e


class TestTotalBreakMinutes:
    def test_no_breaks_is_zero(self):
        assert _work_entry().total_break_minutes == 0

    def test_single_break(self):
        assert _work_entry((60,)).total_break_minutes == 60

    def test_multiple_breaks_are_summed(self):
        assert _work_entry((30, 15, 45)).total_break_minutes == 90

    def test_many_small_breaks(self):
        assert _work_entry((5,) * 12).total_break_minutes == 60


# ── is_work_day helper ─────────────────────────────────────────────────────


class TestIsWorkDay:
    @pytest.mark.parametrize("dt", [DayType.VACATION, DayType.SICK, DayType.HOLIDAY, DayType.FLEX])
    def test_non_work_entries(self, dt):
        e = WorkEntry(date=date(2026, 4, 14), day_type=dt.value)
        assert is_work_day(e) is False

    def test_work_entry(self):
        e = WorkEntry(
            date=date(2026, 4, 14),
            day_type=DayType.WORK.value,
            start_time="09:00",
            end_time="17:00",
        )
        assert is_work_day(e) is True
