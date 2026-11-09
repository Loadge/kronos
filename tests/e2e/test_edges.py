"""E2E: the edges of the app: the security policy, the banner for a server out of reach, the
year dial's own address and the page for a wrong address."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx
import pytest

from .conftest import HASH_OF

pytestmark = pytest.mark.e2e

ARTIFACTS = Path(__file__).resolve().parents[2] / ".artifacts"
BANNER = ".net-banner"
TEXT = "Kronos can't reach the server. Changes won't be saved until it's back."

# Every violation of the Content-Security-Policy lands in window.__csp (the page's own handler is
# not needed: the event is dispatched on the document).
WATCH_CSP = """
window.__csp = [];
document.addEventListener('securitypolicyviolation', e => {
  window.__csp.push(`${e.violatedDirective} ${e.blockedURI || 'inline'} ${e.sample || ''}`);
});
"""

TABS = ["dashboard", "plan", "log", "days", "analytics", "freelance", "settings"]


def _violations(page):
    return page.evaluate("() => window.__csp")


# ── the security policy, with the whole app open under it ───────────────────────────────────


@pytest.fixture
def csp_page(page):
    page.add_init_script(WATCH_CSP)
    return page


@pytest.fixture
def freelance_source(base_url):
    """With an income source the Freelance tab exists, and the sweep opens it too."""
    with httpx.Client(base_url=base_url) as c:
        r = c.post(
            "/api/freelance/sources", json={"name": "Local", "hourly_rate": 60, "currency": "EUR"}
        )
        assert r.status_code == 201, r.text
        yield
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


def test_no_screen_breaks_the_content_security_policy(csp_page, base_url, freelance_source):
    page = csp_page
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("main .page-head", timeout=5000)

    for tab in TABS:
        page.evaluate(f"location.hash = '{HASH_OF.get(tab, tab)}'")
        page.wait_for_function(
            "t => document.querySelector('.tabs [aria-selected=true]')?.textContent.toLowerCase()"
            ".includes(t) || t === 'settings'",
            arg={"log": "day", "days": "wee", "analytics": "yea"}.get(
                tab, tab[:3] if tab != "settings" else tab
            ),
            timeout=5000,
        )
        page.wait_for_timeout(250)
        assert not _violations(page), (tab, _violations(page))

    # Settings: every group of its navigation
    page.evaluate("location.hash = 'settings'")
    page.wait_for_selector(".settings-group-btn", timeout=5000)
    groups = page.locator(".settings-group-btn")
    for i in range(groups.count()):
        groups.nth(i).click()
        page.wait_for_timeout(150)
        assert not _violations(page), ("settings group", i, _violations(page))

    # the command palette and the year dial
    page.keyboard.press("Escape")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.keyboard.press(".")
    page.wait_for_selector(".palette", timeout=3000)
    assert not _violations(page), ("palette", _violations(page))
    page.keyboard.press("Escape")
    page.keyboard.press("k")
    page.wait_for_selector("#yd [data-yd=stage]", timeout=8000)
    page.wait_for_timeout(300)
    assert not _violations(page), ("dial", _violations(page))
    page.keyboard.press("Escape")


@pytest.mark.parametrize("path", ["/timesheet", "/timesheet/freelance"])
def test_a_timesheet_works_under_the_policy(csp_page, base_url, path):
    """The sheets had inline handlers and an inline script: their switches, their print button and
    the scroll they keep across a reload now come from /static/timesheet.js."""
    page = csp_page
    page.goto(f"{base_url}{path}?today=2026-11-04")
    page.wait_for_selector("#ts-form", timeout=5000)
    assert not _violations(page), _violations(page)

    page.evaluate("window.print = () => { window.__printed = true; }")
    page.locator("[data-print]").click()
    assert page.evaluate("window.__printed") is True

    # a switch reloads the page with its parameter: the delegated handler runs
    with page.expect_navigation():
        page.locator("label:has(input[name=hours][value=hm])").click()
    assert "hours=hm" in page.url
    assert not _violations(page), _violations(page)


def test_the_policy_check_can_fail(csp_page, base_url):
    """A positive control: the policy forbids inline scripts, and the sweep must see one."""
    page = csp_page
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("main .page-head", timeout=5000)
    assert not _violations(page)
    page.evaluate(
        "() => { const s = document.createElement('script'); s.textContent = 'window.__x = 1';"
        " document.head.append(s); }"
    )
    page.wait_for_timeout(100)
    assert _violations(page) and "script-src" in _violations(page)[0]
    assert page.evaluate("window.__x") is None


# ── the banner ──────────────────────────────────────────────────────────────────────────────


def _banner_visible(page) -> bool:
    return page.locator(BANNER).is_visible()


def test_going_offline_shows_the_banner_and_coming_back_hides_it(page, base_url):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("main .page-head", timeout=5000)
    assert not _banner_visible(page)

    page.context.set_offline(True)
    page.wait_for_selector(BANNER, state="visible", timeout=3000)
    assert page.locator(BANNER).get_attribute("role") == "status"
    assert page.locator(BANNER).inner_text().startswith(TEXT)
    assert page.get_by_role("button", name="Try again").is_visible()
    # under the header, in the flow
    header = page.locator(".app-header").bounding_box()
    banner = page.locator(BANNER).bounding_box()
    assert banner["y"] >= header["y"] + header["height"] - 1
    ARTIFACTS.mkdir(exist_ok=True)
    page.wait_for_timeout(500)  # let it settle in
    page.screenshot(path=str(ARTIFACTS / "p55-offline-1280.png"))

    page.context.set_offline(False)
    page.wait_for_selector(BANNER, state="hidden", timeout=3000)


def test_the_banner_on_a_phone_never_covers_the_tab_bar_or_the_log_dock(page, base_url):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(f"{base_url}/#days")
    page.wait_for_selector(".log-col-rail", timeout=5000)
    page.context.set_offline(True)
    page.wait_for_selector(BANNER, state="visible", timeout=3000)
    page.wait_for_timeout(500)
    banner = page.locator(BANNER).bounding_box()
    tabs = page.locator(".tabs").bounding_box()
    dock = page.locator(".log-col-rail").bounding_box()
    assert banner["y"] + banner["height"] <= min(tabs["y"], dock["y"]) + 1
    # what a finger meets at the middle of the tab bar and of the dock is theirs, not the banner's
    for box, selector in ((tabs, ".tabs"), (dock, ".log-col-rail")):
        hit = page.evaluate(
            "([x, y, sel]) => !!document.elementFromPoint(x, y)?.closest(sel)",
            [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, selector],
        )
        assert hit, selector
    page.screenshot(path=str(ARTIFACTS / "p55-offline-375.png"))
    page.context.set_offline(False)
    page.wait_for_selector(BANNER, state="hidden", timeout=3000)


def test_a_request_that_never_arrives_shows_it_and_the_next_one_that_does_hides_it(page, base_url):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("main .page-head", timeout=5000)
    assert not _banner_visible(page)

    # the network drops the requests of the Days tab: fetch throws, there is no HTTP error
    page.route("**/api/**", lambda route: route.abort("connectionreset"))
    page.evaluate("location.hash = 'plan'")
    page.wait_for_selector(BANNER, state="visible", timeout=5000)

    # the network is back; the next request that arrives hides it, by itself
    page.unroute("**/api/**")
    page.evaluate("location.hash = 'analytics'")
    page.wait_for_selector(BANNER, state="hidden", timeout=5000)


def test_try_again_asks_the_server_and_keeps_the_banner_while_it_is_gone(page, base_url):
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("main .page-head", timeout=5000)
    page.route("**/api/**", lambda route: route.abort("connectionreset"))
    page.evaluate("location.hash = 'plan'")
    page.wait_for_selector(BANNER, state="visible", timeout=5000)

    page.get_by_role("button", name="Try again").click()
    page.wait_for_timeout(400)
    assert _banner_visible(page)  # asked, and still nobody there

    page.unroute("**/api/**")
    page.get_by_role("button", name="Try again").click()
    page.wait_for_selector(BANNER, state="hidden", timeout=3000)


def test_an_http_error_is_not_a_missing_server(page, base_url):
    """A 500 means the server answered: the banner is for the network, not for errors."""
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("main .page-head", timeout=5000)
    page.route(
        "**/api/entries**",
        lambda route: route.fulfill(status=500, json={"detail": "boom"}),
    )
    page.evaluate("location.hash = 'days'")
    page.wait_for_selector(".error-banner", state="visible", timeout=5000)
    assert not _banner_visible(page)


# ── the dial has its own address ────────────────────────────────────────────────────────────


def test_the_dial_shortcut_opens_the_dial_and_leaves_the_address_clean(page, base_url):
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{base_url}/#dial")
    page.wait_for_selector("#yd [data-yd=stage]", timeout=8000)
    assert "#dial" not in page.url
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.getElementById('yd')", timeout=3000)
    assert page.evaluate("location.hash") == "#dashboard"
    # the app is the Dashboard behind it, as after any other way in
    assert page.locator(".tabs [aria-selected=true]").inner_text().strip().startswith("Dashboard")


def test_the_dial_address_works_in_a_page_that_is_already_open(page, base_url):
    """An installed app that is running gets the shortcut as a hash change, not a reload."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{base_url}/#weeks")
    page.wait_for_selector("main .page-head", timeout=5000)
    page.evaluate("location.hash = 'dial'")
    page.wait_for_selector("#yd [data-yd=stage]", timeout=8000)
    assert page.evaluate("location.hash") == "#weeks"
    page.wait_for_timeout(400)  # its keys are bound once it has drawn
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.getElementById('yd')", timeout=3000)


# ── the page for a wrong address ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("width,height", [(1280, 800), (375, 800)])
def test_a_wrong_address_shows_the_page_and_the_button_goes_home(page, base_url, width, height):
    page.set_viewport_size({"width": width, "height": height})
    response = page.goto(f"{base_url}/nope/not/here")
    assert response.status == 404
    assert page.get_by_role("heading", name="This page isn't on the dial").is_visible()
    assert page.locator(".nf-logo").is_visible()
    assert page.locator(".nf-line").is_visible()
    ARTIFACTS.mkdir(exist_ok=True)
    page.wait_for_timeout(1800)  # the logo's swing is over
    page.screenshot(path=str(ARTIFACTS / f"p55-404-{width}.png"))

    back = page.get_by_role("button", name="Back to Kronos")
    assert back.get_attribute("href") == "/"
    back.click()
    page.wait_for_selector("main .page-head", timeout=5000)
    assert urlparse(page.url).path == "/"
