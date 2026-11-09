"""E2E: the ISO week column of the Log calendar and the week separators of Days > Employee.

The Log calendar has a "Wk" column on its left; each week number is a button that opens that
week in Days (Employee when the week has an entry, Freelance when it only has blocks). Days >
Employee draws one separator row per ISO week while sorted by date, so there is a row to land on.

The week numbers and ranges asserted here are calendar facts (2026-11-02 is a Monday of ISO week
45, 2026-12-28 starts week 53, 2025-12-29 starts week 1 of 2026), not outputs of the code. The
browser clock is fixed to 2026-12-20 so "today" is far from the week being opened: the jump has
to beat the Days tab's own scroll to today.
"""

from __future__ import annotations

import datetime

import httpx
import pytest

pytestmark = pytest.mark.e2e

FIXED_NOW = "2026-12-20T10:00:00"


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


@pytest.fixture(autouse=True)
def _clean(base_url):
    _wipe(base_url)
    yield
    _wipe(base_url)


def _work(date: str, end: str = "18:00", notes: str = "") -> dict:
    # 09:00 to 18:00 with a 60-minute break = 8h, on target.
    return {
        "date": date,
        "day_type": "work",
        "start_time": "09:00",
        "end_time": end,
        "breaks": [{"break_minutes": 60}],
        "notes": notes,
    }


def _seed(base_url: str, dates: list[str]) -> None:
    with httpx.Client(base_url=base_url) as c:
        for d in dates:
            r = c.post("/api/entries", json=_work(d))
            assert r.status_code == 201, r.text


def _source(base_url: str) -> int:
    with httpx.Client(base_url=base_url) as c:
        r = c.post(
            "/api/freelance/sources", json={"name": "Local", "hourly_rate": 60, "currency": "EUR"}
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]


def _block(base_url: str, **body) -> dict:
    with httpx.Client(base_url=base_url) as c:
        r = c.post("/api/freelance/blocks", json=body)
        assert r.status_code == 201, r.text
        return r.json()


def _open_log(page, base_url: str, year: int, month: int) -> None:
    """Log tab on `month` (1-12) of `year`, with the browser clock fixed."""
    page.clock.set_fixed_time(FIXED_NOW)
    page.goto(f"{base_url}/#days")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector(".log-cal-grid.has-wk", timeout=5000)
    page.evaluate(
        "([y, m]) => { const d = Alpine.$data(document.querySelector('main'));"
        " d.calYear = y; d.calMonth = m - 1; }",
        [year, month],
    )
    page.wait_for_selector(".log-cal-wk", timeout=3000)


def _wk_labels(page) -> list[str]:
    return [t.strip() for t in page.locator(".log-cal-grid.has-wk .log-cal-wk").all_inner_texts()]


def _in_viewport(page, selector: str) -> bool:
    return page.evaluate(
        "(sel) => { const r = document.querySelector(sel)?.getBoundingClientRect();"
        " return !!r && r.top >= 0 && r.bottom <= window.innerHeight; }",
        selector,
    )


def _columns(page, selector: str) -> int:
    return page.evaluate(
        "(sel) => getComputedStyle(document.querySelector(sel)).gridTemplateColumns"
        ".split(' ').length",
        selector,
    )


class TestWeekColumn:
    def test_november_2026_reads_44_to_49(self, page, base_url):
        _open_log(page, base_url, 2026, 11)
        assert _wk_labels(page) == ["44", "45", "46", "47", "48", "49"]
        # the header cell and an eighth grid column
        assert page.locator(".log-cal-grid.has-wk .log-cal-dow").first.inner_text() == "Wk"
        assert _columns(page, ".log-cal-grid.has-wk") == 8

    def test_december_28_2026_is_week_53(self, page, base_url):
        _open_log(page, base_url, 2026, 12)
        labels = _wk_labels(page)
        assert labels[-1] == "53"
        last = page.locator(".log-cal-grid.has-wk .log-cal-wk").last
        assert last.get_attribute("aria-label") == "Week 53, Dec 28 – Jan 3"

    def test_december_29_2025_is_week_1_of_2026(self, page, base_url):
        _open_log(page, base_url, 2026, 1)
        # Jan 1 2026 is a Thursday: the first row is the week of Dec 29 and reads 1
        assert _wk_labels(page) == ["1", "2", "3", "4", "5"]
        first = page.locator(".log-cal-grid.has-wk .log-cal-wk").first
        assert first.get_attribute("aria-label") == "Week 1, Dec 29 – Jan 4"

    def test_week_buttons_do_not_look_like_day_cells(self, page, base_url):
        _open_log(page, base_url, 2026, 11)
        wk = page.locator(".log-cal-wk")
        assert wk.count() == 6
        assert page.locator("button.log-cal-wk.log-cal-day").count() == 0
        assert page.locator(".log-cal-wk[aria-pressed]").count() == 0
        # the day cells are still the 30 days of November, nothing else
        assert page.locator(".log-cal-day:not(.log-cal-pad)").count() == 30
        assert page.locator(".log-cal .log-cal-nav").count() == 0
        assert page.locator(".log-cal .log-cal-title").count() == 0

    def test_enabled_only_where_the_week_has_an_entry(self, page, base_url):
        _seed(base_url, ["2026-11-02", "2026-11-03", "2026-11-04"])
        _open_log(page, base_url, 2026, 11)
        w45 = page.locator(".log-cal-wk", has_text="45")
        w46 = page.locator(".log-cal-wk", has_text="46")
        w45.wait_for(timeout=3000)
        page.wait_for_function(
            "() => !document.querySelectorAll('.log-cal-wk')[1].disabled", timeout=3000
        )
        assert w45.is_enabled()
        assert w46.is_disabled()
        assert w45.get_attribute("aria-label") == "Week 45, Nov 2 – 8"
        assert w45.get_attribute("title") == "W45 · Nov 2 – 8"

    def test_the_week_of_the_selected_day_is_marked(self, page, base_url):
        _seed(base_url, ["2026-11-04"])
        _open_log(page, base_url, 2026, 11)
        page.locator("[aria-label='2026-11-04']").click()
        sel = page.locator(".log-cal-wk.sel")
        sel.wait_for(timeout=3000)
        assert sel.inner_text().strip() == "45"
        assert sel.count() == 1


class TestJump:
    def test_clicking_a_week_lands_on_its_separator_in_days_employee(self, page, base_url):
        # W45 is the week to open; filler up to the 18th of December keeps "today" (Dec 20) far
        # from it, so a scroll to the Days tab's today row would leave W45 off screen.
        filler = []
        day = datetime.date(2026, 11, 9)
        while day <= datetime.date(2026, 12, 18):
            if day.weekday() < 5:
                filler.append(day.isoformat())
            day += datetime.timedelta(days=1)
        _seed(base_url, ["2026-11-02", "2026-11-03", "2026-11-04", *filler])
        _open_log(page, base_url, 2026, 11)
        page.wait_for_function(
            "() => !document.querySelectorAll('.log-cal-wk')[1].disabled", timeout=5000
        )
        page.locator(".log-cal-wk", has_text="45").click()
        page.wait_for_url("**/#weeks", timeout=5000)
        page.wait_for_selector("#eweek-2026-11-02", state="attached", timeout=5000)

        # checked after the Days tab's own scroll to today has run and settled
        page.wait_for_timeout(1500)
        assert _in_viewport(page, "#eweek-2026-11-02 .week-sep")
        state = page.evaluate(
            "() => { const d = Alpine.$data(document.querySelector('main'));"
            " return { mode: d.daysMode, year: d.daysYear, sort: d.sortKey }; }"
        )
        assert state == {"mode": "employee", "year": "2026", "sort": "date"}
        sep = page.locator("#eweek-2026-11-02 .week-sep").inner_text()
        assert "W45" in sep and "Nov 2 – 8" in sep and "3 days" in sep
        # three 8 h days; the target half depends on the shared config, so it is not asserted
        assert page.locator("#eweek-2026-11-02 .ws-net").inner_text() == "24h"
        # the jump opens the week it lands on
        btn = page.locator("#eweek-2026-11-02 .week-sep-btn")
        assert btn.get_attribute("aria-expanded") == "true"

    def test_a_week_straddling_two_years_switches_the_year_filter_to_all(self, page, base_url):
        _seed(base_url, ["2026-12-31", "2027-01-01"])
        _open_log(page, base_url, 2026, 12)
        page.wait_for_function(
            "() => !document.querySelectorAll('.log-cal-wk')[4].disabled", timeout=5000
        )
        page.locator(".log-cal-wk", has_text="53").click()
        page.wait_for_url("**/#weeks", timeout=5000)
        page.wait_for_selector("#eweek-2026-12-28", state="attached", timeout=5000)
        page.wait_for_timeout(1500)
        year = page.evaluate("Alpine.$data(document.querySelector('main')).daysYear")
        assert year == "all"
        sep = page.locator("#eweek-2026-12-28 .week-sep").inner_text()
        assert "W53" in sep and "2 days" in sep and "Dec 28 – Jan 3" in sep
        # both days sit under that one separator
        assert page.locator(".week-sep", has_text="W53").count() == 1

    def test_a_week_with_only_freelance_blocks_opens_days_freelance(self, page, base_url):
        src = _source(base_url)
        _block(base_url, date="2026-11-10", source_id=src, hours=2)
        _open_log(page, base_url, 2026, 11)
        page.wait_for_function(
            "() => !document.querySelectorAll('.log-cal-wk')[2].disabled", timeout=5000
        )
        page.locator(".log-cal-wk", has_text="46").click()
        page.wait_for_url("**/#weeks", timeout=5000)
        page.wait_for_selector("[data-testid='days-freelance']", timeout=5000)
        row = page.locator("tr.wk-row#wk-2026-11-09")
        row.wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(800)
        assert _in_viewport(page, "tr.wk-row#wk-2026-11-09")
        mode = page.evaluate("Alpine.$data(document.querySelector('main')).daysMode")
        assert mode == "freelance"


class TestWeekSeparators:
    def test_one_separator_per_week_while_sorted_by_date(self, page, base_url):
        _seed(base_url, ["2026-11-02", "2026-11-03", "2026-11-09", "2026-11-10"])
        page.clock.set_fixed_time(FIXED_NOW)
        page.goto(f"{base_url}/#weeks")
        page.wait_for_selector(".days-table", timeout=5000)
        assert page.locator(".days-table .week-sep").count() == 2
        page.get_by_test_id("wk-expand-all").click()
        assert page.locator(".days-table .month-sep").count() == 1
        # a week separator is not a month separator
        assert page.locator(".days-table .week-sep.month-sep").count() == 0
        # newest first: W46 then W45
        ids = page.locator(".days-table .week-sep-name").all_inner_texts()
        assert ids == ["W46", "W45"]
        # the entry rows keep their anchors
        assert page.locator("tbody#day-row-2026-11-03").count() == 1

    def test_no_week_separators_under_the_net_hours_sort(self, page, base_url):
        _seed(base_url, ["2026-11-02", "2026-11-03", "2026-11-09"])
        page.clock.set_fixed_time(FIXED_NOW)
        page.goto(f"{base_url}/#weeks")
        page.wait_for_selector(".days-table", timeout=5000)
        assert page.locator(".days-table .week-sep").count() == 2
        page.locator(".days-table th.sortable", has_text="Net").click()
        page.wait_for_timeout(200)
        assert page.locator(".days-table .week-sep").count() == 0
        assert page.locator(".days-table .month-sep").count() == 0


class TestOtherCalendarsKeepSevenColumns:
    def test_bulk_modal_and_plan_calendars(self, page, base_url):
        _open_log(page, base_url, 2026, 11)
        assert _columns(page, ".log-cal-grid.has-wk") == 8
        page.locator(".bulk-trigger button").click()
        page.wait_for_selector(".bulk-modal .log-cal-grid", timeout=3000)
        assert _columns(page, ".bulk-modal .log-cal-grid") == 7
        assert page.locator(".bulk-modal .log-cal-wk").count() == 0

        page.goto(f"{base_url}/#plan")
        page.wait_for_selector(".plan-cal .log-cal-grid", timeout=5000)
        assert _columns(page, ".plan-cal .log-cal-grid") == 7
        assert page.locator(".plan-cal .log-cal-wk").count() == 0
