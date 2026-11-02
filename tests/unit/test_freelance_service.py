"""The pure parts of app.services.freelance: weeks left in a year, the sums of blocks."""

from __future__ import annotations

from datetime import date

import pytest
from app.models import FreelanceBlock
from app.services.freelance import Sum, _weeks_left, sum_blocks


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


def _b(minutes: int, rate: float, currency: str, fx: float | None) -> FreelanceBlock:
    return FreelanceBlock(
        date=date(2026, 3, 2),
        source_id=1,
        minutes=minutes,
        rate=rate,
        currency=currency,
        fx_rate=fx,
    )


class TestSums:
    def test_eur_and_usd_blocks_add_up_in_euros(self):
        # 90 min at 60 EUR = 90.00; 2 h at $95 / 1.25 = 152.00
        s = sum_blocks([_b(90, 60, "EUR", None), _b(120, 95, "USD", 1.25)])
        assert (s.minutes, s.hours, s.blocks, s.missing) == (210, 3.5, 2, 0)
        assert s.gross_eur == pytest.approx(242.0)
        assert s.eur_per_hour == pytest.approx(242 / 3.5)

    def test_a_usd_block_without_a_rate_counts_its_hours_but_not_its_money(self):
        s = sum_blocks([_b(60, 100, "USD", None)])
        assert (s.hours, s.gross_eur, s.missing) == (1.0, 0.0, 1)
        assert s.out() == {
            "hours": 1.0,
            "gross_eur": 0.0,
            "eur_per_hour": 0.0,
            "blocks": 1,
            "missing_fx": 1,
        }

    def test_empty(self):
        assert Sum().out()["eur_per_hour"] == 0.0
