# ruff: noqa: E501, F811
"""E2E: what a person sees in the first second (UI_GUIDE.md, "Look at it").

Tests that read the markup cannot see a label that sits off-centre in its button or a name that
wraps onto two lines: both were found only by eye. These measure the drawn boxes instead, on every
tab, for the controls that carry text.
"""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest

from .conftest import HASH_OF, OPEN_ALL_WEEKS
from .test_payout_chain_cell import (  # noqa: F401  (a server with an ECB: a payout has a chip)
    _wipe,
    chain_url,
)

pytestmark = pytest.mark.e2e

TABS = ["dashboard", "plan", "log", "days", "analytics", "freelance", "settings"]

# Controls whose text must sit in the middle of the box and on a single line.
CENTRED = (
    ".head-btn, .btn-action, .seg-toggle button, .year-all, .tabs a, .bz-btn, .q-chip, "
    ".net-banner-retry, .nf-back, .fl-wait-chip, .fl-wait-save, .fx-chip, .dial-tile-key"
)
# A tab is an icon over a label on a phone: it is the label that has to stay on one line
ONE_LINE = (
    ".head-btn, .btn-action, .seg-toggle button, .year-all, .tab-label, "
    ".settings-group-btn, .year-step-v, .wk-tag, .wk-now, .wk-range, "
    ".week-sep-name, .week-sep-range, .ws-days, .ws-net, .ws-target, .ws-delta, .ws-sigma, "
    ".bz-count, .dr-tick b, .dr-tag-big, .net-banner-retry, .nf-back, .fl-wait-chip, "
    ".fl-wait-save, "
    ".fx-chip, .dial-tile-day, .dial-tile-sub, .dial-tile-go, .calc-p .fl-lbl, .q-tip li"
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
    page.goto(f"{base_url}/#{HASH_OF.get(tab, tab)}")
    page.wait_for_selector("main .page-head", timeout=5000)
    if tab == "settings":
        # the navigation lists the freelance group too: open it so its sections are measured
        # (on a phone the navigation is two dropdowns, not these buttons)
        nav = page.locator(".settings-group-btn", has_text="Freelance")
        if nav.is_visible():
            nav.click()
    page.wait_for_timeout(300)  # let the entry animations settle
    assert not (found := _problems(page)), "\n".join(map(str, found))


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_the_offline_banner_fits(page, base_url, width, height):
    """The banner for a server out of reach: its text on its own lines, the button centred and
    tappable, nothing past the edge of the page."""
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("main .page-head", timeout=5000)
    page.context.set_offline(True)
    try:
        page.wait_for_selector(".net-banner", state="visible", timeout=3000)
        page.wait_for_timeout(500)  # it slides in
        assert page.locator(".net-banner-retry").is_visible()
        assert not (found := _problems(page)), "\n".join(map(str, found))
    finally:
        page.context.set_offline(False)


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_the_page_for_a_wrong_address_fits(page, base_url, width, height):
    page.set_viewport_size({"width": width, "height": height})
    assert page.goto(f"{base_url}/nope").status == 404
    page.wait_for_selector(".nf-back", timeout=5000)
    page.wait_for_timeout(1800)  # the logo's swing is over
    assert not (found := _problems(page)), "\n".join(map(str, found))
    # nothing scrolls: the page is one screen
    assert page.evaluate("document.documentElement.scrollHeight <= window.innerHeight + 1")


@pytest.mark.parametrize("state", ["open", "collapsed"])
@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_days_freelance_fits_with_every_week_open(page, base_url, width, height, state):
    """The ⚡ table has its own rows (month, week, source lines, blocks): open them all."""
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/#weeks")
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
    page.goto(f"{base_url}/#weeks")
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
    page.goto(f"{base_url}/#{HASH_OF.get(tab, tab)}")
    page.wait_for_selector("main .page-head", timeout=5000)
    page.evaluate("document.documentElement.style.fontSize = '115%'")
    if tab == "settings":
        page.locator(".settings-group-btn", has_text="Freelance").click()
    page.wait_for_timeout(300)
    assert not (found := _problems(page)), "\n".join(map(str, found))


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_the_waiting_row_and_the_help_fit(page, base_url, width, height):
    """Payouts waiting (chips, amount, account, Save) and the day bar's help: one line of text each,
    centred, nothing clipped, nothing past the edge."""
    with httpx.Client(base_url=base_url) as c:
        src = c.get("/api/freelance/sources").json()[0]["id"]
        monday = date.today() - timedelta(days=date.today().weekday() + 14)
        for i in range(8):  # more than six weeks: the "+N" link is measured too
            day = monday - timedelta(days=7 * i)
            r = c.post(
                "/api/freelance/blocks",
                json={"date": day.isoformat(), "source_id": src, "hours": 2},
            )
            assert r.status_code == 201, r.text
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/#days")
    page.wait_for_selector("[data-testid=pay-wait]", timeout=5000)
    page.locator(".log-form-card .q-chip").click()
    page.wait_for_selector(".q-tip", state="visible")
    page.wait_for_timeout(300)
    assert page.locator("[data-testid=pay-wait-more]").inner_text().startswith("+")
    assert not (found := _problems(page)), "\n".join(map(str, found))


def test_the_measurement_can_fail(page, base_url):
    """A positive control: a button with lopsided padding and a wrapping label must be reported."""
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{base_url}/#year")
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
    page.goto(f"{base_url}/#weeks")
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
    page.goto(f"{base_url}/#days")
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
    page.goto(f"{base_url}/#year")
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


# ── the dotted handle of Settings (Day templates, Income sources, Accounts) ──────
HANDLE_WIDTHS = [(1280, 900), (900, 900), (700, 900), (375, 800), (320, 700)]
LONG_NAME = "Quarterly retainer for the long named client"[:40]
assert len(LONG_NAME) == 40
SHORT_NAMES = {"Early shift", "Standard day", "Bench", "Deutsche Bank"}

MEASURE_HANDLES = """
() => {
  const visible = el => el.offsetParent !== null && el.getBoundingClientRect().width > 0;
  const linesOf = el => {
    const r = document.createRange(); r.selectNodeContents(el);
    const mids = [...r.getClientRects()].filter(x => x.width > 0)
      .map(x => x.top + x.height / 2).sort((a, b) => a - b);
    return mids.length ? 1 + mids.slice(1).filter((m, i) => m - mids[i] > 6).length : 0;
  };
  const grips = [...document.querySelectorAll('.grip')].filter(visible).map(g => {
    const b = g.getBoundingClientRect(), s = g.querySelector('svg').getBoundingClientRect();
    return { name: g.getAttribute('aria-label'), w: b.width, h: b.height,
      dx: (s.left + s.width / 2) - (b.left + b.width / 2),
      dy: (s.top + s.height / 2) - (b.top + b.height / 2) };
  });
  const rows = '.sort-list > .template-item, .sort-list > .src-item';
  const names = [...document.querySelectorAll(rows)].filter(visible)
    .map(r => { const n = r.querySelector('strong'); return [n.textContent.trim(), linesOf(n)]; });
  const heights = [...document.querySelectorAll(rows)].filter(visible)
    .map(r => r.getBoundingClientRect().height);
  const hscroll = document.documentElement.scrollWidth - window.innerWidth;
  return { grips, names, heights, hscroll };
}
"""


def _seed_orderable(c: httpx.Client) -> None:
    """The three lists with rows, one of them a name of forty characters."""
    for name in ("Early shift", "Standard day", LONG_NAME):
        body = {"name": name, "start_time": "09:00", "end_time": "17:00", "breaks": []}
        assert c.post("/api/templates", json=body).status_code == 201
    for name in ("Bench", LONG_NAME):
        body = {"name": name, "hourly_rate": 40, "currency": "EUR"}
        assert c.post("/api/freelance/sources", json=body).status_code == 201
    for name in ("Deutsche Bank", LONG_NAME, "Old savings"):
        r = c.post(
            "/api/freelance/accounts", json={"name": name, "currency": "EUR", "kind": "bank"}
        )
        assert r.status_code == 201
    old = r.json()["id"]
    assert c.put(f"/api/freelance/accounts/{old}", json={"archived": True}).status_code == 200


@pytest.fixture
def orderable(base_url):
    with httpx.Client(base_url=base_url) as c:
        # the lists start empty: an account or a template another module of this worker left behind
        # would be one more row than the audits count
        c.delete("/api/data")
        for kind in ("/api/freelance/sources", "/api/freelance/accounts", "/api/templates"):
            for row in c.get(kind).json():
                c.delete(f"{kind}/{row['id']}")
        _seed_orderable(c)
    yield
    with httpx.Client(base_url=base_url) as c:
        for kind in ("/api/templates", "/api/freelance/accounts"):
            for row in c.get(kind).json():
                c.delete(f"{kind}/{row['id']}")


def _open_settings_group(page, base_url, width, height, group):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/#settings")
    page.wait_for_selector("main .page-head", timeout=5000)
    page.evaluate(f"() => Alpine.$data(document.querySelector('main')).setSettingsGroup('{group}')")
    page.wait_for_selector(".grip", timeout=5000)
    page.wait_for_timeout(400)  # the group's entry animation


def _expected_handles(base_url, group):
    """One handle per row that can move: every template; every source and every live account."""
    with httpx.Client(base_url=base_url) as c:
        if group == "employee":
            return len(c.get("/api/templates").json())
        accounts = [a for a in c.get("/api/freelance/accounts").json() if not a["archived"]]
        return len(c.get("/api/freelance/sources").json()) + len(accounts)


def _handle_problems(page, width, expected):
    found = page.evaluate(MEASURE_HANDLES)
    bad = []
    if len(found["grips"]) != expected:
        bad.append(("handles drawn", len(found["grips"]), expected))
    min_w, min_h = (30, 38) if width <= 375 else (24, 24)
    for g in found["grips"]:
        if g["w"] < min_w - 0.5 or g["h"] < min_h - 0.5:
            bad.append(("handle too small", g["name"], round(g["w"], 1), round(g["h"], 1)))
        if abs(g["dx"]) > 2 or abs(g["dy"]) > 2:
            bad.append(("icon off-centre", g["name"], round(g["dx"], 1), round(g["dy"], 1)))
    with_handle = found["names"]
    # how tall each row is when the handle keeps its width and has no height: the room it takes
    # sideways may wrap a long name, in one font and not in another, and that is not its height
    flat = page.add_style_tag(
        content=".grip, .grip-gap { height: 0 !important; min-height: 0 !important;"
        " margin-block: 0 !important; overflow: hidden !important; }"
    )
    flat_heights = page.evaluate(MEASURE_HANDLES)["heights"]
    flat.evaluate("el => el.remove()")
    # what the names took before there was a handle: the same page with the handle taken out
    page.add_style_tag(content=".grip, .grip-gap { display: none !important; }")
    page.wait_for_timeout(100)
    baseline = page.evaluate(MEASURE_HANDLES)
    before = baseline["names"]
    assert [n for n, _ in with_handle] == [n for n, _ in before]
    # the page does not scroll sideways at any width, 320 included
    if found["hscroll"] > 1:
        bad.append(("h-scroll", found["hscroll"]))
    if width == 1280:  # the handle may not make a row taller on a desktop
        pairs = zip(with_handle, found["heights"], flat_heights, strict=True)
        for (name, _), tall, plain in pairs:
            if abs(tall - plain) > 1:
                bad.append(("row taller with the handle", name, round(plain, 1), round(tall, 1)))
    for (name, now), (_, was) in zip(with_handle, before, strict=True):
        # a name of forty characters, in a font as wide as Linux's, loses its line to the 42px the
        # handle takes below 1280 (accepted); at 1280 it keeps it, and every short name always does
        if now > was and not (name == LONG_NAME[:40] and width < 1280):
            bad.append(("name wraps more", name, was, now))
        if name in SHORT_NAMES and width >= 700 and now != 1:
            bad.append(("short name on several lines", name, now))
    return bad


@pytest.mark.parametrize("group", ["employee", "freelance"])
@pytest.mark.parametrize("width,height", HANDLE_WIDTHS)
def test_the_handles_fit_their_rows(page, base_url, orderable, width, height, group):
    """The handle of a list row: big enough to hit, its dots in the middle, nothing sideways, and no
    name on more lines than it took before the handle."""
    _open_settings_group(page, base_url, width, height, group)
    expected = _expected_handles(base_url, group)
    assert not (found := _handle_problems(page, width, expected)), "\n".join(map(str, found))


@pytest.mark.parametrize("width,height", [(1280, 900), (375, 800)])
def test_the_handle_audit_can_fail(page, base_url, orderable, width, height):
    """A positive control: a handle 14px wide must be reported."""
    _open_settings_group(page, base_url, width, height, "freelance")
    page.add_style_tag(
        content="button.grip, .settings-card button.grip { width: 14px !important; }"
    )
    page.wait_for_timeout(100)
    expected = _expected_handles(base_url, "freelance")
    assert {p[0] for p in _handle_problems(page, width, expected)} >= {"handle too small"}


# ── the four boxes of accounts of an income source (Settings > Freelance) ──────────────────────────
BOX_ACCOUNTS = [
    ("Deutsche Bank", "bank"),
    (LONG_NAME, "wallet"),
    ("Cash box", "cash"),
    ("Kraken", "other"),
]

MEASURE_BOXES = """
(minBox) => {
  const bad = [];
  const visible = el => el.offsetParent !== null && el.getBoundingClientRect().width > 0;
  const mid = r => r.top + r.height / 2;
  const textRect = el => { const g = document.createRange(); g.selectNodeContents(el); return g.getBoundingClientRect(); };
  const who = s => `${s.closest('.src-item').querySelector('strong').textContent.trim()} #${s.dataset.i}`;
  const slots = [...document.querySelectorAll('#settings-sources .slot')].filter(visible);
  for (const s of slots) {
    const b = s.getBoundingClientRect();
    if (b.height < minBox - 0.5) bad.push(['box too short', who(s), Math.round(b.height)]);
    const n = s.querySelector('.slot-n');
    if (n && Math.abs(mid(textRect(n)) - mid(b)) > 2) bad.push(['number off-centre', who(s), Math.round(mid(textRect(n)) - mid(b))]);
    const name = s.querySelector('.slot-name'), icon = s.querySelector('.slot-main svg');
    if (name) {
      if (Math.abs(mid(textRect(name)) - mid(b)) > 2) bad.push(['name off-centre', who(s), Math.round(mid(textRect(name)) - mid(b))]);
      if (name.scrollWidth - name.clientWidth > 1 && getComputedStyle(name).textOverflow !== 'ellipsis') bad.push(['name clipped', who(s)]);
      const g = document.createRange(); g.selectNodeContents(name);
      if (new Set([...g.getClientRects()].map(r => Math.round(r.top))).size > 1) bad.push(['name on two lines', who(s)]);
    }
    if (icon) {
      const r = icon.getBoundingClientRect();
      if (r.width < 4 || Math.abs(mid(r) - mid(b)) > 2) bad.push(['icon off-centre', who(s), Math.round(r.width), Math.round(mid(r) - mid(b))]);
    }
    const x = s.querySelector('.slot-x');
    if (x) {
      const r = x.getBoundingClientRect();
      if (r.width < 23.5 || r.height < 23.5) bad.push(['X too small', who(s), Math.round(r.width), Math.round(r.height)]);
    }
  }
  if (document.documentElement.scrollWidth > window.innerWidth + 1) bad.push(['h-scroll', document.documentElement.scrollWidth - window.innerWidth]);
  const ul = document.querySelector('#settings-sources .picker');
  if (ul) {
    const r = ul.getBoundingClientRect(), card = ul.closest('.settings-card').getBoundingClientRect();
    if (r.left < -0.5 || r.right > window.innerWidth + 0.5) bad.push(['list outside the viewport', Math.round(r.left), Math.round(r.right)]);
    if (r.left < card.left - 0.5 || r.right > card.right + 0.5) bad.push(['list outside its card', Math.round(r.left), Math.round(r.right)]);
  }
  return [bad, slots.length];
}
"""


@pytest.fixture
def boxes(base_url):
    """A source with four filled boxes (one account has a name of forty characters) next to the
    autouse source "Local", whose boxes are empty."""
    with httpx.Client(base_url=base_url) as c:
        ids = []
        for name, kind in BOX_ACCOUNTS:
            r = c.post(
                "/api/freelance/accounts", json={"name": name, "currency": "EUR", "kind": kind}
            )
            assert r.status_code == 201, r.text
            ids.append(r.json()["id"])
        r = c.post(
            "/api/freelance/sources", json={"name": "Bench", "hourly_rate": 40, "currency": "EUR"}
        )
        assert r.status_code == 201, r.text
        assert (
            c.put(f"/api/freelance/sources/{r.json()['id']}", json={"chain": ids}).status_code
            == 200
        )
        # a name of forty characters with four filled boxes, a two-account chain, an archived one
        for name, chain, archived in (
            (LONG_NAME, ids, False),
            ("Pair", [ids[0], ids[2]], False),
            ("Old client", ids[:1], True),
        ):
            r = c.post(
                "/api/freelance/sources", json={"name": name, "hourly_rate": 40, "currency": "EUR"}
            )
            assert r.status_code == 201, r.text
            body = {"chain": chain, "archived": archived}
            assert c.put(f"/api/freelance/sources/{r.json()['id']}", json=body).status_code == 200
    yield
    with httpx.Client(base_url=base_url) as c:
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")
        for a in c.get("/api/freelance/accounts").json():
            c.delete(f"/api/freelance/accounts/{a['id']}")


MEASURE_ROWS = """
(wide) => {
  const bad = [], firsts = [];
  for (const r of document.querySelectorAll('#settings-sources .src-item')) {
    if (r.offsetParent === null) continue;
    const rect = e => e.getBoundingClientRect();
    const who = r.querySelector('strong').textContent.trim();
    const dot = rect(r.querySelector('.fl-dot')), main = rect(r.querySelector('.src-main'));
    const name = rect(r.querySelector('.src-main strong')), chain = rect(r.querySelector('.chain'));
    const first = rect(r.querySelector('.slot'));
    const buttons = [...r.querySelectorAll('.src-actions button')].map(rect);
    if (main.left < dot.right - 0.5 || main.top > dot.bottom || dot.top > main.bottom) bad.push(['name not beside the dot', who]);
    if (Math.abs(first.left - name.left) > 2) bad.push(['box 1 not under the name', who, Math.round(first.left - name.left)]);
    if (chain.top < main.bottom - 0.5) bad.push(['chain not below the name', who]);
    for (const b of buttons) if (b.top + b.height / 2 < chain.top) bad.push(['button above the chain', who]);
    const filled = r.querySelectorAll('.slot.filled').length;
    if (wide && filled <= 2) {
      const last = buttons[buttons.length - 1], row = rect(r);
      if (!buttons.every(b => b.top < chain.bottom && b.bottom > chain.top)) bad.push(['buttons not on the chain line', who]);
      if (Math.abs(last.right - row.right) > 2) bad.push(['buttons not at the right edge', who, Math.round(last.right - row.right)]);
    }
    firsts.push(first.left);
  }
  if (Math.max(...firsts) - Math.min(...firsts) > 2) bad.push(['box 1 is not at the same x in every row']);
  return bad;
}
"""


def _row_problems(page, width):
    return page.evaluate(MEASURE_ROWS, width >= 1280)


def _box_problems(page, width):
    bad, n = page.evaluate(MEASURE_BOXES, 38 if width <= 375 else 24)
    rows = page.locator("#settings-sources .src-item").count()
    if rows < 3 or n != 4 * rows:  # four boxes a source: Bench, Local and the one the seed adds
        bad.append(("boxes drawn", n, rows))
    return bad


def _open_list(page, source, n):
    page.get_by_role("group", name=f"Accounts of {source}, in order").locator(".slot").nth(
        n - 1
    ).locator(".slot-main").click()
    page.wait_for_selector("#settings-sources .picker [role=option]:focus", timeout=5000)
    page.wait_for_timeout(250)  # the list's own entrance


@pytest.mark.parametrize("width,height", HANDLE_WIDTHS)
def test_the_account_boxes_fit_at_every_width(page, base_url, boxes, width, height):
    """Four boxes per source: tall enough to hit, their contents in the middle, no text cut without
    an ellipsis, a list that stays in its card, and a page that never scrolls sideways."""
    _open_settings_group(page, base_url, width, height, "freelance")
    page.wait_for_selector(".chain .slot", timeout=5000)
    page.wait_for_load_state("networkidle")
    assert not (found := _box_problems(page, width)), "\n".join(map(str, found))
    assert not (found := _row_problems(page, width)), "\n".join(map(str, found))
    for source in ("Bench", "Local"):
        for n in (1, 4):
            _open_list(page, source, n)
            assert not (found := _box_problems(page, width)), (source, n, found)
            page.keyboard.press("Escape")
            page.wait_for_selector("#settings-sources .picker", state="detached", timeout=5000)


@pytest.mark.parametrize("width,height", [(1280, 900), (375, 800)])
def test_the_box_audit_can_fail(page, base_url, boxes, width, height):
    """A positive control: a box 14px tall, and a name that spills out without an ellipsis."""
    _open_settings_group(page, base_url, width, height, "freelance")
    page.wait_for_selector(".chain .slot", timeout=5000)
    page.wait_for_load_state("networkidle")
    assert not (found := _box_problems(page, width)), "\n".join(map(str, found))
    page.add_style_tag(
        content=".slot { height: 14px !important; } .slot-name { text-overflow: clip !important; max-width: 3ch !important; }"
        " .slot.filled { max-width: none !important; }"
    )
    page.wait_for_timeout(100)
    kinds = {p[0] for p in _box_problems(page, width)}
    assert {"box too short", "name clipped"} <= kinds, kinds


# ── the name of an account is a chip that can be carried (Settings > Freelance, Accounts) ──────────
MEASURE_CHIPS = """
(minChip) => {
  const bad = [];
  const mid = r => r.top + r.height / 2;
  const textRect = el => { const g = document.createRange(); g.selectNodeContents(el); return g.getBoundingClientRect(); };
  const rows = [...document.querySelectorAll('[data-testid=accounts-card] .sort-list > .src-item')].filter(r => r.offsetParent !== null);
  const chips = [];
  for (const r of rows) {
    const who = r.querySelector('strong').textContent.trim();
    const chip = r.querySelector('.acct-chip');
    if (r.classList.contains('is-archived')) { if (chip) bad.push(['archived name is a chip', who]); continue; }
    if (!chip) { bad.push(['live name is not a chip', who]); continue; }
    const b = chip.getBoundingClientRect(), icon = chip.querySelector('svg').getBoundingClientRect(), name = textRect(chip.querySelector('strong'));
    if (b.height < minChip - 0.5) bad.push(['chip too short', who, Math.round(b.height)]);
    if (Math.abs(mid(icon) - mid(b)) > 2) bad.push(['icon off-centre', who, Math.round(mid(icon) - mid(b))]);
    if (Math.abs(mid(name) - mid(b)) > 2) bad.push(['name off-centre', who, Math.round(mid(name) - mid(b))]);
    if (chip.getAttribute('title') !== 'Drag into a box above') bad.push(['chip without its tip', who]);
    chips.push(who);
  }
  if (document.documentElement.scrollWidth > window.innerWidth + 1) bad.push(['h-scroll', document.documentElement.scrollWidth - window.innerWidth]);
  return { bad, chips, heights: rows.map(r => r.getBoundingClientRect().height) };
}
"""


def _chip_problems(page, width):
    """The chips against their rules, and each row against itself with the chip's own room taken away
    (no minimum height, no padding, no margin): the chip may not make a row taller."""
    min_chip = 38 if width <= 375 else 24
    found = page.evaluate(MEASURE_CHIPS, min_chip)
    bad = [tuple(p) for p in found["bad"]]
    if len(found["chips"]) != 2:  # Deutsche Bank and the long name; the archived one is no chip
        bad.append(("chips drawn", found["chips"]))
    flat = page.add_style_tag(
        content=".acct-chip { min-height: 0 !important; padding: 0 !important; margin: 0 !important; }"
    )
    plain = page.evaluate(MEASURE_CHIPS, 0)["heights"]
    flat.evaluate("el => el.remove()")
    for tall, was in zip(found["heights"], plain, strict=True):
        if tall > was + 1:
            bad.append(("row taller with the chip", round(was, 1), round(tall, 1)))
    return bad


@pytest.mark.parametrize("width,height", HANDLE_WIDTHS)
def test_the_account_chips_fit_their_rows(page, base_url, orderable, width, height):
    """The name of a live account: tall enough to hold, its icon and name in the middle, a tip, no row
    taller for it and no sideways scroll; an archived name is no chip."""
    _open_settings_group(page, base_url, width, height, "freelance")
    page.wait_for_selector(".acct-chip", timeout=5000)
    page.wait_for_load_state("networkidle")
    assert not (found := _chip_problems(page, width)), "\n".join(map(str, found))


@pytest.mark.parametrize("width,height", HANDLE_WIDTHS)
def test_a_carried_name_adds_no_sideways_scroll(page, base_url, orderable, width, height):
    """The copy that follows the pointer (a name of forty characters) is fixed to the window: the page
    does not grow sideways while it is carried, nor when it is over a box."""
    _open_settings_group(page, base_url, width, height, "freelance")
    page.wait_for_selector(".acct-chip", timeout=5000)
    page.wait_for_load_state("networkidle")
    chip = page.locator(".acct-chip").filter(has_text=LONG_NAME[:20])
    chip.scroll_into_view_if_needed()
    box = chip.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 10, y - 10, steps=3)
    page.wait_for_selector(".acct-ghost", timeout=5000)
    slot = page.locator("#settings-sources .slot").first
    slot.scroll_into_view_if_needed()
    b = slot.bounding_box()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=8)
    assert page.locator(".slot.over").count() == 1
    ghost = page.locator(".acct-ghost").bounding_box()
    assert ghost["width"] <= width, ghost
    assert page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 1
    page.mouse.up()
    page.wait_for_selector(".acct-ghost", state="detached", timeout=5000)
    assert page.evaluate("document.documentElement.scrollWidth - window.innerWidth") <= 1


@pytest.mark.parametrize("width,height", [(1280, 900), (375, 800)])
def test_the_chip_audit_can_fail(page, base_url, orderable, width, height):
    """A positive control: a chip 14px tall is reported, and so is a chip that makes its row taller."""
    _open_settings_group(page, base_url, width, height, "freelance")
    page.wait_for_selector(".acct-chip", timeout=5000)
    page.wait_for_load_state("networkidle")
    assert not (found := _chip_problems(page, width)), "\n".join(map(str, found))
    short = page.add_style_tag(
        content=".acct-chip { height: 14px !important; min-height: 0 !important; }"
    )
    assert "chip too short" in {p[0] for p in _chip_problems(page, width)}
    short.evaluate("el => el.remove()")
    tall = page.add_style_tag(content=".acct-chip { min-height: 90px !important; }")
    assert "row taller with the chip" in {p[0] for p in _chip_problems(page, width)}
    tall.evaluate("el => el.remove()")
    assert not (found := _chip_problems(page, width)), "\n".join(map(str, found))


# ── the payout cell (Weeks > Freelance): one line per account of the chain ──────────────────────────
CELL_LONG_NAME = ("Long account name " * 3)[:40]

CELL_AUDIT = """
(phone) => {
  const bad = [], counts = [];
  const box = e => e.getBoundingClientRect();
  const mid = r => r.top + r.height / 2;
  const hit = (a, b) => a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1;
  const seen = e => e.offsetParent !== null && box(e).width > 0;
  for (const row of document.querySelectorAll('.wk-line')) {
    const cell = row.querySelector('.payc');
    if (!cell || !seen(row)) continue;
    const who = row.dataset.source || row.closest('tr').id;
    const lines = [...cell.querySelectorAll('.payc-l')];
    if (['Cell One', 'Cell Two', 'Cell Four'].includes(who)) counts.push(lines.length);
    lines.forEach((l, i) => {
      const mark = l.querySelector('.cur'), field = l.querySelector('.payin'), pick = l.querySelector('select, .payadd');
      const amt = l.querySelector('.amt-box'), x = l.querySelector('.clr');
      const f = box(field), s = box(pick), m = box(mark), a = box(amt), xr = box(x);
      if (f.height < 23.5) bad.push(['field too short', who, i, Math.round(f.height)]);
      if (s.width < 96) bad.push(['select too narrow', who, i, Math.round(s.width)]);
      if (pick.tagName === 'SELECT' && s.height < 23.5) bad.push(['select too short', who, i, Math.round(s.height)]);
      if (Math.abs(mid(f) - mid(s)) > 2 || Math.abs(mid(f) - mid(m)) > 2) bad.push(['mark, amount and select not level', who, i]);
      if (xr.left < a.left - 1 || xr.right > a.right + 1 || xr.top < a.top - 1 || xr.bottom > a.bottom + 1) bad.push(['X outside its field', who, i]);
      if (phone && (xr.width < 23.5 || xr.height < 23.5)) bad.push(['X too small', who, i, Math.round(xr.width), Math.round(xr.height)]);
      if (pick.tagName === 'SELECT' && getComputedStyle(pick).textOverflow !== 'ellipsis') bad.push(['select clipped without an ellipsis', who, i]);
      if (s.right > box(row).right + 1 || s.left < box(row).left - 1) bad.push(['select outside its row', who, i]);
    });
    for (const el of row.querySelectorAll('.wk-conv, .wk-gap b, .wk-eph, .wk-est, .wk-h, .pay-confirm, .pay-del, .wk-tag, .fx-chip, .payadd, .worth span, .wk-status')) {
      if (!seen(el) || !el.textContent.trim()) continue;
      if (el.scrollWidth - el.clientWidth > 1) bad.push(['text clipped', who, el.className]);
      const rg = document.createRange(); rg.selectNodeContents(el);
      const ms = [...rg.getClientRects()].filter(r => r.width > 0).map(mid);
      if (ms.length && Math.max(...ms) - Math.min(...ms) > 6) bad.push(['text on two lines', who, el.className]);
    }
    const first = box(lines[0]), last = box(lines[lines.length - 1]);
    const gap = row.querySelector('.wk-gap b'), chip = row.querySelector('.fx-chip');
    // on the narrowest phones (<= 400px) the Gap and the chip take the row under the cell: below it, not level with a line
    const under = window.innerWidth <= 400;
    if (under && gap && box(gap).top < last.bottom - 1) bad.push(['Gap not under the cell', who]);
    if (!under && gap && Math.abs(mid(box(gap)) - mid(first)) > 6) bad.push(['Gap not level with the first line', who]);
    if (chip && !under) {
      const c = box(chip);
      if (lines.length > 1) { if (Math.abs(mid(c) - mid(last)) > 6) bad.push(['DIFF chip not level with the last line', who]); }
      else if (gap && c.top < box(gap).bottom - 1) bad.push(['DIFF chip over the Gap', who]);
      if (c.bottom > box(row).bottom + 1) bad.push(['DIFF chip out of its row', who]);
    }
    for (const el of row.querySelectorAll('.pay-confirm, .pay-undo, .pay-del, .wk-tag, .wk-gap b, .fx-chip')) {
      if (!seen(el)) continue;
      const r = box(el);
      if (r.left < -1 || r.right > window.innerWidth + 1) bad.push(['outside the viewport', who, el.className, Math.round(r.right)]);
    }
    if (chip) {
      const c = box(chip);
      for (const l of lines) {
        const s = box(l.querySelector('select, .payadd'));
        const near = c.left < s.right + 4 && c.right > s.left - 4 && c.top < s.bottom && c.bottom > s.top;
        if (near || hit(c, box(l.querySelector('.amt-box'))) || hit(c, box(l.querySelector('.cur')))) bad.push(['chip over the cell', who]);
      }
    }
    const confirm = row.querySelector('.pay-confirm'), undo = row.querySelector('.pay-undo');
    if (undo && seen(undo)) {
      const u = box(undo);
      if (phone && (u.width < 23.5 || u.height < 23.5)) bad.push(['arrow too small', who, Math.round(u.width), Math.round(u.height)]);
      if (confirm && seen(confirm) && Math.abs(mid(u) - mid(box(confirm))) > 3) bad.push(['arrow not level with Confirm', who]);
      if (confirm && seen(confirm) && hit(u, box(confirm))) bad.push(['arrow overlaps', who, 'Confirm']);
      for (const el of row.querySelectorAll('.wk-gap b, .fx-chip, .wk-eph, .wk-h, .wk-est, .payc, .wk-head, .wk-src')) {
        if (seen(el) && hit(u, box(el))) bad.push(['arrow overlaps', who, el.className]);
      }
    }
    if (confirm && seen(confirm)) {
      const c = box(confirm);
      for (const el of row.querySelectorAll('.wk-gap b, .fx-chip, .wk-eph, .wk-h, .wk-est, .payc, .wk-head, .wk-src, .wk-status')) {
        if (seen(el) && hit(c, box(el))) bad.push(['Confirm overlaps', who, el.className]);
      }
    }
  }
  const head = document.querySelector('.days-table--fl thead .wk-cols');
  if (head && seen(head)) {
    const lineRow = sel => [...document.querySelectorAll('.days-table--fl .wk-line')].find(r => seen(r) && r.querySelector(sel) && seen(r.querySelector(sel)));
    for (const [sel, edge] of [['.wk-h', 'right'], ['.wk-est', 'right'], ['.wk-pay', 'left'], ['.wk-gap', 'right'], ['.wk-eph', 'right']]) {
      const label = head.querySelector(sel), row = lineRow(sel);
      if (!label || !seen(label) || !row) continue;
      const a = box(label), b = box(row.querySelector(sel));
      const inside = a.left >= -1 && a.right <= window.innerWidth + 1;
      if (!inside || Math.abs(a[edge] - b[edge]) > 8) bad.push(['header off its column', sel, Math.round(a[edge] - b[edge])]);
    }
  }
  // the rail of an open week with several sources runs down the left of its lines: no name, label or field sits on it
  for (const td of document.querySelectorAll('.days-table--fl tr.wk-lines.has-blocks > td')) {
    const rail = getComputedStyle(td, '::before');
    if (rail.content === 'none' || rail.display === 'none') continue;
    const x = box(td).left + parseFloat(rail.left);
    for (const el of td.querySelectorAll('.wk-src > *, .wk-h, .wk-est, .wk-eph, .wk-gap, .payc')) {
      if (!seen(el)) continue;
      // a figure is measured by its text (a column is wider than its number), a name and the cell by their box
      const rg = document.createRange(); rg.selectNodeContents(el);
      const rects = el.matches('.wk-src > *, .payc') ? [box(el)] : [...rg.getClientRects()].filter(r => r.width > 0);
      if (rects.some(r => r.left < x + 2 && r.right > x - 1)) bad.push(['rail crosses', el.closest('.wk-line').dataset.source, el.className]);
    }
  }
  if (document.documentElement.scrollWidth > window.innerWidth + 1) bad.push(['h-scroll', document.documentElement.scrollWidth - window.innerWidth]);
  return [bad, counts.sort()];
}
"""


@pytest.fixture
def cells(chain_url):
    """Weeks > Freelance with a one-line row, a two-line row and a four-line row, each once saved (a Gap and a
    DIFF chip, with a long figure: +214%) and once not (a Confirm), and a one-line row ending in dollars (the euro line). One account has a
    name of forty characters. The server is the one of test_payout_chain_cell.py: it has an ECB, so a payout
    has a chip and a Gap."""
    assert len(CELL_LONG_NAME) == 40
    mondays = [date(2026, 11, 2) - timedelta(days=7 * n) for n in range(8)]
    with httpx.Client(base_url=chain_url) as c:

        def post(path, **body):
            r = c.post(path, json=body)
            assert r.status_code == 201, r.text
            return r.json()

        acct = {
            n: post("/api/freelance/accounts", name=n, currency=cur)["id"]
            for n, cur in (
                ("Stripe", "USD"),
                ("Mercury", "USD"),
                ("Deutsche Bank", "EUR"),
                (CELL_LONG_NAME, "EUR"),
            )
        }
        rows = {
            "One": [("Deutsche Bank", 400)],
            "Two": [("Stripe", 150), ("Deutsche Bank", 400)],
            "Four": [
                ("Stripe", 150),
                ("Mercury", 150),
                (CELL_LONG_NAME, 130),
                ("Deutsche Bank", 400),
            ],
            "Fx": [("Stripe", 130)],
        }
        # a second source in the week of the saved Fx payout: that week has a source line with a badge and one without
        duo = post(
            "/api/freelance/sources",
            name="Cell Duo",
            hourly_rate=70,
            currency="USD",
            chain=[acct["Stripe"]],
        )
        post(
            "/api/freelance/blocks",
            source_id=duo["id"],
            date=(mondays[6] + timedelta(days=2)).isoformat(),
            hours=1,
        )
        for k, (name, legs) in enumerate(rows.items()):
            chain = [acct[a] for a, _ in legs]
            body = {"name": f"Cell {name}", "hourly_rate": 70, "currency": "USD", "chain": chain}
            src = post("/api/freelance/sources", **body)
            saved, unsaved = mondays[2 * k], mondays[2 * k + 1]
            for week in (saved, unsaved):
                day = (week + timedelta(days=2)).isoformat()
                post("/api/freelance/blocks", source_id=src["id"], date=day, hours=2)
            legs_in = [{"account_id": acct[a], "amount": v} for a, v in legs]
            post(
                "/api/freelance/payouts",
                source_id=src["id"],
                week_start=saved.isoformat(),
                legs=legs_in,
            )
    yield
    _wipe(chain_url)


def _open_cells(page, url, width, height, open_week=False):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{url}/#weeks")
    page.wait_for_selector("main .page-head", timeout=5000)
    page.evaluate("Alpine.$data(document.querySelector('main')).daysYear = 'all'")
    page.get_by_role("radio", name="Freelance").click()
    page.wait_for_selector(".days-table--fl .wk-main .payc", timeout=5000)
    page.wait_for_load_state("networkidle")
    if open_week:  # the block rows are there: they make the table wider than its wrap
        page.evaluate(OPEN_ALL_WEEKS)
        page.wait_for_selector(".days-table--fl tr.blk", state="attached", timeout=5000)
    # two rows hold a draft, made through the page: Confirm is solid and the arrow shows (one saved, one not)
    for which in (":has(.pay-confirm)", ":has(.pay-del)"):
        field = page.locator(
            f".wk-line[data-source='Cell Two']{which}, .wk-line[data-source='Cell Four']{which}"
        )
        field.first.get_by_test_id("pay-amount").first.fill("77")
    page.wait_for_function("() => document.querySelectorAll('.pay-undo').length >= 2")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(300)  # the entry animations settle


def _cell_problems(page):
    return page.evaluate(CELL_AUDIT, page.viewport_size["width"] <= 640)


@pytest.mark.parametrize("open_week", [False, True], ids=["closed", "open"])
@pytest.mark.parametrize(
    "width,height",
    [
        *HANDLE_WIDTHS,
        (1100, 800),
        (800, 800),
        (768, 800),
        (641, 800),
        (640, 800),
        (601, 800),
        (412, 800),
        (401, 800),
        (400, 800),
    ],
)
def test_the_payout_cell_fits_at_every_width(page, chain_url, cells, width, height, open_week):
    """A row of one, two and four accounts, saved and not, one account with a name of forty characters:
    nothing scrolls sideways, fields and selects are tall enough, a line's mark, amount and select sit on
    one level, the X is inside its field (and a finger's size on a phone), no text is cut without an
    ellipsis, the Gap is level with the first line and the DIFF chip with the last, and Confirm touches
    nothing, and Confirm, Delete, Gap and chip are inside the window, with a week open too."""
    _open_cells(page, chain_url, width, height, open_week)
    bad, counts = _cell_problems(page)
    assert not bad, "\n".join(map(str, bad))
    assert counts == [1, 1, 2, 2, 4, 4], counts  # every kind of row was measured
    assert page.locator(".pay-undo").count() >= 2 and page.locator(".wk-tag.paid").count() >= 2
    if open_week:  # the week of two sources is open, so its rail was measured against its lines
        assert page.locator(".days-table--fl tr.wk-lines.has-blocks .wk-line").count() >= 2


@pytest.mark.parametrize("width,height", [(1280, 900), (601, 800)])
def test_the_payout_cell_audit_can_fail(page, chain_url, cells, width, height):
    """A positive control: an amount field 14px tall, a chip pushed off its line and a Confirm pulled over
    the Gap are all reported."""
    _open_cells(page, chain_url, width, height)
    assert not (found := _cell_problems(page)[0]), "\n".join(map(str, found))
    tall = page.add_style_tag(content=".payc .payin { height: 14px !important; }")
    assert "field too short" in {p[0] for p in _cell_problems(page)[0]}
    tall.evaluate("el => el.remove()")
    off = page.add_style_tag(content=".wk-chip { margin-top: 150px !important; }")
    assert "DIFF chip not level with the last line" in {p[0] for p in _cell_problems(page)[0]}
    off.evaluate("el => el.remove()")
    over = page.add_style_tag(content=".wk-tail { position: relative; top: 40px; left: -250px; }")
    assert any(p[0].startswith("Confirm overlaps") for p in _cell_problems(page)[0])
    over.evaluate("el => el.remove()")
    arrow = page.add_style_tag(content=".pay-undo { position: relative; left: -45px; }")
    assert "arrow overlaps" in {p[0] for p in _cell_problems(page)[0]}
    arrow.evaluate("el => el.remove()")
    assert not (found := _cell_problems(page)[0]), "\n".join(map(str, found))


@pytest.mark.parametrize("width,height", [(900, 800), (700, 800)])
def test_the_audit_sees_a_confirm_off_the_screen(page, chain_url, cells, width, height):
    """A positive control for the open week: without the rule that keeps a week line as wide as its wrap, the
    block rows push the end of every row off the screen, and the audit says so."""
    _open_cells(page, chain_url, width, height, open_week=True)
    assert not (found := _cell_problems(page)[0]), "\n".join(map(str, found))
    old = page.add_style_tag(
        content=".days-table--fl .wk-line { position: static !important; width: auto !important; }"
    )
    assert "outside the viewport" in {p[0] for p in _cell_problems(page)[0]}
    old.evaluate("el => el.remove()")
    assert not (found := _cell_problems(page)[0]), "\n".join(map(str, found))


@pytest.mark.parametrize("width,height", [(900, 800), (800, 800)])
def test_the_audit_sees_a_narrow_select_a_chip_on_it_and_a_header_off_its_column(
    page, chain_url, cells, width, height
):
    """A positive control: the select's room taken away, the chip moved onto the select, and the header
    rule removed (the header as wide as the table, the lines as wide as the wrap) are each named."""
    _open_cells(page, chain_url, width, height, open_week=True)
    assert not (found := _cell_problems(page)[0]), "\n".join(map(str, found))
    for css, name in (
        (
            ".payc .payacct { width: 40px !important; min-width: 0 !important; flex: none !important; }",
            "select too narrow",
        ),
        (".wk-chip { position: relative; left: -90px; }", "chip over the cell"),
        (
            ".days-table--fl thead .wk-cols { position: static !important; width: auto !important; }",
            "header off its column",
        ),
    ):
        tag = page.add_style_tag(content=css)
        assert name in {p[0] for p in _cell_problems(page)[0]}, name
        tag.evaluate("el => el.remove()")
    assert not (found := _cell_problems(page)[0]), "\n".join(map(str, found))


@pytest.mark.parametrize("width,height", [(700, 800), (375, 800)])
def test_the_audit_sees_a_rail_through_the_labels(page, chain_url, cells, width, height):
    """A positive control for the rail of an open week with several sources: with its lines starting where
    they used to (left of the rail), the audit names the labels and the cell the rail runs through."""
    _open_cells(page, chain_url, width, height, open_week=True)
    assert not (found := _cell_problems(page)[0]), "\n".join(map(str, found))
    old = page.add_style_tag(
        content=".days-table--fl tr.wk-lines .wk-line { padding-left: 0.5rem !important; }"
    )
    crossed = [p for p in _cell_problems(page)[0] if p[0] == "rail crosses"]
    assert {p[1] for p in crossed} == {"Cell Fx", "Cell Duo"}, crossed
    assert any("payc" in p[2] for p in crossed) and any("wk-h" in p[2] for p in crossed), crossed
    old.evaluate("el => el.remove()")
    assert not (found := _cell_problems(page)[0]), "\n".join(map(str, found))


# ── the header of a week's blocks under the column header that sticks ───────────────────────────────
# Scrolled until a block header is right where the column header is stuck, the column header is the one on top:
# the element at the middle of each of its labels is its own.

BLOCK_HEAD_UNDER = """
() => {
  const strip = document.querySelector('.bz').getBoundingClientRect().height;
  const max = document.documentElement.scrollHeight - window.innerHeight;
  for (const h of document.querySelectorAll('.days-table--fl tr.blk-head')) {
    const y = Math.round(window.scrollY + h.getBoundingClientRect().top - strip);
    if (y > 0 && y <= max) { h.dataset.under = '1'; window.scrollTo(0, y); return true; }
  }
  return false;
}
"""

BLOCK_HEAD_IS_UNDER = """
() => {
  const h = document.querySelector('tr.blk-head[data-under]'), th = document.querySelector('.days-table--fl thead th');
  return Math.abs(h.getBoundingClientRect().top - th.getBoundingClientRect().top) < 3;
}
"""

COLUMN_HEAD_AUDIT = """
() => {
  const bad = [];
  let n = 0;
  for (const label of document.querySelectorAll('.days-table--fl thead .wk-cols span')) {
    const r = label.getBoundingClientRect();
    if (!r.width) continue;
    n++;
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    if (!top || !top.closest('thead')) bad.push(['column header covered', label.className, top ? top.tagName + ' of ' + top.parentElement.className : 'nothing']);
  }
  return [bad, n];
}
"""


def _block_head_under_the_column_head(page, chain_url, cells):
    _open_cells(page, chain_url, 1280, 600, open_week=True)
    assert page.evaluate(BLOCK_HEAD_UNDER), (
        "no block header can be scrolled under the column header"
    )
    page.wait_for_function(BLOCK_HEAD_IS_UNDER, timeout=5000)


def test_a_block_header_stays_under_the_stuck_column_header(page, chain_url, cells):
    _block_head_under_the_column_head(page, chain_url, cells)
    bad, measured = page.evaluate(COLUMN_HEAD_AUDIT)
    assert not bad, "\n".join(map(str, bad))
    assert measured == 5, measured  # Hours, Estimate, Payout, Gap, € / h


def test_the_column_header_audit_can_fail(page, chain_url, cells):
    """A positive control: with the block header back on the level of the column header, it is on top."""
    _block_head_under_the_column_head(page, chain_url, cells)
    assert not (found := page.evaluate(COLUMN_HEAD_AUDIT)[0]), "\n".join(map(str, found))
    old = page.add_style_tag(content=".days-table tr.blk-head th { z-index: 1 !important; }")
    assert "column header covered" in {p[0] for p in page.evaluate(COLUMN_HEAD_AUDIT)[0]}
    old.evaluate("el => el.remove()")
    assert not (found := page.evaluate(COLUMN_HEAD_AUDIT)[0]), "\n".join(map(str, found))


# ── the seal of a confirmed payout, at the moment it has landed ───────────────────────────────────────
# The seal is on the page for a second only, so the page measures it itself, in the callback that sees it get
# `hit` (the same task as the class change, before anything moves): inside the window, inside its row, nothing
# of the row under it that is an amount or a select, and no sideways scroll.

SEAL_AUDIT = """
() => {
  window.__landed = [];
  const vis = (e) => e.offsetParent !== null && e.getBoundingClientRect().width > 0;
  new MutationObserver((ms) => ms.forEach((m) => {
    const s = m.target;
    if (!s.classList || !s.classList.contains('seal') || !s.classList.contains('hit') || s.__measured) return;
    s.__measured = true;
    // Where the seal RESTS, from the layout: the rectangle of its `.tail-top` (its offsetParent) plus the seal's own
    // offsets and size. getBoundingClientRect() would include the drop's transform (54px up, 2.4 times the size at
    // the start), and on a loaded machine the animation is behind the timer that adds `hit`.
    const line = s.closest('.wk-line'), L = line.getBoundingClientRect(), T = s.offsetParent.getBoundingClientRect();
    const r = { left: T.left + s.offsetLeft, top: T.top + s.offsetTop, width: s.offsetWidth, height: s.offsetHeight };
    r.right = r.left + r.width; r.bottom = r.top + r.height;
    const bad = [];
    if (r.left < 0 || r.top < 0 || r.right > window.innerWidth || r.bottom > window.innerHeight) bad.push(['seal outside the viewport', `x ${Math.round(r.left)}..${Math.round(r.right)} y ${Math.round(r.top)}..${Math.round(r.bottom)} of ${window.innerHeight}, scroll ${Math.round(window.scrollY)}, row ${Math.round(L.top)}..${Math.round(L.bottom)} ${line.dataset.source}`]);
    // At rest the seal (2.7rem) is taller than the row's first line plus its padding by up to 2px at the top: that
    // overhang is real and is allowed here (2.5px); anything more is reported.
    const slack = 2.5;
    if (r.left < L.left - slack || r.right > L.right + slack || r.top < L.top - slack || r.bottom > L.bottom + slack) bad.push(['seal outside its row', Math.round(r.left - L.left), Math.round(r.right - L.right), Math.round(r.top - L.top), Math.round(r.bottom - L.bottom)]);
    for (const e of line.querySelectorAll('.payin, select.payacct, .payadd, .amt-box')) {
      const b = e.getBoundingClientRect();
      if (vis(e) && r.left < b.right - 1 && b.left < r.right - 1 && r.top < b.bottom - 1 && b.top < r.bottom - 1) bad.push(['seal covers', e.className]);
    }
    if (document.documentElement.scrollWidth > window.innerWidth + 1) bad.push(['h-scroll', document.documentElement.scrollWidth - window.innerWidth]);
    window.__landed.push({ bad, width: Math.round(r.width) });
  })).observe(document.body, { attributes: true, subtree: true, attributeFilter: ['class'] });
}
"""


def _confirm_and_measure(page, source, css=None):
    """Press Confirm on the unsaved row of `source` and answer what the page measured when its seal landed."""
    page.evaluate(SEAL_AUDIT)
    tag = page.add_style_tag(content=css) if css else None
    button = page.locator(
        f".wk-line[data-source='{source}']:has(.pay-confirm)"
    ).first.get_by_test_id("pay-confirm")
    # Confirm is enabled once the row's preview is in (a loaded machine takes longer); only then is the row put in
    # the middle of the window, so that the seal is measured against the window and not against a scroll that
    # stopped short or a row that moved when the previews came in
    page.wait_for_function(
        "(sel) => { const b = document.querySelector(sel); return b && !b.disabled; }",
        arg=f".wk-line[data-source='{source}'] [data-testid=pay-confirm]",
        timeout=20000,
    )
    page.wait_for_load_state("networkidle")
    button.evaluate("e => e.scrollIntoView({ block: 'center' })")
    # a mouse click where the button is: Playwright's own click scrolls the row again on Linux (by a whole row)
    box = button.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_function("() => window.__landed.length === 1", timeout=8000)
    got = page.evaluate("window.__landed")
    page.wait_for_function("() => !document.querySelector('.seal')", timeout=8000)
    if tag is not None:
        tag.evaluate("el => el.remove()")
    return got


@pytest.mark.parametrize("source", ["Cell One", "Cell Four", "Cell Duo"])
@pytest.mark.parametrize(
    "width,height", [(1280, 900), (900, 800), (768, 800), (412, 800), (375, 800), (320, 800)]
)
def test_the_seal_fits_its_row_when_it_lands(page, chain_url, cells, width, height, source):
    _open_cells(page, chain_url, width, height)
    got = _confirm_and_measure(page, source)
    assert got[0]["width"] > 30, got  # it was measured while it was there, at its size
    assert not got[0]["bad"], "\n".join(map(str, got[0]["bad"]))


@pytest.mark.parametrize("width,height", [(1280, 900), (375, 800)])
def test_the_seal_audit_can_fail(page, chain_url, cells, width, height):
    """A positive control: the seal pushed 300px to the right is reported, and the same row is clean without it.
    The push is a margin, which the layout box sees (a transform would not move the box the audit measures)."""
    _open_cells(page, chain_url, width, height)
    pushed = _confirm_and_measure(page, "Cell One", css=".seal { margin-left: 300px !important; }")
    assert pushed[0]["bad"], pushed
    assert "seal outside the viewport" in {
        p[0] for p in pushed[0]["bad"]
    } or "seal outside its row" in {p[0] for p in pushed[0]["bad"]}
    clean = _confirm_and_measure(page, "Cell Four")
    assert not clean[0]["bad"], clean
