"""E2E: the quieter Log form.

Notes are an optional "+ Add note" button that opens one textarea in place (like "+ Add break"
does for breaks). On wide screens the form card has a right-hand rail with the day's result
(Net / Target / Δ and a fill bar) and the Create entry button; below 1100px it is one column.

Nothing here leans on shared server config: the target is set to 8h by the autouse fixture, and
every figure asserted is read off the card next to the times the test typed.
"""

from __future__ import annotations

import datetime
import re

import httpx
import pytest

pytestmark = pytest.mark.e2e

TODAY = datetime.date.today()
YESTERDAY = TODAY - datetime.timedelta(days=1)


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


@pytest.fixture(autouse=True)
def _clean(base_url):
    """Fresh entries and an 8h target (an earlier module may leave another one behind)."""
    _wipe(base_url)
    with httpx.Client(base_url=base_url) as c:
        c.put("/api/config", json={"daily_target_hours": 8, "vacation_budget_days": 0})
    yield
    _wipe(base_url)


def _open_log(page, base_url: str, width: int = 1400, height: int = 900) -> None:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/#log")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector(".log-form-card form", timeout=5000)


def _open_day(page, iso: str) -> None:
    page.evaluate(f"Alpine.$data(document.querySelector('main')).openDayInLog('{iso}')")
    page.wait_for_function(
        "(iso) => Alpine.$data(document.querySelector('main')).form.date === iso", arg=iso
    )
    page.wait_for_timeout(150)


def _notes(page):
    return page.locator("textarea[aria-label='Notes']")


def _add_note_button(page):
    return page.locator(".log-form-card button", has_text="+ Add note")


def _post_entry(base_url: str, iso: str, notes: str = "") -> None:
    with httpx.Client(base_url=base_url) as c:
        r = c.post(
            "/api/entries",
            json={
                "date": iso,
                "day_type": "work",
                "start_time": "09:00",
                "end_time": "17:00",
                "breaks": [],
                "notes": notes,
            },
        )
        assert r.status_code == 201, r.text


def _is_focused(page, locator) -> bool:
    return locator.evaluate("e => e === document.activeElement")


class TestNotesAreOptional:
    def test_a_new_entry_shows_the_add_note_button_and_no_textarea(self, page, base_url):
        _open_log(page, base_url)
        assert _add_note_button(page).is_visible()
        assert not _notes(page).is_visible()
        # exactly one textarea in the card, always in the DOM, and the old columns are gone
        assert page.locator(".log-form-card textarea").count() == 1
        assert page.locator(".log-col-notes, .log-notes-inline").count() == 0

    def test_the_button_looks_like_add_break(self, page, base_url):
        _open_log(page, base_url)
        brk = page.locator(".log-form-card button", has_text="+ Add break")
        note = _add_note_button(page)
        assert brk.is_visible()
        assert note.get_attribute("class") == brk.get_attribute("class")
        props = (
            "e => { const s = getComputedStyle(e); "
            "return [s.height, s.fontSize, s.borderTopWidth, s.color, s.backgroundColor]"
            ".join('|'); }"
        )
        assert note.evaluate(props) == brk.evaluate(props)

    def test_clicking_it_opens_a_focused_textarea(self, page, base_url):
        _open_log(page, base_url)
        _add_note_button(page).click()
        _notes(page).wait_for(state="visible", timeout=3000)
        assert not _add_note_button(page).is_visible()
        page.wait_for_function(
            "() => document.activeElement"
            " === document.querySelector(\"textarea[aria-label='Notes']\")"
        )
        assert page.locator(".log-form-card .char-count").inner_text() == "0 chars"
        _notes(page).type("hello")
        assert page.locator(".log-form-card .char-count").inner_text() == "5 chars"

    def test_the_textarea_grows_with_its_text(self, page, base_url):
        _open_log(page, base_url)
        _add_note_button(page).click()
        _notes(page).wait_for(state="visible", timeout=3000)
        page.wait_for_timeout(400)
        before = _notes(page).bounding_box()["height"]
        _notes(page).fill("\n".join(f"line {i}" for i in range(9)))
        page.wait_for_timeout(100)
        assert _notes(page).bounding_box()["height"] > before + 60

    def test_a_saved_note_comes_back_open_and_a_day_without_one_collapsed(self, page, base_url):
        _open_log(page, base_url)
        _add_note_button(page).click()
        _notes(page).wait_for(state="visible", timeout=3000)
        _notes(page).fill("hello")
        page.locator("button.log-submit-btn").click()
        page.wait_for_selector(".save-ribbon.ribbon-show", timeout=5000)
        assert page.url.endswith("#log")

        with httpx.Client(base_url=base_url) as c:
            assert c.get(f"/api/entries/{TODAY.isoformat()}").json()["notes"] == "hello"
        page.get_by_role("tab", name="Days").click()
        page.wait_for_selector("td.notes-col:has-text('hello')", timeout=5000)

        _post_entry(base_url, YESTERDAY.isoformat())
        _open_day(page, TODAY.isoformat())
        _notes(page).wait_for(state="visible", timeout=3000)
        assert _notes(page).input_value() == "hello"
        assert not _add_note_button(page).is_visible()

        # the next day has no note: back to the button, nothing carried over
        _open_day(page, YESTERDAY.isoformat())
        assert _add_note_button(page).is_visible()
        assert not _notes(page).is_visible()
        assert _notes(page).input_value() == ""

    def test_leaving_a_day_with_notes_or_picking_another_one_collapses_it(self, page, base_url):
        _post_entry(base_url, TODAY.isoformat(), "keep me")
        _post_entry(base_url, YESTERDAY.isoformat())
        _open_log(page, base_url)
        _open_day(page, TODAY.isoformat())
        assert _notes(page).is_visible() and _notes(page).input_value() == "keep me"

        # the back arrow starts a new entry: closed again, nothing carried over
        page.locator("a.back-btn").click()
        page.wait_for_function(
            "() => !Alpine.$data(document.querySelector('main')).editingDate", timeout=3000
        )
        assert _add_note_button(page).is_visible() and not _notes(page).is_visible()
        assert _notes(page).input_value() == ""

        # a note being typed on a new entry, then another day picked in the calendar
        _add_note_button(page).click()
        _notes(page).fill("scratch")
        if YESTERDAY.month != TODAY.month:
            page.locator("button.log-cal-nav[aria-label='Previous month']").click()
        page.locator(f"button.log-cal-day[aria-label='{YESTERDAY.isoformat()}']").click()
        page.wait_for_function(
            "(iso) => Alpine.$data(document.querySelector('main')).editingDate === iso",
            arg=YESTERDAY.isoformat(),
        )
        assert _add_note_button(page).is_visible() and not _notes(page).is_visible()
        assert _notes(page).input_value() == ""


class TestNotesCollapse:
    def test_focusing_out_of_an_empty_textarea_collapses_it(self, page, base_url):
        _open_log(page, base_url)
        _add_note_button(page).click()
        _notes(page).wait_for(state="visible", timeout=3000)
        page.locator(".log-form-card .card-title h3").click()
        _add_note_button(page).wait_for(state="visible", timeout=3000)
        assert not _notes(page).is_visible()

    def test_escape_on_an_empty_textarea_collapses_it(self, page, base_url):
        _open_log(page, base_url)
        _add_note_button(page).click()
        _notes(page).wait_for(state="visible", timeout=3000)
        page.keyboard.press("Escape")
        _add_note_button(page).wait_for(state="visible", timeout=3000)
        # and Escape on a field did not throw the whole form away: still on the Log tab
        assert page.url.endswith("#log")

    def test_a_textarea_with_text_stays_open(self, page, base_url):
        _open_log(page, base_url)
        _add_note_button(page).click()
        _notes(page).fill("keep")
        page.keyboard.press("Escape")  # blurs the field; text in it keeps it open
        page.locator(".log-form-card .card-title h3").click()
        page.wait_for_timeout(300)
        assert _notes(page).is_visible() and _notes(page).input_value() == "keep"

    def test_clearing_the_text_does_not_collapse_it_while_typing(self, page, base_url):
        _open_log(page, base_url)
        _add_note_button(page).click()
        _notes(page).fill("abc")
        _notes(page).fill("")
        page.wait_for_timeout(300)
        assert _notes(page).is_visible() and _is_focused(page, _notes(page))

    def test_collapsing_on_the_way_to_the_button_does_not_lose_the_click(self, page, base_url):
        # narrow layout: the Create button sits below the notes, so a collapse on blur would
        # move it away from under the pointer
        _open_log(page, base_url, width=600, height=900)
        _add_note_button(page).click()
        _notes(page).wait_for(state="visible", timeout=3000)
        page.locator("button.log-submit-btn").click()
        page.wait_for_selector(".save-ribbon.ribbon-show", timeout=5000)
        assert page.url.endswith("#log")
        with httpx.Client(base_url=base_url) as c:
            assert c.get(f"/api/entries/{TODAY.isoformat()}").status_code == 200


class TestRail:
    def test_wide_the_rail_is_right_of_the_form_with_the_result_and_the_button(
        self, page, base_url
    ):
        _open_log(page, base_url, 1400)
        centre = page.locator(".log-col-center").bounding_box()
        rail = page.locator(".log-col-rail").bounding_box()
        assert rail["x"] >= centre["x"] + centre["width"] - 1
        assert abs(rail["y"] - centre["y"]) < 2  # side by side, rail at the top
        assert page.locator(".log-col-rail .impact-card").count() == 1
        assert page.locator(".log-col-rail button.log-submit-btn").count() == 1
        assert (
            page.locator(".log-col-center .impact-card, .log-col-center .form-footer").count() == 0
        )
        assert page.locator(".log-col-rail .impact-card").is_visible()
        assert page.locator(".log-col-rail button.log-submit-btn").inner_text() == "Create entry"

    def test_narrow_the_rail_is_below_the_form(self, page, base_url):
        _open_log(page, base_url, 900)
        centre = page.locator(".log-col-center").bounding_box()
        rail = page.locator(".log-col-rail").bounding_box()
        assert rail["y"] > centre["y"] + centre["height"] - 1
        assert page.locator(".log-col-rail .impact-card").is_visible()

    def test_the_rail_stays_with_the_top_of_the_card_when_scrolling(self, page, base_url):
        _open_log(page, base_url, 1400, 500)
        assert (
            page.locator(".log-col-rail").evaluate("e => getComputedStyle(e).position") == "sticky"
        )

    def test_no_horizontal_overflow_at_360(self, page, base_url):
        _open_log(page, base_url, 360, 800)
        assert page.evaluate("document.documentElement.scrollWidth") <= 360
        _add_note_button(page).click()
        _notes(page).fill("a long note " * 20)
        page.wait_for_timeout(300)
        assert page.evaluate("document.documentElement.scrollWidth") <= 360
        card = page.locator(".log-form-card").bounding_box()
        assert card["x"] + card["width"] <= 360

    def test_the_old_card_hints_are_gone(self, page, base_url):
        with httpx.Client(base_url=base_url) as c:
            r = c.post("/api/freelance/sources", json={"name": "Local", "hourly_rate": 60})
            assert r.status_code == 201, r.text
        _open_log(page, base_url)
        page.wait_for_selector("[data-testid='freelance-panel']", timeout=5000)
        text = page.evaluate("document.querySelector('.log-layout').textContent")
        assert "the day for the job" not in text
        assert "never the job" not in text
        assert "Employee" in text and "Freelance" in text  # the titles stay


class TestResultFigure:
    @staticmethod
    def _fill_times(page, start: str, end: str) -> None:
        times = page.locator(".log-form-card input[type='time']")
        times.nth(0).fill(start)
        times.nth(1).fill(end)
        page.wait_for_timeout(500)  # the bar animates its width

    @staticmethod
    def _figures(page) -> tuple[float, float]:
        cells = page.locator(".log-col-rail .impact-value").all_inner_texts()
        net, target = (float(re.sub(r"[^0-9.]", "", c)) for c in cells[:2])
        return net, target

    @staticmethod
    def _bar(page) -> tuple[float, str]:
        return page.locator(".log-col-rail .impact-fill").evaluate(
            "e => [e.getBoundingClientRect().width / e.parentElement.getBoundingClientRect().width,"
            " getComputedStyle(e).backgroundColor]"
        )

    @staticmethod
    def _token(page, name: str) -> str:
        return page.evaluate(
            "(n) => { const d = document.createElement('i'); d.style.color = `var(${n})`;"
            " document.body.appendChild(d); const c = getComputedStyle(d).color; d.remove();"
            " return c; }",
            name,
        )

    def test_the_bar_is_net_over_target_and_turns_green_past_it(self, page, base_url):
        _open_log(page, base_url)
        self._fill_times(page, "09:00", "13:00")
        net, target = self._figures(page)
        assert (net, target) == (4.0, 8.0)
        frac, colour = self._bar(page)
        assert frac == pytest.approx(0.5, abs=0.02)
        assert colour != self._token(page, "--k-surplus")

        self._fill_times(page, "09:00", "17:00")
        assert self._bar(page)[0] == pytest.approx(1.0, abs=0.02)

        # past the target the bar is capped at the full width and turns the surplus colour
        self._fill_times(page, "09:00", "20:00")
        frac, colour = self._bar(page)
        assert frac == pytest.approx(1.0, abs=0.02)
        assert colour == self._token(page, "--k-surplus")

    def test_the_figures_keep_their_texts(self, page, base_url):
        _open_log(page, base_url)
        self._fill_times(page, "09:00", "17:00")
        text = page.locator(".impact-card").inner_text()
        for word in ("Net", "Target", "Δ", "8h"):
            assert word in text
        big = page.locator(".log-col-rail .impact-cell").first.locator(".impact-value")
        small = page.locator(".log-col-rail .impact-cell").nth(1).locator(".impact-value")
        size = "e => parseFloat(getComputedStyle(e).fontSize)"
        assert big.evaluate(size) > small.evaluate(size) * 1.5

    def test_the_delta_pulses_when_its_value_changes(self, page, base_url):
        _open_log(page, base_url)
        self._fill_times(page, "09:00", "17:00")
        delta = page.locator(".log-col-rail .impact-delta")
        page.locator(".log-form-card input[type='time']").nth(1).fill("18:00")
        page.wait_for_function(
            "() => document.querySelector('.log-col-rail .impact-delta')"
            ".getAnimations().length > 0",
            timeout=2000,
        )
        assert delta.inner_text().strip() == "+1.00h"

    def test_reduced_motion_switches_the_new_motion_off(self, page, base_url):
        page.emulate_media(reduced_motion="reduce")
        _open_log(page, base_url)
        self._fill_times(page, "09:00", "13:00")
        _add_note_button(page).click()
        _notes(page).wait_for(state="visible", timeout=3000)
        assert page.locator(".log-col-rail .impact-fill").evaluate(
            "e => getComputedStyle(e).transitionDuration"
        ) in ("0s", "0.0001s")
        assert (
            page.locator(".log-col-rail .impact-delta").evaluate("e => e.getAnimations().length")
            == 0
        )
        assert page.locator(".log-notes-block").evaluate("e => e.getAnimations().length") == 0
        assert page.locator("button.log-submit-btn").evaluate(
            "e => getComputedStyle(e).transitionDuration"
        ) in ("0s", "0.0001s")
