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
    "Analytics",
    "Year at a glance",
    "Cumulative trend",
    "Monthly breakdown",
    "Yearly breakdown",
    "Weekday pattern",
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
        assert headings == EXPECTED_ORDER

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
