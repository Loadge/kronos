"""E2E: "today" is the date on the wall, not the date in Greenwich.

In Spain the UTC date lags the local one for the first hour or two after midnight, so a block
logged then fell out of "This year" and new entries defaulted to yesterday.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize(
    "zone,now,today",
    [
        ("Europe/Madrid", "2026-11-05T23:30:00Z", "2026-11-06"),  # past midnight in Madrid
        ("America/New_York", "2026-11-06T02:30:00Z", "2026-11-05"),  # still the evening before
    ],
)
def test_today_follows_the_browser_clock(browser, base_url, zone, now, today):
    context = browser.new_context(timezone_id=zone)
    page = context.new_page()
    page.clock.set_fixed_time(now)
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("main .page-head", timeout=5000)
    got = page.evaluate("Alpine.$data(document.querySelector('main')).todayIso()")
    context.close()
    assert got == today
