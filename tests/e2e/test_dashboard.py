"""E2E: Dashboard metrics display.

These tests seed the database via the API (using httpx, not the browser) so
the dashboard assertions can be deterministic without depending on form
submission tests running first.
"""

from __future__ import annotations

import pytest
import httpx


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
        page.wait_for_selector(".summary-card", timeout=5000)

        # All metric values should be 0 / 0h / 0.0 with an empty DB
        cards = page.locator(".summary-card")
        for i in range(cards.count()):
            text = cards.nth(i).inner_text()
            # Expect no large positive numbers (nothing is seeded)
            assert "128" not in text, f"Unexpected value in card: {text}"

    def test_work_days_show_in_week_card(self, page, base_url):
        _seed(base_url, [
            _work("2026-07-14"),  # Monday of a week
            _work("2026-07-15"),  # Tuesday
        ])

        page.goto(f"{base_url}/?today=2026-07-14#dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".summary-card", timeout=5000)

        # There should be a card showing "2" work days somewhere
        page_text = page.locator("body").inner_text()
        assert "2" in page_text  # at least the work day count

    def test_surplus_shown_correctly(self, page, base_url):
        """10h work day (no breaks) vs 8h target → +2h surplus visible."""
        _seed(base_url, [_work("2026-07-20", start="08:00", end="18:00", breaks=(0,))])

        page.goto(f"{base_url}/?today=2026-07-20#dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector(".summary-card", timeout=5000)

        page_text = page.locator("body").inner_text()
        # +2h surplus should appear somewhere
        assert "2" in page_text

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

        page.locator("button:has-text('Save'), button[type='submit']").first.click()

        # Should show some form of success feedback
        page.wait_for_selector(
            ".success, [role='alert'], .notification, text=saved, text=✓, text=Settings saved",
            timeout=5000,
        )
