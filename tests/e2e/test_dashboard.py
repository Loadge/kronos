"""E2E: Dashboard metrics display.

These tests seed the database via the API (using httpx, not the browser) so
the dashboard assertions can be deterministic without depending on form
submission tests running first.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.e2e


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


# ── tests ─────────────────────────────────────────────────────────────────────


class TestDashboardMetrics:
    @pytest.fixture(autouse=True)
    def _clean(self, base_url):
        """Wipe DB before each test so metrics are predictable."""
        _wipe(base_url)
        yield
        _wipe(base_url)

    def test_empty_dashboard_shows_zero_metrics(self, page, base_url):
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".hero-num", timeout=5000)

        # The hero and every chip read zero with an empty DB
        page.wait_for_function(
            "() => document.querySelector('.hero-num')?.innerText.includes('0.00h')", timeout=5000
        )
        chips = page.locator(".chip")
        assert chips.count() == 3
        for i in range(chips.count()):
            text = chips.nth(i).inner_text()
            assert "128" not in text, f"Unexpected value in chip: {text}"
        # Nothing to quick-log from yet, but the row is there since today is empty.
        assert page.locator(".quick-log").is_visible()

    def test_work_days_show_in_week_card(self, page, base_url):
        _seed(
            base_url,
            [
                _work("2026-07-14"),  # Monday of a week
                _work("2026-07-15"),  # Tuesday
            ],
        )

        page.goto(f"{base_url}/#dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".chip", timeout=5000)

        # Two 7h days against 8h: the cumulative chip's tooltip carries the day count
        # and the hero the balance.
        page.wait_for_function(
            "() => document.querySelector('.hero-num')?.innerText.includes('2.00h')", timeout=5000
        )
        assert "−2.00h" in page.locator(".hero-num").inner_text()
        assert "2 work days" in page.locator(".hero-text").get_attribute("title")

    def test_surplus_shown_correctly(self, page, base_url):
        """10h work day (no breaks) vs 8h target → +2h surplus visible."""
        _seed(base_url, [_work("2026-07-20", start="08:00", end="18:00", breaks=())])

        page.goto(f"{base_url}/#dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_function(
            "() => document.querySelector('.hero-num')?.innerText.includes('+2.00h')", timeout=5000
        )
        # The trajectory ends on that value and projects past it.
        chart = page.locator(".traj-wrap")
        assert "+2.00h today" in (chart.get_attribute("aria-label") or "")
        assert page.locator(".traj-line").count() == 1
        assert page.locator(".traj-proj").count() == 1

    def test_analytics_tab_loads_without_error(self, page, base_url):
        page.goto(f"{base_url}/#analytics")
        page.wait_for_load_state("networkidle")

        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.wait_for_timeout(1000)
        assert errors == [], f"JS errors on analytics tab: {errors}"


class TestSettingsTab:
    def test_settings_form_shows_current_values(self, page, base_url):
        page.goto(f"{base_url}/#settings")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("input[type='number']", timeout=5000)

        # Default daily target is 8.0
        target_input = page.locator("input[type='number']").first
        assert target_input.input_value() in ("8", "8.0")

    def test_saving_settings_shows_confirmation(self, page, base_url):
        page.goto(f"{base_url}/#settings")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("input[type='number']", timeout=5000)

        # Change the daily target
        target_input = page.locator("input[type='number']").first
        target_input.fill("7.5")

        # Each section saves its own fields; the button wakes up once something changed.
        save = page.get_by_role("button", name="Save work")
        page.wait_for_function(
            "() => !document.querySelector('#settings-work button[type=submit]').disabled",
            timeout=5000,
        )
        save.click()

        # Should show some form of success feedback. The actual mechanism is the
        # `.save-ribbon` toast (index.html): it toggles a `ribbon-show` class and
        # its `.ribbon-msg` reads "Settings saved". The page also has a
        # permanently-present (but hidden) `[role='alert']` error banner earlier
        # in the DOM, so a comma-joined fallback selector including
        # `[role='alert']` would resolve to that hidden element first and
        # `wait_for_selector` would wait on its (never-changing) state forever —
        # targeting the ribbon directly avoids that.
        page.wait_for_selector(".save-ribbon.ribbon-show:has-text('Settings saved')", timeout=5000)
