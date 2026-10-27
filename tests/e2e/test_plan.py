"""E2E: the time-off planner through the browser.

Drafting by click and drag on the working month, the year strip as month picker,
the ledger with per-block commit / remove / notes, the projection toggle, and the
drafted days showing as ghosts on the Log calendar (and pre-filling its form).
Dates are next week's Monday–Wednesday, so they are always in the future and never
collide with the fixed days-of-month the other modules use.
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


def _next_week_days() -> list[str]:
    today = datetime.date.today()
    monday = today + datetime.timedelta(days=7 - today.weekday())
    return [(monday + datetime.timedelta(days=i)).isoformat() for i in range(3)]


def _open_plan(page, base_url, target_iso: str):
    page.goto(f"{base_url}/#plan")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector(".plan-strip", timeout=5000)
    # Make the target's month the working month (it is this month or the next).
    target = datetime.date.fromisoformat(target_iso)
    page.locator(".plan-mini").nth(target.month - 1).click()
    if target.year != datetime.date.today().year:
        page.locator("button[aria-label='Next year']").click()
        page.wait_for_timeout(300)
        page.locator(".plan-mini").nth(target.month - 1).click()
    page.wait_for_selector(f"button.log-cal-day[aria-label='{target_iso}']", timeout=5000)


def _wait_ghost(page, iso: str, present: bool = True):
    page.wait_for_function(
        "([sel, want]) => "
        "(document.querySelector(sel)?.classList.contains('hm-ghost') ?? false) === want",
        arg=[f"button.log-cal-day[aria-label='{iso}']", present],
        timeout=5000,
    )


class TestNavigation:
    def test_shortcut_and_tab(self, page, base_url):
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_load_state("networkidle")
        page.keyboard.press("p")
        page.wait_for_url("**/#plan", timeout=5000)
        assert page.locator("section[aria-label='Time-off planner']").count() == 1
        assert page.locator(".plan-mini").count() == 12

    def test_year_strip_picks_the_working_month(self, page, base_url):
        page.goto(f"{base_url}/#plan")
        page.wait_for_selector(".plan-strip", timeout=5000)
        page.locator(".plan-mini").nth(2).click()
        assert "March" in page.locator(".plan-cal .log-cal-title").inner_text()
        assert "active" in page.locator(".plan-mini").nth(2).get_attribute("class")


class TestDrafting:
    def test_click_drafts_and_click_again_removes(self, page, base_url):
        mon, _, _ = _next_week_days()
        _open_plan(page, base_url, mon)
        page.locator(f"button.log-cal-day[aria-label='{mon}']").click()
        _wait_ghost(page, mon)
        row = page.locator(".plan-table tr").first
        assert "VACATION · DRAFT" in row.inner_text().upper()
        with httpx.Client(base_url=base_url) as c:
            assert [p["date"] for p in c.get("/api/plans").json()] == [mon]
        page.locator(f"button.log-cal-day[aria-label='{mon}']").click()
        _wait_ghost(page, mon, present=False)
        with httpx.Client(base_url=base_url) as c:
            assert c.get("/api/plans").json() == []

    def test_drag_drafts_a_range_with_the_chosen_type_and_note(self, page, base_url):
        mon, tue, wed = _next_week_days()
        _open_plan(page, base_url, mon)
        page.locator(".plan-type.flex").click()
        page.locator(".plan-note").fill("conference")
        a = page.locator(f"button.log-cal-day[aria-label='{mon}']").bounding_box()
        c = page.locator(f"button.log-cal-day[aria-label='{wed}']").bounding_box()
        page.mouse.move(a["x"] + 10, a["y"] + 10)
        page.mouse.down()
        page.mouse.move(a["x"] + 30, a["y"] + 12)
        page.mouse.move(c["x"] + 10, c["y"] + 10)
        page.mouse.up()
        _wait_ghost(page, wed)
        with httpx.Client(base_url=base_url) as c:
            plans = c.get("/api/plans").json()
        assert [p["date"] for p in plans] == [mon, tue, wed]
        assert {p["day_type"] for p in plans} == {"flex"}
        assert {p["notes"] for p in plans} == {"conference"}
        row = page.locator(".plan-table tr").first
        assert "3 days" in row.inner_text()
        assert "conference" in row.inner_text()
        assert "−24h pool" in row.inner_text()

    def test_projection_reacts_and_toggle_persists(self, page, base_url):
        mon, _, _ = _next_week_days()
        _open_plan(page, base_url, mon)
        before = page.locator(".plan-stat").first.locator(".metric").inner_text()
        page.locator(".plan-type.flex").click()
        page.locator(f"button.log-cal-day[aria-label='{mon}']").click()
        _wait_ghost(page, mon)
        page.wait_for_function(
            "txt => document.querySelector('.plan-stat .metric')?.innerText !== txt",
            arg=before,
            timeout=5000,
        )
        assert page.locator(".plan-stat").first.locator(".metric").inner_text() == "−8.00h"
        page.locator(".seg-toggle button", has_text="At my pace").click()
        page.reload()
        page.wait_for_selector(".seg-toggle", timeout=5000)
        assert "on" in page.locator(".seg-toggle button", has_text="At my pace").get_attribute(
            "class"
        )


class TestLedger:
    def test_commit_creates_the_entries(self, page, base_url):
        mon, tue, _ = _next_week_days()
        with httpx.Client(base_url=base_url) as c:
            c.post(
                "/api/plans", json={"dates": [mon, tue], "day_type": "vacation", "notes": "trip"}
            )
        _open_plan(page, base_url, mon)
        row = page.locator(".plan-table tr").first
        row.locator(".plan-commit").click()
        page.wait_for_function(
            "() => !document.querySelector('.plan-table tr .plan-commit')", timeout=5000
        )
        with httpx.Client(base_url=base_url) as c:
            e = c.get(f"/api/entries/{tue}").json()
            assert e["day_type"] == "vacation" and e["notes"] == "trip"
            assert c.get("/api/plans").json() == []
        assert "logged" in page.locator(".plan-table tr").first.inner_text()
        # The committed days are solid on the calendar now.
        assert "hm-vacation" in page.locator(
            f"button.log-cal-day[aria-label='{mon}']"
        ).get_attribute("class")

    def test_note_can_be_edited_inline(self, page, base_url):
        mon, _, _ = _next_week_days()
        with httpx.Client(base_url=base_url) as c:
            c.post("/api/plans", json={"dates": [mon], "day_type": "holiday"})
        _open_plan(page, base_url, mon)
        page.locator(".plan-note-btn").first.click()
        page.locator(".plan-note-input").fill("local fiesta")
        page.keyboard.press("Enter")
        page.wait_for_selector("text=local fiesta", timeout=5000)
        with httpx.Client(base_url=base_url) as c:
            assert c.get("/api/plans").json()[0]["notes"] == "local fiesta"

    def test_remove_block(self, page, base_url):
        mon, tue, _ = _next_week_days()
        with httpx.Client(base_url=base_url) as c:
            c.post("/api/plans", json={"dates": [mon, tue], "day_type": "vacation"})
        _open_plan(page, base_url, mon)
        page.locator(".plan-remove").first.click()
        page.wait_for_function("() => !document.querySelector('.plan-table')", timeout=5000)
        with httpx.Client(base_url=base_url) as c:
            assert c.get("/api/plans").json() == []


class TestOpenInLog:
    def test_past_day_opens_the_log_tab_with_that_day(self, page, base_url):
        past = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        _open_plan(page, base_url, past)
        page.locator(f"button.log-cal-day[aria-label='{past}']").click()
        page.wait_for_url("**/#log", timeout=5000)
        page.wait_for_function(
            "iso => document.querySelector(`button.log-cal-day[aria-label='${iso}']`)"
            "?.getAttribute('aria-pressed') === 'true'",
            arg=past,
            timeout=5000,
        )
        assert page.locator("h2", has_text="New entry").count() == 1
        with httpx.Client(base_url=base_url) as c:
            assert c.get("/api/plans").json() == []  # nothing was drafted

    def test_logged_future_day_opens_in_edit_mode(self, page, base_url):
        mon, _, _ = _next_week_days()
        with httpx.Client(base_url=base_url) as c:
            c.post("/api/entries", json={"date": mon, "day_type": "holiday", "notes": "fiesta"})
        _open_plan(page, base_url, mon)
        page.locator(f"button.log-cal-day[aria-label='{mon}']").click()
        page.wait_for_url("**/#log", timeout=5000)
        page.wait_for_selector(f"text=Edit {mon}", timeout=5000)
        assert page.locator("select").input_value() == "holiday"

    def test_ledger_deletes_logged_days_after_confirm(self, page, base_url):
        mon, tue, _ = _next_week_days()
        with httpx.Client(base_url=base_url) as c:
            c.post("/api/entries/batch", json={"dates": [mon, tue], "day_type": "vacation"})
        _open_plan(page, base_url, mon)
        row = page.locator(".plan-table tr").first
        assert "logged" in row.inner_text()
        page.once("dialog", lambda d: d.accept())
        row.locator(".plan-delete").click()
        page.wait_for_function("() => !document.querySelector('.plan-table')", timeout=5000)
        with httpx.Client(base_url=base_url) as c:
            assert c.get(f"/api/entries/{mon}").status_code == 404
            assert c.get(f"/api/entries/{tue}").status_code == 404

    def test_ledger_delete_can_be_cancelled(self, page, base_url):
        mon, _, _ = _next_week_days()
        with httpx.Client(base_url=base_url) as c:
            c.post("/api/entries", json={"date": mon, "day_type": "flex"})
        _open_plan(page, base_url, mon)
        page.once("dialog", lambda d: d.dismiss())
        page.locator(".plan-table tr").first.locator(".plan-delete").click()
        page.wait_for_timeout(400)
        with httpx.Client(base_url=base_url) as c:
            assert c.get(f"/api/entries/{mon}").status_code == 200


class TestGhostsElsewhere:
    def test_log_calendar_shows_ghost_and_prefills_the_form(self, page, base_url):
        mon, _, _ = _next_week_days()
        with httpx.Client(base_url=base_url) as c:
            c.post("/api/plans", json={"dates": [mon], "day_type": "flex", "notes": "long weekend"})
        page.goto(f"{base_url}/#log")
        page.wait_for_selector("form", timeout=5000)
        target = datetime.date.fromisoformat(mon)
        if target.month != datetime.date.today().month:
            page.locator("button.log-cal-nav[aria-label='Next month']").click()
        _wait_ghost(page, mon)
        page.locator(f"button.log-cal-day[aria-label='{mon}']").click()
        page.wait_for_function(
            "() => document.querySelector('select')?.value === 'flex'", timeout=5000
        )
        assert page.locator("textarea").first.input_value() == "long weekend"

    def test_logging_a_drafted_day_consumes_the_draft(self, page, base_url):
        mon, _, _ = _next_week_days()
        with httpx.Client(base_url=base_url) as c:
            c.post("/api/plans", json={"dates": [mon], "day_type": "vacation"})
        page.goto(f"{base_url}/#log")
        page.wait_for_selector("form", timeout=5000)
        if datetime.date.fromisoformat(mon).month != datetime.date.today().month:
            page.locator("button.log-cal-nav[aria-label='Next month']").click()
        _wait_ghost(page, mon)
        page.locator(f"button.log-cal-day[aria-label='{mon}']").click()
        page.wait_for_function(
            "() => document.querySelector('select')?.value === 'vacation'", timeout=5000
        )
        page.locator("button.log-submit-btn").click()
        page.wait_for_url("**/#days", timeout=5000)
        page.wait_for_function(
            "() => fetch('/api/plans').then(r => r.json()).then(p => p.length === 0)", timeout=5000
        )
