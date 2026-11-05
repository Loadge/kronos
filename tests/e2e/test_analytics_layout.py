"""E2E: Analytics tab section layout — the order the user chose on 2026-10-01.

WHY this test exists: "Year at a glance" is what the user checks daily, so it
must lead, right after the header. "Records" and "Point-in-time" were sections
the user never looked at: Records moved to the bottom (the last section before
Export) and Point-in-time was removed outright — its API endpoint
(/api/analytics/cumulative) was deliberately kept, but the section and its
date input must not come back.
"""

from __future__ import annotations

import datetime

import httpx
import pytest

pytestmark = pytest.mark.e2e

EXPECTED_ORDER = [
    "Year at a glance",
    "Balance over time",
    "Weekday pattern",
    "Daily surplus",
    "Years",
    "Records",
    "Export",
]


def _seed(base_url: str, entries: list[dict]) -> None:
    with httpx.Client(base_url=base_url) as c:
        for body in entries:
            r = c.post("/api/entries", json=body)
            assert r.status_code == 201, f"seed failed: {r.text}"


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")


class TestAnalyticsLayout:
    @pytest.fixture(autouse=True)
    def _clean(self, base_url):
        _wipe(base_url)
        yield
        _wipe(base_url)

    def test_section_order_matches_user_choice(self, page, base_url):
        # One work entry for today so every section has data under the
        # default (current-year) filter.
        _seed(
            base_url,
            [
                {
                    "date": datetime.date.today().isoformat(),
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "breaks": [{"break_minutes": 60}],
                }
            ],
        )

        page.goto(f"{base_url}/#analytics")
        page.wait_for_selector(".hm-cell", timeout=10000)

        headings = page.locator("section[aria-label=Analytics] h2").all_inner_texts()
        # Balance over time carries a decorative 👔 (aria-hidden): compare the words only
        headings = [h.replace("👔", "").strip() for h in headings]
        # the page's own title first (every tab has one), then the sections in order
        assert headings[0] == "Analytics"
        assert headings[1:] == EXPECTED_ORDER

    def test_point_in_time_section_is_gone(self, page, base_url):
        _seed(
            base_url,
            [
                {
                    "date": datetime.date.today().isoformat(),
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "breaks": [{"break_minutes": 60}],
                }
            ],
        )

        page.goto(f"{base_url}/#analytics")
        page.wait_for_selector(".hm-cell", timeout=10000)

        assert "Point-in-time" not in page.locator("section[aria-label=Analytics]").inner_text()
        assert page.locator("section[aria-label=Analytics] input[type=date]").count() == 0


def _wipe_all(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


def _seed_year(base_url: str, *, freelance: bool) -> None:
    """A dozen work days, and (optionally) a freelance source with blocks in the same range."""
    today = datetime.date.today()
    with httpx.Client(base_url=base_url) as c:
        day, n = today, 0
        while n < 12:
            day -= datetime.timedelta(days=1)
            if day.weekday() >= 5 or day.year != today.year:
                continue
            r = c.post(
                "/api/entries",
                json={
                    "date": day.isoformat(),
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": ("18:00", "19:00", "17:30")[n % 3],
                    "breaks": [{"break_minutes": 60}],
                },
            )
            assert r.status_code == 201, r.text
            if freelance:
                if n == 0:
                    s = c.post(
                        "/api/freelance/sources",
                        json={"name": "Local", "hourly_rate": 60, "currency": "EUR"},
                    )
                    assert s.status_code == 201, s.text
                    source_id = s.json()["id"]
                b = c.post(
                    "/api/freelance/blocks",
                    json={"date": day.isoformat(), "source_id": source_id, "hours": 2},
                )
                assert b.status_code == 201, b.text
            n += 1


class TestBalanceRow:
    """The Balance row: chart column on the left, ledger aside on the right. The aside (with a
    Freelance block) is the taller one, and Weekday pattern + Daily surplus sit under the brush
    to fill the hole that used to open under it."""

    @pytest.fixture(autouse=True)
    def _clean(self, base_url):
        _wipe_all(base_url)
        yield
        _wipe_all(base_url)

    def _open(self, page, base_url: str) -> None:
        page.set_viewport_size({"width": 1280, "height": 900})
        page.goto(f"{base_url}/#analytics")
        page.wait_for_selector(".an-panel .weekday-cell", timeout=10000)
        page.wait_for_selector("[data-testid=an-freelance], .an-ledger-rows", timeout=10000)
        page.wait_for_timeout(300)

    def test_panels_end_where_the_ledger_ends(self, page, base_url):
        _seed_year(base_url, freelance=True)
        self._open(page, base_url)
        assert page.locator("[data-testid=an-freelance]").count() == 1
        ledger = page.locator(".an-ledger").bounding_box()
        ledger_bottom = ledger["y"] + ledger["height"]
        panels = page.locator(".an-chart-col .an-panel")
        assert panels.count() == 2
        for i in range(2):
            box = panels.nth(i).bounding_box()
            assert abs(box["y"] + box["height"] - ledger_bottom) <= 4, (
                f"panel {i} ends at {box['y'] + box['height']:.0f}, ledger at {ledger_bottom:.0f}"
            )
        # the panels sit under the brush, side by side, inside the chart column
        brush = page.locator(".an-brush").bounding_box()
        first, second = panels.nth(0).bounding_box(), panels.nth(1).bounding_box()
        assert first["y"] >= brush["y"] + brush["height"]
        assert abs(first["y"] - second["y"]) <= 1 and second["x"] > first["x"]

    def test_without_freelance_nothing_stretches_or_overlaps(self, page, base_url):
        _seed_year(base_url, freelance=False)
        self._open(page, base_url)
        assert page.locator("[data-testid=an-freelance]").count() == 0
        ledger = page.locator(".an-ledger").bounding_box()
        col = page.locator(".an-chart-col").bounding_box()
        # the aside is the shorter one here, so the column sets the row height...
        assert ledger["height"] < col["height"]
        # ...and the panels stay compact (their natural size) and clear of the Years heading
        for panel in page.locator(".an-chart-col .an-panel").all():
            box = panel.bounding_box()
            assert box["height"] < 260
        years = page.locator("section[aria-label=Analytics] h2", has_text="Years").bounding_box()
        assert years["y"] >= col["y"] + col["height"]

    def test_hints_captions_gone_and_tie_present(self, page, base_url):
        _seed_year(base_url, freelance=True)
        self._open(page, base_url)
        section = page.locator("section[aria-label=Analytics]")
        # only Records keeps its "for the range shown" hint
        assert section.locator(".an-hint", has_text="for the range shown").count() == 1
        assert page.locator(".an-panel .an-hint").count() == 0
        assert page.locator(".an-panel .chart-caption").count() == 0
        assert "work days" not in page.locator(".an-panel").all_inner_texts()[1]
        # what the captions said lives on the charts as tooltips
        assert "work days" in page.locator(".an-hist").get_attribute("title")
        assert "average start" in page.locator(".weekday-grid").get_attribute("title")
        # 👔 before Balance over time and before Employee in both switches
        balance = section.locator("h2", has_text="Balance over time")
        assert balance.inner_text().startswith("👔")
        assert balance.locator("span[aria-hidden=true]").inner_text() == "👔"
        switches = page.locator(".hm-switch button", has_text="Employee")
        assert switches.count() == 2
        for i in range(2):
            assert "👔" in switches.nth(i).inner_text()
