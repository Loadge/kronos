"""E2E: the interactive Analytics — the zoomable chart and what its range drives.

Drag a rectangle on the chart and that span is the new view (the range label and the ledger
follow, Reset wakes up); the presets set the range; the series switch draws bars; the
weekday pattern, histogram and records are computed for the visible range only. Year at a
glance keeps its whole year, with a tooltip per day and a click that opens the day in Log.
"""

from __future__ import annotations

import datetime

import httpx
import pytest

pytestmark = pytest.mark.e2e


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        c.put("/api/config", json={"daily_target_hours": 8})


@pytest.fixture(autouse=True)
def _clean(base_url):
    _wipe(base_url)
    yield
    _wipe(base_url)


def _work(date: str, end: str, notes: str = "") -> dict:
    # 09:00 to `end` with a 60-minute break: "18:00" is on target, "19:00" is +1h, "17:00" −1h.
    return {
        "date": date,
        "day_type": "work",
        "start_time": "09:00",
        "end_time": end,
        "breaks": [{"break_minutes": 60}],
        "notes": notes,
    }


def _seed(base_url: str, entries: list[dict]) -> None:
    with httpx.Client(base_url=base_url) as c:
        for body in entries:
            r = c.post("/api/entries", json=body)
            assert r.status_code == 201, r.text


def _open(page, base_url: str) -> None:
    page.goto(f"{base_url}/#analytics")
    page.wait_for_selector(".an-chart", timeout=10000)
    page.wait_for_timeout(200)


YEAR = datetime.date.today().year


class TestZoom:
    def test_rectangle_zooms_and_reset_restores(self, page, base_url):
        _seed(base_url, [_work(f"{YEAR}-02-02", "19:00"), _work(f"{YEAR}-02-03", "19:00")])
        _open(page, base_url)
        before = page.locator(".an-range").inner_text()
        assert f"Jan 1, {YEAR}" in before
        assert page.locator(".an-reset").is_disabled()

        box = page.locator(".an-chart").bounding_box()
        page.mouse.move(box["x"] + box["width"] * 0.3, box["y"] + 50)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + 120, steps=5)
        page.mouse.up()
        page.wait_for_function(
            "before => document.querySelector('.an-range').innerText !== before",
            arg=before,
            timeout=3000,
        )
        after = page.locator(".an-range").inner_text()
        assert f"Jan 1, {YEAR}" not in after
        assert not page.locator(".an-reset").is_disabled()
        # no preset is lit while zoomed by hand
        assert page.locator(".an-presets button.on").count() == 0

        page.locator(".an-reset").click()
        page.wait_for_function(
            "before => document.querySelector('.an-range').innerText === before",
            arg=before,
            timeout=3000,
        )
        assert page.locator(".an-presets button.on").inner_text() == "This year"

    def test_wheel_zooms_at_the_cursor(self, page, base_url):
        _seed(base_url, [_work(f"{YEAR}-03-02", "19:00")])
        _open(page, base_url)
        before = page.locator(".an-range").inner_text()
        box = page.locator(".an-chart").bounding_box()
        page.mouse.move(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)
        page.mouse.wheel(0, -200)
        page.wait_for_function(
            "before => document.querySelector('.an-range').innerText !== before",
            arg=before,
            timeout=3000,
        )
        days = int(page.locator(".an-range").inner_text().split("·")[-1].split()[0])
        assert days < int(before.split("·")[-1].split()[0])


class TestRangeDrivesThePage:
    def test_presets_and_ledger(self, page, base_url):
        today = datetime.date.today()
        this_month = today.replace(day=1)
        # A +1h day this month and a −1h day earlier in the year (another month).
        earlier = (this_month - datetime.timedelta(days=40)).replace(day=3)
        if earlier.year != today.year:
            earlier = datetime.date(today.year, 1, 3)
        _seed(
            base_url, [_work(this_month.isoformat(), "19:00"), _work(earlier.isoformat(), "17:00")]
        )
        _open(page, base_url)

        ledger = page.locator(".an-ledger")
        assert "±0.00h" in ledger.locator(".an-lrow--big").inner_text()  # this year: +1 −1
        page.locator(".an-presets button", has_text="This month").click()
        page.wait_for_function(
            "() => document.querySelector('.an-lrow--big b').innerText === '+1.00h'", timeout=3000
        )
        assert (
            "1 "
            in ledger.locator(".an-lrow", has_text="Logged days").locator("b").inner_text() + " "
        )
        # records follow the range: the −1h day is out of view now
        labels = page.locator(".an-rec-label").all_inner_texts()
        assert "Longest day" in labels
        assert "Most deficit month" not in labels
        page.locator(".an-presets button", has_text="All").click()
        page.wait_for_function(
            "() => document.querySelector('.an-lrow--big b').innerText === '±0.00h'", timeout=3000
        )
        assert "Most deficit month" in page.locator(".an-rec-label").all_inner_texts()

    def test_series_switch_draws_bars(self, page, base_url):
        _seed(
            base_url,
            [_work(f"{YEAR}-04-06", "19:00"), {"date": f"{YEAR}-04-07", "day_type": "vacation"}],
        )
        _open(page, base_url)
        assert page.locator(".an-line").count() == 1
        page.get_by_role("radio", name="Per day").click()
        page.wait_for_selector(".an-bar", timeout=3000)
        bars = page.locator(".an-bar")
        assert bars.count() == 2
        classes = " ".join(bars.nth(i).get_attribute("class") or "" for i in range(2))
        assert "hm-surplus" in classes and "hm-vacation" in classes
        page.get_by_role("radio", name="Per month").click()
        page.wait_for_function(
            "() => document.querySelectorAll('.an-bar').length === 1", timeout=3000
        )

    def test_weekday_times_and_histogram(self, page, base_url):
        _seed(
            base_url, [_work(f"{YEAR}-05-04", "19:00"), _work(f"{YEAR}-05-11", "19:30")]
        )  # two Mondays
        _open(page, base_url)
        mon = page.locator(".weekday-cell", has_text="Mon")
        assert "09:00" in mon.locator(".weekday-times").inner_text()
        assert "19:15" in mon.locator(".weekday-times").inner_text()
        assert page.locator(".an-hist i").count() == 12
        assert "2 work days" in page.locator(".an-two .chart-caption").last.inner_text()


class TestYearAtAGlance:
    def test_tooltip_and_click_open_the_day(self, page, base_url):
        date = f"{YEAR}-06-10"
        _seed(base_url, [_work(date, "19:00", notes="Release day")])
        _open(page, base_url)
        cell = page.locator(f".hm-cell[data-date='{date}']")
        cell.hover()
        tip = page.locator(".hm-tip")
        tip.wait_for(state="visible", timeout=3000)
        text = tip.inner_text()
        assert (
            "Jun 10" in text
            and "+1.00h" in text
            and "Release day" in text
            and "open in Log" in text
        )
        cell.click()
        page.wait_for_url("**/#log", timeout=3000)
        page.wait_for_selector(f"h2:has-text('Edit {date}')", timeout=5000)

    def test_empty_day_offers_to_log_it(self, page, base_url):
        _seed(base_url, [_work(f"{YEAR}-06-10", "19:00")])
        _open(page, base_url)
        cell = page.locator(f".hm-cell[data-date='{YEAR}-06-11']")
        cell.hover()
        tip = page.locator(".hm-tip")
        tip.wait_for(state="visible", timeout=3000)
        assert "no entry" in tip.inner_text() and "log it" in tip.inner_text()
        cell.click()
        page.wait_for_url("**/#log", timeout=3000)
        page.wait_for_selector("h2:has-text('New entry')", timeout=5000)
        assert (
            page.locator(".log-cal-day[aria-pressed='true']").get_attribute("aria-label")
            == f"{YEAR}-06-11"
        )
