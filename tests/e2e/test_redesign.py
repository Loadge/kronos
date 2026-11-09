"""E2E: the redesigned navigation, dashboard, Settings and Days.

Five tabs plus the gear; the dashboard's hero, trajectory, week strip and quick-log
(only while today is empty); Settings as cards that save their own fields once
something changed; Days as a dense table whose rows open the day in Log, with a
separator and subtotal per month and the notes in the last column.
"""

from __future__ import annotations

import datetime

import httpx
import pytest

pytestmark = pytest.mark.e2e


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        c.put("/api/config", json={"daily_target_hours": 8, "vacation_budget_days": 20})


@pytest.fixture(autouse=True)
def _clean(base_url):
    _wipe(base_url)
    yield
    _wipe(base_url)


def _work(date: str, start="09:00", end="18:00", notes=""):
    return {
        "date": date,
        "day_type": "work",
        "start_time": start,
        "end_time": end,
        "breaks": [{"break_minutes": 60}],
        "notes": notes,
    }


def _wait_for(fetch, pred, timeout: float = 5.0):
    """Poll an HTTP read until `pred` holds (autosaves land a moment after the keystroke)."""
    import time

    deadline = time.monotonic() + timeout
    while True:
        value = fetch()
        if pred(value):
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"still not there after {timeout}s: {value!r}")
        time.sleep(0.1)


def _post(base_url: str, *bodies: dict) -> None:
    with httpx.Client(base_url=base_url) as c:
        for body in bodies:
            r = c.post("/api/entries", json=body)
            assert r.status_code == 201, r.text


# ── navigation ────────────────────────────────────────────────────────────────


class TestNavigation:
    def test_five_tabs_and_the_gear(self, page, base_url):
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_load_state("networkidle")
        tabs = page.locator("nav[role='tablist'] a[role='tab']")
        assert tabs.all_inner_texts() == ["Dashboard", "Plan", "Days", "Weeks", "Year"]
        # The accented first letter is the tab's shortcut; Dashboard has none (Escape goes there).
        assert page.locator(".tabs .tab-key").all_inner_texts() == ["P", "D", "W", "Y"]
        assert tabs.nth(0).locator(".tab-key").count() == 0

        gear = page.get_by_role("button", name="Settings")
        gear.click()
        page.wait_for_url("**/#settings", timeout=3000)
        assert "is-open" in (gear.get_attribute("class") or "")
        page.wait_for_selector(".settings-card", timeout=5000)

    def test_s_opens_settings_and_l_and_a_do_nothing(self, page, base_url):
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector(".hero-num", timeout=5000)
        page.keyboard.press("l")
        page.keyboard.press("a")
        page.wait_for_timeout(300)
        assert page.url.endswith("#dashboard")
        page.keyboard.press("s")
        page.wait_for_url("**/#settings", timeout=3000)

    def test_palette_has_no_week_command(self, page, base_url):
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector(".hero-num", timeout=5000)
        page.keyboard.press(".")
        page.wait_for_selector(".palette", timeout=3000)
        labels = page.locator(".palette li[role='option']").all_inner_texts()
        assert not any(label.startswith("Week ") for label in labels)
        assert any("Settings" in label for label in labels)


# ── dashboard ─────────────────────────────────────────────────────────────────


class TestDashboard:
    def test_quick_log_disappears_once_today_is_logged(self, page, base_url):
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector(".quick-log", timeout=5000)
        assert page.locator(".quick-log").is_visible()

        page.locator(".quick-log-btn", has_text="Sick").click()
        page.wait_for_selector(".save-ribbon.ribbon-show", timeout=5000)
        page.wait_for_function(
            "() => getComputedStyle(document.querySelector('.quick-log')).display === 'none'",
            timeout=5000,
        )
        today = datetime.date.today().isoformat()
        cell = page.locator(f".wd[aria-label*='{today}']")
        assert "SICK" in cell.inner_text().upper()

    def test_hero_chips_and_trajectory(self, page, base_url):
        # the server's day, not this machine's: CI runs on UTC and the app on Madrid time
        today = datetime.date.fromisoformat(httpx.get(f"{base_url}/api/dashboard").json()["today"])
        monday = today - datetime.timedelta(days=today.weekday())
        _post(base_url, _work(monday.isoformat(), "09:00", "19:00"))  # 9h net → +1
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_function(
            "() => document.querySelector('.hero-num')?.innerText === '+1.00h'", timeout=5000
        )
        assert "since" in page.locator(".hero-label").inner_text()
        assert today.strftime("%a") in page.locator(".today-chip").inner_text()
        assert page.locator(".chip").count() == 3
        assert page.locator(".traj-line").count() == 1
        assert "by Dec 31" in (page.locator(".traj-wrap").get_attribute("aria-label") or "")
        # the strip: Monday's bar carries the surplus colour, the day opens in Log
        day = page.locator(f".wd[aria-label*='{monday.isoformat()}']")
        assert "hm-surplus" in (day.locator(".wd-bar").get_attribute("class") or "")
        day.click()
        page.wait_for_url("**/#days", timeout=3000)
        page.wait_for_function(
            "d => Alpine.$data(document.querySelector('main')).editingDate === d",
            arg=monday.isoformat(),
            timeout=5000,
        )

    def test_vacation_notches(self, page, base_url):
        today = datetime.date.today()
        _post(base_url, {"date": today.isoformat(), "day_type": "vacation"})
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector(".vac-notches i", timeout=5000)
        notches = page.locator(".vac-notches i")
        assert notches.count() == 20
        assert "vac-used" in (notches.nth(0).get_attribute("class") or "")
        assert "vac-left" in (notches.nth(1).get_attribute("class") or "")
        assert "1 used · 19 left of 20" in page.locator(".vac-sub").inner_text()


# ── settings ──────────────────────────────────────────────────────────────────


class TestSettingsSections:
    def test_index_has_two_levels(self, page, base_url):
        """Three groups; the open group's sections under it; the other groups' cards are
        not on the page until their group is opened."""
        page.goto(f"{base_url}/#settings")
        page.evaluate("localStorage.removeItem('k-settings-group')")
        page.reload()
        page.wait_for_selector(".settings-index a", timeout=5000)
        groups = page.locator(".settings-group-btn")
        assert [t.split("\n")[0] for t in groups.all_inner_texts()] == [
            "👔 Employee",
            "⚡ Freelance",
            "🧰 General",
        ]
        assert page.locator(
            ".settings-group.open .settings-group-sections a"
        ).all_inner_texts() == [
            "Work",
            "Leave",
            "Holidays",
            "Profile",
            "Templates",
        ]
        assert page.locator("#settings-data").count() == 0
        page.locator(".settings-index a", has_text="Profile").click()
        page.wait_for_function(
            "() => document.querySelector('.settings-index a.active')?.innerText === 'Profile'",
            timeout=3000,
        )
        # the General group holds the data card, and the index follows
        groups.nth(2).click()
        page.wait_for_selector("#settings-data", timeout=3000)
        assert page.locator("#settings-work").count() == 0
        assert page.locator(
            ".settings-group.open .settings-group-sections a"
        ).all_inner_texts() == ["Country", "Data"]
        # the choice survives a reload
        page.reload()
        page.wait_for_selector("#settings-data", timeout=5000)

    def test_sections_save_themselves(self, page, base_url):
        """No save buttons: a field saves half a second after the last keystroke, a switch
        at once, an invalid value waits and says so; each section sends only its fields."""
        page.goto(f"{base_url}/#settings")
        page.wait_for_selector("#set-budget", timeout=5000)
        assert page.locator(".settings-card button", has_text="Save").count() == 0
        leave_status = page.locator("#settings-leave .settings-card-head .settings-saved")
        work_status = page.locator("#settings-work .settings-card-head .settings-saved")
        assert leave_status.inner_text() == "" and work_status.inner_text() == ""

        page.locator("#set-budget").fill("25")
        page.wait_for_selector("#settings-leave .settings-saved.is-saved", timeout=5000)
        with httpx.Client(base_url=base_url) as c:
            cfg = c.get("/api/config").json()
        assert cfg["vacation_budget_days"] == 25 and cfg["daily_target_hours"] == 8
        # the confirmation fades by itself
        page.wait_for_function(
            "() => document.querySelector('#settings-leave .settings-card-head .settings-saved')"
            ".innerText === ''",
            timeout=5000,
        )

        # an empty target is invalid: nothing is sent, the card says so
        page.locator("#set-target").fill("")
        page.wait_for_selector("#settings-work .settings-saved.is-invalid", timeout=5000)
        assert work_status.inner_text() == "check the value"
        page.locator("#set-target").fill("7")
        # the longest wait here: a debounce, a request, and a runner that may be busy
        page.wait_for_selector("#settings-work .settings-saved.is-saved", timeout=15000)
        # a switch saves at once
        page.locator("#set-reset").check()
        with httpx.Client(base_url=base_url) as c:
            _wait_for(
                lambda: c.get("/api/config").json(),
                lambda cfg: cfg["reset_annually"] is True and cfg["daily_target_hours"] == 7,
            )
        # the page stays on Settings
        assert page.url.endswith("#settings")

    def test_the_target_timeline_saves_itself(self, page, base_url):
        page.goto(f"{base_url}/#settings")
        page.wait_for_selector("#set-target", timeout=5000)
        page.locator(".target-schedule summary").click()
        page.locator(".target-schedule-actions button", has_text="Add a change").click()
        rows = page.locator(".target-schedule-row")
        assert rows.count() == 2
        rows.nth(1).locator("input[type='date']").fill("2026-06-01")
        rows.nth(1).locator("input[type='number']").fill("6")
        page.wait_for_selector(".target-schedule-actions .settings-saved.is-saved", timeout=5000)
        with httpx.Client(base_url=base_url) as c:
            sched = _wait_for(
                lambda: c.get("/api/config/daily-target-schedule").json()["rows"],
                lambda rows: rows[-1]["hours"] == 6,
            )
        assert sched[-1] == {"effective_from": "2026-06-01", "hours": 6.0}
        # the current target follows the latest row, a moment after the save
        page.wait_for_function(
            "() => document.querySelector('#set-target').value === '6'", timeout=5000
        )


# ── days ──────────────────────────────────────────────────────────────────────


class TestDaysTable:
    def test_month_separators_rows_and_notes(self, page, base_url):
        year = datetime.date.today().year
        _post(
            base_url,
            _work(f"{year}-03-02", "09:00", "19:00", notes="Release day"),  # +1
            _work(f"{year}-03-03", "09:00", "17:00"),  # −1
            _work(f"{year}-02-10", "09:00", "18:00", notes="Dentist at **13:00**"),  # ±0
        )
        page.goto(f"{base_url}/#weeks")
        page.wait_for_selector(".days-table .week-sep", timeout=5000)
        page.get_by_test_id("wk-expand-all").click()
        page.wait_for_selector(".days-table .day-row", timeout=5000)

        seps = page.locator(".days-table .month-sep")
        assert seps.count() == 2
        march = seps.nth(0).inner_text()
        assert f"March {year}" in march
        assert "2 days" in march and "16h / 16h" in march and "±0.00h" in march
        assert f"February {year}" in seps.nth(1).inner_text()

        # notes are in the last text column, rendered (markdown), no toggle needed
        row = page.locator(f"#day-row-{year}-02-10")
        assert "Dentist at 13:00" in row.locator(".notes-col").inner_text()
        assert row.locator(".notes-col strong").count() == 1
        assert row.locator("td").nth(1).inner_text().lower() == "tue"

        # sorted by net hours there is no month boundary to mark
        page.locator("th", has_text="Net").click()
        page.wait_for_function(
            "() => document.querySelectorAll('.days-table .month-sep').length === 0", timeout=3000
        )
        page.locator("th", has_text="Date").click()
        page.wait_for_function(
            "() => document.querySelectorAll('.days-table .month-sep').length === 2", timeout=3000
        )

        # the whole row opens the day in Log
        page.locator(f"#day-row-{year}-03-03 td").nth(3).click()
        page.wait_for_url("**/#days", timeout=3000)
        page.wait_for_function(
            "d => Alpine.$data(document.querySelector('main')).editingDate === d",
            arg=f"{year}-03-03",
            timeout=5000,
        )

    def test_search_keeps_notes_visible_and_highlights(self, page, base_url):
        year = datetime.date.today().year
        _post(
            base_url,
            _work(f"{year}-04-06", notes="Sprint planning in Madrid"),
            _work(f"{year}-04-07", notes="Quiet day"),
        )
        page.goto(f"{base_url}/#weeks")
        page.wait_for_selector(".days-table .week-sep", timeout=5000)
        page.locator(".notes-search").fill("madrid")
        page.wait_for_function(
            "() => document.querySelectorAll('.days-table .day-row').length === 1", timeout=3000
        )
        assert page.locator(".notes-col mark").inner_text() == "Madrid"
        assert page.locator(".days-table .day-row").count() == 1
