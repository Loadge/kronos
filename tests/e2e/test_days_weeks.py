"""E2E: Days > Employee has one line per week.

A week's numbers (Net, Target, delta, Sigma) are always on screen, under the table's own columns;
the arrow only shows or hides the week's day rows, as in Days > Freelance. The browser clock is
fixed to Wednesday 2026-11-04, so the current week is W45 (Nov 2 - 8) and every other week starts
closed. Weeks are seeded as real ones: five days of 09:00 to 18:00 with a 60-minute break are 8h
each, 40h a week, against the 8h daily target of the shared config.
"""

from __future__ import annotations

import datetime

import httpx
import pytest

pytestmark = pytest.mark.e2e

FIXED_NOW = "2026-11-04T10:00:00"
W45 = "2026-11-02"  # the current week
W44 = "2026-10-26"
W43 = "2026-10-19"
W38 = "2026-09-14"
WIDTHS = [(375, 800), (640, 900), (768, 900), (1024, 800), (1280, 900)]


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


@pytest.fixture(autouse=True)
def _clean(base_url):
    """Fresh entries and an 8h target: the wipe keeps settings, and an earlier module of the same
    worker may have left another target, which the weekly maths below assume away."""
    _wipe(base_url)
    with httpx.Client(base_url=base_url) as c:
        c.put("/api/config", json={"daily_target_hours": 8, "vacation_budget_days": 0})
    yield
    _wipe(base_url)


def _day(monday: str, offset: int) -> str:
    return (datetime.date.fromisoformat(monday) + datetime.timedelta(days=offset)).isoformat()


def _week(base_url: str, monday: str, ends: list[str] | None = None, notes: str = "") -> None:
    """Five working days from Monday: 09:00 to `ends[i]` (18:00 = 8h) with a 60-minute break."""
    ends = ends or ["18:00"] * 5
    with httpx.Client(base_url=base_url) as c:
        for i, end in enumerate(ends):
            body = {
                "date": _day(monday, i),
                "day_type": "work",
                "start_time": "09:00",
                "end_time": end,
                "breaks": [{"break_minutes": 60}],
            }
            if notes:
                body["notes"] = notes
            r = c.post("/api/entries", json=body)
            assert r.status_code == 201, r.text


def _open(page, base_url: str, size=(1280, 900)) -> None:
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.clock.set_fixed_time(FIXED_NOW)
    page.goto(f"{base_url}/#weeks")
    page.wait_for_selector(".days-table tr.week-sep", timeout=5000)
    page.wait_for_timeout(300)


def _state(page, expr: str):
    return page.evaluate(f"() => Alpine.$data(document.querySelector('main')).{expr}")


def _expanded(page, monday: str) -> str:
    return page.locator(f"#eweek-{monday} .week-sep-btn").get_attribute("aria-expanded")


def _collapse_all(page) -> None:
    """Press `−` when no week is open: it is aria-disabled and does nothing, and Playwright only
    clicks such a control when forced. What is asserted after it holds either way."""
    page.get_by_test_id("wk-collapse-all").click(force=True)


def _centre(page, selector: str) -> float:
    b = page.locator(selector).bounding_box()
    return b["y"] + b["height"] / 2


class TestCollapsedWeekLine:
    def test_the_numbers_sit_on_one_line_under_their_headers(self, page, base_url):
        _week(base_url, W43, ["18:00", "18:00", "18:00", "18:00", "20:00"])  # 42h, +2
        _week(base_url, W44, ["18:00", "18:00", "18:00", "18:00", "19:00"])  # 41h, +1
        _open(page, base_url)
        assert _expanded(page, W44) == "false" and _expanded(page, W43) == "false"
        # no day of a closed week is in the DOM
        assert page.locator(".days-table tr.day-row").count() == 0
        assert page.locator(f"#day-row-{_day(W44, 2)}").count() == 0

        line = f"#eweek-{W44} tr.week-sep"
        ys = {
            "id": _centre(page, f"{line} .week-sep-name"),
            "net": _centre(page, f"{line} .ws-net"),
            "target": _centre(page, f"{line} .ws-target"),
            "delta": _centre(page, f"{line} .ws-delta"),
            "sigma": _centre(page, f"{line} .ws-sigma"),
        }
        assert max(ys.values()) - min(ys.values()) <= 4, ys
        assert page.locator(f"{line} .ws-net").inner_text() == "41h"
        assert page.locator(f"{line} .ws-target").inner_text() == "40h"
        assert page.locator(f"{line} .ws-delta").inner_text() == "+1.00h"
        assert page.locator(f"{line} .ws-sigma").inner_text() == "+3.00h"
        assert page.locator(f"{line} .week-sep-name").inner_text() == "W44"
        assert page.locator(f"{line} .week-sep-range").inner_text() == "Oct 26 – Nov 1"
        assert page.locator(f"{line} .ws-days").inner_text() == "5 days"

        # each number sits in its header's column
        for cls, header in [
            ("ws-net", "Net"),
            ("ws-target", "Target"),
            ("ws-delta", "Δ"),
            ("ws-sigma", "Σ"),
        ]:
            cell = page.locator(f"{line} .{cls}").bounding_box()
            head = page.locator("th.num", has_text=header).first.bounding_box()
            assert abs(cell["x"] - head["x"]) <= 2 and abs(cell["width"] - head["width"]) <= 2, (
                header,
                cell,
                head,
            )

        # two collapsed weeks sit one under the other
        gap = page.locator(f"#eweek-{W43}").bounding_box()["y"]
        gap -= page.locator(f"#eweek-{W44}").bounding_box()["y"]
        assert 0 < abs(gap) < 60, gap

    def test_the_current_week_has_its_tag_and_the_others_do_not(self, page, base_url):
        _week(base_url, W45, ["18:00"] * 3)
        _week(base_url, W44)
        _open(page, base_url)
        assert page.locator(f"#eweek-{W45} .wk-now").inner_text().lower() == "this week"
        assert page.locator(f"#eweek-{W44} .wk-now").count() == 0
        assert page.locator(f"#eweek-{W45} .ws-days").inner_text() == "3 days"


class TestSigma:
    @pytest.mark.parametrize("newest_first", [True, False])
    def test_the_running_total_at_the_last_day_of_each_week(self, page, base_url, newest_first):
        _week(base_url, W43, ["18:00", "18:00", "18:00", "18:00", "19:00"])  # +1h
        _week(base_url, W44, ["18:00", "18:00", "18:00", "18:00", "20:00"])  # +2h
        _open(page, base_url)
        if not newest_first:
            page.locator("th.sortable", has_text="Date").click()
            page.wait_for_function(
                "() => document.querySelector('.week-sep-name').textContent === 'W43'"
            )
        sigma = {
            "W43": page.locator(f"#eweek-{W43} .ws-sigma").inner_text(),
            "W44": page.locator(f"#eweek-{W44} .ws-sigma").inner_text(),
        }
        assert sigma == {"W43": "+1.00h", "W44": "+3.00h"}

    def test_it_follows_the_filter(self, page, base_url):
        # the Sigma is the running total inside the filter: a note search drops the weeks before it
        _week(base_url, W43, ["18:00", "18:00", "18:00", "18:00", "19:00"])
        _week(base_url, W44, ["18:00", "18:00", "18:00", "18:00", "20:00"], notes="audit")
        _open(page, base_url)
        page.locator(".notes-search").fill("audit")
        page.wait_for_function(
            "(m) => !document.getElementById('eweek-' + m)", arg=W43, timeout=3000
        )
        assert page.locator(f"#eweek-{W44} .ws-sigma").inner_text() == "+2.00h"


class TestToggling:
    def test_arrow_and_line_both_toggle_and_only_the_current_week_starts_open(self, page, base_url):
        _week(base_url, W45)
        _week(base_url, W44)
        _open(page, base_url)
        assert _expanded(page, W45) == "true" and _expanded(page, W44) == "false"
        assert page.locator(f"#eweek-{W44} .week-sep-btn").get_attribute("aria-label") == (
            "W44 Oct 26 – Nov 1"
        )
        assert page.locator(".days-table tr.day-row").count() == 5

        page.locator(f"#eweek-{W44} .week-sep-btn").click()
        assert _expanded(page, W44) == "true"
        assert page.locator(".days-table tr.day-row").count() == 10
        page.locator(f"#eweek-{W44} .week-sep-btn").click()
        assert _expanded(page, W44) == "false"
        assert page.locator(".days-table tr.day-row").count() == 5

        # anywhere on the line: here the Net cell
        page.locator(f"#eweek-{W44} .ws-net").click()
        assert _expanded(page, W44) == "true"
        page.locator(f"#eweek-{W45} .ws-sigma").click()
        assert _expanded(page, W45) == "false"
        assert page.locator(".days-table tr.day-row").count() == 5

    def test_month_rows_stay_with_their_totals_when_every_week_is_closed(self, page, base_url):
        _week(base_url, W43)
        _week(base_url, W44)
        _open(page, base_url)
        _collapse_all(page)
        assert page.locator(".days-table tr.day-row").count() == 0
        month = page.locator(".days-table .month-sep").first.inner_text()
        assert "October 2026" in month and "10 days" in month and "80h / 80h" in month

    def test_opening_a_week_does_not_move_the_numbers(self, page, base_url):
        _week(base_url, W43)
        _week(base_url, W44)
        _open(page, base_url)
        _collapse_all(page)
        page.wait_for_timeout(200)
        cells = [f"#eweek-{W43} {c}" for c in (".ws-net", ".ws-target", ".ws-delta", ".ws-sigma")]
        closed = [page.locator(c).bounding_box()["x"] for c in cells]
        page.locator(f"#eweek-{W44} .week-sep-btn").click()
        page.wait_for_selector(".days-table tr.day-row", timeout=3000)
        page.wait_for_timeout(200)
        opened = [page.locator(c).bounding_box()["x"] for c in cells]
        assert all(abs(a - b) <= 2 for a, b in zip(closed, opened, strict=True)), (closed, opened)

    def test_the_arrow_is_not_the_dashboards_week_head(self, page, base_url):
        _week(base_url, W44)
        _open(page, base_url)
        assert page.locator(".days-table .wk-head").count() == 0
        # the dashboard's strip head stretches over its row; this button is as wide as its text
        assert page.locator(f"#eweek-{W44} .week-sep-btn").bounding_box()["width"] < 300


class TestSortedByNet:
    def test_a_flat_list_of_days(self, page, base_url):
        _week(base_url, W45)
        _week(base_url, W44)
        _week(base_url, W43)
        _open(page, base_url)
        assert page.get_by_test_id("wk-expand-all").count() == 1
        page.locator("th.sortable", has_text="Net").click()
        page.wait_for_function("() => !document.querySelector('.days-table tr.week-sep')")
        assert page.locator(".week-sep-btn").count() == 0
        assert page.get_by_test_id("wk-expand-all").count() == 0
        assert page.get_by_test_id("wk-collapse-all").count() == 0
        assert page.locator(".days-table tr.day-row").count() == 15
        page.locator("th.sortable", has_text="Date").click()
        page.wait_for_selector(".days-table tr.week-sep")
        assert page.get_by_test_id("wk-expand-all").count() == 1


class TestNotesSearch:
    def test_weeks_open_while_there_is_text_and_each_goes_back_when_it_clears(self, page, base_url):
        _week(base_url, W43, notes="alpha review")
        _week(base_url, W44, notes="alpha review")
        _open(page, base_url)
        page.locator(f"#eweek-{W43} .week-sep-btn").click()  # W43 open by hand, W44 closed
        assert _expanded(page, W43) == "true" and _expanded(page, W44) == "false"

        page.locator(".notes-search").fill("alpha")
        page.wait_for_function(
            "(m) => document.querySelector('#eweek-' + m + ' .week-sep-btn')"
            ".getAttribute('aria-expanded') === 'true'",
            arg=W44,
        )
        assert _expanded(page, W43) == "true" and _expanded(page, W44) == "true"
        assert page.locator(".days-table tr.day-row").count() == 10
        # an arrow still closes a week while the search has text
        page.locator(f"#eweek-{W44} .week-sep-btn").click()
        assert _expanded(page, W44) == "false"
        assert page.locator(".days-table tr.day-row").count() == 5

        page.locator(".notes-search").fill("")
        page.wait_for_function("() => !document.querySelector('.days-table tr.day-row mark')")
        assert _expanded(page, W43) == "true"
        assert _expanded(page, W44) == "false"
        assert page.locator(".days-table tr.day-row").count() == 5

    def test_expand_all_in_employee_leaves_a_freelance_only_week_alone(self, page, base_url):
        src = None
        with httpx.Client(base_url=base_url) as c:
            r = c.post(
                "/api/freelance/sources",
                json={"name": "Local", "hourly_rate": 60, "currency": "EUR"},
            )
            assert r.status_code == 201, r.text
            src = r.json()["id"]
            r = c.post(
                "/api/freelance/blocks", json={"date": _day(W38, 2), "source_id": src, "hours": 3}
            )
            assert r.status_code == 201, r.text
        _week(base_url, W44)
        _open(page, base_url)
        page.get_by_role("radio", name="Freelance").click()
        page.locator(f"tr.wk-row#wk-{W38} .wk-head").click()  # open the Freelance-only week
        assert _state(page, f"daysWeekOpen['{W38}']") is True
        page.get_by_role("radio", name="Employee").click()
        # a week open by hand, so that `−` has something to close and writes its False
        page.locator(f"#eweek-{W44} .week-sep-btn").click()
        page.get_by_test_id("wk-collapse-all").click()
        assert _state(page, f"daysWeekOpen['{W38}']") is True
        assert _state(page, f"daysWeekOpen['{W44}']") is False
        page.get_by_test_id("wk-expand-all").click()
        assert _state(page, f"daysWeekOpen['{W38}']") is True
        assert _state(page, f"daysWeekOpen['{W44}']") is True
        assert page.locator(".days-table tr.day-row").count() == 5

    def test_expand_all_in_freelance_leaves_an_employee_only_week_alone(self, page, base_url):
        with httpx.Client(base_url=base_url) as c:
            r = c.post(
                "/api/freelance/sources",
                json={"name": "Local", "hourly_rate": 60, "currency": "EUR"},
            )
            assert r.status_code == 201, r.text
            r = c.post(
                "/api/freelance/blocks",
                json={"date": _day(W38, 2), "source_id": r.json()["id"], "hours": 3},
            )
            assert r.status_code == 201, r.text
        _week(base_url, W44)
        _open(page, base_url)
        page.locator(f"#eweek-{W44} .week-sep-btn").click()
        assert _state(page, f"daysWeekOpen['{W44}']") is True
        page.get_by_role("radio", name="Freelance").click()
        page.locator(f"tr.wk-row#wk-{W38} .wk-head").click()  # so that `−` has something to close
        page.get_by_test_id("wk-collapse-all").click()
        assert _state(page, f"daysWeekOpen['{W44}']") is True
        assert _state(page, f"daysWeekOpen['{W38}']") is False


def _open_log(page, base_url: str) -> None:
    page.clock.set_fixed_time(FIXED_NOW)
    page.goto(f"{base_url}/#days")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector(".log-cal-grid.has-wk", timeout=5000)
    page.evaluate(
        "() => { const d = Alpine.$data(document.querySelector('main'));"
        " d.calYear = 2026; d.calMonth = 9; }"
    )
    page.wait_for_selector(".log-cal-wk", timeout=3000)


def _in_viewport(page, selector: str) -> bool:
    return page.evaluate(
        "(sel) => { const r = document.querySelector(sel)?.getBoundingClientRect();"
        " return !!r && r.top >= 0 && r.bottom <= window.innerHeight; }",
        selector,
    )


class TestJumps:
    def test_the_log_calendar_week_button_opens_scrolls_to_and_flashes_the_week(
        self, page, base_url
    ):
        _week(base_url, W44)
        _week(base_url, W43)
        _open_log(page, base_url)
        page.wait_for_function(
            "() => [...document.querySelectorAll('.log-cal-wk')].some(b => !b.disabled)",
            timeout=5000,
        )
        page.locator(".log-cal-wk", has_text="44").click()
        page.wait_for_url("**/#weeks", timeout=5000)
        page.wait_for_selector(f"#eweek-{W44}", state="attached", timeout=5000)
        page.wait_for_function(
            "(m) => document.getElementById('eweek-' + m).classList.contains('week-flash')",
            arg=W44,
            timeout=5000,
        )
        assert _expanded(page, W44) == "true"
        assert page.locator(f"#day-row-{_day(W44, 4)}").count() == 1
        page.wait_for_timeout(800)
        assert _in_viewport(page, f"#eweek-{W44} .week-sep")
        # the other week was not opened by the jump
        assert _expanded(page, W43) == "false"

    def test_today_falls_back_to_its_week_line_when_the_day_is_hidden(self, page, base_url):
        # a week that is closed holds the last logged day before today (Fri Oct 30); weeks above it
        # (newer, listed first) push it off a short screen
        _week(base_url, W44)
        for n in range(1, 9):  # W46 to W53: all in 2026, so the year filter keeps them
            _week(base_url, _day(W45, 7 * n))
        page.set_viewport_size({"width": 1280, "height": 500})
        page.clock.set_fixed_time(FIXED_NOW)
        # the Days tab scrolls to today when it is opened with the entries already loaded
        page.goto(f"{base_url}/#days")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".log-cal-grid", timeout=5000)
        page.get_by_role("tab", name="Weeks").click()
        page.wait_for_selector(f"#eweek-{W44}", state="attached", timeout=5000)
        assert page.locator(f"#day-row-{_day(W44, 4)}").count() == 0
        page.wait_for_function(
            "(m) => document.getElementById('eweek-' + m).classList.contains('week-flash')",
            arg=W44,
            timeout=5000,
        )
        page.wait_for_timeout(1200)
        assert _in_viewport(page, f"#eweek-{W44} .week-sep")


@pytest.mark.parametrize("state", ["collapsed", "open"])
@pytest.mark.parametrize("width,height", WIDTHS)
def test_nothing_scrolls_sideways_and_the_numbers_are_there(page, base_url, width, height, state):
    """Eleven weeks of ten-hour days: the running Sigma of the newest is +110.00h, three digits."""
    start = datetime.date.fromisoformat(W44) - datetime.timedelta(days=7 * 10)
    for n in range(11):
        _week(base_url, (start + datetime.timedelta(days=7 * n)).isoformat(), ["20:00"] * 5)
    _open(page, base_url, (width, height))
    # a no-op when nothing is open (the control is aria-disabled): forced
    button = "wk-collapse-all" if state == "collapsed" else "wk-expand-all"
    page.get_by_test_id(button).click(force=True)
    page.wait_for_timeout(300)
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    line = f"#eweek-{W44} tr.week-sep"
    for cls, text in [
        ("ws-net", "50h"),
        ("ws-target", "40h"),
        ("ws-delta", "+10.00h"),
        ("ws-sigma", "+110.00h"),
    ]:
        cell = page.locator(f"{line} .{cls}")
        assert cell.is_visible()
        assert cell.inner_text() == text
        box = cell.bounding_box()
        # between 641 and 900px the open table (notes column and all) scrolls inside its wrapper,
        # as it always did; the page itself never scrolls sideways (checked above)
        if state == "collapsed" or not 640 < width <= 900:
            assert box["x"] >= 0 and box["x"] + box["width"] <= width + 0.5, (cls, box)
        one_line = cell.evaluate(
            """el => {
              const r = document.createRange(); r.selectNodeContents(el);
              const rects = [...r.getClientRects()].filter(x => x.width > 0);
              const mids = rects.map(x => x.top + x.height / 2);
              return {
                lines: Math.max(...mids) - Math.min(...mids),
                clipped: el.scrollWidth - el.clientWidth,
              };
            }"""
        )
        assert one_line["lines"] <= 6 and one_line["clipped"] <= 1, (cls, one_line)
    arrow = page.locator(f"{line} .week-sep-btn").bounding_box()
    assert arrow["height"] >= 24 - 0.5 and arrow["width"] >= 24 - 0.5, arrow
    if width <= 640:
        # line 1: arrow, week, range; line 2: days, Net / Target, delta and the labelled Sigma
        top = _centre(page, f"{line} .week-sep-name")
        low = _centre(page, f"{line} .ws-net")
        assert low - top >= 12, (top, low)
        assert (
            page.locator(f"{line} .ws-sigma")
            .evaluate("el => getComputedStyle(el, '::before').content")
            .startswith('"Σ')
        )
        assert page.locator("main thead").first.is_hidden()
