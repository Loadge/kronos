"""The printable timesheet's rows, totals and hour formatting."""

from __future__ import annotations

from datetime import date

import pytest
from app.models import Break, DayType, WorkEntry
from app.services.computations import DailyTargetSchedule
from app.services.timesheet import (
    build_timesheet,
    fmt_days,
    fmt_hours,
    fmt_signed,
    period_label,
)

T8 = DailyTargetSchedule.constant(8.0)
MON_FRI = [0, 1, 2, 3, 4]
TODAY = date(2026, 9, 30)


def _work(d, start="09:00", end="17:30", breaks=(30,)):
    e = WorkEntry(date=d, day_type=DayType.WORK, start_time=start, end_time=end)
    e.breaks = [Break(break_minutes=m) for m in breaks]
    return e


def _leave(d, day_type="vacation", fraction=1.0, start=None, end=None, notes=None):
    return WorkEntry(
        date=d, day_type=day_type, fraction=fraction, start_time=start, end_time=end, notes=notes
    )


def _sheet(
    entries, start=date(2026, 9, 1), end=date(2026, 9, 30), today=TODAY, style="dec", week=MON_FRI
):
    return build_timesheet(
        entries,
        start=start,
        end=end,
        today=today,
        schedule=T8,
        work_week_days=week,
        hours_style=style,
    )


class TestFormatting:
    @pytest.mark.parametrize(
        "hours, dec, hm",
        [
            (7.5, "7.50", "7:30"),
            (8, "8.00", "8:00"),
            (0.25, "0.25", "0:15"),
            (0, "0.00", "0:00"),
            (-1.75, "−1.75", "−1:45"),
            (9.1, "9.10", "9:06"),
        ],
    )
    def test_fmt_hours(self, hours, dec, hm):
        assert fmt_hours(hours, "dec") == dec
        assert fmt_hours(hours, "hm") == hm

    def test_fmt_signed(self):
        assert fmt_signed(1.5, "hm") == "+1:30"
        assert fmt_signed(-0.25, "hm") == "−0:15"
        assert fmt_signed(0, "dec") == "±0.00"
        assert fmt_signed(0.004, "dec") == "±0.00"

    def test_fmt_days(self):
        assert fmt_days(19.5) == "19.5"
        assert fmt_days(20.0) == "20"
        assert fmt_days(0.375) == "0.38"


class TestPeriodLabel:
    def test_whole_month(self):
        assert period_label(date(2026, 9, 1), date(2026, 9, 30)) == "September 2026"

    def test_whole_year(self):
        assert period_label(date(2026, 1, 1), date(2026, 12, 31)) == "2026"

    def test_whole_months(self):
        assert period_label(date(2026, 8, 1), date(2026, 9, 30)) == "August – September 2026"

    def test_partial_range(self):
        assert period_label(date(2026, 3, 3), date(2026, 4, 14)) == "3 Mar – 14 Apr 2026"

    def test_year_to_date(self):
        assert period_label(date(2026, 1, 1), date(2026, 10, 26)) == "1 Jan – 26 Oct 2026"

    def test_cross_year(self):
        assert period_label(date(2025, 12, 15), date(2026, 1, 10)) == "2025-12-15 – 2026-01-10"


class TestRows:
    def test_every_calendar_day_is_listed(self):
        ts = _sheet([])
        assert len(ts.months) == 1
        assert len(ts.months[0].rows) == 30
        assert ts.months[0].rows[0].day == "01"
        assert ts.months[0].rows[0].weekday == "Tue"
        assert not ts.multi_month

    def test_weekend_and_gap_kinds(self):
        ts = _sheet([_work(date(2026, 9, 1))])
        rows = {r.date: r for r in ts.months[0].rows}
        assert rows[date(2026, 9, 1)].kind == "work"
        assert rows[date(2026, 9, 2)].kind == "gap"  # past work-week day, unlogged
        assert rows[date(2026, 9, 5)].kind == "empty"  # Saturday
        assert rows[date(2026, 9, 5)].weekend

    def test_future_days_are_empty_not_gaps(self):
        ts = _sheet([], today=date(2026, 9, 10))
        rows = {r.date: r for r in ts.months[0].rows}
        assert rows[date(2026, 9, 10)].kind == "gap"  # today counts
        assert rows[date(2026, 9, 11)].kind == "empty"
        assert ts.totals.gaps == 8  # Sep 1–10 has eight Mon–Fri days

    def test_work_row_numbers(self):
        ts = _sheet([_work(date(2026, 9, 1), "09:00", "18:00", (60,))], style="hm")
        r = ts.months[0].rows[0]
        assert (r.start, r.end, r.breaks, r.net, r.target) == (
            "09:00",
            "18:00",
            "1:00",
            "8:00",
            "8:00",
        )
        assert r.delta == "±0:00" and r.delta_sign == 0
        assert r.running == "±0:00"

    def test_whole_day_leave_prints_blank_numbers_but_keeps_running(self):
        ts = _sheet(
            [_work(date(2026, 9, 1), "09:00", "18:30", (30,)), _leave(date(2026, 9, 2), "holiday")]
        )
        r1, r2 = ts.months[0].rows[:2]
        assert r1.delta == "+1.00"
        assert r2.kind == "leave"
        assert r2.type_label == "holiday"
        assert (r2.net, r2.target, r2.delta) == ("", "", "")
        assert r2.running == "+1.00" and r2.running_sign == 1

    def test_partial_leave_shows_its_hours_and_numbers(self):
        ts = _sheet([_leave(date(2026, 9, 1), "vacation", 0.5, "09:00", "13:00")])
        r = ts.months[0].rows[0]
        assert r.kind == "partial"
        assert r.type_label == "vacation · 4h"
        assert (r.net, r.target, r.delta) == ("4.00", "4.00", "±0.00")

    def test_flex_day_is_blank_numbers_but_drains_running(self):
        ts = _sheet([_leave(date(2026, 9, 1), "flex")])
        r = ts.months[0].rows[0]
        assert (r.net, r.target, r.delta) == ("", "", "")
        assert r.running == "−8.00" and r.running_sign == -1

    def test_notes_are_stripped(self):
        ts = _sheet([_leave(date(2026, 9, 1), "sick", notes="  dentist \n")])
        assert ts.months[0].rows[0].notes == "dentist"

    def test_custom_work_week_marks_friday_as_weekend(self):
        ts = _sheet([], week=[0, 1, 2, 3])
        rows = {r.date: r for r in ts.months[0].rows}
        assert rows[date(2026, 9, 4)].weekend  # Friday
        assert rows[date(2026, 9, 4)].kind == "empty"


class TestTotals:
    def test_month_totals(self):
        entries = [
            _work(date(2026, 9, 1), "09:00", "18:00", (60,)),  # 8
            _work(date(2026, 9, 2), "09:00", "19:00", (60,)),  # 9
            _leave(date(2026, 9, 3), "vacation"),
            _leave(date(2026, 9, 4), "sick", 0.5, "09:00", "13:00"),  # 4 / 4
        ]
        ts = _sheet(entries, today=date(2026, 9, 4))
        t = ts.totals
        assert t.net == 21.0
        assert t.target == 20.0
        assert t.balance == 1.0
        assert t.work_days == 2.5
        assert t.off_days == 1.5
        assert (t.vacation, t.sick, t.holiday, t.flex) == (1.0, 0.5, 0, 0)
        assert t.gaps == 0

    def test_multi_month_sections_and_grand_totals(self):
        entries = [
            _work(date(2026, 8, 31), "09:00", "18:00", (60,)),
            _work(date(2026, 9, 1), "09:00", "18:00", (60,)),
        ]
        ts = _sheet(entries, start=date(2026, 8, 1), end=date(2026, 9, 30))
        assert ts.multi_month
        assert [m.abbr for m in ts.months] == ["Aug", "Sep"]
        assert ts.months[0].label == "August 2026"
        assert ts.months[0].totals.net == 8.0
        assert ts.months[1].totals.net == 8.0
        assert ts.totals.net == 16.0
        assert ts.months[0].totals.gaps == 20  # Aug 2026 has 21 Mon–Fri days, one logged
        assert ts.period_label == "August – September 2026"

    def test_running_balance_spans_months(self):
        entries = [
            _work(date(2026, 8, 31), "09:00", "19:00", (60,)),
            _work(date(2026, 9, 1), "09:00", "19:00", (60,)),
        ]
        ts = _sheet(entries, start=date(2026, 8, 31), end=date(2026, 9, 1))
        assert ts.months[1].rows[0].running == "+2.00"

    def test_end_before_start_rejected(self):
        with pytest.raises(ValueError):
            _sheet([], start=date(2026, 9, 2), end=date(2026, 9, 1))
