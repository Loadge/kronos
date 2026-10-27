"""Partial-day leave math.

A leave entry carries ``fraction`` (the share of the day that is leave) and, when
partial, the hours worked in the rest of the day. The invariants under test:

* vacation / sick / holiday: target = T * (1 - fraction); whole day → 0.
* flex: target = T regardless of the fraction (the whole day charges the pool).
* net hours are counted on partial days, never on whole-day leave.
* summaries split a partial day into fractional work / non-work counts.
"""

from __future__ import annotations

from datetime import date

import pytest
from app.models import Break, DayType, WorkEntry
from app.services.computations import (
    DailyTargetSchedule,
    daily_net_hours,
    daily_target_for,
    leave_fraction,
    leave_hours_for,
    summarize,
)


def _leave(day_type, fraction=1.0, start=None, end=None, breaks=(), d=date(2026, 4, 14)):
    e = WorkEntry(date=d, day_type=day_type, fraction=fraction, start_time=start, end_time=end)
    e.breaks = [Break(break_minutes=m) for m in breaks]
    return e


def _work(start="09:00", end="17:00", breaks=(60,), d=date(2026, 4, 14)):
    e = WorkEntry(date=d, day_type=DayType.WORK, start_time=start, end_time=end)
    e.breaks = [Break(break_minutes=m) for m in breaks]
    return e


class TestModel:
    def test_fraction_defaults_to_whole_day_on_transient_objects(self):
        assert WorkEntry(date=date(2026, 1, 1), day_type="vacation").fraction == 1.0

    def test_is_partial(self):
        assert _leave("vacation", 0.5).is_partial
        assert not _leave("vacation", 1.0).is_partial
        # A work day is never "partial" whatever the column says.
        assert not WorkEntry(date=date(2026, 1, 1), day_type="work", fraction=0.5).is_partial


class TestLeaveFraction:
    def test_work_day_is_zero(self):
        assert leave_fraction(_work()) == 0.0

    def test_whole_day_leave_is_one(self):
        assert leave_fraction(_leave("sick")) == 1.0

    def test_partial(self):
        assert leave_fraction(_leave("vacation", 0.375)) == 0.375


class TestDailyTargetFor:
    @pytest.mark.parametrize("day_type", ["vacation", "sick", "holiday"])
    def test_leave_charges_only_the_worked_share(self, day_type):
        assert daily_target_for(_leave(day_type, 1.0), 8.0) == 0.0
        assert daily_target_for(_leave(day_type, 0.5), 8.0) == 4.0
        assert daily_target_for(_leave(day_type, 0.375), 8.0) == 5.0

    def test_flex_always_charges_the_full_target(self):
        assert daily_target_for(_leave("flex", 1.0), 8.0) == 8.0
        assert daily_target_for(_leave("flex", 0.5), 8.0) == 8.0

    def test_partial_leave_uses_the_target_in_force_on_that_date(self):
        schedule = DailyTargetSchedule.from_rows([(date(2026, 1, 1), 8.0), (date(2026, 6, 1), 6.0)])
        before = _leave("vacation", 0.5, d=date(2026, 5, 29))
        after = _leave("vacation", 0.5, d=date(2026, 6, 1))
        assert daily_target_for(before, schedule) == 4.0
        assert daily_target_for(after, schedule) == 3.0


class TestLeaveHours:
    def test_work_day_has_none(self):
        assert leave_hours_for(_work(), 8.0) == 0.0

    def test_whole_day_is_the_target(self):
        assert leave_hours_for(_leave("holiday"), 7.5) == 7.5

    def test_partial_is_fraction_times_target(self):
        assert leave_hours_for(_leave("vacation", 0.375), 8.0) == 3.0
        assert leave_hours_for(_leave("flex", 0.25), 8.0) == 2.0


class TestDailyNetHours:
    def test_whole_day_leave_is_zero_even_with_stray_times(self):
        # Validation forbids this, but the math must not trust it.
        assert daily_net_hours(_leave("vacation", 1.0, "09:00", "13:00")) == 0.0

    def test_partial_day_counts_the_worked_hours(self):
        assert daily_net_hours(_leave("vacation", 0.5, "09:00", "13:30", breaks=(30,))) == 4.0

    def test_partial_day_without_times_is_zero(self):
        assert daily_net_hours(_leave("sick", 0.5)) == 0.0


class TestSurplusScenarios:
    """The worked examples agreed for the phase (T = 8h, worked 09:00–13:00)."""

    def _surplus(self, e):
        return round(daily_net_hours(e) - daily_target_for(e, 8.0), 2)

    def test_half_vacation_with_its_hours_is_neutral(self):
        assert self._surplus(_leave("vacation", 0.5, "09:00", "13:00")) == 0.0

    def test_half_flex_with_its_hours_costs_half_the_target(self):
        assert self._surplus(_leave("flex", 0.5, "09:00", "13:00")) == -4.0

    def test_three_hours_sick_leaving_early(self):
        # 8h day, 3h sick → target 5h; worked 09:00–14:00 → 5h → neutral.
        assert self._surplus(_leave("sick", 0.375, "09:00", "14:00")) == 0.0

    def test_partial_vacation_without_hours_shows_the_shortfall(self):
        assert self._surplus(_leave("vacation", 0.5)) == -4.0


class TestSummarize:
    def test_partial_day_splits_the_day_counts(self):
        s = summarize([_leave("vacation", 0.375, "09:00", "14:00")], 8.0)
        assert s.work_days == 0.62  # 1 - 0.375, rounded to 2 decimals
        assert s.non_work_days == 0.38
        assert s.target_hours == 5.0
        assert s.net_hours == 5.0
        assert s.surplus_hours == 0.0

    def test_week_with_a_half_day_still_adds_up(self):
        days = [
            _work(d=date(2026, 4, 13)),
            _work(d=date(2026, 4, 14)),
            _work(d=date(2026, 4, 15)),
            _leave("vacation", 0.5, "09:00", "13:00", d=date(2026, 4, 16)),
            _leave("vacation", 1.0, d=date(2026, 4, 17)),
        ]
        s = summarize(days, 8.0)
        assert s.work_days == 3.5
        assert s.non_work_days == 1.5
        assert s.work_days + s.non_work_days == len(days)
        assert s.target_hours == 28.0  # 3 × 8 + 4 + 0
        assert s.net_hours == 25.0  # 3 × 7 + 4
        assert s.surplus_hours == -3.0

    def test_whole_days_unchanged(self):
        s = summarize([_work(), _leave("flex", d=date(2026, 4, 15))], 8.0)
        assert s.work_days == 1.0
        assert s.non_work_days == 1.0
        assert s.target_hours == 16.0
        assert s.surplus_hours == -9.0

    def test_partial_flex_charges_full_target_but_counts_fractional_days(self):
        s = summarize([_leave("flex", 0.25, "09:00", "15:00")], 8.0)
        assert s.target_hours == 8.0
        assert s.net_hours == 6.0
        assert s.surplus_hours == -2.0
        assert s.work_days == 0.75
        assert s.non_work_days == 0.25
