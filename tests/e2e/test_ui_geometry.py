"""E2E: what a person sees in the first second (UI_GUIDE.md, "Look at it").

Tests that read the markup cannot see a label that sits off-centre in its button or a name that
wraps onto two lines: both were found only by eye. These measure the drawn boxes instead, on every
tab, for the controls that carry text.
"""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest

pytestmark = pytest.mark.e2e

TABS = ["dashboard", "plan", "log", "days", "analytics", "freelance", "settings"]

# Controls whose text must sit in the middle of the box and on a single line.
CENTRED = ".head-btn, .btn-action, .seg-toggle button, .year-all, .tabs a"
ONE_LINE = (
    ".head-btn, .btn-action, .seg-toggle button, .year-all, .tabs a, "
    ".settings-group-btn, .year-step-v"
)
# Desktop and phone: the heads wrap on a phone, which is where labels break.
VIEWPORTS = [(1280, 900), (375, 800)]

MEASURE = """
([centred, oneLine]) => {
  const bad = [];
  const text = el => el.innerText.trim().replace(/\\s+/g, ' ');
  const label = el => `${el.className} "${text(el).slice(0, 30)}"`;
  const visible = el => el.offsetParent !== null && el.getBoundingClientRect().width > 0;
  const rangeOf = el => { const r = document.createRange(); r.selectNodeContents(el); return r; };
  for (const el of document.querySelectorAll(centred)) {
    if (!visible(el) || !text(el)) continue;
    const t = rangeOf(el).getBoundingClientRect(), b = el.getBoundingClientRect();
    const dy = (t.top + t.height / 2) - (b.top + b.height / 2);
    const dx = (t.left + t.width / 2) - (b.left + b.width / 2);
    // an emoji can be a few px taller than the letters: allow 2px, compare the middles
    if (Math.abs(dy) > 2 || Math.abs(dx) > 3) {
      bad.push(['off-centre', label(el), Math.round(dx), Math.round(dy)]);
    }
  }
  for (const el of document.querySelectorAll(oneLine)) {
    if (!visible(el) || !text(el)) continue;
    const rects = [...rangeOf(el).getClientRects()].filter(r => r.width > 0);
    const middles = rects.map(r => r.top + r.height / 2);
    if (middles.length && Math.max(...middles) - Math.min(...middles) > 6) {
      bad.push(['wraps', label(el)]);
    }
    if (el.scrollWidth - el.clientWidth > 1) bad.push(['clipped', label(el)]);
  }
  if (document.documentElement.scrollWidth > window.innerWidth + 1) bad.push(['h-scroll', 'page']);
  return bad;
}
"""


@pytest.fixture(autouse=True)
def _freelance_source(base_url):
    """With an income source the pill, the freelance buttons and the Freelance tab all exist."""
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        r = c.post(
            "/api/freelance/sources",
            json={"name": "Local", "hourly_rate": 60, "currency": "EUR"},
        )
        assert r.status_code == 201, r.text
        # a row in the Plan ledger: its table once pushed the whole page past the edge of a phone,
        # which an empty ledger never shows
        soon = [(date.today() + timedelta(days=n)).isoformat() for n in (7, 8, 9)]
        body = {"dates": soon, "day_type": "vacation", "notes": "long weekend"}
        r = c.post("/api/plans", json=body)
        assert r.status_code == 200, r.text
    yield
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        # the sources outlive /api/data, and a leftover one adds the Freelance tab everywhere
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


def _problems(page):
    return page.evaluate(MEASURE, [CENTRED, ONE_LINE])


@pytest.mark.parametrize("width,height", VIEWPORTS)
@pytest.mark.parametrize("tab", TABS)
def test_text_is_centred_and_on_one_line(page, base_url, tab, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/#{tab}")
    page.wait_for_selector("main .page-head", timeout=5000)
    if tab == "settings":
        # the navigation lists the freelance group too: open it so its sections are measured
        # (on a phone the navigation is two dropdowns, not these buttons)
        nav = page.locator(".settings-group-btn", has_text="Freelance")
        if nav.is_visible():
            nav.click()
    page.wait_for_timeout(300)  # let the entry animations settle
    assert _problems(page) == []


@pytest.mark.parametrize("tab", ["settings", "analytics", "freelance"])
def test_labels_survive_larger_text(page, base_url, tab):
    """A stress: a bigger default font (a browser set to "large", or a font with wider emoji)
    must not break a label or a head onto two lines. It passes on this machine with or without
    the Settings nav fix, so it guards the heads more than the nav; the nav fix itself (`nowrap`,
    a wider column) is defensive, because the wrap Miguel saw could not be reproduced here."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{base_url}/#{tab}")
    page.wait_for_selector("main .page-head", timeout=5000)
    page.evaluate("document.documentElement.style.fontSize = '115%'")
    if tab == "settings":
        page.locator(".settings-group-btn", has_text="Freelance").click()
    page.wait_for_timeout(300)
    assert _problems(page) == []


def test_the_measurement_can_fail(page, base_url):
    """A positive control: a button with lopsided padding and a wrapping label must be reported."""
    page.goto(f"{base_url}/#analytics")
    page.wait_for_selector("main .page-head", timeout=5000)
    page.evaluate(
        """() => {
          const a = document.createElement('a');
          a.className = 'head-btn';
          a.textContent = 'Off centre';
          a.style.cssText = 'padding:0 0 14px 0;height:2rem;display:inline-block';
          document.querySelector('.page-head-controls').prepend(a);
          const b = document.createElement('button');
          b.className = 'settings-group-btn';
          b.style.cssText = 'width:40px;white-space:normal';
          b.textContent = 'Two words here';
          document.querySelector('.page-head').after(b);
        }"""
    )
    found = _problems(page)
    assert {p[0] for p in found} == {"off-centre", "wraps", "clipped"}, found


def test_there_is_no_theme_switch_and_no_line_under_the_title(page, base_url):
    # an older version stored "light": it must not bring the light theme back
    page.add_init_script("localStorage.setItem('k-theme', 'light')")
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("main .page-head", timeout=5000)
    assert page.locator("html").get_attribute("data-theme") == "dark"
    assert page.locator("[aria-label*='mode' i]").count() == 0
    assert page.locator(".theme-toggle:not(.settings-btn)").count() == 0
    assert page.locator(".app-header .subtitle").count() == 0
    assert "ahead overall" not in page.locator(".app-header").inner_text()
