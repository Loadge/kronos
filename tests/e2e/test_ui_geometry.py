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
CENTRED = ".head-btn, .btn-action, .seg-toggle button, .year-all, .tabs a, .bz-btn"
ONE_LINE = (
    ".head-btn, .btn-action, .seg-toggle button, .year-all, .tabs a, "
    ".settings-group-btn, .year-step-v, .wk-tag, .wk-now, .wk-range, "
    ".week-sep-name, .week-sep-range, .ws-days, .ws-net, .ws-target, .ws-delta, .ws-sigma, "
    ".bz-count, .dr-tick b, .dr-tag-big"
)
# Desktop and phone: the heads wrap on a phone, which is where labels break.
VIEWPORTS = [(1280, 900), (375, 800)]

# What a finger must be able to hit: 24px each way (WCAG 2.2, target size minimum). Inline links in
# a sentence are exempt, so they are not in this list.
TAPPABLE = "button, select, input, [role=tab], a[role=button]"
TAP_MIN = 24

MEASURE = """
([centred, oneLine, tappable, tapMin, phone]) => {
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
  if (phone) {
    for (const el of document.querySelectorAll(tappable)) {
      if (!visible(el) || el.type === 'hidden' || el.closest('.visually-hidden')) continue;
      const b = el.getBoundingClientRect();
      if (b.width < tapMin - 0.5 || b.height < tapMin - 0.5) {
        const size = `${Math.round(b.width)}x${Math.round(b.height)}`;
        const name = el.getAttribute('aria-label') || el.getAttribute('placeholder') || '';
        const home = el.parentElement ? el.parentElement.className : '';
        const what = `${el.tagName.toLowerCase()} ${label(el)} ${name} in ${home}`;
        bad.push(['tap-small', what, size]);
      }
    }
    for (const el of document.querySelectorAll('.days-wrap')) {
      if (visible(el) && el.scrollWidth > el.clientWidth + 1) bad.push(['inner-scroll', label(el)]);
    }
  }
  return bad;
}
"""


def _seed_days(c: httpx.Client) -> None:
    """Rows for the Days tables: a worked day with breaks and a long note, a vacation day, and
    freelance blocks in euros and dollars. An empty table never shows a row that is too wide."""
    sources = {s["name"]: s["id"] for s in c.get("/api/freelance/sources").json()}
    local = sources["Local"]
    r = c.post(
        "/api/freelance/sources",
        json={"name": "Northwind overseas", "hourly_rate": 70, "currency": "USD"},
    )
    assert r.status_code == 201, r.text
    overseas = r.json()["id"]
    note = {"notes": "Evening call, then the invoice"}
    day, made = date.today(), 0
    while made < 6:
        day -= timedelta(days=1)
        if day.weekday() >= 5 or day.year != date.today().year:
            continue
        body = {"date": day.isoformat(), "day_type": "work"}
        if made == 3:
            body["day_type"] = "vacation"
        else:
            body |= {"start_time": "09:30", "end_time": "18:00", "breaks": [{"break_minutes": 60}]}
        if made == 0:
            body["notes"] = "Dentist at eleven, then the long review with the whole team"
        r = c.post("/api/entries", json=body)
        assert r.status_code == 201, r.text
        if made < 2:
            blocks = [
                {"source_id": local, "start_time": "19:00", "end_time": "21:00"} | note,
                {"source_id": overseas, "hours": 1.5, "fx_rate": 1.1},
            ]
            for block in blocks:
                r = c.post("/api/freelance/blocks", json={"date": day.isoformat()} | block)
                assert r.status_code == 201, r.text
        made += 1


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
        _seed_days(c)
    yield
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        # the sources outlive /api/data, and a leftover one adds the Freelance tab everywhere
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


def _problems(page):
    phone = page.viewport_size["width"] <= 640
    return page.evaluate(MEASURE, [CENTRED, ONE_LINE, TAPPABLE, TAP_MIN, phone])


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
    assert not (found := _problems(page)), "\n".join(map(str, found))


@pytest.mark.parametrize("state", ["open", "collapsed"])
@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_days_freelance_fits_with_every_week_open(page, base_url, width, height, state):
    """The ⚡ table has its own rows (month, week, source lines, blocks): open them all."""
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/#days")
    page.wait_for_selector("main .page-head", timeout=5000)
    page.get_by_role("radio", name="Freelance").click()
    page.wait_for_selector(".bz-strip", timeout=5000)  # the bezel is part of what is measured
    if state == "open":
        # the week of today may be the only one: then it is open already and `+` is aria-disabled
        page.get_by_test_id("wk-expand-all").click(force=True)
        page.wait_for_selector(".days-table--fl tr.blk", timeout=5000)
    else:  # the week lines alone: they are the page now
        page.get_by_test_id("wk-collapse-all").click(force=True)
        page.wait_for_selector(".days-table--fl .wk-main", timeout=5000)
        assert not page.locator(".days-table--fl tr.blk").count()
    page.wait_for_timeout(300)
    assert not (found := _problems(page)), "\n".join(map(str, found))


@pytest.mark.parametrize("state", ["open", "collapsed"])
@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_days_employee_fits_with_every_week_open_and_collapsed(
    page, base_url, width, height, state
):
    """The Employee table has a line per week: measure it with the days shown and hidden."""
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/#days")
    page.wait_for_selector("main .page-head", timeout=5000)
    page.wait_for_selector(".days-table tr.week-sep", timeout=5000)
    page.wait_for_selector(".bz-strip", timeout=5000)  # the bezel is part of what is measured
    # forced: the seed walks back from today, so in early January a button may have nothing to do
    if state == "open":
        page.get_by_test_id("wk-expand-all").click(force=True)
        page.wait_for_selector(".days-table tr.day-row", timeout=5000)
    else:
        page.get_by_test_id("wk-collapse-all").click(force=True)
        page.wait_for_function("() => !document.querySelector('.days-table tr.day-row')")
    page.wait_for_timeout(300)
    assert not (found := _problems(page)), "\n".join(map(str, found))


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
    assert not (found := _problems(page)), "\n".join(map(str, found))


def test_the_measurement_can_fail(page, base_url):
    """A positive control: a button with lopsided padding and a wrapping label must be reported."""
    page.set_viewport_size({"width": 1280, "height": 900})
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


@pytest.mark.parametrize("freelance", [False, True], ids=["employee", "freelance"])
def test_a_bezel_count_that_wraps_is_reported(page, base_url, freelance):
    """A positive control for the bezel's chip: its count on two lines must be reported."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{base_url}/#days")
    page.wait_for_selector("main .page-head", timeout=5000)
    if freelance:
        page.get_by_role("radio", name="Freelance").click()
    page.wait_for_selector(".bz-count", timeout=5000)
    page.wait_for_timeout(300)
    assert not (found := _problems(page)), "\n".join(map(str, found))
    page.add_style_tag(content=".bz-count { white-space: normal; width: 3ch; overflow: hidden; }")
    page.wait_for_timeout(100)
    assert {p[0] for p in _problems(page)} & {"wraps", "clipped"}


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_a_day_ribbon_label_that_wraps_is_reported(page, base_url, width, height):
    """A positive control for the day ribbon's ruler: a label on two lines must be reported. The
    tag a drag floats over the ribbon is measured too (it only exists while a handle moves)."""
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/#log")
    page.wait_for_selector(".dr-tick b", timeout=5000)
    page.wait_for_timeout(300)
    assert page.locator(".dr-tick b").evaluate_all("l => l.filter(e => e.offsetParent).length") >= 4
    page.locator(".dr-grip--end").scroll_into_view_if_needed()
    box = page.locator(".dr-grip--end").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] / 2 + 12, box["y"] + box["height"] / 2, steps=4)
    page.wait_for_selector(".dr-tag-big", timeout=3000)
    assert not (found := _problems(page)), "\n".join(map(str, found))
    page.mouse.up()
    page.add_style_tag(content=".dr-tick b { white-space: normal; width: 1ch; overflow: hidden; }")
    page.wait_for_timeout(100)
    assert {p[0] for p in _problems(page)} & {"wraps", "clipped"}


def test_the_phone_checks_can_fail(page, base_url):
    """A positive control for the two checks that only run on a phone: a 14px button must be
    reported as `tap-small`, and a table wider than its wrap as `inner-scroll`."""
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(f"{base_url}/#analytics")
    page.wait_for_selector("main .page-head", timeout=5000)
    page.wait_for_timeout(300)
    assert not (found := _problems(page)), "\n".join(map(str, found))
    page.evaluate(
        """() => {
          const b = document.createElement('button');
          b.style.cssText = 'width:14px;height:14px;padding:0;margin:0;display:block';
          document.querySelector('.page-head').after(b);
          const w = document.createElement('div');
          w.className = 'days-wrap';
          w.style.cssText = 'overflow-x:auto;width:100px';
          w.innerHTML = '<div style="width:300px;height:10px"></div>';
          document.querySelector('.page-head').after(w);
        }"""
    )
    found = {p[0] for p in _problems(page)}
    assert {"tap-small", "inner-scroll"} <= found, found


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
