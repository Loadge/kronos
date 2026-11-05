"""E2E: every page starts with the same page head (UI_GUIDE.md, "Page anatomy").

The guide says: the title on the left, the controls on the right, and in the controls the page's
own buttons first, then the Employee/Freelance pill, then the year selector. These tests walk
every tab so a new page, or a change to one, cannot quietly put a control somewhere else.
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.e2e

TABS = ["dashboard", "plan", "log", "days", "analytics", "freelance", "settings"]
# the tabs that carry the pill (both sides of the app on one page)
PILL_TABS = ["days", "analytics"]
# the tabs whose head ends with the year selector
YEAR_TABS = ["plan", "log", "days", "analytics", "freelance"]


@pytest.fixture(autouse=True)
def _freelance_source(base_url):
    """The pill and the freelance buttons only exist once an income source does."""
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


@pytest.mark.parametrize("tab", TABS)
def test_every_tab_has_one_page_head_with_title_then_controls(page, base_url, tab):
    _open(page, base_url, tab)
    heads = page.locator("main .page-head")
    assert heads.count() == 1, f"{tab}: {heads.count()} page heads"
    children = heads.first.evaluate("el => [...el.children].map(c => c.className)")
    assert children[0].split()[0] == "page-head-title", (tab, children)
    assert any("page-head-controls" in c for c in children), (tab, children)


@pytest.mark.parametrize("tab", YEAR_TABS)
def test_the_year_selector_is_the_last_control_of_the_head(page, base_url, tab):
    _open(page, base_url, tab)
    ctl = page.locator("main .page-head .page-head-controls")
    # by where each control is drawn, not by its place in the markup (a CSS `order` would move it)
    last = ctl.evaluate(
        "el => { const k = [...el.children].filter(c => c.offsetParent !== null)"
        ".sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);"
        " return k[k.length - 1].className }"
    )
    assert "year-step" in last, (tab, last)


@pytest.mark.parametrize("tab", PILL_TABS)
def test_the_pill_sits_just_before_the_year_and_after_the_page_buttons(page, base_url, tab):
    _open(page, base_url, tab)
    order = page.locator("main .page-head .page-head-controls").evaluate(
        "el => [...el.children].filter(c => c.offsetParent !== null)"
        ".sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left).map(c =>"
        " c.classList.contains('hm-switch') ? 'pill'"
        " : c.classList.contains('head-btn') ? 'btn'"
        " : c.classList.contains('year-all') || c.classList.contains('year-step') ? 'year'"
        " : 'other')"
    )
    assert "pill" in order, (tab, order)
    i = order.index("pill")
    assert all(k in ("btn", "other") for k in order[:i]), (tab, order)  # page buttons first
    assert all(k == "year" for k in order[i + 1 :]), (tab, order)  # then only the year


def test_the_pill_keeps_its_height_between_pages(page, base_url):
    ys = {}
    for tab in PILL_TABS:
        _open(page, base_url, tab)
        ys[tab] = page.locator("main .page-head .hm-switch").bounding_box()["y"]
    assert abs(ys["days"] - ys["analytics"]) < 2, ys


@pytest.mark.parametrize("tab", TABS)
def test_the_controls_end_at_the_right_edge_of_the_head(page, base_url, tab):
    _open(page, base_url, tab)
    head = page.locator("main .page-head").bounding_box()
    ctl = page.locator("main .page-head .page-head-controls").bounding_box()
    assert (head["x"] + head["width"]) - (ctl["x"] + ctl["width"]) < 2, (tab, head, ctl)
