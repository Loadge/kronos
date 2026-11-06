"""E2E: the day ribbon in Log.

The day drawn from 06:00 to midnight: the employee span as a brass bar with a grip at each end,
breaks as notches cut out of it, the target as a flag, timed freelance blocks on a second lane. A
drag writes the same fields the time inputs write, and nothing else: only Create entry and Save
changes save a day.

The browser clock is fixed to Wednesday 2026-11-04, so the form's date is that day and nothing
depends on the hour the suite runs at. Most tests ask for reduced motion, so a bar never eases while
a test measures it. Days are real ones: 09:00 to 17:00 with a lunch at 13:00 on an 8h target.
"""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

FIXED_NOW = "2026-11-04T10:00:00"
TODAY = "2026-11-04"
LO, HI = 360, 1440  # the ribbon's range, in minutes: 06:00 to midnight
WIDTHS = [(375, 800), (640, 900), (768, 900), (1024, 800), (1280, 900)]
LUNCH = {"break_minutes": 30, "start_time": "13:00", "end_time": "13:30"}
MAIN = "Alpine.$data(document.querySelector('main'))"
CANCEL = """() => document.querySelector('.dr-field').dispatchEvent(
  new PointerEvent('pointercancel', { pointerId: 1, pointerType: 'mouse', bubbles: true }))"""


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


@pytest.fixture(autouse=True)
def _clean(base_url):
    """No entries, no sources and an 8h target: an earlier module may have left others."""
    _wipe(base_url)
    with httpx.Client(base_url=base_url) as c:
        c.put("/api/config", json={"daily_target_hours": 8, "vacation_budget_days": 0})
    yield
    _wipe(base_url)


def _open(page, base_url: str, size=(1280, 900), reduced: bool = True) -> None:
    page.set_viewport_size({"width": size[0], "height": size[1]})
    if reduced:
        page.emulate_media(reduced_motion="reduce")
    page.clock.set_fixed_time(FIXED_NOW)
    page.goto(f"{base_url}/#log")
    page.wait_for_selector(".dr-field", timeout=5000)


def _state(page, expr: str):
    return page.evaluate(f"() => {MAIN}.{expr}")


def _day(page, start="09:00", end="17:00", breaks=None) -> None:
    """Put a day in the form and wait until the ribbon draws it."""
    page.evaluate(
        f"""([s, e, b]) => {{
          const a = {MAIN};
          a.form.start_time = s; a.form.end_time = e; a.form.breaks = b;
        }}""",
        [start, end, breaks or []],
    )
    page.wait_for_function(
        "([s, e]) => document.querySelector('.dr-bar')?.getAttribute('aria-valuetext')"
        " === `Day from ${s} to ${e}`",
        arg=[start, end],
        timeout=5000,
    )


def _form(page) -> dict:
    return page.evaluate(
        f"""() => {{
          const f = {MAIN}.form;
          return {{ start: f.start_time, end: f.end_time,
            breaks: f.breaks.map(b => [b.start_time, b.end_time, b.break_minutes]) }};
        }}"""
    )


def _min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _lane(page, lane: str = "emp") -> dict:
    page.locator(f".dr-lane--{lane}").scroll_into_view_if_needed()
    return page.locator(f".dr-lane--{lane}").bounding_box()


def _x(page, minutes: float, lo: int = LO) -> float:
    b = _lane(page)
    return b["x"] + (minutes - lo) / (HI - lo) * b["width"]


def _y(page, lane: str = "emp") -> float:
    b = _lane(page, lane)
    return b["y"] + b["height"] / 2


def _press(page, hhmm: str, dy: float = 0, lane: str = "emp") -> None:
    page.mouse.move(_x(page, _min(hhmm)), _y(page, lane) + dy)
    page.mouse.down()


def _drag(page, a: str, b: str, dy: float = 0, steps: int = 12, lane: str = "emp") -> None:
    """Press at a time of day, move to another (optionally lower or higher too) and release."""
    _press(page, a, lane=lane)
    page.mouse.move(_x(page, _min(b)), _y(page, lane) + dy, steps=steps)
    page.mouse.up()


def _time_inputs(page):
    return page.locator(".log-times .grid input[type=time]")


def _net(page):
    return page.locator(".impact-card .impact-value").first


def _tip_text(page) -> str:
    return page.locator(".dr-tag").inner_text()


def _pct(page, selector: str) -> tuple[float, float]:
    """Left edge and width of an element as percentages of the employee lane."""
    lane = page.locator(".dr-lane--emp").bounding_box()
    box = page.locator(selector).first.bounding_box()
    return (box["x"] - lane["x"]) / lane["width"] * 100, box["width"] / lane["width"] * 100


def _at(minutes: float, lo: int = LO) -> float:
    return (minutes - lo) / (HI - lo) * 100


def _requests_that_write(page) -> list:
    seen: list = []
    page.on("request", lambda r: seen.append(r) if r.method != "GET" else None)
    return seen


class TestShape:
    def test_the_ribbon_sits_at_the_top_of_the_times_and_the_inputs_stay(self, page, base_url):
        _open(page, base_url)
        first = page.locator(".log-times > :not(hr)").first
        assert first.get_attribute("data-testid") == "day-ribbon"
        assert _time_inputs(page).count() == 2
        assert page.get_by_role("button", name="+ Add break").is_visible()
        assert page.locator(".dr-lane--fl").count() == 0  # no source, no freelance lane

    def test_a_bar_from_0900_to_1700_sits_at_16_67_percent_and_spans_44_44(self, page, base_url):
        _open(page, base_url)
        _day(page)
        left, width = _pct(page, ".dr-bar")
        assert left == pytest.approx(16.67, abs=0.1)
        assert width == pytest.approx(44.44, abs=0.1)
        # the grips sit on the ends of the bar
        start = page.locator(".dr-grip--start").bounding_box()
        bar = page.locator(".dr-bar").bounding_box()
        assert start["x"] + start["width"] / 2 == pytest.approx(bar["x"], abs=1)

    def test_the_ruler_has_an_hour_tick_and_a_label_every_three_hours(self, page, base_url):
        _open(page, base_url)
        labels = page.locator(".dr-tick b").all_inner_texts()
        assert [t for t in labels if t] == ["06", "09", "12", "15", "18", "21", "24"]
        assert page.locator(".dr-tick").count() == 19
        # a tick is not a tab stop: start, bar and end are the only ones
        assert page.locator(".dr [tabindex='0']").count() == 3

    def test_a_ranged_break_is_a_notch_with_two_grips(self, page, base_url):
        _open(page, base_url)
        _day(page, breaks=[LUNCH])
        assert page.locator(".dr-notch[data-dr=nbody]").count() == 1
        assert page.locator(".dr-grip--nstart").count() == 1
        assert page.locator(".dr-grip--nend").count() == 1
        left, width = _pct(page, ".dr-notch[data-dr=nbody]")
        assert left == pytest.approx(_at(13 * 60), abs=0.1)
        assert width == pytest.approx(30 / (HI - LO) * 100, abs=0.1)

    def test_the_notch_is_cut_out_in_the_cards_background(self, page, base_url):
        _open(page, base_url)
        _day(page, breaks=[LUNCH])
        got = page.evaluate(
            """() => {
              const bg = e => getComputedStyle(e).backgroundColor;
              const probe = document.createElement('i');
              probe.style.backgroundColor = 'var(--k-surface)';
              document.body.append(probe);
              const surface = bg(probe);
              probe.remove();
              return [bg(document.querySelector('.dr-notch')), surface];
            }"""
        )
        assert got[0] == got[1]


class TestKnownDays:
    def test_leave_days_with_hours_show_it_and_a_whole_leave_day_does_not(self, page, base_url):
        _open(page, base_url)
        page.evaluate(
            f"() => {{ const a = {MAIN}; a.form.day_type = 'vacation'; a.form.leave_hours = 4; }}"
        )
        expect(page.locator(".dr")).to_have_count(1)
        assert _state(page, "logPreview().target_hours") == 4
        _day(page, "09:00", "13:00")
        expect(page.locator(".dr-flag")).to_have_attribute("title", "Target reached at 13:00")
        page.evaluate(f"() => {{ {MAIN}.form.leave_hours = 8; }}")
        expect(page.locator(".dr")).to_have_count(0)

    def test_a_start_of_0530_opens_the_range_at_0500(self, page, base_url):
        _open(page, base_url)
        _day(page, "05:30", "17:00")
        hours = page.locator(".dr-in").evaluate(
            "e => getComputedStyle(e).getPropertyValue('--dr-hours').trim()"
        )
        assert hours == "19"
        left, _ = _pct(page, ".dr-bar")
        assert left == pytest.approx(30 / 1140 * 100, abs=0.1)
        assert page.locator(".dr-grip--start").get_attribute("aria-valuemin") == "300"
        # the 06 label is at 60 of 1140 minutes
        lane = page.locator(".dr-lane--emp").bounding_box()
        tick = page.locator(".dr-tick", has=page.locator("b", has_text="06")).bounding_box()
        assert (tick["x"] - lane["x"]) / lane["width"] * 100 == pytest.approx(
            60 / 1140 * 100, abs=0.2
        )

    def test_an_empty_or_invalid_span_draws_no_bar_and_a_drag_on_the_lane_draws_one(
        self, page, base_url
    ):
        _open(page, base_url)
        page.evaluate(
            f"""() => {{ const a = {MAIN};
              a.form.start_time = ''; a.form.end_time = '';
              a.form.breaks = [{{ break_minutes: 30, start_time: '', end_time: '' }}]; }}"""
        )
        expect(page.locator(".dr-bar")).to_have_count(
            0
        )  # and a half typed break row does not crash it
        expect(page.locator(".dr-lane--emp")).to_be_visible()
        _drag(page, "10:00", "12:30")
        assert (_form(page)["start"], _form(page)["end"]) == ("10:00", "12:30")
        expect(page.locator(".dr-bar")).to_have_count(1)
        # an end before the start is no bar either
        page.evaluate(f"() => {{ {MAIN}.form.end_time = '08:00'; }}")
        expect(page.locator(".dr-bar")).to_have_count(0)

    def test_a_break_row_half_typed_does_not_stop_the_ribbon(self, page, base_url):
        _open(page, base_url)
        _day(page, breaks=[{"break_minutes": "", "start_time": "", "end_time": ""}])
        expect(page.locator(".dr-bar")).to_have_count(1)
        assert page.locator(".dr-notch").count() == 0


class TestDragging:
    def test_the_end_grip_to_1847_snaps_to_1845_and_everything_follows(self, page, base_url):
        _open(page, base_url)
        _day(page)
        _press(page, "17:00")
        page.mouse.move(_x(page, _min("18:47")), _y(page), steps=10)
        # while the pointer is still down: the tag, the input and the impact card already follow
        expect(page.locator(".dr-tag")).to_be_visible()
        assert "18:45" in _tip_text(page)
        assert "9.75h" in _tip_text(page)
        assert "+1.75h" in _tip_text(page)
        assert _form(page)["end"] == "18:45"
        page.mouse.up()
        assert _form(page)["end"] == "18:45"
        expect(_time_inputs(page).nth(1)).to_have_value("18:45")
        expect(_net(page)).to_have_text("9.75h")
        expect(page.locator(".impact-delta")).to_have_text("+1.75h")
        expect(page.locator(".dr-tag")).to_have_count(0)

    def test_the_start_grip_writes_the_start_input(self, page, base_url):
        _open(page, base_url)
        _day(page)
        _drag(page, "09:00", "08:15")
        assert _form(page)["start"] == "08:15"
        expect(_time_inputs(page).nth(0)).to_have_value("08:15")

    def test_everything_snaps_to_fifteen_minutes(self, page, base_url):
        _open(page, base_url)
        _day(page)
        for target, want in [("17:03", "17:00"), ("17:12", "17:15"), ("18:19", "18:15")]:
            _drag(page, _form(page)["end"], target)
            assert _form(page)["end"] == want, target

    def test_dragging_the_bar_moves_the_day_and_the_lunch_with_it(self, page, base_url):
        _open(page, base_url)
        _day(page, "09:00", "17:00", [{**LUNCH, "start_time": "13:00", "end_time": "13:30"}])
        assert _net(page).inner_text() == "7.5h"
        _drag(page, "11:00", "13:00")
        got = _form(page)
        assert (got["start"], got["end"]) == ("11:00", "19:00")
        assert got["breaks"] == [["15:00", "15:30", 30]]
        expect(_net(page)).to_have_text("7.5h")  # the day moved, it did not change

    def test_a_drag_of_a_notch_moves_the_break_and_its_grips_resize_it(self, page, base_url):
        _open(page, base_url)
        _day(page, breaks=[LUNCH])
        _drag(page, "13:15", "14:15")
        assert _form(page)["breaks"] == [["14:00", "14:30", 30]]
        _drag(page, "14:30", "15:00")  # the end grip
        assert _form(page)["breaks"] == [["14:00", "15:00", 60]]
        _drag(page, "14:00", "13:30")  # the start grip
        assert _form(page)["breaks"] == [["13:30", "15:00", 90]]
        expect(_net(page)).to_have_text("6.5h")

    def test_the_vibration_ticks_at_each_snap_and_is_longer_at_the_target(self, page, base_url):
        page.add_init_script(
            "window.__v = []; navigator.vibrate = p => { window.__v.push(p); return true; };"
        )
        _open(page, base_url)
        _day(page)
        _drag(page, "17:00", "16:00", steps=24)  # net 8h to 7h: it crosses the 8h target once
        calls = page.evaluate("window.__v")
        assert calls.count(20) == 1, calls
        assert calls.count(8) == 3, calls

    def test_the_ribbon_is_computed_once_per_render_and_a_drag_renders_when_a_value_snaps(
        self, page, base_url
    ):
        _open(page, base_url)
        _day(page)
        page.evaluate(
            f"""() => {{ const a = {MAIN};
              const real = a.dayRibbon; window.__n = 0;
              a.dayRibbon = function () {{ window.__n++; return real.call(this); }}; }}"""
        )
        page.wait_for_function("window.__n >= 1")  # swapping it rendered once
        n0 = page.evaluate("window.__n")
        _press(page, "17:00")
        page.mouse.move(_x(page, _min("18:00")), _y(page), steps=60)  # 60 events, 4 snaps
        page.mouse.up()
        used = page.evaluate("window.__n") - n0
        assert 4 <= used <= 8, used


class TestClamps:
    def test_the_end_cannot_cross_the_start(self, page, base_url):
        _open(page, base_url)
        _day(page)
        _drag(page, "17:00", "07:00")
        got = _form(page)
        assert (got["start"], got["end"]) == ("09:00", "09:15")

    def test_the_start_stops_at_the_edge_of_the_range_and_the_end_before_midnight(
        self, page, base_url
    ):
        _open(page, base_url)
        _day(page)
        _press(page, "09:00")
        page.mouse.move(_x(page, _min("06:00")) - 60, _y(page), steps=10)
        page.mouse.up()
        assert _form(page)["start"] == "06:00"
        _press(page, "17:00")
        right = min(_x(page, HI) + 60, page.viewport_size["width"] - 1)
        page.mouse.move(right, _y(page), steps=10)
        page.mouse.up()
        assert _form(page)["end"] == "23:45"

    def test_a_break_cannot_leave_the_bar(self, page, base_url):
        _open(page, base_url)
        _day(page, breaks=[LUNCH])
        _drag(page, "13:15", "23:00")
        assert _form(page)["breaks"] == [["16:30", "17:00", 30]]
        _drag(page, "16:45", "07:00")
        assert _form(page)["breaks"] == [["09:00", "09:30", 30]]

    def test_a_grip_stops_at_a_break_instead_of_leaving_it_outside(self, page, base_url):
        _open(page, base_url)
        _day(page, breaks=[LUNCH])
        _drag(page, "17:00", "10:00")
        assert (_form(page)["start"], _form(page)["end"]) == ("09:00", "13:30")
        _drag(page, "09:00", "15:00")
        assert (_form(page)["start"], _form(page)["end"]) == ("13:00", "13:30")

    def test_two_breaks_never_overlap(self, page, base_url):
        _open(page, base_url)
        first = {"break_minutes": 30, "start_time": "12:00", "end_time": "12:30"}
        second = {"break_minutes": 30, "start_time": "14:00", "end_time": "14:30"}
        _day(page, breaks=[first, second])
        _drag(page, "14:15", "08:00")  # the second, dragged over the first
        assert _form(page)["breaks"] == [["12:00", "12:30", 30], ["12:30", "13:00", 30]]
        _drag(page, "13:00", "16:00")  # the second's end grip: free to the end of the bar
        assert _form(page)["breaks"] == [["12:00", "12:30", 30], ["12:30", "16:00", 210]]
        _drag(page, "12:30", "15:00")  # the first's end grip, stopped by the second
        assert _form(page)["breaks"] == [["12:00", "12:30", 30], ["12:30", "16:00", 210]]

    def test_the_form_never_holds_a_break_outside_the_bar_after_any_drag(self, page, base_url):
        _open(page, base_url)
        _day(page, breaks=[LUNCH])
        for a, b in [
            ("09:00", "14:00"),
            ("17:00", "08:00"),
            ("13:15", "20:00"),
            ("11:00", "06:30"),
        ]:
            _drag(page, a, b)
            got = _form(page)
            for s, e, _ in got["breaks"]:
                assert got["start"] <= s < e <= got["end"], got


class TestBreaksOnTheRibbon:
    def test_a_double_click_adds_a_30_minute_break_at_the_clicked_quarter(self, page, base_url):
        _open(page, base_url)
        _day(page)
        page.mouse.dblclick(_x(page, _min("14:07")), _y(page))
        assert _form(page)["breaks"] == [["14:00", "14:30", 30]]
        expect(page.locator(".dr-notch[data-dr=nbody]")).to_have_count(1)
        expect(_net(page)).to_have_text("7.5h")
        assert page.get_by_role("button", name="+ Add break").is_visible()

    def test_a_double_click_near_the_end_is_clamped_inside_the_bar(self, page, base_url):
        _open(page, base_url)
        _day(page)
        page.mouse.dblclick(_x(page, _min("16:50")), _y(page))
        assert _form(page)["breaks"] == [["16:30", "17:00", 30]]

    def test_a_double_click_on_a_taken_stretch_finds_a_free_one(self, page, base_url):
        _open(page, base_url)
        taken = {"break_minutes": 30, "start_time": "09:00", "end_time": "09:30"}
        _day(page, "09:00", "10:00", [taken])
        page.mouse.dblclick(_x(page, _min("09:50")), _y(page))
        assert _form(page)["breaks"][1] == ["09:30", "10:00", 30]
        page.mouse.dblclick(_x(page, _min("09:50")), _y(page))  # no stretch of 30 minutes is left
        assert len(_form(page)["breaks"]) == 2

    def test_dragging_a_notch_off_the_lane_removes_the_break(self, page, base_url):
        _open(page, base_url)
        _day(page, breaks=[LUNCH])
        _press(page, "13:15")
        page.mouse.move(_x(page, _min("13:15")), _y(page) + 100, steps=8)
        expect(page.locator(".dr-notch.is-off")).to_have_count(1)  # it will go: still there
        assert _tip_text(page).strip() == "Remove"
        assert len(_form(page)["breaks"]) == 1
        page.mouse.up()
        assert _form(page)["breaks"] == []
        expect(page.locator(".dr-notch")).to_have_count(0)

    def test_a_notch_dragged_a_little_off_the_lane_and_back_stays(self, page, base_url):
        _open(page, base_url)
        _day(page, breaks=[LUNCH])
        _press(page, "13:15")
        page.mouse.move(_x(page, _min("13:15")), _y(page) + 100, steps=8)
        page.mouse.move(_x(page, _min("14:15")), _y(page) + 5, steps=8)
        page.mouse.up()
        assert _form(page)["breaks"] == [["14:00", "14:30", 30]]

    def test_a_minutes_only_break_is_dashed_centred_and_becomes_ranged_when_dragged(
        self, page, base_url
    ):
        _open(page, base_url)
        _day(page, breaks=[{"break_minutes": 45, "start_time": "", "end_time": ""}])
        dash = page.locator(".dr-notch--dash")
        expect(dash).to_have_count(1)
        assert dash.evaluate("e => getComputedStyle(e).borderTopStyle") == "dashed"
        bar, box = page.locator(".dr-bar").bounding_box(), dash.bounding_box()
        assert box["x"] + box["width"] / 2 == pytest.approx(bar["x"] + bar["width"] / 2, abs=1)
        assert box["width"] / bar["width"] == pytest.approx(45 / 480, abs=0.01)
        expect(_net(page)).to_have_text("7.25h")  # it counts the same
        _drag(page, "13:00", "14:00")  # it follows the pointer by a quarter hour at a time
        assert _form(page)["breaks"] == [["13:45", "14:30", 45]]
        expect(page.locator(".dr-notch--dash")).to_have_count(0)
        expect(_net(page)).to_have_text("7.25h")

    def test_two_minutes_only_breaks_sit_side_by_side(self, page, base_url):
        _open(page, base_url)
        _day(
            page,
            breaks=[
                {"break_minutes": 30, "start_time": "", "end_time": ""},
                {"break_minutes": 15, "start_time": "", "end_time": ""},
            ],
        )
        boxes = [page.locator(".dr-notch--dash").nth(n).bounding_box() for n in range(2)]
        assert boxes[0]["x"] + boxes[0]["width"] == pytest.approx(boxes[1]["x"], abs=1.5)


class TestTheFlag:
    def test_with_a_lunch_the_flag_is_where_the_8_hours_are_done(self, page, base_url):
        _open(page, base_url)
        lunch = {"break_minutes": 60, "start_time": "14:00", "end_time": "15:00"}
        _day(page, "09:00", "19:00", [lunch])
        expect(page.locator(".dr-flag")).to_have_attribute("title", "Target reached at 18:00")
        left, _ = _pct(page, ".dr-flag")
        lane_width = page.locator(".dr-lane--emp").bounding_box()["width"]
        assert left + 7 / lane_width * 100 == pytest.approx(_at(18 * 60), abs=0.2)
        # the part of the bar after it is the surplus, in the coin tone
        over_left, over_width = _pct(page, ".dr-over")
        assert over_left == pytest.approx(_at(18 * 60), abs=0.2)
        assert over_width == pytest.approx(60 / (HI - LO) * 100, abs=0.2)
        assert page.locator(".dr-miss").count() == 0

    def test_the_flag_agrees_with_the_preview_on_a_7_33_hour_target(self, page, base_url):
        with httpx.Client(base_url=base_url) as c:
            c.put("/api/config", json={"daily_target_hours": 7.33})
        _open(page, base_url)
        _day(page, "09:00", "18:00", [LUNCH])
        title = page.locator(".dr-flag").get_attribute("title")
        reached = title.removeprefix("Target reached at ")
        assert reached == "16:50"  # 09:00 + 7h20 + the half hour of lunch
        # a day that ends there has exactly the target as its net
        _day(page, "09:00", reached, [LUNCH])
        assert _state(page, "logPreview().target_hours") == 7.33
        assert _state(page, "logPreview().net_hours") == 7.33

    def test_a_day_that_ends_at_1500_has_no_flag_and_a_dashed_stretch_as_long_as_the_deficit(
        self, page, base_url
    ):
        _open(page, base_url)
        _day(page, "09:00", "15:00")
        expect(page.locator(".dr-flag")).to_have_count(0)
        left, width = _pct(page, ".dr-miss")
        assert left == pytest.approx(_at(15 * 60), abs=0.1)
        assert width == pytest.approx(2 * 60 / (HI - LO) * 100, abs=0.1)
        style = page.locator(".dr-miss").evaluate("e => getComputedStyle(e).borderTopStyle")
        assert style == "dashed"
        assert page.locator(".dr-over").count() == 0

    def test_the_flag_waves_once_after_a_drag_that_makes_it_appear(self, page, base_url):
        _open(page, base_url, reduced=False)
        _day(page, "09:00", "15:00")
        page.evaluate(
            """() => { window.__wave = 0;
              document.querySelector('.dr-field').addEventListener('animationstart', e => {
                if (e.animationName === 'dr-wave') window.__wave++;
              }); }"""
        )
        _drag(page, "15:00", "17:00")  # now the 8 hours are done: the flag is new
        page.wait_for_function("window.__wave >= 1", timeout=5000)
        _drag(page, "17:00", "18:00")  # it moves along; it does not wave again
        page.wait_for_timeout(300)
        assert page.evaluate("window.__wave") == 1


class TestKeyboard:
    def _focus_start(self, page):
        page.locator(".log-col-center select").first.focus()
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.dataset.dr") == "start"

    def test_tab_reaches_the_start_grip_and_the_arrows_step_it(self, page, base_url):
        _open(page, base_url)
        _day(page)
        self._focus_start(page)
        grip = page.locator(".dr-grip--start")
        assert grip.get_attribute("role") == "slider"
        assert grip.get_attribute("aria-label") == "Start time"
        assert grip.get_attribute("aria-valuetext") == "Start 09:00"
        page.keyboard.press("ArrowRight")
        assert _form(page)["start"] == "09:15"
        expect(grip).to_have_attribute("aria-valuetext", "Start 09:15")
        page.keyboard.press("Shift+ArrowRight")
        assert _form(page)["start"] == "10:15"
        page.keyboard.press("ArrowLeft")
        assert _form(page)["start"] == "10:00"
        page.keyboard.press("Home")
        assert _form(page)["start"] == "06:00"
        page.keyboard.press("End")
        assert _form(page)["start"] == "16:45"  # a quarter hour short of the end
        expect(grip).to_have_attribute("aria-valuetext", "Start 16:45")

    def test_the_end_grip_and_the_bar_have_names_and_limits(self, page, base_url):
        _open(page, base_url)
        _day(page, "09:15", "18:45")
        bar, end = page.locator(".dr-bar"), page.locator(".dr-grip--end")
        assert bar.get_attribute("role") == "slider"
        assert bar.get_attribute("aria-valuetext") == "Day from 09:15 to 18:45"
        assert bar.get_attribute("aria-label") == "Day"
        assert end.get_attribute("aria-valuetext") == "End 18:45"
        end.focus()
        page.keyboard.press("End")
        assert _form(page)["end"] == "23:45"
        page.keyboard.press("Home")
        assert _form(page)["end"] == "09:30"
        bar.focus()
        page.keyboard.press("ArrowRight")
        assert (_form(page)["start"], _form(page)["end"]) == ("09:30", "09:45")
        page.keyboard.press("Shift+ArrowRight")
        assert (_form(page)["start"], _form(page)["end"]) == ("10:30", "10:45")
        page.keyboard.press("Home")
        assert _form(page)["start"] == "06:00"
        page.keyboard.press("End")
        assert _form(page)["end"] == "23:45"

    def test_delete_on_a_notch_removes_the_break_and_arrows_move_it(self, page, base_url):
        _open(page, base_url)
        _day(page, breaks=[LUNCH])
        notch = page.locator(".dr-notch[data-dr=nbody]")
        assert notch.get_attribute("aria-valuetext") == "Break from 13:00 to 13:30"
        notch.focus()
        page.keyboard.press("ArrowRight")
        assert _form(page)["breaks"] == [["13:15", "13:45", 30]]
        page.keyboard.press("End")
        assert _form(page)["breaks"] == [["16:30", "17:00", 30]]
        page.keyboard.press("Delete")
        assert _form(page)["breaks"] == []
        expect(page.locator(".dr-notch")).to_have_count(0)

    def test_a_notch_grip_resizes_with_the_arrows(self, page, base_url):
        _open(page, base_url)
        _day(page, breaks=[LUNCH])
        page.locator(".dr-grip--nend").focus()
        page.keyboard.press("Shift+ArrowRight")
        assert _form(page)["breaks"] == [["13:00", "14:30", 90]]
        page.keyboard.press("Home")  # the shortest: a quarter hour
        assert _form(page)["breaks"] == [["13:00", "13:15", 15]]

    def test_the_strip_adds_one_tab_stop_per_handle_and_none_per_hour(self, page, base_url):
        _open(page, base_url)
        _day(page, breaks=[LUNCH])
        # start, bar, the break's body and two grips, end
        assert page.locator(".dr [tabindex='0']").count() == 6

    def test_focus_shows_a_ring_for_the_keyboard_and_not_after_a_click(self, page, base_url):
        _open(page, base_url)
        _day(page)
        self._focus_start(page)
        grip = page.locator(".dr-grip--start")
        assert grip.evaluate("e => e.matches(':focus-visible')")
        assert grip.evaluate("e => getComputedStyle(e, '::before').outlineStyle") == "solid"
        page.mouse.click(_x(page, _min("13:00")), _y(page))  # a click on the bar
        bar = page.locator(".dr-bar")
        assert not bar.evaluate("e => e.matches(':focus-visible')")
        assert bar.evaluate("e => getComputedStyle(e).outlineStyle") == "none"


class TestAHand:
    """What a finger does that a mouse does not: swipe, wobble, grip. Real touch, via CDP."""

    def _touch(self, page):
        cdp = page.context.new_cdp_session(page)
        cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
        return cdp

    def _finger(self, cdp, kind: str, x: float = 0, y: float = 0) -> None:
        points = [] if kind == "touchEnd" else [{"x": x, "y": y}]
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})

    def _ready(self, page, base_url):
        _open(page, base_url, (375, 800))
        _day(page)
        # the ribbon in the middle of the screen, with a page above and below it to scroll
        page.evaluate(
            """() => { const r = document.querySelector('.dr').getBoundingClientRect();
              window.scrollTo(0, window.scrollY + r.top - 400); }"""
        )
        page.wait_for_function(
            "Math.abs(document.querySelector('.dr').getBoundingClientRect().top - 400) < 5"
        )

    def test_a_vertical_swipe_from_the_body_scrolls_the_page_and_changes_nothing(
        self, page, base_url
    ):
        self._ready(page, base_url)
        cdp = self._touch(page)
        x, y = _x(page, _min("13:00")), _y(page)
        before, scroll = _form(page), page.evaluate("window.scrollY")
        self._finger(cdp, "touchStart", x, y)
        for step in range(1, 13):
            self._finger(cdp, "touchMove", x + step, y - step * 20)  # a hand drifts a little
            page.wait_for_timeout(16)
        self._finger(cdp, "touchEnd")
        page.wait_for_timeout(300)
        assert page.evaluate("window.scrollY") > scroll + 100  # the page did scroll
        assert _form(page) == before
        assert page.locator(".dr--drag").count() == 0

    def test_a_wobbling_finger_that_stays_under_6px_changes_nothing(self, page, base_url):
        self._ready(page, base_url)
        cdp = self._touch(page)
        x, y = _x(page, _min("13:00")), _y(page)
        before = _form(page)
        self._finger(cdp, "touchStart", x, y)
        for dx in (2, 5, 3, 5, 1):
            self._finger(cdp, "touchMove", x + dx, y)
            page.wait_for_timeout(16)
        self._finger(cdp, "touchEnd")
        page.wait_for_timeout(200)
        assert _form(page) == before

    def test_a_finger_that_only_just_wakes_the_drag_does_not_make_the_day_jump(
        self, page, base_url
    ):
        """The 6px a finger waits are not a distance: the day moves from where the drag began."""
        self._ready(page, base_url)
        cdp = self._touch(page)
        x, y = _x(page, _min("13:00")), _y(page)
        before = _form(page)
        self._finger(cdp, "touchStart", x, y)
        self._finger(cdp, "touchMove", x + 14, y)  # past the 6px it waits, in one go
        page.wait_for_timeout(50)
        self._finger(cdp, "touchEnd")
        page.wait_for_timeout(200)
        assert _form(page) == before

    def test_a_sideways_finger_on_the_body_moves_the_day(self, page, base_url):
        self._ready(page, base_url)
        cdp = self._touch(page)
        x0, x1, y = _x(page, _min("13:00")), _x(page, _min("15:00")), _y(page)
        self._finger(cdp, "touchStart", x0, y)
        for step in range(1, 11):
            self._finger(cdp, "touchMove", x0 + (x1 - x0) * step / 10, y)
            page.wait_for_timeout(16)
        self._finger(cdp, "touchEnd")
        page.wait_for_timeout(200)
        got = _form(page)
        assert got["start"] > "09:00", got  # it moved, by what the finger travelled after its 6px
        assert _min(got["end"]) - _min(got["start"]) == 480, got  # and kept its length

    def test_a_sideways_drag_on_the_end_grip_changes_the_end(self, page, base_url):
        self._ready(page, base_url)
        cdp = self._touch(page)
        x0, x1, y = _x(page, _min("17:00")), _x(page, _min("18:00")), _y(page)
        scroll = page.evaluate("window.scrollY")
        self._finger(cdp, "touchStart", x0, y)
        for step in range(1, 11):
            self._finger(cdp, "touchMove", x0 + (x1 - x0) * step / 10, y)
            page.wait_for_timeout(16)
        assert "18:00" in _tip_text(page)
        self._finger(cdp, "touchEnd")
        page.wait_for_timeout(200)
        assert _form(page)["end"] == "18:00"
        assert page.evaluate("window.scrollY") == scroll

    def test_a_finger_that_lands_beside_a_grip_still_takes_it(self, page, base_url):
        self._ready(page, base_url)
        cdp = self._touch(page)
        x0, y = _x(page, _min("17:00")) + 18, _y(page)  # 18px off: inside the 44px hit area
        self._finger(cdp, "touchStart", x0, y)
        for step in range(1, 7):
            self._finger(cdp, "touchMove", x0 + step * 4, y)
            page.wait_for_timeout(16)
        self._finger(cdp, "touchEnd")
        page.wait_for_timeout(200)
        assert _form(page)["end"] > "17:00"
        assert _form(page)["start"] == "09:00"

    def test_the_grips_are_at_least_44px_to_hit_and_drawn_smaller(self, page, base_url):
        _open(page, base_url, (375, 800))
        _day(page)
        for sel in (".dr-grip--start", ".dr-grip--end"):
            box = page.locator(sel).bounding_box()
            assert box["width"] >= 44 and box["height"] >= 44, (sel, box)
        dot = page.locator(".dr-grip--start").evaluate(
            "e => parseFloat(getComputedStyle(e, '::before').width)"
        )
        assert dot < 24

    def test_touch_action_none_on_grips_and_notches_and_pan_y_on_the_body_and_the_lane(
        self, page, base_url
    ):
        _open(page, base_url)
        _day(page, breaks=[LUNCH])
        css = "e => getComputedStyle(e).touchAction"
        assert page.locator(".dr-grip--end").evaluate(css) == "none"
        assert page.locator(".dr-notch").evaluate(css) == "none"
        assert page.locator(".dr-grip--nstart").evaluate(css) == "none"
        assert page.locator(".dr-bar").evaluate(css) == "pan-y"
        assert page.locator(".dr-lane--emp").evaluate(css) == "pan-y"


class TestTheHandle:
    def test_when_two_grips_overlap_the_one_nearest_the_pointer_wins(self, page, base_url):
        _open(page, base_url)
        _day(page, "12:00", "12:15")  # six or seven pixels between the grips
        assert _x(page, _min("12:15")) - _x(page, _min("12:00")) < 12
        y = _y(page)
        page.mouse.move(_x(page, _min("12:15")) + 3, y)  # nearer the end
        page.mouse.down()
        page.mouse.move(_x(page, _min("13:00")), y, steps=8)
        page.mouse.up()
        got = _form(page)
        assert (got["start"], got["end"]) == ("12:00", "13:00")
        page.mouse.move(_x(page, _min("12:00")) - 3, y)  # nearer the start
        page.mouse.down()
        page.mouse.move(_x(page, _min("11:00")), y, steps=8)
        page.mouse.up()
        got = _form(page)
        assert (got["start"], got["end"]) == ("11:00", "13:00")

    def test_a_mouse_reaches_12px_from_a_grip_and_not_30(self, page, base_url):
        _open(page, base_url)
        _day(page)
        y = _y(page)
        page.mouse.move(_x(page, _min("17:00")) + 10, y)
        page.mouse.down()
        page.mouse.move(_x(page, _min("18:00")) + 10, y, steps=8)
        page.mouse.up()
        assert _form(page)["end"] == "18:00"
        # 30px outside the bar there is nothing to take
        page.mouse.move(_x(page, _min("18:00")) + 30, y)
        page.mouse.down()
        page.mouse.move(_x(page, _min("20:00")) + 30, y, steps=8)
        page.mouse.up()
        assert _form(page)["end"] == "18:00"


class TestCancel:
    def test_a_pointercancel_restores_the_day_from_before_the_press(self, page, base_url):
        _open(page, base_url)
        _day(page, breaks=[LUNCH])
        _press(page, "11:00")
        page.mouse.move(_x(page, _min("13:00")), _y(page), steps=8)
        assert _form(page)["start"] == "11:00"  # it moved
        page.evaluate(CANCEL)
        got = _form(page)
        assert (got["start"], got["end"], got["breaks"]) == (
            "09:00",
            "17:00",
            [["13:00", "13:30", 30]],
        )
        expect(page.locator(".dr--drag")).to_have_count(0)
        page.mouse.up()
        assert _form(page)["start"] == "09:00"

    def test_a_pointercancel_in_the_middle_of_a_grip_drag_restores_the_end(self, page, base_url):
        _open(page, base_url)
        _day(page)
        _press(page, "17:00")
        page.mouse.move(_x(page, _min("19:00")), _y(page), steps=8)
        assert _form(page)["end"] == "19:00"
        page.evaluate(CANCEL)
        assert _form(page)["end"] == "17:00"
        page.mouse.up()


class TestFreelanceLane:
    def _sources(self, base_url) -> list[int]:
        ids = []
        with httpx.Client(base_url=base_url) as c:
            for name, rate in (("Local", 60), ("Northwind", 80)):
                body = {"name": name, "hourly_rate": rate, "currency": "EUR"}
                r = c.post("/api/freelance/sources", json=body)
                assert r.status_code == 201, r.text
                ids.append(r.json()["id"])
        return ids

    def _block(self, base_url, source: int, **times) -> dict:
        with httpx.Client(base_url=base_url) as c:
            r = c.post("/api/freelance/blocks", json={"date": TODAY, "source_id": source} | times)
            assert r.status_code == 201, r.text
            return r.json()

    def _blocks(self, base_url) -> list:
        with httpx.Client(base_url=base_url) as c:
            return c.get("/api/freelance/blocks").json()

    def _wait_editing(self, page) -> None:
        page.wait_for_function(f"() => {MAIN}.flForm.id !== null", timeout=5000)

    def test_no_lane_without_a_source(self, page, base_url):
        _open(page, base_url)
        assert page.locator(".dr-lane--fl").count() == 0

    def test_a_timed_block_is_drawn_in_its_source_colour_and_an_hours_only_one_is_not(
        self, page, base_url
    ):
        local, north = self._sources(base_url)
        self._block(base_url, local, start_time="19:00", end_time="20:30")
        self._block(base_url, north, start_time="07:00", end_time="08:00")
        self._block(base_url, local, hours=1.5)  # hours only: no place in the day
        _open(page, base_url)
        _day(page)
        expect(page.locator(".dr-block")).to_have_count(2)
        got = page.evaluate(
            """() => {
              const css = v => { const p = document.createElement('i'); p.style.color = v;
                document.body.append(p); const c = getComputedStyle(p).color;
                p.remove(); return c; };
              return { brass: css('var(--k-brass)'), ink: css('var(--k-ink)'),
                blocks: Object.fromEntries([...document.querySelectorAll('.dr-block')]
                  .map(e => [e.title, getComputedStyle(e).backgroundColor])) };
            }"""
        )
        assert got["blocks"]["Local · 19:00–20:30"] == got["brass"]
        assert got["blocks"]["Northwind · 07:00–08:00"] == got["ink"]
        # and it sits where it is in the day
        left, width = _pct(page, ".dr-block[title^='Local']")
        assert left == pytest.approx(_at(19 * 60), abs=0.2)
        assert width == pytest.approx(90 / (HI - LO) * 100, abs=0.2)

    def test_a_click_on_a_block_opens_it_in_the_editor(self, page, base_url):
        local, _ = self._sources(base_url)
        block = self._block(base_url, local, start_time="19:00", end_time="20:30")
        _open(page, base_url)
        _day(page)
        page.mouse.click(_x(page, _min("19:45")), _y(page, "fl"))
        self._wait_editing(page)
        assert _state(page, "flForm.id") == block["id"]
        assert _state(page, "flForm.by") == "times"
        assert _state(page, "flForm.start_time") == "19:00"
        expect(page.get_by_role("button", name="Save block")).to_be_visible()

    def test_a_block_opens_from_the_keyboard_too(self, page, base_url):
        local, _ = self._sources(base_url)
        block = self._block(base_url, local, start_time="19:00", end_time="20:30")
        _open(page, base_url)
        _day(page)
        page.locator(".dr-block").focus()
        page.keyboard.press("Enter")
        self._wait_editing(page)
        assert _state(page, "flForm.id") == block["id"]

    def test_a_drag_on_the_empty_lane_fills_the_editor_and_saves_nothing(self, page, base_url):
        local, _ = self._sources(base_url)
        self._block(base_url, local, start_time="19:00", end_time="20:30")
        _open(page, base_url)
        _day(page)
        # a block being edited, then a drag in the empty stretch: it becomes a new one
        page.mouse.click(_x(page, _min("19:45")), _y(page, "fl"))
        self._wait_editing(page)
        before = self._blocks(base_url)
        writes = _requests_that_write(page)
        _press(page, "10:00", lane="fl")
        page.mouse.move(_x(page, _min("12:08")), _y(page, "fl"), steps=10)
        assert "10:00–12:15" in _tip_text(page)
        page.mouse.up()
        assert _state(page, "flForm.id") is None
        assert _state(page, "flForm.by") == "times"
        assert _state(page, "flForm.start_time") == "10:00"
        assert _state(page, "flForm.end_time") == "12:15"
        expect(page.get_by_role("button", name="+ Add block")).to_be_visible()
        assert self._blocks(base_url) == before
        assert writes == []
        # dragging leftwards works the same
        _drag(page, "15:00", "14:00", lane="fl")
        assert _state(page, "flForm.start_time") == "14:00"
        assert _state(page, "flForm.end_time") == "15:00"
        assert self._blocks(base_url) == before

    def test_a_block_is_not_moved_by_dragging_it(self, page, base_url):
        local, _ = self._sources(base_url)
        self._block(base_url, local, start_time="19:00", end_time="20:30")
        _open(page, base_url)
        _day(page)
        before = self._blocks(base_url)
        _drag(page, "19:45", "21:00", lane="fl")
        assert self._blocks(base_url) == before
        assert _state(page, "flForm.id") is None


class TestNothingIsSavedByADrag:
    def test_the_entry_is_untouched_until_create_entry_and_then_holds_the_dragged_values(
        self, page, base_url
    ):
        _open(page, base_url)
        _day(page)
        writes = _requests_that_write(page)
        _drag(page, "17:00", "18:45")
        _drag(page, "11:00", "11:30")
        page.mouse.dblclick(_x(page, _min("15:00")), _y(page))
        _drag(page, "15:15", "15:15", dy=100)  # off the lane: the break goes again
        page.wait_for_load_state("networkidle")
        assert writes == []
        with httpx.Client(base_url=base_url) as c:
            assert c.get(f"/api/entries/{TODAY}").status_code == 404
        assert (_form(page)["start"], _form(page)["end"]) == ("09:30", "19:15")
        assert _form(page)["breaks"] == []
        with page.expect_response(
            lambda r: r.url.endswith("/api/entries") and r.request.method == "POST"
        ):
            page.get_by_role("button", name="Create entry").click()
        with httpx.Client(base_url=base_url) as c:
            saved = c.get(f"/api/entries/{TODAY}").json()
        assert (saved["start_time"], saved["end_time"]) == ("09:30", "19:15")
        assert saved["breaks"] == []

    def test_an_edited_entry_is_untouched_until_save_changes(self, page, base_url):
        body = {
            "date": TODAY,
            "day_type": "work",
            "start_time": "09:00",
            "end_time": "17:00",
            "breaks": [{"break_minutes": 30, "start_time": "13:00", "end_time": "13:30"}],
        }
        with httpx.Client(base_url=base_url) as c:
            assert c.post("/api/entries", json=body).status_code == 201
            saved = c.get(f"/api/entries/{TODAY}").json()
        _open(page, base_url)
        page.locator(f"button.log-cal-day[aria-label='{TODAY}']").click()
        page.wait_for_function(f"() => {MAIN}.editingDate === '{TODAY}'", timeout=5000)
        page.wait_for_selector(".dr-notch[data-dr=nbody]")
        writes = _requests_that_write(page)
        _drag(page, "13:15", "15:15")
        _drag(page, "17:00", "18:00")
        page.wait_for_load_state("networkidle")
        assert writes == []
        with httpx.Client(base_url=base_url) as c:
            assert c.get(f"/api/entries/{TODAY}").json() == saved
        with page.expect_response(lambda r: "/api/entries/" in r.url and r.request.method == "PUT"):
            page.get_by_role("button", name="Save changes").click()
        with httpx.Client(base_url=base_url) as c:
            after = c.get(f"/api/entries/{TODAY}").json()
        assert after["end_time"] == "18:00"
        assert [(b["start_time"], b["end_time"]) for b in after["breaks"]] == [("15:00", "15:30")]


class TestMotion:
    def test_nothing_moves_on_load(self, page, base_url):
        _open(page, base_url, reduced=False)
        _day(page, breaks=[LUNCH])
        page.wait_for_timeout(100)
        running = page.evaluate(
            "() => document.getAnimations()"
            ".filter(a => (a.animationName || '').startsWith('dr-')).length"
        )
        assert running == 0
        assert page.locator(".dr-pop, .dr-open, .dr-wave, .dr-puff").count() == 0

    def test_a_release_settles_the_grip_with_a_spring_a_new_notch_opens_and_a_removed_one_puffs(
        self, page, base_url
    ):
        _open(page, base_url, reduced=False)
        _day(page)
        page.evaluate(
            """() => { window.__seen = new Set();
              const note = (el, c) => el.classList && el.classList.contains(c)
                && window.__seen.add(c);
              new MutationObserver(list => {
                for (const r of list) for (const c of ['dr-pop', 'dr-open', 'dr-puff']) {
                  if (r.type === 'attributes') note(r.target, c);
                  r.addedNodes.forEach(n => note(n, c));
                }
              }).observe(document.querySelector('.dr-field'),
                { attributes: true, childList: true, subtree: true,
                  attributeFilter: ['class'] }); }"""
        )
        _drag(page, "17:00", "18:00")
        page.wait_for_function("window.__seen.has('dr-pop')", timeout=5000)
        page.mouse.dblclick(_x(page, _min("12:00")), _y(page))
        page.wait_for_function("window.__seen.has('dr-open')", timeout=5000)
        _drag(page, "12:15", "12:15", dy=100)
        page.wait_for_function("window.__seen.has('dr-puff')", timeout=5000)

    def test_the_bar_eases_to_a_new_place_and_a_drag_does_not_lag(self, page, base_url):
        _open(page, base_url, reduced=False)
        _day(page)
        css = "e => getComputedStyle(e).transitionDuration"
        assert page.locator(".dr-bar").evaluate(css).startswith("0.28")
        _press(page, "11:00")
        page.mouse.move(_x(page, _min("12:00")), _y(page), steps=4)
        assert page.locator(".dr-bar").evaluate(css) == "0s"  # while dragging: exactly the pointer
        page.mouse.up()

    def test_reduced_motion_turns_all_of_it_off(self, page, base_url):
        _open(page, base_url)
        _day(page, "09:00", "18:00", [LUNCH])
        got = page.evaluate(
            """() => {
              const g = document.querySelector('.dr-grip--end');
              const n = document.querySelector('.dr-notch');
              const flag = document.querySelector('.dr-flag');
              g.classList.add('dr-pop'); n.classList.add('dr-open'); flag.classList.add('dr-wave');
              const cs = (e, p) => getComputedStyle(e, p);
              return [cs(document.querySelector('.dr-bar')).transitionDuration,
                cs(g, '::before').animationName, cs(n).animationName,
                cs(flag.firstElementChild).animationName];
            }"""
        )
        assert got == ["0s", "none", "none", "none"]


class TestNothingScrollsSideways:
    @pytest.mark.parametrize("width,height", WIDTHS)
    def test_the_tag_at_either_end_stays_inside_and_the_ruler_labels_do_not_overlap(
        self, page, base_url, width, height
    ):
        _open(page, base_url, (width, height))
        _day(page)
        for start, beyond in [("17:00", HI + 40), ("09:00", LO - 40)]:
            x_to = min(max(_x(page, beyond), 1), width - 1)
            _press(page, start)
            page.mouse.move(x_to, _y(page), steps=10)
            expect(page.locator(".dr-tag")).to_be_visible()
            tag = page.locator(".dr-tag").bounding_box()
            field = page.locator(".dr-field").bounding_box()
            assert tag["x"] >= field["x"] - 1, (width, start, tag, field)
            assert tag["x"] + tag["width"] <= field["x"] + field["width"] + 1, (width, start)
            assert page.evaluate("document.documentElement.scrollWidth") <= width, (width, start)
            page.mouse.up()
        labels = page.evaluate(
            """() => [...document.querySelectorAll('.dr-tick b')]
              .filter(b => b.offsetParent !== null && b.textContent.trim())
              .map(b => { const r = b.getBoundingClientRect(); return [r.left, r.right]; })"""
        )
        for (_, right), (left, _) in zip(labels, labels[1:], strict=False):
            assert right <= left, (width, labels)
        # a label every 3 hours above 640px, every 6 at 640px and below
        assert len(labels) == (7 if width > 640 else 4)

    @pytest.mark.parametrize("width,height", WIDTHS)
    def test_no_horizontal_scroll_with_breaks_blocks_and_the_flag_drawn(
        self, page, base_url, width, height
    ):
        with httpx.Client(base_url=base_url) as c:
            body = {"name": "Local", "hourly_rate": 60, "currency": "EUR"}
            source = c.post("/api/freelance/sources", json=body).json()["id"]
            times = {"start_time": "21:00", "end_time": "23:45"}
            c.post("/api/freelance/blocks", json={"date": TODAY, "source_id": source} | times)
        _open(page, base_url, (width, height))
        minutes_only = {"break_minutes": 20, "start_time": "", "end_time": ""}
        _day(page, "06:00", "23:45", [LUNCH, minutes_only])
        assert page.evaluate("document.documentElement.scrollWidth") <= width
        field = page.locator(".dr-field").bounding_box()
        for sel in (".dr-bar", ".dr-block", ".dr-notch"):
            box = page.locator(sel).first.bounding_box()
            assert box["x"] >= field["x"] - 1, sel
            assert box["x"] + box["width"] <= field["x"] + field["width"] + 1, sel
