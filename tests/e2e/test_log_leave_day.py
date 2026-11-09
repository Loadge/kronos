"""E2E: leaving a day being edited in Log is done on the calendar.

A click on the day being edited leaves the edit; a click on another day leaves it and
selects that day, with a fresh form. Fixed dates in October 2026, so nothing here depends on
the hour the suite runs.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.e2e

D14, D15, D16, D17 = "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17"
DATA = "Alpine.$data(document.querySelector('main'))"


def _post(base_url, iso, start, end, notes, breaks=()):
    with httpx.Client(base_url=base_url) as c:
        r = c.post(
            "/api/entries",
            json={
                "date": iso,
                "day_type": "work",
                "start_time": start,
                "end_time": end,
                "breaks": [{"break_minutes": m} for m in breaks],
                "notes": notes,
            },
        )
        assert r.status_code == 201, r.text


@pytest.fixture(autouse=True)
def _data(base_url):
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        c.put("/api/config", json={"daily_target_hours": 8, "vacation_budget_days": 0})
    _post(base_url, D14, "07:30", "15:45", "note of the 14th", breaks=[30])
    _post(base_url, D15, "08:15", "16:00", "note of the 15th")
    _post(base_url, D17, "10:00", "18:00", "note of the 17th")
    yield
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")


def _state(page):
    return page.evaluate(
        f"() => {{ const a = {DATA}; return {{ editing: a.editingDate, date: a.form.date,"
        " start: a.form.start_time, end: a.form.end_time, notes: a.form.notes,"
        " breaks: a.form.breaks.length, type: a.form.day_type, leave: a.form.leave_hours,"
        " year: a.calYear, month: a.calMonth }; }"
    )


def _day(page, iso):
    return page.locator(f".log-cal-day[aria-label='{iso}']")


def _edit_14(page, base_url):
    page.goto(f"{base_url}/#days")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector(".log-form-card form", timeout=5000)
    page.evaluate(f"{DATA}.openDayInLog('{D14}')")
    page.wait_for_function(f"() => {DATA}.editingDate === '{D14}'", timeout=5000)
    page.wait_for_selector(
        f".log-cal-day[aria-label='{D15}'].hm-surplus, "
        f".log-cal-day[aria-label='{D15}']:not(.hm-empty)",
        timeout=5000,
    )


def _wait_editing(page, iso):
    page.wait_for_function(f"() => {DATA}.editingDate === '{iso}'", timeout=5000)


class TestLeaveDay:
    def test_click_on_the_day_being_edited_leaves_it(self, page, base_url):
        _edit_14(page, base_url)
        assert _state(page)["breaks"] == 1
        _day(page, D14).click()
        page.wait_for_function(f"() => {DATA}.editingDate === null", timeout=5000)
        st = _state(page)
        assert st["editing"] is None
        assert page.locator(".form-footer .btn-action").inner_text() == "Create entry"
        assert (st["year"], st["month"]) == (2026, 9)
        assert "October 2026" in page.locator(".log-cal").get_attribute("aria-label")

    def test_click_on_another_day_with_an_entry_opens_it(self, page, base_url):
        _edit_14(page, base_url)
        _day(page, D15).click()
        _wait_editing(page, D15)
        st = _state(page)
        assert (st["date"], st["start"], st["end"]) == (D15, "08:15", "16:00")
        assert st["notes"] == "note of the 15th"
        assert st["breaks"] == 0
        assert page.locator(".form-footer .btn-action").inner_text() == "Save changes"

    def test_click_on_an_empty_day_starts_a_fresh_entry(self, page, base_url):
        _edit_14(page, base_url)
        assert _state(page)["notes"] == "note of the 14th"
        _day(page, D16).click()
        page.wait_for_function(f"() => {DATA}.form.date === '{D16}'", timeout=5000)
        page.wait_for_timeout(300)
        st = _state(page)
        assert st["editing"] is None
        assert st["date"] == D16
        assert (st["start"], st["end"]) == ("09:00", "17:00")
        assert st["notes"] == ""
        assert st["breaks"] == 0
        assert st["type"] == "work"
        assert st["leave"] is None
        assert page.locator(".form-footer .btn-action").inner_text() == "Create entry"
        assert page.locator("textarea[aria-label='Notes']").count() == 0 or (
            page.locator("textarea[aria-label='Notes']").input_value() == ""
        )

    def test_click_on_a_drafted_day_starts_from_its_draft(self, page, base_url):
        with httpx.Client(base_url=base_url) as c:
            body = {"dates": [D16], "day_type": "vacation", "notes": "long weekend"}
            r = c.post("/api/plans", json=body)
            assert r.status_code == 200, r.text
        _edit_14(page, base_url)
        _day(page, D16).click()
        page.wait_for_function(f"() => {DATA}.form.day_type === 'vacation'", timeout=5000)
        st = _state(page)
        assert st["editing"] is None
        assert st["date"] == D16
        assert st["notes"] == "long weekend"
        assert st["breaks"] == 0  # the break of the 14th stayed behind

    def test_unsaved_changes_are_discarded(self, page, base_url):
        _edit_14(page, base_url)
        notes = page.locator("textarea[aria-label='Notes']")
        notes.fill("typed but never saved")
        _day(page, D15).click()
        _wait_editing(page, D15)
        _day(page, D14).click()
        _wait_editing(page, D14)
        assert _state(page)["notes"] == "note of the 14th"
        with httpx.Client(base_url=base_url) as c:
            assert c.get(f"/api/entries/{D14}").json()["notes"] == "note of the 14th"

    def test_no_day_is_disabled_or_dimmed_while_editing(self, page, base_url):
        _edit_14(page, base_url)
        res = page.evaluate(
            "() => [...document.querySelectorAll('.log-cal-day')].map(b => ({"
            " pad: b.classList.contains('log-cal-pad'), disabled: b.disabled,"
            " opacity: getComputedStyle(b).opacity }))"
        )
        days = [r for r in res if not r["pad"]]
        pads = [r for r in res if r["pad"]]
        assert len(days) == 31
        assert [r for r in days if r["disabled"]] == []
        assert {r["opacity"] for r in days} == {"1"}
        assert pads and all(r["disabled"] for r in pads)
        assert page.locator(".log-cal--editing").count() == 0

    @pytest.mark.parametrize("editing", [False, True])
    def test_title_is_just_log_and_there_is_no_back_button(self, page, base_url, editing):
        _edit_14(page, base_url)
        if not editing:
            _day(page, D14).click()
            page.wait_for_function(f"() => {DATA}.editingDate === null", timeout=5000)
        assert page.locator(".back-btn").count() == 0
        h2 = page.locator("section[aria-label='Days'] .page-head h2")
        assert h2.count() == 1
        assert h2.inner_text() == "Days"
        assert h2.locator(".page-sub").count() == 0

    def test_escape_still_leaves_the_edit(self, page, base_url):
        _edit_14(page, base_url)
        page.locator("section[aria-label='Days'] .page-head h2").click()
        page.keyboard.press("Escape")
        page.wait_for_function(f"() => {DATA}.editingDate === null", timeout=5000)
        st = _state(page)
        assert (st["year"], st["month"]) == (2026, 9)

    def test_a_late_answer_for_the_first_click_does_not_overwrite_the_second(self, page, base_url):
        held = []

        def hold_15(route):
            held.append(route)

        _edit_14(page, base_url)
        page.route(f"**/api/entries/{D15}", hold_15)
        _day(page, D15).click()
        for _ in range(50):
            if held:
                break
            page.wait_for_timeout(50)
        assert len(held) == 1
        _day(page, D17).click()
        _wait_editing(page, D17)
        held[0].continue_()
        page.wait_for_timeout(500)
        st = _state(page)
        assert st["editing"] == D17
        assert st["date"] == D17
        assert st["notes"] == "note of the 17th"
        assert (st["start"], st["end"]) == ("10:00", "18:00")
