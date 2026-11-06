"""E2E: the structure of the header and of each page head, as a screen reader gets it.

An aria snapshot pins what is there, in order, by role and accessible name, on any OS and with no
picture to maintain. "Children: equal" means an extra child fails: this is what catches a line
that comes back under the title, or a control added to a head without a decision.
"""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

YEAR = """
- navigation "{name} year":
  - button "Previous year"
  - text: /\\d{{4}}/
  - button "Next year"
"""

HEADER = """
- /children: equal
- button "Open the year dial"
- heading "Kronos" [level=1]
- text: /v\\d+/
- tablist:
  - /children: equal
  - tab "Dashboard"
  - tab "Plan"
  - tab "Log"
  - tab "Days"
  - tab "Analytics"
  - tab "Freelance"
- button "Keyboard shortcuts"
- button "Settings"
"""

HEADS = {
    "dashboard": """
- /children: equal
- heading "Dashboard" [level=2]
- text: /\\w+, \\w+ \\d+/
""",
    "plan": """
- /children: equal
- heading "Plan" [level=2]
"""
    + YEAR.format(name="Plan"),
    "log": """
- /children: equal
- heading /Log/ [level=2]
- button /Add freelance/
"""
    + YEAR.format(name="Log"),
    "days": """
- /children: equal
- heading "Days" [level=2]
- searchbox "Filter entries by notes"
- button "PDF"
- radiogroup "Days of":
  - /children: equal
  - radio "Employee"
  - radio "Freelance"
- button "All"
"""
    + YEAR.format(name="Days"),
    "analytics": """
- /children: equal
- heading "Analytics" [level=2]
- button "CSV"
- button "JSON"
- button "Freelance CSV"
- button "Payouts CSV"
- radiogroup "Heatmap shows":
  - /children: equal
  - radio "Employee"
  - radio "Freelance"
"""
    + YEAR.format(name="Analytics"),
    "freelance": """
- /children: equal
- heading "Freelance" [level=2]
- button /Freelance options/
- button "Freelance CSV"
- button "Payouts CSV"
"""
    + YEAR.format(name="Freelance"),
    "settings": """
- /children: equal
- heading /Settings/ [level=2]
""",
}


@pytest.fixture(autouse=True)
def _freelance_source(base_url):
    """The pill, the freelance buttons and the sixth tab exist once an income source does."""
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        r = c.post(
            "/api/freelance/sources",
            json={"name": "Local", "hourly_rate": 60, "currency": "EUR"},
        )
        assert r.status_code == 201, r.text
    yield
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        # the sources outlive /api/data, and a leftover one adds the Freelance tab everywhere
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


def _open(page, base_url, tab):
    page.goto(f"{base_url}/#{tab}")
    page.wait_for_selector("main .page-head", timeout=5000)


def test_the_app_header(page, base_url):
    _open(page, base_url, "analytics")
    expect(page.locator("header.app-header")).to_match_aria_snapshot(HEADER)


@pytest.mark.parametrize("tab", list(HEADS))
def test_the_head_of_each_page(page, base_url, tab):
    _open(page, base_url, tab)
    expect(page.locator("main .page-head")).to_match_aria_snapshot(HEADS[tab])


def test_an_extra_child_fails(page, base_url):
    """A positive control: the snapshot really does refuse something it was not told about."""
    _open(page, base_url, "dashboard")
    page.evaluate(
        "document.querySelector('.brand-line').insertAdjacentHTML('afterend', '<p>an extra</p>')"
    )
    with pytest.raises(AssertionError):
        expect(page.locator("header.app-header")).to_match_aria_snapshot(HEADER, timeout=1000)
