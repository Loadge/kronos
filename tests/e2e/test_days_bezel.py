"""E2E: the bezel, the strip of ticks that replaces "Expand all / Collapse all" in Days.

One tick per week, lit when the week is open. It is the map of the year and the way to open,
close and reach weeks, in Employee (the week's surplus about a centre line) and in
Freelance (the week's euros from a baseline). The browser clock is fixed to Wednesday
2026-11-04, so the current week is W45 (Nov 2 - 8) and every other week starts closed;
nothing here depends on the hour the suite runs at.
Weeks are real ones: five days of 09:00 to 18:00 with a 60-minute break are 8h each, against the 8h
daily target the fixture sets.
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
W42 = "2026-10-12"
W41 = "2026-10-05"
W34 = "2026-08-17"
W33 = "2026-08-10"
W32 = "2026-08-03"
TICK = ".bz-tick"
FIRST_2026 = "2025-12-29"  # the Monday of the week holding Jan 1 2026
LAST_2026 = "2026-12-28"  # the Monday of the week holding Dec 31 2026
WIDTHS = [(375, 800), (640, 900), (768, 900), (1024, 800), (1280, 900)]


def _day(monday: str, offset: int) -> str:
    return (datetime.date.fromisoformat(monday) + datetime.timedelta(days=offset)).isoformat()


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


@pytest.fixture(autouse=True)
def _clean(base_url):
    """Fresh entries and an 8h target: an earlier module of this worker may have left another."""
    _wipe(base_url)
    with httpx.Client(base_url=base_url) as c:
        c.put("/api/config", json={"daily_target_hours": 8, "vacation_budget_days": 0})
    yield
    _wipe(base_url)


def _week(base_url: str, monday: str, last_end: str = "18:00", notes: str = "") -> None:
    """Five working days from Monday: 09:00 to 18:00 with a 60-minute break (8h, the target),
    except the Friday, which ends at `last_end`: 19:00 is a week of +1.00h, 20:00 of +2.00h."""
    with httpx.Client(base_url=base_url) as c:
        for i in range(5):
            body = {
                "date": _day(monday, i),
                "day_type": "work",
                "start_time": "09:00",
                "end_time": last_end if i == 4 else "18:00",
                "breaks": [{"break_minutes": 60}],
            }
            if notes:
                body["notes"] = notes
            r = c.post("/api/entries", json=body)
            assert r.status_code == 201, r.text


def _entry(base_url: str, date: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        body = {"date": date, "day_type": "work", "start_time": "09:00", "end_time": "18:00"}
        r = c.post("/api/entries", json=body | {"breaks": [{"break_minutes": 60}]})
        assert r.status_code == 201, r.text


def _source(base_url: str, rate: int = 100) -> int:
    with httpx.Client(base_url=base_url) as c:
        r = c.post(
            "/api/freelance/sources", json={"name": "Local", "hourly_rate": rate, "currency": "EUR"}
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]


def _block(base_url: str, source: int, monday: str, hours: float, offset: int = 1) -> None:
    with httpx.Client(base_url=base_url) as c:
        body = {"date": _day(monday, offset), "source_id": source, "hours": hours}
        r = c.post("/api/freelance/blocks", json=body)
        assert r.status_code == 201, r.text


def _payout(base_url: str, source: int, monday: str, amount: float) -> None:
    with httpx.Client(base_url=base_url) as c:
        body = {"source_id": source, "week_start": monday, "amount": amount}
        r = c.post("/api/freelance/payouts", json=body)
        assert r.status_code == 201, r.text


def _open_days(page, base_url: str, size=(1280, 900), freelance: bool = False) -> None:
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.clock.set_fixed_time(FIXED_NOW)
    page.goto(f"{base_url}/#days")
    if freelance:
        page.get_by_role("radio", name="Freelance").click()
    page.wait_for_selector(".bz-strip", timeout=5000)
    page.wait_for_timeout(300)


def _state(page, expr: str):
    return page.evaluate(f"() => Alpine.$data(document.querySelector('main')).{expr}")


def _set(page, assignment: str) -> None:
    page.evaluate(f"() => {{ Alpine.$data(document.querySelector('main')).{assignment}; }}")
    page.wait_for_timeout(250)


def _tick(page, monday: str):
    return page.locator(f"{TICK}[data-monday='{monday}']")


def _bar(page, monday: str) -> dict:
    return page.locator(f"{TICK}[data-monday='{monday}'] .bz-bar").bounding_box()


def _count(page) -> str:
    return page.locator(".bz-count").inner_text()


def _line(page, monday: str):
    """The week's line in the table: `eweek-` in Employee, `wk-` in Freelance."""
    return page.locator(f"#eweek-{monday}, #wk-{monday}")


def _visible_under_strip(page, monday: str) -> bool:
    return page.evaluate(
        """(m) => {
          const el = document.getElementById('eweek-' + m) || document.getElementById('wk-' + m);
          const bz = document.querySelector('.bz').getBoundingClientRect();
          const r = el.getBoundingClientRect();
          return r.top >= bz.bottom - 1 && r.bottom <= window.innerHeight;
        }""",
        monday,
    )


def _colour(page, css: str) -> str:
    """What a CSS colour (`var(--paid)`) computes to, as the browser writes it."""
    return page.evaluate(
        """(v) => { const p = document.createElement('i'); p.style.color = v;
          document.body.append(p); const c = getComputedStyle(p).color; p.remove(); return c; }""",
        css,
    )


def _bar_colour(page, monday: str) -> str:
    return page.evaluate(
        "(m) => getComputedStyle(document.querySelector(`.bz-tick[data-monday='${m}'] .bz-bar`))"
        ".backgroundColor",
        monday,
    )


def _wait_flash(page, monday: str) -> None:
    page.wait_for_function(
        "(m) => (document.getElementById('eweek-' + m) || document.getElementById('wk-' + m))"
        ".classList.contains('week-flash')",
        arg=monday,
        timeout=5000,
    )


def _centre(page, monday: str) -> tuple[float, float]:
    b = _tick(page, monday).bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def _drag(page, mondays: list[str]) -> None:
    x0, y = _centre(page, mondays[0])
    x1, _ = _centre(page, mondays[-1])
    page.mouse.move(x0, y)
    page.mouse.down()
    page.mouse.move(x1, y, steps=25)
    page.mouse.up()
    page.wait_for_timeout(200)


# ---------------------------------------------------------------------------------------------
class TestSlotsAndHeights:
    def test_employee_a_year_has_53_slots_and_heights_follow_the_surplus(self, page, base_url):
        _week(base_url, W32, "19:00")  # +1.00h
        _week(base_url, W33, "20:00")  # +2.00h
        _week(base_url, W34, "17:00")  # -1.00h
        _open_days(page, base_url)
        ticks = page.locator(TICK)
        assert ticks.count() == 53
        assert ticks.first.get_attribute("data-monday") == FIRST_2026
        assert ticks.last.get_attribute("data-monday") == LAST_2026
        assert page.locator(f"{TICK}:not(.empty)").count() == 3

        plus1, plus2, minus1 = _bar(page, W32), _bar(page, W33), _bar(page, W34)
        assert plus2["height"] == pytest.approx(2 * plus1["height"], abs=0.6), (plus1, plus2)
        assert minus1["height"] == pytest.approx(plus1["height"], abs=0.6)
        # the centre line: surplus rises above it, the deficit hangs under it
        box = _tick(page, W32).bounding_box()
        middle = box["y"] + box["height"] / 2
        assert plus1["y"] + plus1["height"] == pytest.approx(middle, abs=1)
        assert plus2["y"] + plus2["height"] == pytest.approx(middle, abs=1)
        assert minus1["y"] == pytest.approx(middle, abs=1)
        # one scale for the strip: the largest absolute value fills half the tick
        assert plus2["height"] == pytest.approx(box["height"] / 2, abs=1)

    def test_a_week_with_data_is_at_least_two_pixels_tall(self, page, base_url):
        _week(base_url, W32, "20:00")  # +2.00h
        _week(base_url, W33, "18:00")  # +0.00h: the same as its target
        _open_days(page, base_url)
        assert _bar(page, W33)["height"] >= 2
        assert _bar(page, W33)["height"] < _bar(page, W32)["height"]

    def test_employee_the_edge_week_of_a_year_is_not_lost(self, page, base_url):
        _entry(base_url, "2025-12-30")  # Tuesday of the week of Dec 29: a 2025 day
        _week(base_url, W44)  # a 2026 week too, so that the strip shows before the year changes
        _open_days(page, base_url)
        _set(page, "daysYear = '2025'")
        ticks = page.locator(TICK)
        assert ticks.count() == 53  # Dec 30 2024 to Dec 29 2025
        assert ticks.first.get_attribute("data-monday") == "2024-12-30"
        assert ticks.last.get_attribute("data-monday") == "2025-12-29"
        assert "empty" not in (_tick(page, "2025-12-29").get_attribute("class") or "")
        assert page.locator(f"{TICK}:not(.empty)").count() == 1
        assert _line(page, "2025-12-29").count() == 1  # and the table lists the same week

    def test_freelance_heights_follow_the_euros_and_the_colours_the_tag(self, page, base_url):
        src = _source(base_url, rate=100)
        _block(base_url, src, W41, 10)  # EUR 1,000.00, estimated
        _block(base_url, src, W42, 20)  # EUR 2,000.00, estimated
        _block(base_url, src, W45, 18)  # EUR 1,800.00 estimated ...
        _payout(base_url, src, W45, 1789.07)  # ... paid out as EUR 1,789.07
        _open_days(page, base_url, freelance=True)
        assert page.locator(TICK).count() == 53
        thousand, two_thousand = _bar(page, W41), _bar(page, W42)
        assert two_thousand["height"] == pytest.approx(2 * thousand["height"], abs=0.6)
        # bars rise from the baseline: the three share a bottom edge
        assert thousand["y"] + thousand["height"] == pytest.approx(
            two_thousand["y"] + two_thousand["height"], abs=1
        )
        # W45 is the current week, open by default and paid out: teal. W41 opened by hand: brass.
        _tick(page, W41).click()
        page.wait_for_timeout(500)
        assert _bar_colour(page, W45) == _colour(page, "var(--paid)")
        assert _bar_colour(page, W41) == _colour(page, "var(--k-brass)")
        # a closed week is quiet, whatever its tag
        assert _bar_colour(page, W42) == _colour(page, "var(--k-border-strong)")
        # the current week wears its mark, open or closed
        assert _tick(page, W45).evaluate("e => getComputedStyle(e, '::after').width") == "4px"
        assert _tick(page, W41).evaluate("e => getComputedStyle(e, '::after').content") == "none"


class TestLabels:
    def test_a_year_shows_the_initial_of_each_month_at_its_first_tick(self, page, base_url):
        _week(base_url, W44)
        _open_days(page, base_url)
        labels = page.locator(".bz-lab")
        assert labels.all_inner_texts() == list("JFMAMJJASOND")
        assert page.locator(f"{TICK}[data-monday='{FIRST_2026}'] .bz-lab").inner_text() == "J"

    def test_all_over_two_years_has_every_week_and_the_years(self, page, base_url):
        _week(base_url, "2025-11-03")
        _week(base_url, "2026-02-02")
        _open_days(page, base_url)
        _set(page, "daysYear = 'all'")
        mondays = page.locator(TICK).evaluate_all("els => els.map(e => e.dataset.monday)")
        first, last = datetime.date(2025, 11, 3), datetime.date(2026, 2, 2)
        expected = [
            (first + datetime.timedelta(days=7 * n)).isoformat()
            for n in range((last - first).days // 7 + 1)
        ]
        assert mondays == expected and len(mondays) == 14
        # gaps are empty ticks: the two weeks with data have their tick, the twelve between do not
        assert page.locator(f"{TICK}:not(.empty)").count() == 2
        assert page.locator(f"{TICK}.empty").count() == 12
        assert page.locator(".bz-lab").all_inner_texts() == ["2025", "2026"]
        assert page.locator(f"{TICK}[data-monday='2025-11-03'] .bz-lab").inner_text() == "2025"
        assert page.locator(f"{TICK}[data-monday='2025-12-29'] .bz-lab").inner_text() == "2026"


class TestPressing:
    def _weeks(self, base_url) -> None:
        """Twenty-six weeks from W20, so that the oldest is far under the first screen."""
        start = datetime.date(2026, 5, 11)
        for n in range(26):
            _week(base_url, (start + datetime.timedelta(days=7 * n)).isoformat())

    def test_employee_a_closed_tick_opens_scrolls_to_and_flashes_the_week(self, page, base_url):
        self._weeks(base_url)
        _open_days(page, base_url)
        oldest = "2026-05-11"
        assert not _visible_under_strip(page, oldest)
        _tick(page, oldest).click()
        _wait_flash(page, oldest)
        page.wait_for_function(
            "(m) => { const r = document.getElementById('eweek-' + m).getBoundingClientRect();"
            " return r.top > 0 && r.bottom < window.innerHeight; }",
            arg=oldest,
            timeout=5000,
        )
        page.wait_for_timeout(500)
        assert _visible_under_strip(page, oldest)
        assert _tick(page, oldest).get_attribute("aria-pressed") == "true"
        assert page.locator(f"#day-row-{_day(oldest, 4)}").count() == 1

    def test_employee_an_open_tick_closes_the_week_and_does_not_scroll(self, page, base_url):
        self._weeks(base_url)
        _open_days(page, base_url)
        # a week high enough to be centred: closing one near the end shortens the page
        mid = W32
        _tick(page, mid).click()
        _wait_flash(page, mid)
        page.wait_for_timeout(1000)
        y = page.evaluate("window.scrollY")
        assert y > 300
        _tick(page, mid).click()
        page.wait_for_timeout(700)
        assert _tick(page, mid).get_attribute("aria-pressed") == "false"
        assert page.locator(f"#day-row-{_day(mid, 4)}").count() == 0
        assert page.evaluate("window.scrollY") == y

    def test_freelance_a_closed_tick_opens_scrolls_to_and_flashes_the_week(self, page, base_url):
        src = _source(base_url)
        start = datetime.date(2026, 5, 11)
        for n in range(26):
            _block(base_url, src, (start + datetime.timedelta(days=7 * n)).isoformat(), 10)
        _open_days(page, base_url, freelance=True)
        oldest = "2026-05-11"
        assert not _visible_under_strip(page, oldest)
        _tick(page, oldest).click()
        _wait_flash(page, oldest)
        page.wait_for_timeout(1000)
        assert _visible_under_strip(page, oldest)
        assert _state(page, f"daysWeekOpen['{oldest}']") is True
        mid = W32  # high enough to be centred: near the end, closing shortens the page
        _tick(page, mid).click()
        _wait_flash(page, mid)
        page.wait_for_timeout(1000)
        y = page.evaluate("window.scrollY")
        _tick(page, mid).click()
        page.wait_for_timeout(700)
        assert _state(page, f"daysWeekOpen['{mid}']") is False
        assert page.evaluate("window.scrollY") == y


class TestDragging:
    def _four(self, base_url) -> None:
        # W32, (no data), W34, W35: four slots with one empty among them
        for monday in (W32, W34, "2026-08-24"):
            _week(base_url, monday)

    def test_a_drag_opens_the_ticks_with_data_it_crosses_and_only_those(self, page, base_url):
        self._four(base_url)
        _open_days(page, base_url)
        for m in (W32, W34, "2026-08-24"):
            assert _state(page, f"daysWeekIsOpen('{m}')") is False
        y = page.evaluate("window.scrollY")
        _drag(page, [W32, W33, W34, "2026-08-24"])
        for m in (W32, W34, "2026-08-24"):
            assert _tick(page, m).get_attribute("aria-pressed") == "true", m
        assert page.locator(f"{TICK}[aria-pressed='true']").count() == 3  # W45 has no data
        assert "empty" in (_tick(page, W33).get_attribute("class") or "")
        assert (
            _state(page, f"daysWeekOpen.hasOwnProperty('{W33}')") is False
        )  # the empty slot was never written
        # a drag across several ticks does not jump
        page.wait_for_timeout(800)
        assert page.evaluate("window.scrollY") == y

    def test_a_drag_from_an_open_tick_closes(self, page, base_url):
        self._four(base_url)
        _open_days(page, base_url)
        _drag(page, [W32, W33, W34, "2026-08-24"])
        assert page.locator(f"{TICK}[aria-pressed='true']").count() == 3
        _drag(page, [W32, W33, W34, "2026-08-24"])
        for m in (W32, W34, "2026-08-24"):
            assert _tick(page, m).get_attribute("aria-pressed") == "false", m
        assert _state(page, f"daysWeekOpen.hasOwnProperty('{W33}')") is False

    def test_a_drag_leaves_every_other_week_as_it_was(self, page, base_url):
        self._four(base_url)
        _week(base_url, W44)
        _open_days(page, base_url)
        _tick(page, W44).click()
        page.wait_for_timeout(300)
        _drag(page, [W34, "2026-08-24"])
        assert _tick(page, W44).get_attribute("aria-pressed") == "true"
        assert _tick(page, W32).get_attribute("aria-pressed") == "false"


class TestAHandOnTheStrip:
    """What a hand does that a straight mouse line does not: wander, swipe, tap with a finger."""

    def _weeks(self, base_url) -> None:
        start = datetime.date(2026, 5, 11)
        for n in range(26):
            _week(base_url, (start + datetime.timedelta(days=7 * n)).isoformat())

    def _touch(self, page):
        cdp = page.context.new_cdp_session(page)
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
        return cdp

    def _finger(self, cdp, kind: str, x: float = 0, y: float = 0) -> None:
        points = [] if kind == "touchEnd" else [{"x": x, "y": y}]
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})

    def test_a_drag_that_wanders_off_the_strip_keeps_painting(self, page, base_url):
        for monday in (W32, W33, W34):
            _week(base_url, monday)
        _open_days(page, base_url)
        x0, y = _centre(page, W32)
        x1, _ = _centre(page, W34)
        page.mouse.move(x0, y)
        page.mouse.down()
        page.mouse.move(x0, y + 200, steps=4)  # well under the strip, over the table
        page.mouse.move(x1, y + 200, steps=25)
        page.mouse.up()
        page.wait_for_timeout(200)
        for m in (W32, W33, W34):
            assert _tick(page, m).get_attribute("aria-pressed") == "true", m

    def test_a_vertical_swipe_from_a_tick_scrolls_and_toggles_nothing(self, page, base_url):
        self._weeks(base_url)
        _open_days(page, base_url, (375, 800))
        cdp = self._touch(page)
        x, y = _centre(page, W32)
        before = _count(page)
        self._finger(cdp, "touchStart", x, y)
        for step in range(1, 13):
            self._finger(cdp, "touchMove", x, y - step * 20)
            page.wait_for_timeout(16)
        self._finger(cdp, "touchEnd")
        page.wait_for_timeout(400)
        assert page.evaluate("window.scrollY") > 100  # the page did scroll
        assert _count(page) == before
        assert _tick(page, W32).get_attribute("aria-pressed") == "false"

    def test_a_tap_opens_and_jumps(self, page, base_url):
        self._weeks(base_url)
        _open_days(page, base_url, (375, 800))
        cdp = self._touch(page)
        x, y = _centre(page, W32)
        self._finger(cdp, "touchStart", x, y)
        self._finger(cdp, "touchEnd")
        _wait_flash(page, W32)
        assert _tick(page, W32).get_attribute("aria-pressed") == "true"
        page.wait_for_timeout(300)  # a finger has no hover: nothing would ever take a tooltip away
        assert float(page.locator(".bz-tip").evaluate("e => getComputedStyle(e).opacity")) == 0

    def test_a_sideways_finger_paints(self, page, base_url):
        self._weeks(base_url)
        _open_days(page, base_url, (375, 800))
        cdp = self._touch(page)
        x0, y = _centre(page, W32)
        x1, _ = _centre(page, "2026-08-24")
        self._finger(cdp, "touchStart", x0, y)
        for step in range(1, 11):
            self._finger(cdp, "touchMove", x0 + (x1 - x0) * step / 10, y)
            page.wait_for_timeout(16)
        self._finger(cdp, "touchEnd")
        page.wait_for_timeout(300)
        for m in (W32, W33, W34, "2026-08-24"):
            assert _tick(page, m).get_attribute("aria-pressed") == "true", m

    def test_on_a_phone_the_flash_washes_the_row_and_not_each_cell(self, page, base_url):
        self._weeks(base_url)
        _open_days(page, base_url, (375, 800))
        _tick(page, W32).click()
        _wait_flash(page, W32)
        names = page.locator(f"#eweek-{W32} tr").first.evaluate(
            """tr => [getComputedStyle(tr).animationName,
              ...[...tr.children].map(td => getComputedStyle(td).animationName)]"""
        )
        assert names[0] == "week-wash"
        assert set(names[1:]) == {"none"}
        # and the cells let it through: an opaque one stays a dark patch on the wash
        for row in (f"#eweek-{W32} tr", f"#day-row-{_day(W32, 4)} tr"):
            backgrounds = page.locator(row).first.evaluate(
                "tr => [...tr.children].map(td => getComputedStyle(td).backgroundColor)"
            )
            assert set(backgrounds) == {"rgba(0, 0, 0, 0)"}, (row, backgrounds)

    def test_the_tooltip_leaves_with_the_pointer_after_a_click(self, page, base_url):
        _week(base_url, W32)
        _open_days(page, base_url)
        _tick(page, W32).click()
        page.mouse.move(5, 400)
        page.wait_for_timeout(300)
        assert float(page.locator(".bz-tip").evaluate("e => getComputedStyle(e).opacity")) == 0

    def test_a_row_of_the_table_carries_no_stray_style(self, page, base_url):
        _week(base_url, W45)
        _open_days(page, base_url)
        assert page.locator("tbody[style='null']").count() == 0

    def test_the_focus_ring_of_a_chip_button_is_not_cut(self, page, base_url):
        _week(base_url, W45)
        _open_days(page, base_url)
        assert page.locator(".bz-chip").evaluate("e => getComputedStyle(e).overflow") == "visible"


class TestTheChip:
    def _three(self, base_url) -> None:
        for monday in (W43, W44, W45):
            _week(base_url, monday)

    def test_plus_minus_and_the_count(self, page, base_url):
        self._three(base_url)
        _open_days(page, base_url)
        plus, minus = page.get_by_test_id("wk-expand-all"), page.get_by_test_id("wk-collapse-all")
        assert _count(page) == "1 of 3 open"  # the current week
        assert plus.get_attribute("aria-label") == "Expand all weeks"
        assert minus.get_attribute("aria-label") == "Collapse all weeks"
        assert plus.get_attribute("aria-disabled") is None
        assert minus.get_attribute("aria-disabled") is None

        plus.click()
        assert _count(page) == "3 of 3 open"
        assert plus.get_attribute("aria-disabled") == "true"
        assert plus.get_attribute("disabled") is None  # aria-disabled, never the attribute
        assert minus.get_attribute("aria-disabled") is None
        assert page.locator(".days-table tr.day-row").count() == 15
        plus.click(force=True)  # a disabled one does nothing
        assert _count(page) == "3 of 3 open"
        assert page.locator(".days-table tr.day-row").count() == 15

        minus.click()
        assert _count(page) == "0 of 3 open"
        assert minus.get_attribute("aria-disabled") == "true"
        assert minus.get_attribute("disabled") is None
        assert plus.get_attribute("aria-disabled") is None
        assert page.locator(".days-table tr.day-row").count() == 0
        minus.click(force=True)
        assert _count(page) == "0 of 3 open"

    def test_a_disabled_button_is_dim_and_still_a_button_of_24px(self, page, base_url):
        self._three(base_url)
        _open_days(page, base_url)
        page.get_by_test_id("wk-expand-all").click()
        page.wait_for_timeout(500)
        opacity = page.get_by_test_id("wk-expand-all").evaluate("e => getComputedStyle(e).opacity")
        assert float(opacity) < 0.6
        assert (
            float(
                page.get_by_test_id("wk-collapse-all").evaluate("e => getComputedStyle(e).opacity")
            )
            == 1
        )
        for tid in ("wk-expand-all", "wk-collapse-all"):
            box = page.get_by_test_id(tid).bounding_box()
            assert box["width"] >= 24 and box["height"] >= 24, (tid, box)

    def test_the_chip_sits_at_the_right_end_of_the_strip_in_both_modes(self, page, base_url):
        src = _source(base_url)
        for monday in (W43, W44, W45):
            _week(base_url, monday)
            _block(base_url, src, monday, 10)
        rights = []
        for freelance in (False, True):
            _open_days(page, base_url, freelance=freelance)
            strip, chip = (
                page.locator(".bz-strip").bounding_box(),
                page.locator(".bz-chip").bounding_box(),
            )
            assert chip["x"] >= strip["x"] + strip["width"] - 1  # beside the strip, after it
            assert abs((chip["y"] + chip["height"] / 2) - (strip["y"] + strip["height"] / 2)) < 30
            rights.append(round(chip["x"] + chip["width"]))
        assert abs(rights[0] - rights[1]) <= 1, rights

    def test_expand_in_employee_leaves_a_freelance_only_week_alone(self, page, base_url):
        src = _source(base_url)
        _block(base_url, src, W32, 5)  # a Freelance-only week
        _week(base_url, W44)
        _open_days(page, base_url)
        page.get_by_test_id("wk-expand-all").click()
        assert _tick(page, W44).get_attribute("aria-pressed") == "true"
        assert _state(page, f"daysWeekOpen.hasOwnProperty('{W32}')") is False
        page.get_by_role("radio", name="Freelance").click()
        page.wait_for_selector(".bz-strip")
        assert _tick(page, W32).get_attribute("aria-pressed") == "false"
        assert _count(page) == "0 of 1 open"  # W44 has no block: it is no tick here

    def test_the_wave_after_plus_is_capped_and_never_on_load(self, page, base_url):
        start = datetime.date(2026, 5, 11)
        for n in range(26):
            _week(base_url, (start + datetime.timedelta(days=7 * n)).isoformat())
        _open_days(page, base_url)
        # on load: nothing is animating and no delay is set
        assert _state(page, "daysWave") == {}
        assert page.locator("tbody.row-in").count() == 0
        page.get_by_test_id("wk-expand-all").click()
        wave = _state(page, "daysWave")
        assert len(wave) == 25  # every week that was closed
        assert min(wave.values()) == 0 and max(wave.values()) <= 380
        assert list(wave.values()) == sorted(wave.values())  # left to right
        assert page.locator("tbody.row-in").count() > 0
        assert page.locator(".bz-chip.bz-glint").count() == 1
        page.wait_for_timeout(1700)
        assert _state(page, "daysWave") == {}
        assert page.locator("tbody.row-in").count() == 0


class TestKeyboard:
    def _weeks(self, base_url) -> None:
        for monday in (W32, W34, "2026-08-24"):  # one empty slot (W33) between the first two
            _week(base_url, monday)

    def test_the_strip_is_one_tab_stop(self, page, base_url):
        self._weeks(base_url)
        _open_days(page, base_url)
        assert page.locator(f"{TICK}[tabindex='0']").count() == 1
        assert page.locator(f"{TICK}[tabindex='-1']").count() == 2  # the other two with data
        page.locator("nav.year-step button").last.focus()
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.classList.contains('bz-tick')")
        first = page.evaluate("document.activeElement.dataset.monday")
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.classList.contains('bz-btn')")
        assert page.evaluate("document.activeElement.dataset.testid") == "wk-collapse-all"
        page.keyboard.press("Shift+Tab")
        assert page.evaluate("document.activeElement.dataset.monday") == first
        # focus is visible
        outline = page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
        assert outline == "solid"

    def test_arrows_skip_empty_slots_and_enter_opens(self, page, base_url):
        self._weeks(base_url)
        _open_days(page, base_url)
        _tick(page, W32).focus()
        page.keyboard.press("ArrowRight")
        assert page.evaluate("document.activeElement.dataset.monday") == W34  # not the empty W33
        page.keyboard.press("ArrowLeft")
        assert page.evaluate("document.activeElement.dataset.monday") == W32
        page.keyboard.press("ArrowLeft")
        assert page.evaluate("document.activeElement.dataset.monday") == W32  # the first one: stays
        assert page.locator(f"{TICK}[tabindex='0']").count() == 1  # still one stop, now here
        page.keyboard.press("ArrowRight")
        page.keyboard.press("Enter")
        assert _tick(page, W34).get_attribute("aria-pressed") == "true"
        _wait_flash(page, W34)
        page.keyboard.press("Space")
        assert _tick(page, W34).get_attribute("aria-pressed") == "false"
        assert page.evaluate("document.activeElement.dataset.monday") == W34  # focus stays put

    def test_home_and_end_reach_the_ends(self, page, base_url):
        self._weeks(base_url)
        _week(base_url, W44)
        _open_days(page, base_url)
        _tick(page, W34).focus()
        page.keyboard.press("End")
        assert page.evaluate("document.activeElement.dataset.monday") == W44
        page.keyboard.press("ArrowRight")
        assert page.evaluate("document.activeElement.dataset.monday") == W44
        page.keyboard.press("Home")
        assert page.evaluate("document.activeElement.dataset.monday") == W32

    def test_the_names_say_week_range_and_value_and_whether_it_is_open(self, page, base_url):
        _week(base_url, W32, "19:30")
        _open_days(page, base_url)
        tick = _tick(page, W32)
        assert tick.get_attribute("role") == "button"
        assert tick.get_attribute("aria-label") == "W32 · Aug 3 – 9 · +1.50h"
        assert tick.get_attribute("aria-pressed") == "false"
        tick.click()
        assert tick.get_attribute("aria-pressed") == "true"
        # an empty slot is not a control
        empty = _tick(page, W33)
        assert empty.get_attribute("role") is None and empty.get_attribute("tabindex") is None


class TestNotesSearch:
    def test_ticks_without_a_hit_go_empty_and_clearing_restores_each_week(self, page, base_url):
        _week(base_url, W41)
        _week(base_url, W43, notes="alpha review")
        _week(base_url, W44, notes="alpha review")
        _open_days(page, base_url)
        _tick(page, W43).click()  # open by hand: W43 open, W44 and W41 closed
        page.wait_for_timeout(300)
        assert _count(page) == "1 of 3 open"

        page.locator(".notes-search").fill("alpha")
        page.wait_for_function(
            "(m) => document.querySelector(`.bz-tick[data-monday='${m}']`)"
            ".classList.contains('empty')",
            arg=W41,
            timeout=3000,
        )
        assert page.locator(f"{TICK}:not(.empty)").count() == 2
        assert _count(page) == "2 of 2 open"  # the hits: a hit is never hidden
        # the strip acts on the search's own map
        _tick(page, W44).click()
        assert _count(page) == "1 of 2 open"
        assert _state(page, f"daysWeekOpen['{W43}']") is True
        assert _state(page, f"daysWeekOpen.hasOwnProperty('{W44}')") is False

        page.get_by_label("Clear search").click()
        page.wait_for_function(
            "(m) => !document.querySelector(`.bz-tick[data-monday='${m}']`)"
            ".classList.contains('empty')",
            arg=W41,
            timeout=3000,
        )
        assert _tick(page, W43).get_attribute("aria-pressed") == "true"
        assert _tick(page, W44).get_attribute("aria-pressed") == "false"
        assert _tick(page, W41).get_attribute("aria-pressed") == "false"
        assert _count(page) == "1 of 3 open"

    def test_freelance_only_the_ticked_sources_count(self, page, base_url):
        src = _source(base_url)
        with httpx.Client(base_url=base_url) as c:
            r = c.post(
                "/api/freelance/sources",
                json={"name": "Other", "hourly_rate": 50, "currency": "EUR"},
            )
            other = r.json()["id"]
        _block(base_url, src, W43, 10)
        _block(base_url, other, W44, 10)
        _open_days(page, base_url, freelance=True)
        assert page.locator(f"{TICK}:not(.empty)").count() == 2
        _set(page, f"daysToggleSource({other})")
        assert page.locator(f"{TICK}:not(.empty)").count() == 1
        assert "empty" in (_tick(page, W44).get_attribute("class") or "")


class TestWhenItShows:
    def test_sorted_by_net_there_is_no_strip(self, page, base_url):
        _week(base_url, W44)
        _open_days(page, base_url)
        assert page.locator(".bz").count() == 1
        page.locator("th.sortable", has_text="Net").click()
        page.wait_for_function("() => !document.querySelector('.days-table tr.week-sep')")
        assert page.locator(".bz").count() == 0
        assert page.get_by_test_id("wk-expand-all").count() == 0
        page.locator("th.sortable", has_text="Date").click()
        page.wait_for_selector(".bz-strip")

    def test_no_entries_no_strip(self, page, base_url):
        page.clock.set_fixed_time(FIXED_NOW)
        page.goto(f"{base_url}/#days")
        page.wait_for_selector("text=No entries yet", timeout=5000)
        page.wait_for_timeout(300)
        assert page.locator(".bz").count() == 0

    def test_freelance_without_rows_has_no_strip(self, page, base_url):
        _source(base_url)
        _week(base_url, W44)
        page.clock.set_fixed_time(FIXED_NOW)
        page.goto(f"{base_url}/#days")
        page.get_by_role("radio", name="Freelance").click()
        page.wait_for_selector("text=No freelance blocks here", timeout=5000)
        assert page.locator(".bz").count() == 0

    def test_a_year_with_no_week_in_view_has_no_strip_and_the_old_links_are_gone(
        self, page, base_url
    ):
        _week(base_url, W44)
        _open_days(page, base_url)
        assert page.locator(".wk-tools").count() == 0
        _set(page, "daysYear = '2024'")
        assert page.locator(".bz").count() == 0


class TestSticky:
    def _year(self, base_url) -> None:
        """Forty-five weeks, so that the table is far taller than a screen."""
        start = datetime.date(2026, 1, 5)
        src = _source(base_url)
        for n in range(45):
            monday = (start + datetime.timedelta(days=7 * n)).isoformat()
            _week(base_url, monday)
            _block(base_url, src, monday, 10)

    @pytest.mark.parametrize("freelance", [False, True], ids=["employee", "freelance"])
    def test_at_1280_the_strip_sticks_and_the_header_sits_under_it(self, page, base_url, freelance):
        self._year(base_url)
        _open_days(page, base_url, (1280, 900), freelance=freelance)
        page.evaluate("window.scrollTo(0, 1500)")
        page.wait_for_timeout(400)
        assert page.evaluate("window.scrollY") >= 1400
        bz = page.locator(".bz").bounding_box()
        assert bz["y"] == pytest.approx(0, abs=0.5)
        head = page.locator(".days-table thead th").first.bounding_box()
        assert head["y"] >= bz["y"] + bz["height"] - 0.5, (bz, head)
        # the header is stuck right under it, not floating far below
        assert head["y"] <= bz["y"] + bz["height"] + 2
        # a solid background, so nothing shows through
        bg = page.locator(".bz").evaluate("e => getComputedStyle(e).backgroundColor")
        assert bg == _colour(page, "var(--k-bg)")
        # nor through the pixel between the strip and the headers
        shadow = page.locator(".bz").evaluate("e => getComputedStyle(e).boxShadow")
        assert shadow.startswith(bg) and " 2px " in shadow, shadow

    @pytest.mark.parametrize("freelance", [False, True], ids=["employee", "freelance"])
    def test_at_900_it_does_not_stick_and_the_headers_are_as_before(
        self, page, base_url, freelance
    ):
        self._year(base_url)
        _open_days(page, base_url, (900, 900), freelance=freelance)
        page.evaluate("window.scrollTo(0, 1500)")
        page.wait_for_timeout(400)
        assert page.locator(".bz").evaluate("e => getComputedStyle(e).position") != "sticky"
        assert page.locator(".bz").bounding_box()["y"] < 0  # scrolled away with the page
        assert (
            page.locator(".days-table thead th").first.evaluate("e => getComputedStyle(e).top")
            == "0px"
        )

    def test_the_strip_does_not_cover_a_week_it_jumped_to(self, page, base_url):
        self._year(base_url)
        _open_days(page, base_url)
        _tick(page, "2026-01-05").click()
        _wait_flash(page, "2026-01-05")
        page.wait_for_timeout(1200)
        assert _visible_under_strip(page, "2026-01-05")


class TestTooltip:
    def test_employee_the_text_and_it_stays_inside_the_strip_at_both_ends(self, page, base_url):
        _week(base_url, W32, "19:30")
        _entry(base_url, "2026-01-01")  # in the first slot (the week of Dec 29)
        _entry(base_url, "2026-12-28")  # in the last slot
        _open_days(page, base_url)
        tip = page.locator(".bz-tip")
        _tick(page, W32).hover()
        page.wait_for_timeout(300)
        assert tip.inner_text() == "W32 · Aug 3 – 9 · +1.50h"
        assert float(tip.evaluate("e => getComputedStyle(e).opacity")) == 1
        strip = page.locator(".bz-strip").bounding_box()
        for monday in (FIRST_2026, LAST_2026):
            _tick(page, monday).hover()
            page.wait_for_timeout(300)
            box = tip.bounding_box()
            assert box["x"] >= strip["x"] - 0.5, (monday, box, strip)
            assert box["x"] + box["width"] <= strip["x"] + strip["width"] + 0.5, (monday, box)
            assert (
                box["y"] >= strip["y"] - 0.5
                and box["y"] + box["height"] <= strip["y"] + strip["height"]
            )
            assert page.evaluate("document.documentElement.scrollWidth") <= 1280
        page.mouse.move(5, 400)
        page.wait_for_timeout(300)
        assert float(tip.evaluate("e => getComputedStyle(e).opacity")) == 0

    def test_freelance_the_text_and_it_stays_inside_the_strip(self, page, base_url):
        src = _source(base_url)
        _block(base_url, src, W45, 18)
        _payout(base_url, src, W45, 1789.07)
        _block(base_url, src, FIRST_2026, 3, offset=3)  # Thu Jan 1 2026: the first slot
        _block(base_url, src, LAST_2026, 3)
        _open_days(page, base_url, freelance=True)
        tip = page.locator(".bz-tip")
        _tick(page, W45).hover()
        page.wait_for_timeout(300)
        assert tip.inner_text() == "W45 · Nov 2 – 8 · €1,789.07"
        assert _tick(page, W45).get_attribute("aria-label") == "W45 · Nov 2 – 8 · €1,789.07"
        strip = page.locator(".bz-strip").bounding_box()
        _tick(page, LAST_2026).hover()
        page.wait_for_timeout(300)
        box = tip.bounding_box()
        assert box["x"] + box["width"] <= strip["x"] + strip["width"] + 0.5, box
        assert page.evaluate("document.documentElement.scrollWidth") <= 1280

    def test_keyboard_focus_shows_it_too(self, page, base_url):
        _week(base_url, W32, "19:30")
        _open_days(page, base_url)
        _tick(page, W32).focus()
        page.wait_for_timeout(300)
        assert page.locator(".bz-tip").inner_text() == "W32 · Aug 3 – 9 · +1.50h"
        assert float(page.locator(".bz-tip").evaluate("e => getComputedStyle(e).opacity")) == 1


@pytest.mark.parametrize("freelance", [False, True], ids=["employee", "freelance"])
@pytest.mark.parametrize("width,height", WIDTHS)
def test_nothing_scrolls_sideways_the_count_is_one_line_and_the_buttons_are_big_enough(
    page, base_url, width, height, freelance
):
    src = _source(base_url)
    # a spread of weeks over two years, with a first and a last slot of 2026
    mondays = [W32, W41, W43, W44, W45, FIRST_2026, LAST_2026, "2025-11-03"]
    for monday in mondays:
        _week(base_url, monday)
        _block(base_url, src, monday, 10)
    _payout(base_url, src, W45, 1789.07)
    _open_days(page, base_url, (width, height), freelance=freelance)
    for year in ("'2026'", "'all'"):
        _set(page, f"daysYear = {year}")
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        assert (
            page.locator(".bz-count").evaluate(
                """e => { const r = document.createRange(); r.selectNodeContents(e);
              const m = [...r.getClientRects()].filter(x => x.width > 0)
                .map(x => x.top + x.height / 2);
              return Math.max(...m) - Math.min(...m); }"""
            )
            < 4
        )
        for tid in ("wk-expand-all", "wk-collapse-all"):
            box = page.get_by_test_id(tid).bounding_box()
            assert box["width"] >= 24 - 0.5 and box["height"] >= 24 - 0.5, (tid, box)
        strip, chip = (
            page.locator(".bz-strip").bounding_box(),
            page.locator(".bz-chip").bounding_box(),
        )
        if width <= 640:
            # the strip takes the width and the chip is under it, at the right
            wrap = page.locator(".days-wrap").bounding_box()
            assert strip["x"] == pytest.approx(wrap["x"], abs=1), (strip, wrap)
            assert strip["width"] == pytest.approx(wrap["width"], abs=1), (strip, wrap)
            assert chip["y"] >= strip["y"] + strip["height"] - 1, (strip, chip)
            assert chip["x"] + chip["width"] == pytest.approx(strip["x"] + strip["width"], abs=2)
        else:
            assert chip["y"] < strip["y"] + strip["height"]
        # every tick is there and fits the strip's width
        ticks = page.locator(TICK)
        n = ticks.count()
        last = ticks.last.bounding_box()
        assert n >= 53
        assert last["x"] + last["width"] <= strip["x"] + strip["width"] + 0.5
        assert ticks.first.bounding_box()["x"] >= strip["x"] - 0.5
