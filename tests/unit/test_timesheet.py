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


# ---------- the freelance sheet -----------------------------------------------------


class TestFreelanceSheet:
    def test_fmt_money(self):
        from app.services.timesheet import fmt_money

        assert fmt_money(170.068) == "€170.07"
        assert fmt_money(190, "USD") == "$190.00"
        assert fmt_money(12345.5) == "€12,345.50"
        assert fmt_money(0.125) == "€0.13"  # a half cent up, like tax.money
        assert fmt_money(-3) == "−€3.00"

    def test_rows_totals_and_months(self):
        from datetime import date
        from types import SimpleNamespace

        from app.services.timesheet import build_freelance_timesheet

        src = SimpleNamespace(name="Northwind")
        blocks = [
            SimpleNamespace(
                id=2,
                date=date(2026, 11, 2),
                minutes=90,
                start_time=None,
                end_time=None,
                rate=60.0,
                currency="EUR",
                fx_rate=None,
                amount=90.0,
                amount_eur=90.0,
                notes=None,
                source=SimpleNamespace(name="Local"),
            ),
            SimpleNamespace(
                id=1,
                date=date(2026, 10, 31),
                minutes=240,
                start_time="09:30",
                end_time="13:30",
                rate=95.0,
                currency="USD",
                fx_rate=1.1172,
                amount=380.0,
                amount_eur=380 / 1.1172,
                notes="report",
                source=src,
            ),
            SimpleNamespace(
                id=3,
                date=date(2026, 10, 3),
                minutes=60,
                start_time=None,
                end_time=None,
                rate=95.0,
                currency="USD",
                fx_rate=None,
                amount=95.0,
                amount_eur=None,
                notes=None,
                source=src,
            ),
        ]
        sheet = build_freelance_timesheet(
            blocks,
            start=date(2026, 10, 1),
            end=date(2026, 11, 30),
            sources=["Northwind", "Local"],
            work_week_days=[0, 1, 2, 3, 4],
            hours_style="dec",
        )
        assert sheet.multi_month and [m.abbr for m in sheet.months] == ["Oct", "Nov"]
        oct_rows = sheet.months[0].rows
        assert [r.day for r in oct_rows] == ["03", "31"]  # sorted by date whatever the ids
        assert (oct_rows[1].hours, oct_rows[1].rate, oct_rows[1].amount, oct_rows[1].eur) == (
            "4.00",
            "$95.00",
            "$380.00",
            "€340.14",
        )
        assert oct_rows[0].missing_fx and oct_rows[0].eur == "" and oct_rows[0].weekend
        t = sheet.months[0].totals
        assert (t.blocks, t.minutes, t.missing_fx) == (2, 300, 1)
        assert t.amounts_label == "$475.00"
        assert sheet.totals.amounts_label == "€90.00 · $475.00"  # euros first
        assert sheet.totals.eur == pytest.approx(90 + 380 / 1.1172)
        assert sheet.totals.hours == pytest.approx(6.5)


# ---------- the freelance sheet with payouts ----------------------------------------


def _blk(id, d, minutes, rate, currency, source, fx=None):
    from types import SimpleNamespace

    amount = minutes / 60 * rate
    return SimpleNamespace(
        id=id,
        date=d,
        minutes=minutes,
        start_time=None,
        end_time=None,
        rate=rate,
        currency=currency,
        fx_rate=fx,
        amount=amount,
        amount_eur=amount if currency == "EUR" else amount / fx,
        notes=None,
        source=source,
    )


def _line(d, block, amount, eur, payout_id, currency, source_id=1):
    from app.services.freelance import Line

    return Line(
        date=d,
        source_id=source_id,
        block_id=None if block is None else block.id,
        minutes=0 if block is None else block.minutes,
        amount=amount,
        est_eur=None,
        eur=eur,
        paid=payout_id is not None,
        payout_id=payout_id,
        currency=currency,
    )


def _payout(id, week_start, amount, currency, source, fx=None, note=None, source_id=1):
    from types import SimpleNamespace

    return SimpleNamespace(
        id=id,
        source_id=source_id,
        week_start=week_start,
        amount=amount,
        currency=currency,
        note=note,
        source=source,
        amount_eur=amount if currency == "EUR" else (amount / fx if fx else None),
    )


def _freelance(blocks, lines, payouts, start=date(2026, 10, 1), end=date(2026, 11, 30)):
    from app.services.timesheet import build_freelance_timesheet

    return build_freelance_timesheet(
        blocks,
        start=start,
        end=end,
        sources=["Northwind", "Local"],
        work_week_days=MON_FRI,
        lines=lines,
        payouts=payouts,
    )


class TestFreelanceSheetPayouts:
    NORTH = type("S", (), {"name": "Northwind"})()
    LOCAL = type("S", (), {"name": "Local"})()

    def test_payout_row_follows_the_last_block_and_the_totals_use_it(self):
        # $237.50 of blocks (2.5 h at $95), paid $300.00 at 1.1172 -> 268.53 EUR
        b = _blk(1, date(2026, 10, 27), 150, 95.0, "USD", self.NORTH, fx=1.1172)
        p = _payout(7, date(2026, 10, 26), 300.0, "USD", self.NORTH, fx=1.1172)
        sheet = _freelance(
            [b], [_line(b.date, b, 300.0, 268.53, 7, "USD")], [p], end=date(2026, 10, 31)
        )
        rows = sheet.months[0].rows
        assert [r.is_payout for r in rows] == [False, True]
        assert rows[0].amount == "$237.50" and rows[0].eur == "€212.59"  # the block's own estimate
        assert rows[1].text == "W44 payout $300.00 · +$62.50 over the estimate"
        assert (rows[1].eur, rows[1].source, rows[1].missing_fx) == ("€268.53", "Northwind", False)
        t = sheet.totals
        assert t.eur == pytest.approx(268.53) and t.amounts_label == "$300.00"
        assert (t.blocks, t.minutes) == (1, 150) and sheet.has_payouts

    def test_under_the_estimate_and_a_payout_without_a_rate(self):
        b = _blk(1, date(2026, 10, 27), 90, 60.0, "EUR", self.LOCAL)  # EUR 90.00
        p = _payout(2, date(2026, 10, 26), 40.0, "EUR", self.LOCAL, source_id=2)
        sheet = _freelance(
            [b], [_line(b.date, b, 40.0, 40.0, 2, "EUR", 2)], [p], end=date(2026, 10, 31)
        )
        assert sheet.months[0].rows[1].text == "W44 payout €40.00 · -€50.00 under the estimate"
        assert sheet.totals.eur == pytest.approx(40.0)

        usd = _blk(3, date(2026, 10, 28), 60, 95.0, "USD", self.NORTH, fx=1.1172)
        p2 = _payout(4, date(2026, 10, 26), 100.0, "USD", self.NORTH, fx=None)  # no rate: no euros
        sheet = _freelance(
            [usd], [_line(usd.date, usd, 100.0, None, 4, "USD")], [p2], end=date(2026, 10, 31)
        )
        row = sheet.months[0].rows[1]
        assert row.missing_fx and row.eur == "" and "+$5.00 over" in row.text
        assert sheet.totals.eur == 0 and sheet.totals.missing_fx == 1  # never 1:1 for dollars

    def test_a_payout_with_no_blocks_prints_alone_in_the_month_of_its_sunday(self):
        b = _blk(1, date(2026, 10, 5), 60, 60.0, "EUR", self.LOCAL)
        p = _payout(9, date(2026, 10, 26), 500.0, "EUR", self.LOCAL, note="bonus", source_id=2)
        sunday = date(2026, 11, 1)
        sheet = _freelance([b], [_line(sunday, None, 500.0, 500.0, 9, "EUR", 2)], [p])
        assert [m.abbr for m in sheet.months] == ["Oct", "Nov"]
        row = sheet.months[1].rows[0]
        assert row.is_payout and row.notes == "bonus"
        assert row.text == "W44 payout €500.00 · no blocks that week"
        nov = sheet.months[1].totals
        assert (nov.blocks, nov.minutes, nov.eur) == (0, 0, 500.0)
        assert sheet.totals.eur == pytest.approx(500.0 + 60.0)  # the Oct block counts its estimate

    def test_a_week_across_months_splits_the_payout_by_line_and_prints_one_row(self):
        # Mon 26 Oct .. Sun 1 Nov: blocks Thu 29 Oct (EUR 60) and Sun 1 Nov (EUR 120), paid 150
        a = _blk(1, date(2026, 10, 29), 60, 60.0, "EUR", self.LOCAL)
        c = _blk(2, date(2026, 11, 1), 120, 60.0, "EUR", self.LOCAL)
        p = _payout(5, date(2026, 10, 26), 150.0, "EUR", self.LOCAL, source_id=2)
        lines = [
            _line(a.date, a, 50.0, 50.0, 5, "EUR", 2),
            _line(c.date, c, 100.0, 100.0, 5, "EUR", 2),
        ]
        sheet = _freelance([c, a], lines, [p])
        oct_, nov = sheet.months
        assert [r.is_payout for r in oct_.rows] == [
            False
        ]  # the row waits for the week's last block
        assert [r.is_payout for r in nov.rows] == [False, True]
        assert nov.rows[1].text == "W44 payout €150.00 · -€30.00 under the estimate"
        assert (oct_.totals.eur, nov.totals.eur, sheet.totals.eur) == (50.0, 100.0, 150.0)
        assert sheet.totals.blocks == 2

    def test_without_a_payout_the_lines_change_nothing(self):
        b = _blk(1, date(2026, 10, 27), 150, 95.0, "USD", self.NORTH, fx=1.1172)
        plain = _freelance([b], [], [], end=date(2026, 10, 31))
        unpaid = _freelance(
            [b], [_line(b.date, b, 237.5, 212.58, None, "USD")], [], end=date(2026, 10, 31)
        )
        assert unpaid == plain and not plain.has_payouts
        assert plain.totals.eur == 237.5 / 1.1172  # the unrounded sum it always was
