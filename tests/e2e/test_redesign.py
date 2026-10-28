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
        assert tabs.all_inner_texts() == ["Dashboard", "Plan", "Log", "Days", "Analytics"]
        # The accented first letter is the tab's shortcut; Dashboard has none (Escape goes there).
        assert page.locator(".tabs .tab-key").all_inner_texts() == ["P", "L", "D", "A"]
        assert tabs.nth(0).locator(".tab-key").count() == 0

        gear = page.get_by_role("button", name="Settings")
        gear.click()
        page.wait_for_url("**/#settings", timeout=3000)
        assert "is-open" in (gear.get_attribute("class") or "")
        page.wait_for_selector(".settings-card", timeout=5000)

    def test_s_opens_settings_and_w_does_nothing(self, page, base_url):
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector(".hero-num", timeout=5000)
        page.keyboard.press("w")
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
        assert not any(label.startswith("Week") for label in labels)
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
        today = datetime.date.today()
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
        assert "by December 31" in (page.locator(".traj-wrap").get_attribute("aria-label") or "")
        # the strip: Monday's bar carries the surplus colour, the day opens in Log
        day = page.locator(f".wd[aria-label*='{monday.isoformat()}']")
        assert "hm-surplus" in (day.locator(".wd-bar").get_attribute("class") or "")
        day.click()
        page.wait_for_url("**/#log", timeout=3000)
        page.wait_for_selector(f"h2:has-text('Edit {monday.isoformat()}')", timeout=5000)

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
    def test_index_lists_the_sections(self, page, base_url):
        page.goto(f"{base_url}/#settings")
        page.wait_for_selector(".settings-index a", timeout=5000)
        assert page.locator(".settings-index a").all_inner_texts() == [
            "Work",
            "Leave",
            "Holidays",
            "Profile",
            "Templates",
            "Data",
        ]
        page.locator(".settings-index a", has_text="Profile").click()
        page.wait_for_function(
            "() => document.querySelector('.settings-index a.active')?.innerText === 'Profile'",
            timeout=3000,
        )

    def test_each_section_saves_only_its_fields_once_dirty(self, page, base_url):
        page.goto(f"{base_url}/#settings")
        page.wait_for_selector("#set-budget", timeout=5000)
        save_leave = page.locator("#settings-leave button[type='submit']")
        save_work = page.locator("#settings-work button[type='submit']")
        assert save_leave.is_disabled()
        assert save_work.is_disabled()

        page.locator("#set-budget").fill("25")
        page.locator("#set-target").fill("7")
        page.wait_for_function(
            "() => !document.querySelector('#settings-leave button[type=submit]').disabled",
            timeout=3000,
        )
        save_leave.click()
        page.wait_for_selector(".save-ribbon.ribbon-show:has-text('Settings saved')", timeout=5000)
        page.wait_for_function(
            "() => document.querySelector('#settings-leave button[type=submit]').disabled",
            timeout=3000,
        )
        # Leave went through; the still-dirty Work section did not.
        assert not save_work.is_disabled()
        with httpx.Client(base_url=base_url) as c:
            cfg = c.get("/api/config").json()
        assert cfg["vacation_budget_days"] == 25
        assert cfg["daily_target_hours"] == 8
        # The page stays on Settings: the other sections can still be edited.
        assert page.url.endswith("#settings")


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
        page.goto(f"{base_url}/#days")
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
        page.wait_for_url("**/#log", timeout=3000)
        page.wait_for_selector(f"h2:has-text('Edit {year}-03-03')", timeout=5000)

    def test_search_keeps_notes_visible_and_highlights(self, page, base_url):
        year = datetime.date.today().year
        _post(
            base_url,
            _work(f"{year}-04-06", notes="Sprint planning in Madrid"),
            _work(f"{year}-04-07", notes="Quiet day"),
        )
        page.goto(f"{base_url}/#days")
        page.wait_for_selector(".days-table .day-row", timeout=5000)
        page.locator(".notes-search").fill("madrid")
        page.wait_for_function(
            "() => document.querySelectorAll('.days-table .day-row').length === 1", timeout=3000
        )
        assert page.locator(".notes-col mark").inner_text() == "Madrid"
        assert "1 entries" in page.locator(".days-count").inner_text()
