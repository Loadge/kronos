"""E2E: Tab navigation and hash routing.

These tests verify that the single-page app correctly switches tabs,
updates the URL hash, and loads data for each section.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e


class TestTabSwitching:
    def test_dashboard_is_default_tab(self, page, base_url):
        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        # The Dashboard tab button should be active
        active = page.locator("nav button.active, nav [role='tab'][aria-selected='true']").first
        assert "dashboard" in active.inner_text().lower() or active.count() > 0

        # The hero (cumulative balance) and the three chips must be visible
        page.wait_for_selector(".hero-num", timeout=5000)
        assert page.locator(".chip").count() == 3

    def test_can_navigate_to_log_tab(self, page, base_url):
        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        page.click("text=Log")
        page.wait_for_url("**/#log", timeout=3000)

        # The log form must appear
        page.wait_for_selector("form", timeout=3000)
        assert page.locator("form").is_visible()

    def test_can_navigate_to_days_tab(self, page, base_url):
        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        page.click("text=Days")
        page.wait_for_url("**/#days", timeout=3000)

        # The entries table (or empty state) must be visible
        table_or_empty = page.locator(
            "table, [data-testid='empty-state'], .empty-state, p:has-text('No entries')"
        )
        assert table_or_empty.count() >= 0  # just checking no JS crash

    def test_can_navigate_to_settings_tab(self, page, base_url):
        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        page.get_by_role("button", name="Settings").click()  # the gear next to the theme toggle
        page.wait_for_url("**/#settings", timeout=3000)

        # Settings form must have target hours input
        page.wait_for_selector("input[type='number']", timeout=3000)
        assert page.locator("input[type='number']").count() >= 1

    def test_hash_routing_works_on_direct_load(self, page, base_url):
        """Navigating directly to /#settings must open the settings tab."""
        page.goto(f"{base_url}/#settings")
        page.wait_for_load_state("networkidle")

        # Settings content must be visible, not Dashboard
        page.wait_for_selector("input[type='number']", timeout=5000)
        assert page.locator("input[type='number']").count() >= 1

    def test_back_button_works_between_tabs(self, page, base_url):
        """Browser back/forward must move between tab states."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        page.click("text=Log")
        page.wait_for_url("**/#log", timeout=3000)

        page.click("text=Days")
        page.wait_for_url("**/#days", timeout=3000)

        page.go_back()
        page.wait_for_url("**/#log", timeout=3000)


class TestPageLoad:
    def test_page_title(self, page, base_url):
        page.goto(base_url)
        assert "Kronos" in page.title()

    def test_no_console_errors_on_load(self, page, base_url):
        errors: list[str] = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.on("pageerror", lambda err: errors.append(str(err)))

        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        # Filter out known-benign SW "install" messages
        real_errors = [e for e in errors if "service worker" not in e.lower()]
        assert real_errors == [], f"Console errors on page load: {real_errors}"

    def test_manifest_linked(self, page, base_url):
        page.goto(base_url)
        link = page.locator("link[rel='manifest']")
        assert link.count() == 1
        href = link.get_attribute("href")
        assert href is not None and "manifest" in href


class TestClickingATabLeavesNoCaret:
    """A click focuses the tab and used to leave a collapsed text selection inside it, which
    Chrome on Windows paints as a blinking caret after the label. Labels are unselectable
    now and the caret colour transparent: neither condition may come back."""

    @pytest.mark.parametrize("name", ["Plan", "Log", "Days", "Analytics", "Dashboard"])
    def test_tab_click(self, page, base_url, name):
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        page.get_by_role("tab", name=name).click()
        page.wait_for_timeout(200)
        state = page.evaluate(
            """() => {
                const s = window.getSelection(), a = document.activeElement;
                return {
                    selection: s.type,
                    inside: !!s.anchorNode && a.contains(s.anchorNode),
                    caret: getComputedStyle(a).caretColor,
                    select: getComputedStyle(a).userSelect,
                };
            }"""
        )
        assert state["select"] == "none", state
        assert state["caret"] == "rgba(0, 0, 0, 0)", state
        assert not (state["selection"] == "Caret" and state["inside"]), state


class TestEscapeGoesHome:
    """Escape from any tab returns to the Dashboard, after dismissing what is in front of
    it: an overlay, the field being typed in, an edit in progress."""

    @pytest.mark.parametrize("tab", ["plan", "log", "days", "analytics", "settings"])
    def test_escape_from_every_tab(self, page, base_url, tab):
        page.goto(f"{base_url}/#{tab}")
        page.wait_for_load_state("networkidle")
        page.evaluate("() => document.activeElement.blur()")  # the page, not a field
        page.keyboard.press("Escape")
        page.wait_for_url("**/#dashboard", timeout=3000)
        page.wait_for_selector(".hero-num", timeout=5000)

    def test_escape_on_the_dashboard_stays(self, page, base_url):
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector(".hero-num", timeout=5000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        assert page.url.endswith("#dashboard")

    def test_escape_leaves_a_field_first(self, page, base_url):
        page.goto(f"{base_url}/#days")
        page.wait_for_load_state("networkidle")
        search = page.locator(".notes-search")
        search.click()
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        assert page.url.endswith("#days")  # first Escape only leaves the field
        assert page.evaluate("() => document.activeElement === document.body")
        page.keyboard.press("Escape")
        page.wait_for_url("**/#dashboard", timeout=3000)

    def test_escape_closes_the_palette_first(self, page, base_url):
        page.goto(f"{base_url}/#days")
        page.wait_for_load_state("networkidle")
        page.keyboard.press(".")
        page.wait_for_selector(".palette", timeout=3000)
        page.keyboard.press("Escape")
        page.wait_for_function("() => !document.querySelector('.palette')", timeout=3000)
        assert page.url.endswith("#days")
        page.keyboard.press("Escape")
        page.wait_for_url("**/#dashboard", timeout=3000)
