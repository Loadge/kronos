"""E2E: staying in the Log tab after a save, the version label and the "Update ready" pill.

Saving or deleting an entry no longer throws the user to Days. The header shows the app
version faintly next to the title. The page remembers which build it loaded (the
``kronos-build`` meta tag), asks ``/api/version`` when it becomes visible again, and offers a
quiet pill when the server has a newer one. It never reloads by itself.

Nothing here depends on state left by another test: each test wipes the DB first and sets the
date it asserts on, and the "newer build" is a routed ``/api/version`` answer.
"""

from __future__ import annotations

import datetime
import json
import time

import httpx
import pytest

pytestmark = pytest.mark.e2e

NEWER = {"version": "99", "build": "deadbeef00"}


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")


@pytest.fixture(autouse=True)
def _clean(base_url):
    _wipe(base_url)
    yield
    _wipe(base_url)


def _day(day: int) -> str:
    return datetime.date.today().replace(day=day).isoformat()


def _open(page, base_url: str, tab: str = "log") -> None:
    page.goto(f"{base_url}/#{tab}")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("main .app-header", timeout=5000)


def _announce_newer_build(page) -> None:
    """Every /api/version answer says the server has moved on."""
    page.route(
        "**/api/version",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(NEWER)
        ),
    )


def _become_visible(page) -> None:
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")


def _pill(page):
    return page.locator("button.update-pill")


class TestStayInLog:
    def test_saving_a_new_entry_keeps_the_log_tab(self, page, base_url):
        date_str = _day(10)
        _open(page, base_url)
        page.locator(f".log-cal-day[aria-label='{date_str}']").click()
        page.select_option("select", "vacation")

        page.locator("button.btn-action--block").click()

        page.wait_for_selector(".save-ribbon.ribbon-show", timeout=5000)
        assert "Saved" in page.locator(".ribbon-msg").inner_text()
        page.wait_for_function(
            "iso => document.querySelector(`[aria-label='${iso}']`)?.className.includes('hm-empty')"
            " === false",
            arg=date_str,
            timeout=5000,
        )
        cell = page.locator(f".log-cal-day[aria-label='{date_str}']")
        assert "hm-vacation" in (cell.get_attribute("class") or "")
        assert page.url.endswith("#log")
        assert page.evaluate("Alpine.$data(document.querySelector('main')).tab") == "log"
        # the form is ready for the next day and the saved one reached the server
        assert page.locator("button.btn-action--block").inner_text() == "Create entry"
        with httpx.Client(base_url=base_url) as c:
            assert c.get(f"/api/entries/{date_str}").json()["day_type"] == "vacation"

    def test_the_calendar_stays_on_the_month_being_worked_in(self, page, base_url):
        _open(page, base_url)
        # a month that is not this one (March 2025), so a reset to "now" would show
        page.evaluate(
            "() => { const d = Alpine.$data(document.querySelector('main'));"
            " d.calYear = 2025; d.calMonth = 2; }"
        )
        page.locator(".log-cal-day[aria-label='2025-03-10']").click()
        page.select_option("select", "vacation")

        page.locator("button.btn-action--block").click()

        page.wait_for_selector(".save-ribbon.ribbon-show", timeout=5000)
        month = page.evaluate(
            "() => { const d = Alpine.$data(document.querySelector('main'));"
            " return [d.calYear, d.calMonth]; }"
        )
        assert month == [2025, 2]
        assert page.url.endswith("#log")

    def test_editing_and_saving_keeps_the_log_tab(self, page, base_url):
        date_str = _day(11)
        with httpx.Client(base_url=base_url) as c:
            r = c.post("/api/entries", json={"date": date_str, "day_type": "vacation"})
            assert r.status_code == 201, r.text
        _open(page, base_url)
        page.locator(f".log-cal-day[aria-label='{date_str}']").click()
        page.get_by_role("button", name="Delete").wait_for(timeout=5000)
        page.select_option("select", "sick")

        page.locator("button.btn-action--block").click()

        page.wait_for_selector(".save-ribbon.ribbon-show", timeout=5000)
        assert page.url.endswith("#log")
        page.wait_for_function(
            "iso => document.querySelector(`[aria-label='${iso}']`)?.className.includes('hm-sick')",
            arg=date_str,
            timeout=5000,
        )

    def test_deleting_an_entry_keeps_the_log_tab(self, page, base_url):
        date_str = _day(12)
        with httpx.Client(base_url=base_url) as c:
            r = c.post("/api/entries", json={"date": date_str, "day_type": "vacation"})
            assert r.status_code == 201, r.text
        _open(page, base_url)
        page.locator(f".log-cal-day[aria-label='{date_str}']").click()
        page.get_by_role("button", name="Delete").wait_for(timeout=5000)

        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Delete").click()

        page.wait_for_selector(".save-ribbon.ribbon-show", timeout=5000)
        assert page.locator(".ribbon-msg").inner_text() == f"Deleted {date_str}"
        assert page.url.endswith("#log")
        assert page.evaluate("Alpine.$data(document.querySelector('main')).tab") == "log"
        page.wait_for_function(
            "iso => document.querySelector(`[aria-label='${iso}']`)"
            "?.className.includes('hm-empty')",
            arg=date_str,
            timeout=5000,
        )
        with httpx.Client(base_url=base_url) as c:
            assert c.get(f"/api/entries/{date_str}").status_code == 404

    def test_a_second_submit_while_saving_is_ignored(self, page, base_url):
        date_str = _day(13)
        posts: list[str] = []

        def slow_post(route):
            if route.request.method == "POST":
                posts.append(route.request.url)
                time.sleep(0.6)
            route.continue_()

        page.route("**/api/entries", slow_post)
        _open(page, base_url)
        page.locator(f".log-cal-day[aria-label='{date_str}']").click()
        page.select_option("select", "vacation")
        page.evaluate(
            "() => { const d = Alpine.$data(document.querySelector('main'));"
            " d.saveEntry(); d.saveEntry(); }"
        )
        page.wait_for_selector(".save-ribbon.ribbon-show", timeout=5000)
        page.wait_for_timeout(800)
        assert len(posts) == 1
        assert page.locator(".error-banner").is_visible() is False


class TestVersionLabel:
    def test_the_header_shows_a_faint_version_next_to_the_title(self, page, base_url):
        _open(page, base_url, "dashboard")
        label = page.locator(".app-header .brand-ver")
        assert label.inner_text() == "v40"
        title = page.locator(".app-header h1")
        a, b = title.bounding_box(), label.bounding_box()
        assert b["x"] >= a["x"] + a["width"] - 1  # to the right of the title
        assert abs((b["y"] + b["height"]) - (a["y"] + a["height"])) < 12  # on its line
        style = label.evaluate(
            "el => { const s = getComputedStyle(el);"
            " return { color: s.color, opacity: Number(s.opacity),"
            " h1: getComputedStyle(el.parentElement.querySelector('h1')).color,"
            " size: parseFloat(s.fontSize), h1size: parseFloat("
            "getComputedStyle(el.parentElement.querySelector('h1')).fontSize) }; }"
        )
        assert style["opacity"] < 1 or style["color"] != style["h1"]
        assert style["size"] < style["h1size"]
        assert label.get_attribute("title").startswith("build ")


class TestUpdatePill:
    def test_a_newer_build_shows_the_pill(self, page, base_url):
        _open(page, base_url, "dashboard")
        assert not _pill(page).is_visible()
        _announce_newer_build(page)
        _become_visible(page)
        _pill(page).wait_for(state="visible", timeout=5000)
        assert "Update ready" in _pill(page).inner_text()

    def test_the_real_endpoint_leaves_the_pill_hidden(self, page, base_url):
        _open(page, base_url, "dashboard")
        with page.expect_response("**/api/version") as seen:
            _become_visible(page)
        body = seen.value.json()
        meta = page.locator("meta[name='kronos-build']").get_attribute("content")
        assert body["build"] == meta
        page.wait_for_timeout(300)
        assert not _pill(page).is_visible()

    def test_a_newer_build_is_found_when_the_connection_comes_back(self, page, base_url):
        _open(page, base_url, "dashboard")
        _announce_newer_build(page)
        page.evaluate("window.dispatchEvent(new Event('online'))")
        _pill(page).wait_for(state="visible", timeout=5000)

    def test_clicking_it_reloads_and_the_pill_is_gone(self, page, base_url):
        _open(page, base_url, "dashboard")
        _announce_newer_build(page)
        _become_visible(page)
        _pill(page).wait_for(state="visible", timeout=5000)
        page.evaluate("window.__beforeReload = true")
        page.unroute("**/api/version")  # the reloaded page sees the real build

        with page.expect_navigation(timeout=10000):
            _pill(page).click()

        page.wait_for_load_state("networkidle")
        assert page.evaluate("window.__beforeReload") is None
        with page.expect_response("**/api/version"):
            _become_visible(page)
        page.wait_for_timeout(300)
        assert not _pill(page).is_visible()

    def test_nothing_shows_while_offline(self, page, base_url):
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        _open(page, base_url, "dashboard")
        page.context.set_offline(True)
        try:
            _become_visible(page)
            page.wait_for_timeout(800)
            assert not _pill(page).is_visible()
            assert not page.locator(".error-banner").is_visible()
        finally:
            page.context.set_offline(False)
        assert errors == []

    def test_a_failing_endpoint_is_silent(self, page, base_url):
        _open(page, base_url, "dashboard")
        page.route("**/api/version", lambda route: route.fulfill(status=500, body="boom"))
        with page.expect_response("**/api/version"):
            _become_visible(page)
        page.wait_for_timeout(300)
        assert not _pill(page).is_visible()
        assert not page.locator(".error-banner").is_visible()

    def test_the_page_never_reloads_by_itself(self, page, base_url):
        _open(page, base_url, "dashboard")
        page.evaluate("window.__stillHere = 'yes'")
        _announce_newer_build(page)
        _become_visible(page)
        _pill(page).wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(2000)
        assert page.evaluate("window.__stillHere") == "yes"
        assert _pill(page).is_visible()
