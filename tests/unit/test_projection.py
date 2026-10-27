"""Time-off projection maths: carrying the balance to a horizon with drafts."""

from __future__ import annotations

from datetime import date

from app.models import Break, DayType, Plan, WorkEntry
from app.services.computations import DailyTargetSchedule, project_balance

MON_FRI = [0, 1, 2, 3, 4]
T8 = DailyTargetSchedule.constant(8.0)


def _draft(d, day_type="vacation", fraction=1.0):
    return Plan(date=d, day_type=day_type, fraction=fraction)


def _project(
    entries=(),
    drafts=(),
    balance=10.0,
    pace=0.5,
    start=date(2026, 11, 2),
    end=date(2026, 11, 6),
    schedule=T8,
    week=MON_FRI,
):
    return project_balance(
        balance_today=balance,
        pace_per_day=pace,
        start=start,
        end=end,
        work_week_days=week,
        entries_by_date={e.date: e for e in entries},
        drafts_by_date={p.date: p for p in drafts},
        schedule=schedule,
    )


class TestEmptyWeek:
    def test_on_target_keeps_the_balance(self):
        pr = _project()
        assert pr.on_target == 10.0
        assert pr.scheduled_days_left == 5
        assert pr.open_days_left == 5
        assert pr.drafted_days == 0

    def test_at_pace_adds_pace_per_scheduled_day(self):
        assert _project().at_pace == 12.5  # 10 + 5 × 0.5

    def test_weekend_days_add_nothing(self):
        pr = _project(start=date(2026, 11, 7), end=date(2026, 11, 8))  # Sat, Sun
        assert pr.scheduled_days_left == 0
        assert pr.at_pace == 10.0


class TestDrafts:
    def test_vacation_is_neutral_on_target_and_skips_the_pace(self):
        pr = _project(drafts=[_draft(date(2026, 11, 3))])
        assert pr.on_target == 10.0
        assert pr.at_pace == 12.0  # 4 open days × 0.5
        assert pr.drafted_days == 1
        assert pr.open_days_left == 4
        assert pr.scheduled_days_left == 5

    def test_holiday_behaves_like_vacation(self):
        assert _project(drafts=[_draft(date(2026, 11, 3), "holiday")]).on_target == 10.0

    def test_flex_drains_the_target_of_that_date(self):
        pr = _project(drafts=[_draft(date(2026, 11, 3), "flex")])
        assert pr.on_target == 2.0
        assert pr.drafted_flex_hours == 8.0
        assert pr.at_pace == 4.0  # 10 − 8 + 4 × 0.5

    def test_flex_uses_the_date_effective_target(self):
        sched = DailyTargetSchedule.from_rows([(date(2026, 1, 1), 8.0), (date(2026, 11, 3), 6.0)])
        pr = _project(drafts=[_draft(date(2026, 11, 3), "flex")], schedule=sched)
        assert pr.drafted_flex_hours == 6.0
        assert pr.on_target == 4.0

    def test_partial_draft_counts_its_share(self):
        pr = _project(drafts=[_draft(date(2026, 11, 3), "flex", 0.5)])
        assert pr.drafted_days == 0.5
        assert pr.drafted_flex_hours == 4.0
        assert pr.on_target == 6.0
        assert pr.open_days_left == 4.5
        assert pr.at_pace == 6.0 + 4.5 * 0.5

    def test_draft_on_a_weekend_counts_but_has_no_worked_share(self):
        pr = _project(
            drafts=[_draft(date(2026, 11, 7), "flex")],
            start=date(2026, 11, 7),
            end=date(2026, 11, 7),
        )
        assert pr.drafted_days == 1
        assert pr.on_target == 2.0
        assert pr.scheduled_days_left == 0
        assert pr.open_days_left == 0


class TestRealFutureEntries:
    def test_logged_holiday_counts_as_real_and_not_scheduled(self):
        hol = WorkEntry(date=date(2026, 11, 3), day_type=DayType.HOLIDAY)
        pr = _project(entries=[hol])
        assert pr.on_target == 10.0
        assert pr.scheduled_days_left == 4
        assert pr.at_pace == 12.0

    def test_real_entry_wins_over_a_draft_on_the_same_date(self):
        hol = WorkEntry(date=date(2026, 11, 3), day_type=DayType.HOLIDAY)
        pr = _project(entries=[hol], drafts=[_draft(date(2026, 11, 3), "flex")])
        assert pr.on_target == 10.0
        assert pr.drafted_days == 0
        assert pr.drafted_flex_hours == 0

    def test_day_logged_ahead_contributes_its_surplus(self):
        e = WorkEntry(
            date=date(2026, 11, 3), day_type=DayType.WORK, start_time="09:00", end_time="19:00"
        )
        e.breaks = [Break(break_minutes=60)]  # 9h worked → +1
        pr = _project(entries=[e])
        assert pr.on_target == 11.0
        assert pr.at_pace == 11.0 + 4 * 0.5

    def test_future_flex_entry_drains(self):
        e = WorkEntry(date=date(2026, 11, 3), day_type=DayType.FLEX)
        assert _project(entries=[e]).on_target == 2.0


class TestHorizon:
    def test_start_after_end_is_a_no_op(self):
        pr = _project(start=date(2026, 12, 31), end=date(2026, 12, 30))
        assert pr.on_target == 10.0 and pr.scheduled_days_left == 0

    def test_custom_work_week(self):
        pr = _project(week=[0, 1, 2, 3])  # Mon–Thu
        assert pr.scheduled_days_left == 4
        assert pr.at_pace == 12.0
