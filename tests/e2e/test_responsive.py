"""E2E: Responsive layout contract across mobile/tablet/desktop viewports.

Pins down the responsive behaviour actually implemented in
``backend/static/styles.css`` (verified there directly, not assumed from a
prior summary) so a future change that breaks it gets caught:

- ``.app-header``: below ``min-width: 720px`` it is a 2-row CSS grid
  (brand+toggle on top, full-width ``nav.tabs`` below). At/above 720px it
  becomes a single flex row — brand left, tabs+controls right.
- ``.log-layout``: single column below ``min-width: 900px``. At/above it, a
  280px calendar sidebar (``.log-col-left`` / ``.log-cal``) sits beside the
  form (``.log-form-card``).
- ``.week-grid``: ``repeat(7, minmax(0,1fr))`` above ``max-width: 640px``
  (seven same-row day cards). At/below it, a single stacked column of
  horizontally-laid-out day rows.
- ``.heatmap-scroll``: ``overflow-x: auto`` — its content may be wider than
  its box and scroll internally, but the page itself must never gain
  horizontal scroll because of it.

These are structural/functional assertions (bounding boxes, scroll widths),
not pixel-perfect screenshots — they tolerate cosmetic tweaks but catch a
breakpoint being removed, inverted, or renamed.
"""

from __future__ import annotations

import datetime

import httpx
import pytest

pytestmark = pytest.mark.e2e

MOBILE = (375, 812)
TABLET = (768, 1024)
DESKTOP = (1280, 800)

# Dashboard, Log, Week, Days, Analytics — per the no-overflow check's scope.
OVERFLOW_TABS = ["dashboard", "log", "week", "days", "analytics"]


# ── helpers ───────────────────────────────────────────────────────────────────


def _seed(base_url: str, entries: list[dict]) -> None:
    """POST entries directly to the API — bypasses the browser form."""
    with httpx.Client(base_url=base_url) as c:
        for body in entries:
            r = c.post("/api/entries", json=body)
            assert r.status_code == 201, f"seed failed: {r.text}"


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")


def _work(date, start="09:00", end="17:00", breaks=(60,)):
    return {
        "date": date,
        "day_type": "work",
        "start_time": start,
        "end_time": end,
        "breaks": [{"break_minutes": m} for m in breaks],
    }


def _current_week_workdays() -> list[str]:
    """Two ISO dates (Mon, Tue) in the *current* real week.

    The app reads the real browser clock, so seeded data must land in the
    actual current week/year for the Week tab and the Analytics heatmap
    (default year) to show it.
    """
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    return [monday.isoformat(), (monday + datetime.timedelta(days=1)).isoformat()]


def _no_horizontal_overflow(page) -> bool:
    return page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"
    )


@pytest.fixture(autouse=True)
def _seeded(base_url):
    """Seed real work-day entries so every tab has content to lay out.

    Empty states can hide layout bugs (e.g. an empty heatmap has nothing to
    overflow), so this runs for every test in the module.
    """
    _wipe(base_url)
    _seed(base_url, [_work(d) for d in _current_week_workdays()])
    yield
    _wipe(base_url)


# ── 1. no horizontal page overflow, at every viewport, on every tab ────────────


class TestNoHorizontalOverflow:
    @pytest.mark.parametrize("tab", OVERFLOW_TABS)
    @pytest.mark.parametrize("width,height", [MOBILE, TABLET, DESKTOP])
    def test_no_horizontal_overflow(self, page, base_url, width, height, tab):
        page.set_viewport_size({"width": width, "height": height})
        page.goto(f"{base_url}/#{tab}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(150)  # let Alpine finish rendering (heatmap, grids)

        assert _no_horizontal_overflow(page), (
            f"tab={tab} viewport={width}x{height} caused page-level horizontal overflow"
        )


# ── 2. header: stacked on mobile, single row on desktop ────────────────────────


class TestHeaderLayout:
    def test_mobile_nav_stacks_below_brand(self, page, base_url):
        page.set_viewport_size({"width": MOBILE[0], "height": MOBILE[1]})
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_load_state("networkidle")

        tabs = page.locator("nav[role='tablist'] a[role='tab']")
        assert tabs.count() == 6
        for i in range(tabs.count()):
            assert tabs.nth(i).is_visible(), f"tab {i} not visible on mobile"

        brand_box = page.locator(".brand").bounding_box()
        nav_box = page.locator("nav[role='tablist']").bounding_box()
        assert brand_box is not None
        assert nav_box is not None
        # Stacked: nav's top is at or below the brand's bottom.
        assert nav_box["y"] >= brand_box["y"] + brand_box["height"] - 1

    def test_desktop_nav_beside_brand(self, page, base_url):
        page.set_viewport_size({"width": DESKTOP[0], "height": DESKTOP[1]})
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_load_state("networkidle")

        brand_box = page.locator(".brand").bounding_box()
        nav_box = page.locator("nav[role='tablist']").bounding_box()
        assert brand_box is not None
        assert nav_box is not None

        brand_top, brand_bottom = brand_box["y"], brand_box["y"] + brand_box["height"]
        nav_top, nav_bottom = nav_box["y"], nav_box["y"] + nav_box["height"]
        # Same row: the two vertical extents overlap.
        assert nav_top < brand_bottom and brand_top < nav_bottom


# ── 3. Log tab: calendar stacked on mobile, side-by-side at >=900px ────────────


class TestLogLayout:
    def test_mobile_calendar_stacks_above_form(self, page, base_url):
        page.set_viewport_size({"width": MOBILE[0], "height": MOBILE[1]})
        page.goto(f"{base_url}/#log")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("form", timeout=5000)

        cal_box = page.locator(".log-cal").first.bounding_box()
        form_box = page.locator(".log-form-card").bounding_box()
        assert cal_box is not None
        assert form_box is not None
        # Stacked: form's top is at or below the calendar's bottom.
        assert form_box["y"] >= cal_box["y"] + cal_box["height"] - 1

    def test_desktop_calendar_beside_form(self, page, base_url):
        page.set_viewport_size({"width": DESKTOP[0], "height": DESKTOP[1]})
        page.goto(f"{base_url}/#log")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("form", timeout=5000)

        cal_box = page.locator(".log-cal").first.bounding_box()
        form_box = page.locator(".log-form-card").bounding_box()
        assert cal_box is not None
        assert form_box is not None

        # Side by side: calendar is left of the form...
        assert cal_box["x"] < form_box["x"]
        # ...and their vertical extents overlap.
        cal_top, cal_bottom = cal_box["y"], cal_box["y"] + cal_box["height"]
        form_top, form_bottom = form_box["y"], form_box["y"] + form_box["height"]
        assert cal_top < form_bottom and form_top < cal_bottom


# ── 4. Week tab: 7-column row on desktop, stacked column on mobile ─────────────


class TestWeekGrid:
    def test_desktop_seven_columns_same_row(self, page, base_url):
        page.set_viewport_size({"width": DESKTOP[0], "height": DESKTOP[1]})
        page.goto(f"{base_url}/#week")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".week-day", timeout=5000)

        cards = page.locator(".week-day")
        assert cards.count() == 7
        tops = [cards.nth(i).bounding_box()["y"] for i in range(7)]
        assert max(tops) - min(tops) <= 5, f"day-card tops not aligned: {tops}"

    def test_mobile_single_stacked_column(self, page, base_url):
        page.set_viewport_size({"width": MOBILE[0], "height": MOBILE[1]})
        page.goto(f"{base_url}/#week")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".week-day", timeout=5000)

        cards = page.locator(".week-day")
        assert cards.count() == 7
        boxes = [cards.nth(i).bounding_box() for i in range(7)]
        for i in range(1, 7):
            prev_bottom = boxes[i - 1]["y"] + boxes[i - 1]["height"]
            assert boxes[i]["y"] >= prev_bottom - 1, (
                f"week-day {i} is not below week-day {i - 1} (not a single stacked column)"
            )


# ── 5. Analytics heatmap: scrolls internally, never the page ───────────────────


class TestHeatmapScroll:
    def test_mobile_heatmap_scrolls_internally_without_page_overflow(self, page, base_url):
        page.set_viewport_size({"width": MOBILE[0], "height": MOBILE[1]})
        page.goto(f"{base_url}/#analytics")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".heatmap-scroll", timeout=5000)

        dims = page.locator(".heatmap-scroll").evaluate(
            "el => ({sw: el.scrollWidth, cw: el.clientWidth})"
        )
        assert dims["sw"] > dims["cw"], "heatmap has no overflowing content to scroll"
        assert _no_horizontal_overflow(page), "heatmap caused page-level horizontal scroll"
