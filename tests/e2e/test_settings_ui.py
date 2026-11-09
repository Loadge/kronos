"""E2E: Settings follows the shared page rules.

The two lives wear their marks in the settings navigation (sidebar and phone dropdowns), the
empty states are one short line, and the secondary openers are outline buttons.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.e2e


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")
        for t in c.get("/api/templates").json():
            c.delete(f"/api/templates/{t['id']}")


@pytest.fixture(autouse=True)
def _clean(base_url):
    _wipe(base_url)
    yield
    _wipe(base_url)


def _open_settings(page, base_url: str) -> None:
    page.goto(f"{base_url}/#settings")
    page.evaluate("localStorage.removeItem('k-settings-group')")
    page.reload()
    page.wait_for_selector(".settings-group-btn", timeout=5000)


class TestSettingsUiConsistency:
    def test_the_group_entries_wear_their_marks(self, page, base_url):
        _open_settings(page, base_url)
        texts = [t.strip() for t in page.locator(".settings-group-btn").all_inner_texts()]
        assert texts == ["👔 Employee", "⚡ Freelance", "🧰 General"]
        # the emoji are decoration: the accessible name stays Employee / Freelance / General
        marks = page.locator(".settings-group-btn span[aria-hidden='true']").all_inner_texts()
        assert [m for m in marks if m] == ["👔", "⚡", "🧰"]
        assert page.get_by_role("button", name="Employee", exact=True).count() == 1
        assert page.get_by_role("button", name="Freelance", exact=True).count() == 1
        assert page.get_by_role("button", name="General", exact=True).count() == 1

    def test_the_phone_dropdown_wears_them_too(self, page, base_url):
        page.set_viewport_size({"width": 375, "height": 800})
        page.goto(f"{base_url}/#settings")
        page.wait_for_selector(".settings-dropdowns select", timeout=5000)
        options = page.locator(".settings-dropdowns select").first.locator("option")
        assert [t.strip() for t in options.all_inner_texts()] == [
            "👔 Employee",
            "⚡ Freelance",
            "🧰 General",
        ]

    def test_empty_states_and_openers(self, page, base_url):
        _open_settings(page, base_url)
        page.wait_for_selector("#settings-templates", timeout=5000)
        empty = page.locator("#settings-templates .settings-empty")
        assert empty.inner_text().strip() == "No templates yet. Save one in Days"
        empty.locator("a", has_text="Save one in Days").click()
        page.wait_for_url("**/#days", timeout=3000)
        page.goto(f"{base_url}/#settings")
        page.wait_for_selector("#settings-templates", timeout=5000)
        # "+ Add a change" is an outline opener, not the old ghost button
        page.locator(".target-schedule summary").click()
        opener = page.locator(".target-schedule-actions button", has_text="Add a change")
        classes = opener.get_attribute("class").split()
        assert {"secondary", "outline", "compact"} <= set(classes)
        assert "btn-action-ghost" not in classes
        # sources: one line and a link that lands on the form
        page.locator(".settings-group-btn", has_text="Freelance").click()
        page.wait_for_selector("#settings-sources", timeout=3000)
        empty = page.locator("#settings-sources .settings-empty")
        assert empty.inner_text().strip() == "No sources yet. Add one."
        empty.locator("a", has_text="Add one").click()
        assert page.evaluate("document.activeElement.getAttribute('aria-label')") == "Source name"
