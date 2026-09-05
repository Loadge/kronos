"""E2E: Log form — creating entries and optimistic UI navigation.

Tests in this module create real entries via the browser form, using
distinct days-of-month so tests within this file don't collide with each
other. An autouse fixture wipes the DB before/after every test here too:
"unique dates" only guards against collisions *within* this file — the full
suite shares one live server/DB across all e2e modules, and another file
picking the same day-of-month (as tests/e2e/test_happy_paths.py's fixed
dates once did) would otherwise collide silently depending on file run
order.
"""

from __future__ import annotations

import datetime

import httpx
import pytest

pytestmark = pytest.mark.e2e


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")


@pytest.fixture(autouse=True)
def _clean(base_url):
    _wipe(base_url)
    yield
    _wipe(base_url)


def _open_log_tab(page, base_url):
    page.goto(f"{base_url}/#log")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("form", timeout=5000)


def _day_in_current_month(day: int) -> str:
    """ISO date for `day` of the real current month/year.

    The Log tab's calendar (app.js: `calYear`/`calMonth`) always initializes
    from `new Date()`, so a date within the currently-running month/year is
    visible without clicking the `.log-cal-nav` prev/next buttons.
    """
    return datetime.date.today().replace(day=day).isoformat()


def _select_calendar_date(page, date_str: str) -> None:
    """Click the calendar-day cell for `date_str` (must be in the displayed month).

    Each unpadded day cell in `_tab_log.html` carries `aria-label="<iso-date>"`
    (see `calDays()` in app.js), so this is a direct, unambiguous locator —
    no native `input[type=date]` exists anymore.
    """
    page.locator(f"[aria-label='{date_str}']").click()


class TestLogFormRendering:
    def test_form_has_date_field(self, page, base_url):
        _open_log_tab(page, base_url)
        # No native date input anymore — dates are picked via calendar-day cells.
        assert page.locator("button.log-cal-day").count() >= 1

    def test_form_has_day_type_select(self, page, base_url):
        _open_log_tab(page, base_url)
        assert page.locator("select").count() >= 1

    def test_work_day_shows_time_fields(self, page, base_url):
        _open_log_tab(page, base_url)
        # Default should be "work" day type — time inputs must be visible
        page.wait_for_selector("input[name='start_time'], input[type='time']", timeout=3000)
        assert page.locator("input[type='time']").count() >= 2

    def test_selecting_vacation_hides_time_fields(self, page, base_url):
        _open_log_tab(page, base_url)
        page.select_option("select", "vacation")
        # Time fields should disappear (x-show / x-if)
        page.wait_for_timeout(300)  # allow Alpine transition
        time_inputs = page.locator("input[type='time']:visible")
        assert time_inputs.count() == 0


class TestLogFormSubmission:
    def test_submit_work_day_navigates_to_days_tab(self, page, base_url):
        _open_log_tab(page, base_url)

        _select_calendar_date(page, _day_in_current_month(3))

        page.select_option("select", "work")
        time_inputs = page.locator("input[type='time']")
        time_inputs.nth(0).fill("09:00")
        time_inputs.nth(1).fill("17:00")

        # Submit
        page.locator("button.log-submit-btn").click()

        # Optimistic navigation: should land on Days tab immediately
        page.wait_for_url("**/#days", timeout=5000)

    def test_submit_vacation_day_appears_in_days_list(self, page, base_url):
        date_str = _day_in_current_month(4)
        _open_log_tab(page, base_url)

        _select_calendar_date(page, date_str)
        page.select_option("select", "vacation")

        page.locator("button.log-submit-btn").click()
        page.wait_for_url("**/#days", timeout=5000)

        # Wait for the entry to appear in the table
        page.wait_for_selector(f"td:has-text('{date_str}'), td:has-text('vacation')", timeout=5000)

    def test_duplicate_date_shows_error(self, page, base_url):
        """Selecting a date that's already logged must load it for editing —
        not silently create a duplicate or crash.

        The old native `input[type=date]` flow let you type an arbitrary date
        and submit it twice, which the backend rejected with a 409 shown in
        the `.error-banner`. The calendar-day picker replaced that entirely:
        `calSelectDay` (app.js) always calls `probeDate` first, which finds
        the existing entry and calls `editEntry()` — so picking an
        already-logged date now loads it for editing *before* a duplicate
        POST could ever be attempted. A genuine duplicate-POST error can no
        longer be reached through this UI, so this test instead asserts the
        replacement guarantee: no crash, and the form switches into edit mode
        for that date.
        """
        date_str = _day_in_current_month(5)
        with httpx.Client(base_url=base_url) as c:
            r = c.post("/api/entries", json={"date": date_str, "day_type": "vacation"})
            assert r.status_code == 201, f"seed failed: {r.text}"

        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        _open_log_tab(page, base_url)
        _select_calendar_date(page, date_str)

        page.wait_for_selector(f"h2:has-text('Edit {date_str}')", timeout=5000)
        assert errors == [], f"JS errors selecting an already-logged date: {errors}"
