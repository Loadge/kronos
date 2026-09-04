"""E2E: Year at a glance heatmap — week-number row.

Each column of the heatmap is a calendar week *within its own month* (see
app.js:heatmapCells). Below the month-label row, each column also carries the
ISO-8601 week number of its first day. A week that straddles a month boundary
(e.g. 2026-04-27..05-03, ISO week 18) legitimately produces the same number in
both the outgoing and incoming month's column — that's not a bug.

The expected sequence below is computed independently with Python's stdlib
`datetime.isocalendar()`, not by re-deriving the app's own column math, so the
test can actually catch a regression in that math rather than just echoing it.
"""

from __future__ import annotations

import calendar
import datetime

import httpx
import pytest

pytestmark = pytest.mark.e2e

YEAR = 2026


def _expected_week_numbers(year: int) -> list[str]:
    """ISO week number of each month-relative week column, in column order."""
    numbers: list[str] = []
    for month in range(1, 13):
        offset = calendar.weekday(year, month, 1)  # Mon=0..Sun=6
        days_in_month = calendar.monthrange(year, month)[1]
        weeks_in_month = -(-(offset + days_in_month) // 7)
        for w in range(weeks_in_month):
            first_day = next(
                dom for dom in range(1, days_in_month + 1) if (offset + dom - 1) // 7 == w
            )
            iso_week = datetime.date(year, month, first_day).isocalendar()[1]
            numbers.append(str(iso_week))
    return numbers


def _seed(base_url: str, entries: list[dict]) -> None:
    with httpx.Client(base_url=base_url) as c:
        for body in entries:
            r = c.post("/api/entries", json=body)
            assert r.status_code == 201, f"seed failed: {r.text}"


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")


class TestHeatmapWeekNumbers:
    @pytest.fixture(autouse=True)
    def _clean(self, base_url):
        _wipe(base_url)
        yield
        _wipe(base_url)

    def test_week_numbers_match_iso_calendar(self, page, base_url):
        # One entry is enough to make 2026 appear in the year filter.
        _seed(
            base_url,
            [
                {
                    "date": f"{YEAR}-01-05",
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "breaks": [{"break_minutes": 60}],
                }
            ],
        )

        page.goto(f"{base_url}/#analytics")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".hm-week-label", timeout=5000)

        page.locator("select").first.select_option(str(YEAR))
        page.wait_for_timeout(200)  # Alpine re-render after the year switch

        labels = page.locator(".hm-week-label").all_inner_texts()
        assert labels == _expected_week_numbers(YEAR)

    def test_week_number_font_size_matches_day_cell(self, page, base_url):
        """The number size should match the day-square size (13px), per spec."""
        _seed(
            base_url,
            [
                {
                    "date": f"{YEAR}-01-05",
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "breaks": [{"break_minutes": 60}],
                }
            ],
        )

        page.goto(f"{base_url}/#analytics")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".hm-week-label", timeout=5000)

        week_label = page.locator(".hm-week-label").first
        day_cell = page.locator(".hm-cell").first
        assert week_label.evaluate("el => getComputedStyle(el).fontSize") == "13px"
        assert day_cell.evaluate("el => getComputedStyle(el).height") == "13px"
