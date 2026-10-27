"""E2E: partial-day leave through the browser.

The Log form's "Time off" slider turns a leave day into a partial one, reveals the
time fields for the hours worked, and the saved entry shows up with its hours on the
Days table, the Week view, and the calendar cells. Dates use days 20–24 of the current
month so they don't collide with the other e2e modules (see test_log_form.py).
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
    """Fresh entries and an 8h target — the wipe keeps settings, and an earlier module
    (test_happy_paths) leaves the target at 6.5h, which the hour maths below assume away."""
    _wipe(base_url)
    with httpx.Client(base_url=base_url) as c:
        c.put("/api/config", json={"daily_target_hours": 8, "vacation_budget_days": 0})
    yield
    _wipe(base_url)


def _open_log_tab(page, base_url):
    page.goto(f"{base_url}/#log")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("form", timeout=5000)


def _day_in_current_month(day: int) -> str:
    return datetime.date.today().replace(day=day).isoformat()


def _set_slider(page, hours: float) -> None:
    # `fill` sets the value and fires input/change, which x-model.number picks up.
    page.locator("input[type='range']").fill(str(hours))
    page.wait_for_timeout(200)


class TestLogFormSlider:
    def test_slider_appears_for_leave_and_defaults_to_full_day(self, page, base_url):
        _open_log_tab(page, base_url)
        assert page.locator("input[type='range']").count() == 0
        page.select_option("select", "vacation")
        page.wait_for_selector("[data-testid='leave-slider']", timeout=3000)
        assert "Full day" in page.locator(".leave-slider-value").inner_text()
        # Whole day: no time fields.
        assert page.locator("input[type='time']:visible").count() == 0

    def test_moving_the_slider_reveals_time_fields_and_preview(self, page, base_url):
        _open_log_tab(page, base_url)
        page.select_option("select", "vacation")
        page.wait_for_selector("input[type='range']")
        _set_slider(page, 3)
        assert "3h off" in page.locator(".leave-slider-value").inner_text()
        page.wait_for_selector("input[type='time']", timeout=3000)
        times = page.locator("input[type='time']")
        times.nth(0).fill("09:00")
        times.nth(1).fill("14:00")
        page.wait_for_timeout(200)
        preview = page.locator(".impact-card").inner_text()
        assert "5h" in preview  # net 5h against a 5h target
        assert "±0.00h" in preview

    def test_slider_back_to_the_top_hides_time_fields(self, page, base_url):
        _open_log_tab(page, base_url)
        page.select_option("select", "sick")
        page.wait_for_selector("input[type='range']")
        _set_slider(page, 2)
        page.wait_for_selector("input[type='time']", timeout=3000)
        _set_slider(page, 8)
        page.wait_for_timeout(300)
        assert page.locator("input[type='time']:visible").count() == 0
        assert "Full day" in page.locator(".leave-slider-value").inner_text()


class TestSaveAndDisplay:
    def test_partial_vacation_round_trip(self, page, base_url):
        date_str = _day_in_current_month(20)
        _open_log_tab(page, base_url)
        page.locator(f"[aria-label='{date_str}']").click()
        page.select_option("select", "vacation")
        page.wait_for_selector("input[type='range']")
        _set_slider(page, 4)
        times = page.locator("input[type='time']")
        times.nth(0).fill("09:00")
        times.nth(1).fill("13:00")
        page.locator("button.log-submit-btn").click()
        page.wait_for_url("**/#days", timeout=5000)

        # Days table: pill carries the hours, net/target reflect the worked half.
        row = page.locator(f"#day-row-{date_str}")
        row.wait_for(timeout=5000)
        page.wait_for_function(
            "sel => !document.querySelector(sel)?.classList.contains('row-saving')",
            arg=f"#day-row-{date_str} tr",
            timeout=5000,
        )
        text = row.inner_text()
        assert "VACATION · 4H" in text.upper()
        assert "4h" in text

        # Server agrees.
        with httpx.Client(base_url=base_url) as c:
            e = c.get(f"/api/entries/{date_str}").json()
        assert e["fraction"] == 0.5
        assert e["net_hours"] == 4.0
        assert e["target_hours"] == 4.0

    def test_edit_reopens_with_slider_position_and_hours(self, page, base_url):
        date_str = _day_in_current_month(21)
        with httpx.Client(base_url=base_url) as c:
            r = c.post(
                "/api/entries",
                json={
                    "date": date_str,
                    "day_type": "sick",
                    "fraction": 0.25,
                    "start_time": "08:30",
                    "end_time": "15:00",
                    "breaks": [{"break_minutes": 30}],
                },
            )
            assert r.status_code == 201, r.text
        _open_log_tab(page, base_url)
        page.locator(f"[aria-label='{date_str}']").click()
        page.wait_for_selector("text=Edit " + date_str, timeout=5000)
        assert page.locator("select").input_value() == "sick"
        assert page.locator("input[type='range']").input_value() == "2"
        assert "2h off" in page.locator(".leave-slider-value").inner_text()
        times = page.locator("input[type='time']")
        assert times.nth(0).input_value() == "08:30"
        assert times.nth(1).input_value() == "15:00"

    def test_calendar_and_week_show_the_split(self, page, base_url):
        date_str = _day_in_current_month(22)
        with httpx.Client(base_url=base_url) as c:
            c.post(
                "/api/entries",
                json={
                    "date": date_str,
                    "day_type": "vacation",
                    "fraction": 0.5,
                    "start_time": "09:00",
                    "end_time": "13:00",
                },
            )
        _open_log_tab(page, base_url)
        cell = page.locator(f"button.log-cal-day[aria-label='{date_str}']")
        cell.wait_for(timeout=5000)
        page.wait_for_function(
            "sel => (document.querySelector(sel)?.getAttribute('style') || '')"
            ".includes('linear-gradient')",
            arg=f"button.log-cal-day[aria-label='{date_str}']",
            timeout=5000,
        )
        assert "hm-partial" in (cell.get_attribute("class") or "")
        assert "50%" in (cell.get_attribute("style") or "")

        # Week view: navigate to the week containing the date.
        page.goto(f"{base_url}/#week")
        page.wait_for_selector(".week-grid", timeout=5000)
        target = datetime.date.fromisoformat(date_str)
        for _ in range(6):
            if page.locator(f".week-day[aria-label*='{date_str}']").count():
                break
            today = datetime.date.today()
            if target < today:
                page.locator("button[aria-label='Previous week']").click()
            else:
                page.locator("button[aria-label='Next week']").click()
            page.wait_for_timeout(200)
        day = page.locator(f".week-day[aria-label*='{date_str}']")
        day.wait_for(timeout=5000)
        assert "VACATION · 4H" in day.inner_text().upper()
        assert "4h" in day.inner_text()
        total = page.locator(".week-total").inner_text()
        assert "0.5 work days, 0.5 off" in total

    def test_dashboard_counts_are_fractional(self, page, base_url):
        # vacation_days_used only counts days up to today, so stay on or before it.
        date_str = _day_in_current_month(min(23, datetime.date.today().day))
        with httpx.Client(base_url=base_url) as c:
            c.put("/api/config", json={"vacation_budget_days": 22.5})
            c.post("/api/entries", json={"date": date_str, "day_type": "vacation", "fraction": 0.5})
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector(".summary-card .metric", timeout=5000)
        month = page.locator(".summary-card", has_text="This month").inner_text()
        assert "0.5 work days, 0.5 off" in month
        vac = page.locator(".vacation-bar-wrap")
        vac.wait_for(timeout=5000)
        assert "0.5 / 22.5 days used" in vac.inner_text()
        assert "22 days remaining" in vac.inner_text()
