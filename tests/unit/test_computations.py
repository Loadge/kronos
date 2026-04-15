"""Unit tests for net-hours, period summaries, and calendar helpers."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models import Break, DayType, WorkEntry
from app.services.computations import (
    PeriodSummary,
    daily_net_hours,
    daily_target_for,
    iso_week_bounds,
    month_bounds,
    month_range,
    net_hours,
    net_minutes,
    summarize,
)


# ---------- factory ---------------------------------------------------------


def make_entry(
    d: date,
    *,
    day_type: DayType = DayType.WORK,
    start: str | None = "09:00",
    end: str | None = "17:00",
    breaks_min: list[int] | None = None,
) -> WorkEntry:
    if breaks_min is None:
        breaks_min = [60]
    entry = WorkEntry(
        date=d,
        day_type=day_type.value,
        start_time=start if day_type is DayType.WORK else None,
        end_time=end if day_type is DayType.WORK else None,
    )
    entry.breaks = [Break(break_minutes=m) for m in (breaks_min if day_type is DayType.WORK else [])]
    return entry


# ---------- net_minutes / net_hours ----------------------------------------


class TestNetMinutes:
    def test_simple(self):
        assert net_minutes("09:00", "17:00", 60) == 7 * 60

    def test_no_break(self):
        assert net_minutes("09:00", "17:30", 0) == 8 * 60 + 30

    def test_multiple_breaks_aggregated_upstream(self):
        # Caller passes the sum — here we just verify subtraction.
        assert net_minutes("08:00", "18:00", 90) == 10 * 60 - 90

    def test_missing_times_yields_zero(self):
        assert net_minutes(None, None, 0) == 0
        assert net_minutes("09:00", None, 0) == 0
        assert net_minutes(None, "17:00", 0) == 0

    def test_break_exceeds_span_clamps_to_zero(self):
        assert net_minutes("09:00", "10:00", 120) == 0

    def test_rejects_end_before_start(self):
        with pytest.raises(ValueError):
            net_minutes("17:00", "09:00", 0)


class TestNetHours:
    def test_round_trip(self):
        assert net_hours("09:00", "17:00", 60) == 7.0
        assert net_hours("09:00", "17:30", 0) == 8.5


# ---------- daily target / daily net hours ---------------------------------


class TestDailyTargetFor:
    @pytest.mark.parametrize(
        "day_type,expected",
        [
            (DayType.WORK, 8.0),
            (DayType.VACATION, 0.0),
            (DayType.SICK, 0.0),
            (DayType.HOLIDAY, 0.0),
        ],
    )
    def test_target(self, day_type, expected):
        entry = make_entry(date(2026, 4, 14), day_type=day_type)
        assert daily_target_for(entry, 8.0) == expected


class TestDailyNetHours:
    def test_work(self):
        e = make_entry(date(2026, 4, 14), start="09:00", end="17:00", breaks_min=[60])
        assert daily_net_hours(e) == 7.0

    @pytest.mark.parametrize("dt", [DayType.VACATION, DayType.SICK, DayType.HOLIDAY])
    def test_non_work(self, dt):
        e = make_entry(date(2026, 4, 14), day_type=dt)
        assert daily_net_hours(e) == 0.0


# ---------- summarize -------------------------------------------------------


class TestSummarize:
    def test_empty(self):
        s = summarize([], 8.0)
        assert s == PeriodSummary(0.0, 0.0, 0, 0)
        assert s.surplus_hours == 0.0

    def test_all_work_week(self):
        entries = [make_entry(date(2026, 4, 13) + timedelta(days=i)) for i in range(5)]
        s = summarize(entries, 8.0)
        assert s.target_hours == 40.0
        assert s.net_hours == 35.0  # 7h each
        assert s.surplus_hours == -5.0
        assert s.work_days == 5
        assert s.non_work_days == 0

    def test_mixed_week(self):
        # 3 work days (9→17 with 60min break = 7h each) + 1 vacation + 1 holiday
        base = date(2026, 4, 13)
        entries = [
            make_entry(base + timedelta(days=0)),
            make_entry(base + timedelta(days=1)),
            make_entry(base + timedelta(days=2)),
            make_entry(base + timedelta(days=3), day_type=DayType.VACATION),
            make_entry(base + timedelta(days=4), day_type=DayType.HOLIDAY),
        ]
        s = summarize(entries, 8.0)
        assert s.target_hours == 24.0  # 8 × 3 work days only
        assert s.net_hours == 21.0  # 7 × 3
        assert s.surplus_hours == -3.0
        assert s.work_days == 3
        assert s.non_work_days == 2

    def test_all_vacation(self):
        entries = [
            make_entry(date(2026, 4, 13) + timedelta(days=i), day_type=DayType.VACATION)
            for i in range(5)
        ]
        s = summarize(entries, 8.0)
        assert s.target_hours == 0.0
        assert s.net_hours == 0.0
        assert s.surplus_hours == 0.0

    def test_surplus_when_overworked(self):
        entries = [
            make_entry(date(2026, 4, 13), start="08:00", end="19:00", breaks_min=[60])
        ]  # 10h
        s = summarize(entries, 8.0)
        assert s.net_hours == 10.0
        assert s.target_hours == 8.0
        assert s.surplus_hours == 2.0


# ---------- calendar helpers ----------------------------------------------


class TestIsoWeekBounds:
    @pytest.mark.parametrize(
        "d,monday,sunday",
        [
            # 2026-04-14 is a Tuesday
            (date(2026, 4, 14), date(2026, 4, 13), date(2026, 4, 19)),
            (date(2026, 4, 13), date(2026, 4, 13), date(2026, 4, 19)),  # Monday itself
            (date(2026, 4, 19), date(2026, 4, 13), date(2026, 4, 19)),  # Sunday
            # Year boundary: 2026-01-01 is a Thursday
            (date(2026, 1, 1), date(2025, 12, 29), date(2026, 1, 4)),
        ],
    )
    def test_bounds(self, d, monday, sunday):
        assert iso_week_bounds(d) == (monday, sunday)


class TestMonthBounds:
    @pytest.mark.parametrize(
        "d,first,last",
        [
            (date(2026, 4, 14), date(2026, 4, 1), date(2026, 4, 30)),
            (date(2026, 12, 31), date(2026, 12, 1), date(2026, 12, 31)),
            (date(2024, 2, 14), date(2024, 2, 1), date(2024, 2, 29)),  # leap
            (date(2025, 2, 14), date(2025, 2, 1), date(2025, 2, 28)),  # non-leap
        ],
    )
    def test_bounds(self, d, first, last):
        assert month_bounds(d) == (first, last)


class TestMonthRange:
    def test_single_month(self):
        assert month_range(date(2026, 4, 1), date(2026, 4, 30)) == [(2026, 4)]

    def test_spans_year_boundary(self):
        assert month_range(date(2025, 11, 1), date(2026, 2, 1)) == [
            (2025, 11),
            (2025, 12),
            (2026, 1),
            (2026, 2),
        ]

    def test_start_equals_end_month(self):
        assert month_range(date(2026, 4, 10), date(2026, 4, 20)) == [(2026, 4)]
