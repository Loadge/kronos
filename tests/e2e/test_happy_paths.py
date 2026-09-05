"""E2E: full cross-tab happy-path journeys.

The rest of the e2e suite covers narrow slices — form rendering, tab
navigation, single-field submission. Nobody exercises a *complete* journey:
log something through the real browser form, then confirm it shows up
correctly everywhere it's supposed to (Days table, Dashboard, Analytics
heatmap), edit it, and delete it. These tests fill that gap.

Following test_dashboard.py's convention: setup/verification state that
isn't the behavior under test goes through httpx directly against the API;
the actual journey under test (submitting the Log form, clicking
Edit/Delete, switching tabs) always goes through the real browser.

Dates are anchored to the *real* current month (`datetime.date.today()`)
because the Log tab's calendar (`app.js` calYear/calMonth, see
_tab_log.html) always opens on the real current month, and calendar days
are clickable regardless of past/future — see calSelectDay()/calDays() in
app.js. Anchoring to "now" lets every test click a day without first
navigating the calendar with calNext()/calPrev().
"""

from __future__ import annotations

import datetime

import httpx
import pytest

pytestmark = pytest.mark.e2e

_TODAY = datetime.date.today()


def _iso(day: int) -> str:
    """An ISO date string for `day` in the real current month/year."""
    return f"{_TODAY.year:04d}-{_TODAY.month:02d}-{day:02d}"


# Distinct days-of-month per test (every month has at least 28 days).
WORK_DATE = _iso(3)
EDIT_DATE = _iso(4)
DELETE_DATE = _iso(5)
VACATION_DATE = _iso(6)
SICK_DATE = _iso(7)


# ── helpers (pattern from test_dashboard.py / test_analytics_heatmap.py) ──


def _seed(base_url: str, entries: list[dict]) -> None:
    """POST entries directly to the API — bypasses the browser form."""
    with httpx.Client(base_url=base_url) as c:
        for body in entries:
            r = c.post("/api/entries", json=body)
            assert r.status_code == 201, f"seed failed: {r.text}"


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")


def _set_daily_target(base_url: str, hours: float) -> None:
    with httpx.Client(base_url=base_url) as c:
        r = c.put("/api/config", json={"daily_target_hours": hours})
        assert r.status_code == 200, f"config update failed: {r.text}"


def _work(iso_date: str, start: str = "09:00", end: str = "17:00") -> dict:
    return {"date": iso_date, "day_type": "work", "start_time": start, "end_time": end}


@pytest.fixture(autouse=True)
def _clean(base_url):
    """Wipe entries before/after each test — journeys need a deterministic DB."""
    _wipe(base_url)
    yield
    _wipe(base_url)


def _cell(row, index: int):
    return row.locator("td").nth(index)


# ── journeys ────────────────────────────────────────────────────────────


class TestFullWorkDayJourney:
    """Log a work day via the real form; confirm it lands correctly in the
    Days table, the Dashboard's "This month" card, and the Analytics
    heatmap — the three places a logged day is supposed to show up."""

    def test_work_day_appears_in_days_dashboard_and_heatmap(self, page, base_url):
        _set_daily_target(base_url, 8)

        # ── Log via the real browser form ──
        page.goto(f"{base_url}/#log")
        page.wait_for_load_state("networkidle")
        # Target the specific day directly rather than the bare ".log-cal-day"
        # class: that also matches invisible padding cells (`.log-cal-pad`,
        # `visibility: hidden`) that fill out the grid before day 1, and
        # Playwright's wait would resolve to the first (invisible) match.
        day_button = page.locator(f".log-cal-day[aria-label='{WORK_DATE}']")
        day_button.wait_for(timeout=5000)
        day_button.click()

        # Day type defaults to 'work'. 08:00-17:00, no breaks -> 9h net vs
        # an 8h target -> +1h surplus, which is what every downstream
        # assertion below is keyed on.
        time_inputs = page.locator("input[type='time']")
        time_inputs.nth(0).fill("08:00")
        time_inputs.nth(1).fill("17:00")

        page.locator("button.log-submit-btn").click()
        page.wait_for_url("**/#days", timeout=5000)

        # ── Days table ──
        row = page.locator(f"#day-row-{WORK_DATE}")
        page.wait_for_selector(f"#day-row-{WORK_DATE}", timeout=5000)
        # Wait past the optimistic-insert window for the server-confirmed row
        # (Edit button only renders once `_saving` clears).
        row.get_by_role("button", name="Edit").wait_for(timeout=5000)

        assert _cell(row, 0).inner_text() == WORK_DATE
        pill = row.locator(".day-pill")
        # text_content(), not inner_text(): the pill is CSS-uppercased for
        # display, but the underlying x-text value (what we actually want to
        # verify) is the lowercase day_type.
        assert pill.text_content() == "work"
        assert "work" in (pill.get_attribute("class") or "")
        assert _cell(row, 5).inner_text() == "9h"  # Net
        assert _cell(row, 6).inner_text() == "8h"  # Target
        delta_cell = _cell(row, 7)
        assert delta_cell.inner_text() == "+1.00h"
        assert "surplus" in (delta_cell.get_attribute("class") or "")

        # ── Dashboard: "This month" card reflects the new entry ──
        page.get_by_role("tab", name="Dashboard").click()
        month_card = page.locator("article[data-id='month']")
        month_card.wait_for(timeout=5000)
        month_text = month_card.inner_text()
        assert "Surplus" in month_text
        assert "9h worked" in month_text
        assert "8h target" in month_text
        assert "1 work days" in month_text
        assert "0 off" in month_text

        # ── Analytics: heatmap cell carries the surplus color class ──
        page.get_by_role("tab", name="Analytics").click()
        page.wait_for_selector(".hm-cell", timeout=5000)
        cell = page.locator(f".hm-cell[title='{WORK_DATE} · work · +1h']")
        cell.wait_for(timeout=5000)
        assert "hm-surplus" in (cell.get_attribute("class") or "")


class TestEditEntryJourney:
    """Edit an existing entry via the Days table's Edit button (which drops
    the Log tab into edit mode), and confirm the change lands in Days."""

    def test_edit_via_days_table_updates_net_hours(self, page, base_url):
        _set_daily_target(base_url, 8)
        _seed(base_url, [_work(EDIT_DATE, start="09:00", end="17:00")])  # 8h net == target

        page.goto(f"{base_url}/#days")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(f"#day-row-{EDIT_DATE}", timeout=5000)

        row = page.locator(f"#day-row-{EDIT_DATE}")
        assert _cell(row, 5).inner_text() == "8h"  # sanity: pre-edit net

        row.get_by_role("button", name="Edit").click()

        # Log tab now in edit mode for this date.
        page.wait_for_selector(f"h2:has-text('Edit {EDIT_DATE}')", timeout=5000)
        page.get_by_role("button", name="Delete").wait_for(timeout=5000)

        time_inputs = page.locator("input[type='time']")
        time_inputs.nth(1).fill("18:00")  # end_time 17:00 -> 18:00: net becomes 9h

        page.locator("button.log-submit-btn").click()

        # Back on the Days table with the updated row.
        page.wait_for_selector(f"#day-row-{EDIT_DATE}", timeout=5000)
        row = page.locator(f"#day-row-{EDIT_DATE}")
        row.get_by_role("button", name="Edit").wait_for(timeout=5000)

        assert _cell(row, 3).inner_text() == "18:00"  # End
        assert _cell(row, 5).inner_text() == "9h"  # Net
        assert _cell(row, 7).inner_text() == "+1.00h"  # Delta


class TestDeleteEntryJourney:
    """Delete an entry via the Log tab's Delete button, reached through the
    Days table's Edit button, and confirm it's gone from Days."""

    def test_delete_via_log_tab_removes_entry_from_days_table(self, page, base_url):
        _seed(base_url, [_work(DELETE_DATE)])

        page.goto(f"{base_url}/#days")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(f"#day-row-{DELETE_DATE}", timeout=5000)

        page.locator(f"#day-row-{DELETE_DATE}").get_by_role("button", name="Edit").click()
        page.wait_for_selector(f"h2:has-text('Edit {DELETE_DATE}')", timeout=5000)

        # deleteEntry() calls the browser's native confirm() — accept it.
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Delete").click()

        page.wait_for_selector("text=No entries yet", timeout=5000)
        assert page.locator(f"#day-row-{DELETE_DATE}").count() == 0

        # Confirm at the source too, not just in the rendered table.
        with httpx.Client(base_url=base_url) as c:
            r = c.get(f"/api/entries/{DELETE_DATE}")
            assert r.status_code == 404


class TestNonWorkDayTypes:
    """Log a non-work day (vacation / sick) and confirm both the Days pill
    and the Analytics heatmap color reflect the specific day type — not
    just "some entry exists"."""

    @pytest.mark.parametrize(
        "day_type,iso_date",
        [
            ("vacation", VACATION_DATE),
            ("sick", SICK_DATE),
        ],
    )
    def test_non_work_day_shows_correct_pill_and_heatmap_color(
        self, page, base_url, day_type, iso_date
    ):
        page.goto(f"{base_url}/#log")
        page.wait_for_load_state("networkidle")
        # See the comment in TestFullWorkDayJourney: target the specific day
        # rather than the bare ".log-cal-day" class, which also matches
        # invisible padding cells.
        day_button = page.locator(f".log-cal-day[aria-label='{iso_date}']")
        day_button.wait_for(timeout=5000)
        day_button.click()
        page.select_option("select", day_type)

        page.locator("button.log-submit-btn").click()
        page.wait_for_url("**/#days", timeout=5000)

        row = page.locator(f"#day-row-{iso_date}")
        page.wait_for_selector(f"#day-row-{iso_date}", timeout=5000)
        row.get_by_role("button", name="Edit").wait_for(timeout=5000)

        pill = row.locator(".day-pill")
        assert pill.text_content() == day_type
        assert day_type in (pill.get_attribute("class") or "")
        # Non-work days contribute 0h to net/target — same convention as
        # the work-day journey's exact-string checks.
        assert _cell(row, 5).inner_text() == "0h"

        page.get_by_role("tab", name="Analytics").click()
        page.wait_for_selector(".hm-cell", timeout=5000)
        cell = page.locator(f".hm-cell[title='{iso_date} · {day_type} · 0h']")
        cell.wait_for(timeout=5000)
        assert f"hm-{day_type}" in (cell.get_attribute("class") or "")


class TestSettingsPersistence:
    """Change a Settings value, save, reload the page, and confirm the new
    value is still there — proving it survived a real server round-trip,
    not just client-side Alpine state."""

    def test_daily_target_hours_persists_after_reload(self, page, base_url):
        page.goto(f"{base_url}/#settings")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("input[type='number']", timeout=5000)

        target_input = page.locator("input[type='number']").first
        target_input.fill("6.5")

        page.get_by_role("button", name="Save settings").click()
        page.wait_for_url("**/#dashboard", timeout=5000)

        # Force a real reload — a fresh JS app instance re-fetching config,
        # not just Alpine state that never left the page.
        page.reload()
        page.wait_for_load_state("networkidle")
        page.get_by_role("tab", name="Settings").click()
        page.wait_for_selector("input[type='number']", timeout=5000)

        target_input = page.locator("input[type='number']").first
        assert target_input.input_value() == "6.5"

        # Confirm at the source too, independent of any client-side caching.
        with httpx.Client(base_url=base_url) as c:
            cfg = c.get("/api/config").json()
            assert cfg["daily_target_hours"] == 6.5
