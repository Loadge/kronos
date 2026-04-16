"""E2E: Log form — creating entries and optimistic UI navigation.

Tests in this module create real entries via the browser form.  Each test
uses a fresh page (function-scoped by default) but they all share the same
live server, so entries accumulate.  Tests use unique dates to avoid
conflicts with each other.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.e2e


def _open_log_tab(page, base_url):
    page.goto(f"{base_url}/#log")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("form", timeout=5000)


class TestLogFormRendering:
    def test_form_has_date_field(self, page, base_url):
        _open_log_tab(page, base_url)
        assert page.locator("input[name='date'], input[type='date']").count() >= 1

    def test_form_has_day_type_select(self, page, base_url):
        _open_log_tab(page, base_url)
        assert page.locator("select").count() >= 1

    def test_work_day_shows_time_fields(self, page, base_url):
        _open_log_tab(page, base_url)
        # Default should be "work" day type — time inputs must be visible
        page.wait_for_selector("input[name='start_time'], input[type='time']", timeout=3000)
        assert page.locator("input[type='time']").count() >= 2

    def test_selecting_vacation_hides_time_fields(self, page, base_url):
        _open_log_tab(page, base_url)
        page.select_option("select", "vacation")
        # Time fields should disappear (x-show / x-if)
        page.wait_for_timeout(300)  # allow Alpine transition
        time_inputs = page.locator("input[type='time']:visible")
        assert time_inputs.count() == 0


class TestLogFormSubmission:
    def test_submit_work_day_navigates_to_days_tab(self, page, base_url):
        _open_log_tab(page, base_url)

        # Fill in the form
        date_input = page.locator("input[type='date']").first
        date_input.fill("2026-06-01")

        page.select_option("select", "work")
        time_inputs = page.locator("input[type='time']")
        time_inputs.nth(0).fill("09:00")
        time_inputs.nth(1).fill("17:00")

        # Submit
        page.locator("button[type='submit'], button:has-text('Save'), button:has-text('Create')").first.click()

        # Optimistic navigation: should land on Days tab immediately
        page.wait_for_url("**/#days", timeout=5000)

    def test_submit_vacation_day_appears_in_days_list(self, page, base_url):
        _open_log_tab(page, base_url)

        date_input = page.locator("input[type='date']").first
        date_input.fill("2026-06-02")
        page.select_option("select", "vacation")

        page.locator("button[type='submit'], button:has-text('Save'), button:has-text('Create')").first.click()
        page.wait_for_url("**/#days", timeout=5000)

        # Wait for the entry to appear in the table
        page.wait_for_selector("td:has-text('2026-06-02'), td:has-text('vacation')", timeout=5000)

    def test_duplicate_date_shows_error(self, page, base_url):
        """Submitting the same date twice must show a validation error, not crash."""
        _open_log_tab(page, base_url)

        # First submission
        date_input = page.locator("input[type='date']").first
        date_input.fill("2026-06-03")
        page.select_option("select", "vacation")
        page.locator("button[type='submit'], button:has-text('Save'), button:has-text('Create')").first.click()
        page.wait_for_url("**/#days", timeout=5000)

        # Second submission — same date
        page.goto(f"{base_url}/#log")
        page.wait_for_selector("form", timeout=5000)
        date_input = page.locator("input[type='date']").first
        date_input.fill("2026-06-03")
        page.select_option("select", "vacation")
        page.locator("button[type='submit'], button:has-text('Save'), button:has-text('Create')").first.click()

        # Should show an error message (not crash silently)
        page.wait_for_selector(
            ".error, [role='alert'], .notification, text=already exists, text=conflict, text=409",
            timeout=5000,
        )
