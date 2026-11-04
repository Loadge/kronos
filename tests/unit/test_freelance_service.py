"""The pure parts of app.services.freelance: weeks left in a year, the sums of blocks."""

from __future__ import annotations

from datetime import date

import pytest
from app.models import FreelanceBlock, FreelancePayout, IncomeSource
from app.services.freelance import Line, Sum, _weeks_left, money_lines, split_cents, sum_lines


class TestWeeksLeft:
    def test_spreads_the_days_off_over_the_year(self):
        # mid-year, 28 days off: half the year left, half the days off still ahead
        # (183 - 28 * 183 / 365) / 7 = (183 - 14.0384) / 7 = 24.1374
        assert _weeks_left(date(2026, 7, 1), 2026, 28) == pytest.approx(24.1374, abs=1e-4)

    def test_no_days_off(self):
        assert _weeks_left(date(2026, 12, 24), 2026, 0) == pytest.approx(1.0)

    def test_before_the_year_is_the_whole_year(self):
        assert _weeks_left(date(2025, 11, 1), 2026, 0) == pytest.approx(365 / 7)
        assert _weeks_left(date(2025, 11, 1), 2026, 35) == pytest.approx(330 / 7)

    def test_the_year_over_is_zero_and_never_negative(self):
        assert _weeks_left(date(2026, 12, 31), 2026, 0) == 0
        assert _weeks_left(date(2027, 3, 1), 2026, 0) == 0
        assert _weeks_left(date(2026, 12, 30), 2026, 365) == 0


def _b(minutes: int, rate: float, currency: str, fx: float | None) -> Line:
    block = FreelanceBlock(
        date=date(2026, 3, 2),
        source_id=1,
        minutes=minutes,
        rate=rate,
        currency=currency,
        fx_rate=fx,
    )
    eur = block.amount_eur
    return Line(block.date, 1, 1, minutes, block.amount, eur, eur, False, None, currency)


class TestSums:
    def test_eur_and_usd_blocks_add_up_in_euros(self):
        # 90 min at 60 EUR = 90.00; 2 h at $95 / 1.25 = 152.00
        s = sum_lines([_b(90, 60, "EUR", None), _b(120, 95, "USD", 1.25)])
        assert (s.minutes, s.hours, s.blocks, s.missing) == (210, 3.5, 2, 0)
        assert s.gross_eur == pytest.approx(242.0)
        assert s.eur_per_hour == pytest.approx(242 / 3.5)

    def test_a_usd_block_without_a_rate_counts_its_hours_but_not_its_money(self):
        s = sum_lines([_b(60, 100, "USD", None)])
        assert (s.hours, s.gross_eur, s.missing) == (1.0, 0.0, 1)
        assert s.out() == {
            "hours": 1.0,
            "gross_eur": 0.0,
            "eur_per_hour": 0.0,
            "blocks": 1,
            "missing_fx": 1,
            "paid_out_eur": 0.0,
            "estimated_eur": 0.0,
        }

    def test_empty(self):
        assert Sum().out()["eur_per_hour"] == 0.0

    def test_paid_and_estimated_lines_are_told_apart(self):
        paid = Line(date(2026, 3, 2), 1, 1, 60, 10.0, 8.0, 10.0, True, 5)
        est = Line(date(2026, 3, 3), 1, 2, 60, 20.0, 20.0, 20.0, False, None)
        s = sum_lines([paid, est])
        assert (s.gross_eur, s.paid_out_eur, s.estimated_eur) == (30.0, 10.0, 20.0)


class TestSplitCents:
    def test_largest_remainder_two_weights(self):
        # 25000 * 2/3 = 16666.67 and 25000 * 1/3 = 8333.33: the spare cent goes to the first
        assert split_cents(25000, [200, 100]) == [16667, 8333]

    def test_ties_go_to_the_earlier_position(self):
        assert split_cents(100, [1, 1, 1]) == [34, 33, 33]

    def test_the_shares_always_add_up_to_the_total(self):
        for total in (0, 1, 7, 99, 12345):
            for weights in ([1], [3, 1, 1], [0.1, 0.2, 0.7], [5, 5, 5, 5, 5, 5, 5]):
                assert sum(split_cents(total, weights)) == total

    def test_weights_of_nothing_split_evenly(self):
        assert split_cents(10, [0, 0]) == [5, 5]

    def test_no_weights(self):
        assert split_cents(10, []) == []


class TestMoneyLines:
    def _source(self, db_session, currency="EUR"):
        src = IncomeSource(name="S", hourly_rate=50, currency=currency)
        db_session.add(src)
        db_session.commit()
        return src

    def test_a_payout_with_no_blocks_is_one_line_on_the_sunday(self, db_session):
        src = self._source(db_session)
        db_session.add(
            FreelancePayout(
                source_id=src.id, week_start=date(2026, 1, 12), amount=100.0, currency="EUR"
            )
        )
        db_session.commit()
        (line,) = money_lines(db_session, date(2026, 1, 1), date(2026, 1, 31))
        assert (line.date, line.block_id, line.minutes) == (date(2026, 1, 18), None, 0)
        assert (line.eur, line.paid, line.est_eur) == (100.0, True, None)
        # a range that stops before the Sunday does not see it
        assert money_lines(db_session, date(2026, 1, 12), date(2026, 1, 17)) == []

    def test_a_range_cutting_a_week_still_splits_the_whole_week(self, db_session):
        src = self._source(db_session)
        for day, minutes in ((date(2026, 1, 5), 240), (date(2026, 1, 7), 120)):
            db_session.add(
                FreelanceBlock(date=day, source_id=src.id, minutes=minutes, rate=50, currency="EUR")
            )
        db_session.add(
            FreelancePayout(
                source_id=src.id, week_start=date(2026, 1, 5), amount=250.0, currency="EUR"
            )
        )
        db_session.commit()
        # only the second half of the week is asked for: it still gets 83.33, not 250.00
        (line,) = money_lines(db_session, date(2026, 1, 6), date(2026, 1, 11))
        assert (line.date, line.eur) == (date(2026, 1, 7), 83.33)
