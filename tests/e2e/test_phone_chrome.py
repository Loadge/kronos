"""E2E: the phone's chrome (UI_GUIDE.md, "On a phone").

Up to 640px the tabs are a bar fixed to the bottom of the screen, and in Log the day's result and
its main button are a dock just above it. One brass line (the ink) marks the active tab on every
width and slides when the tab changes. The Log page folds its calendar's legend and shrinks its year
to twelve letters; the command palette scrolls inside its panel.

The browser clock is fixed to 2026-11-04, so the form's date is that day and nothing depends on the
hour the suite runs at. Hands are touch hands where a phone has one (tap, not click). State that
lives for a moment (a slide, a fade) is caught by an event or waited for, never read once.
"""

from __future__ import annotations

import time

import httpx
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

FIXED_NOW = "2026-11-04T10:00:00"
TODAY = "2026-11-04"
MAIN = "Alpine.$data(document.querySelector('main'))"
NAMES = ["Dashboard", "Plan", "Log", "Days", "Analytics", "Freelance"]
TABS = ["dashboard", "plan", "log", "days", "analytics", "freelance", "settings"]
MINUS = "−"


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


@pytest.fixture(autouse=True)
def _data(base_url):
    """An 8h target, a few worked days and one income source (it adds the sixth tab, which is
    the one that has to fit in a column)."""
    _wipe(base_url)
    with httpx.Client(base_url=base_url) as c:
        c.put("/api/config", json={"daily_target_hours": 8, "vacation_budget_days": 0})
        r = c.post(
            "/api/freelance/sources",
            json={"name": "Local", "hourly_rate": 60, "currency": "EUR"},
        )
        assert r.status_code == 201, r.text
        for day in ("2026-09-10", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"):
            r = c.post(
                "/api/entries",
                json={"date": day, "day_type": "work", "start_time": "09:00", "end_time": "17:30"},
            )
            assert r.status_code == 201, r.text
    yield
    _wipe(base_url)


@pytest.fixture
def phone(browser):
    """A page of its own with the clock fixed: `make(width, height, touch=True, reduced=False)`."""
    contexts = []

    def make(width: int = 375, height: int = 800, touch: bool = True, reduced: bool = False):
        context = browser.new_context(
            viewport={"width": width, "height": height},
            locale="en-GB",
            has_touch=touch,
            reduced_motion="reduce" if reduced else "no-preference",
        )
        # the milestone toast belongs to a first visit; the log records every animation that starts
        context.add_init_script("localStorage.setItem('k-milestone-seen', '100000')")
        context.add_init_script(
            "window.__fx = []; document.addEventListener('animationstart', "
            "e => window.__fx.push(e.animationName), true)"
        )
        contexts.append(context)
        page = context.new_page()
        page.clock.set_fixed_time(FIXED_NOW)
        return page

    yield make
    for context in contexts:
        context.close()


def _open(page, base_url: str, tab: str) -> None:
    page.goto(f"{base_url}/#{tab}")
    page.wait_for_selector("main .page-head", timeout=10000)
    if tab != "settings":
        page.wait_for_function(
            "() => document.querySelector('.tabs-ink')?.dataset.placed === '1'", timeout=10000
        )


def _go(page, name: str, touch: bool) -> None:
    tab = page.get_by_role("tab", name=name, exact=True)
    tab.tap() if touch else tab.click()


def _state(page, expr: str):
    return page.evaluate(f"() => {MAIN}.{expr}")


def _until(page, js: str, what: str, seconds: float = 6.0):
    """Evaluate `js` until it answers with no problem (None); fail with the last answer."""
    deadline, last = time.monotonic() + seconds, None
    while time.monotonic() < deadline:
        last = page.evaluate(js)
        if last is None:
            return
        time.sleep(0.1)
    raise AssertionError(f"{what}: {last}")


# ── a. the bar ────────────────────────────────────────────────────────────────

BAR = """() => {
  const nav = document.querySelector('.tabs');
  const bar = nav.getBoundingClientRect();
  const tabs = [...nav.querySelectorAll('[role=tab]')].map(a => {
    const r = a.getBoundingClientRect(), l = a.querySelector('.tab-label');
    const range = document.createRange(); range.selectNodeContents(l);
    const lines = new Set([...range.getClientRects()].map(x => Math.round(x.top))).size;
    const lr = l.getBoundingClientRect(), ic = a.querySelector('svg.tab-ic');
    const keyEl = a.querySelector('.tab-key') || l;
    const iconOn = !!ic && ic.getAttribute('aria-hidden') === 'true'
      && getComputedStyle(ic).display !== 'none';
    return { name: l.textContent.trim(), w: r.width, h: r.height, lines,
             inside: lr.left >= r.left - 0.5 && lr.right <= r.right + 0.5,
             clip: a.scrollWidth - a.clientWidth,
             key: getComputedStyle(keyEl).color === getComputedStyle(a).color,
             icon: iconOn };
  });
  const cs = getComputedStyle(nav);
  return { top: bar.top, bottom: bar.bottom, h: innerHeight,
           sw: document.documentElement.scrollWidth,
           iw: innerWidth, position: cs.position, bg: cs.backgroundColor, tabs,
           inHeader: !!nav.closest('header.app-header') };
}"""


@pytest.mark.parametrize("width", [375, 320])
def test_the_tabs_are_a_bar_at_the_bottom_of_the_screen(phone, base_url, width):
    page = phone(width, 700)
    _open(page, base_url, "dashboard")
    s = page.evaluate(BAR)
    assert s["position"] == "fixed", s
    assert abs(s["bottom"] - s["h"]) <= 0.5, s  # the bar ends where the screen ends
    assert s["bottom"] - s["top"] >= 56, s
    assert s["bg"] == "rgb(31, 28, 22)", s  # --k-surface: solid
    assert [t["name"] for t in s["tabs"]] == NAMES
    widths = [t["w"] for t in s["tabs"]]
    assert max(widths) - min(widths) <= 0.5, widths  # equal columns
    for t in s["tabs"]:
        assert t["h"] >= 44, t
        assert t["lines"] == 1, t  # "Analytics" and "Freelance" on one line
        assert t["inside"] and t["clip"] <= 0, t  # and not clipped
        assert t["icon"], t
        assert t["key"], t  # the shortcut letter is not coloured on a phone
    assert s["sw"] <= s["iw"], s
    # the names did not change: icons are decoration
    for name in NAMES:
        assert page.get_by_role("tab", name=name, exact=True).count() == 1, name
    assert page.get_by_role("tablist").locator("[role=tab]").count() == 6


def test_from_641px_the_tabs_are_in_the_header_and_have_no_icons(phone, base_url):
    page = phone(641, 800, touch=False)
    _open(page, base_url, "dashboard")
    s = page.evaluate(BAR)
    assert s["inHeader"] and s["position"] != "fixed", s
    assert s["bottom"] < 250, s  # at the top of the page, not the screen's bottom
    assert not any(t["icon"] for t in s["tabs"]), s["tabs"]
    assert page.locator(".tabs .tab-ic").first.is_hidden()
    # the key letters are still brass here
    assert not any(t["key"] for t in s["tabs"] if t["name"] != "Dashboard"), s["tabs"]


# ── b. nothing hides under the bar or the dock ────────────────────────────────

CLEAR = """() => {
  window.scrollTo(0, document.documentElement.scrollHeight);
  const bar = document.querySelector('.tabs').getBoundingClientRect();
  const dockEl = document.querySelector('.log-col-rail');
  const fixedDock = dockEl && getComputedStyle(dockEl).position === 'fixed';
  const dock = fixedDock ? dockEl.getBoundingClientRect() : null;
  const floor = Math.min(bar.top, dock ? dock.top : Infinity);
  let lowest = 0, what = '';
  for (const el of document.querySelectorAll('main > section *')) {
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    if (el.offsetParent === null || r.width === 0 || r.height === 0) continue;
    if (['fixed', 'absolute'].includes(cs.position) || cs.visibility === 'hidden') continue;
    if (el.closest('.visually-hidden, .dr-tag, .hm-tip, svg')) continue;
    if (dock && el.closest('.log-col-rail')) continue; // the dock is what we measure against
    if (r.bottom > lowest) { lowest = r.bottom; what = el.tagName + '.' + el.className; }
  }
  const root = document.documentElement;
  const scrolled = Math.ceil(scrollY + innerHeight) >= root.scrollHeight - 1;
  return lowest <= floor + 0.5 && scrolled
    ? null : { lowest, floor, what, scrolled, hasDock: !!dock };
}"""


@pytest.mark.parametrize("tab", TABS)
def test_the_last_element_of_a_page_scrolls_clear_of_the_bar_and_the_dock(phone, base_url, tab):
    page = phone(375, 700)
    _open(page, base_url, tab)
    page.wait_for_timeout(500)  # a page that loads its data grows while it does
    _until(page, CLEAR, f"the end of {tab} is under the bar")
    assert page.evaluate("document.documentElement.scrollWidth") <= 375
    assert page.evaluate("getComputedStyle(document.body).overflow") != "hidden"  # no scroll lock


# ── c. the keyboard is up ─────────────────────────────────────────────────────


def _bar_and_dock_visible(page) -> bool:
    return page.locator(".tabs").is_visible() and page.locator(".log-col-rail").is_visible()


def test_a_time_field_leaves_the_bar_and_the_dock_in_place(phone, base_url):
    """A time field opens the phone's picker and stays focused after it: the dock must not go."""
    page = phone(375, 800)
    _open(page, base_url, "log")
    page.wait_for_selector(".log-times input[type=time]", timeout=5000)
    target = page.locator(".log-times .grid input[type=time]").first
    target.scroll_into_view_if_needed()
    target.tap()
    assert page.evaluate("el => document.activeElement === el", target.element_handle())
    page.wait_for_timeout(350)
    expect(page.locator(".tabs")).to_be_visible()
    expect(page.locator(".log-col-rail")).to_be_visible()


@pytest.mark.parametrize("field", ["number", "textarea"])
def test_a_field_with_focus_hides_the_bar_and_the_dock_and_blur_brings_them_back(
    phone, base_url, field
):
    page = phone(375, 800)
    _open(page, base_url, "log")
    page.wait_for_selector(".log-times input[type=time]", timeout=5000)
    expect(page.locator(".tabs")).to_be_visible()
    expect(page.locator(".log-col-rail")).to_be_visible()
    if field == "number":
        page.get_by_role("button", name="+ Add break").tap()
        target = page.locator(".break-input-line input[type=number]").first
    else:
        page.get_by_role("button", name="+ Add note").tap()
        target = page.locator("textarea[aria-label='Notes']")
    target.scroll_into_view_if_needed()
    target.tap()
    assert page.evaluate("el => document.activeElement === el", target.element_handle())
    expect(page.locator(".tabs")).to_be_hidden()
    expect(page.locator(".log-col-rail")).to_be_hidden()
    # a finger on the heading takes the focus away
    page.locator("main h2").first.scroll_into_view_if_needed()
    page.locator("main h2").first.tap()
    expect(page.locator(".tabs")).to_be_visible()
    expect(page.locator(".log-col-rail")).to_be_visible()


# ── d. the ink ────────────────────────────────────────────────────────────────

INK = """(phone) => {
  const inkEl = document.querySelector('.tabs-ink'), ink = inkEl.getBoundingClientRect();
  const onEl = document.querySelector('.tabs [role=tab][aria-selected=true]');
  if (!onEl) return 'no active tab';
  const on = onEl.getBoundingClientRect();
  const opacity = parseFloat(getComputedStyle(inkEl).opacity);
  const box = r => [r.left, r.top, r.width, r.bottom].map(Math.round);
  const at = `ink ${box(ink)} tab ${box(on)}`;
  if (Math.abs(ink.left - on.left) > 2 || Math.abs(ink.width - on.width) > 2) {
    return 'not on the tab: ' + at;
  }
  const edge = phone
    ? ink.top <= on.top + 3 && ink.bottom <= on.top + 6
    : on.bottom - 4 <= ink.top && ink.bottom <= on.bottom + 4;
  if (!edge) return 'wrong edge: ' + at;
  return opacity === 1 ? null : 'opacity ' + opacity;
}"""


def _wait_ink(page, phone_layout: bool) -> None:
    deadline, last = time.monotonic() + 6, None
    while time.monotonic() < deadline:
        last = page.evaluate(INK, phone_layout)
        if last is None:
            return
        time.sleep(0.1)
    raise AssertionError(last)


@pytest.mark.parametrize("width,height,touch", [(1280, 900, False), (375, 800, True)])
def test_the_ink_sits_on_the_active_tab_and_follows_a_click_and_a_resize(
    phone, base_url, width, height, touch
):
    page = phone(width, height, touch=touch)
    phone_layout = width <= 640
    _open(page, base_url, "log")
    _wait_ink(page, phone_layout)
    # first paint: placed, not slid
    assert page.evaluate("document.querySelector('.tabs-ink').getAnimations().length") == 0
    # a change of tab: the line slides (the transition starts: caught by its event)
    page.evaluate(
        "() => { window.__slid = false; document.querySelector('.tabs-ink')"
        ".addEventListener('transitionrun', () => { window.__slid = true; }); }"
    )
    _go(page, "Analytics", touch)
    page.wait_for_function("() => window.__slid === true", timeout=6000)
    _wait_ink(page, phone_layout)
    assert page.evaluate(
        "document.querySelector('.tabs [aria-selected=true]').textContent.trim()"
    ) == ("Analytics")
    # a resize puts it under the active tab again, with no slide
    other = (375, 800) if width > 640 else (1280, 900)
    page.set_viewport_size({"width": other[0], "height": other[1]})
    _wait_ink(page, other[0] <= 640)
    page.set_viewport_size({"width": width, "height": height})
    _wait_ink(page, phone_layout)


@pytest.mark.parametrize("width,height,touch", [(1280, 900, False), (375, 800, True)])
def test_with_settings_open_the_ink_is_gone(phone, base_url, width, height, touch):
    page = phone(width, height, touch=touch)
    _open(page, base_url, "dashboard")
    _wait_ink(page, width <= 640)
    gear = page.get_by_role("button", name="Settings")
    gear.tap() if touch else gear.click()
    expect(page.locator(".tabs-ink")).to_have_css("opacity", "0")
    assert page.locator(".tabs [aria-selected=true]").count() == 0
    _go(page, "Days", touch)
    expect(page.locator(".tabs-ink")).to_have_css("opacity", "1")
    _wait_ink(page, width <= 640)


def test_the_ink_finds_the_freelance_tab_when_it_appears(phone, base_url):
    """Six columns are narrower than five: the line must follow the tab when one is added."""
    with httpx.Client(base_url=base_url) as c:
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")
    page = phone(375, 800)
    _open(page, base_url, "log")
    _wait_ink(page, True)
    assert page.locator(".tabs [role=tab]").count() == 5
    with httpx.Client(base_url=base_url) as c:
        c.post(
            "/api/freelance/sources", json={"name": "Late", "hourly_rate": 50, "currency": "EUR"}
        )
    page.evaluate(f"() => {MAIN}.loadSources()")
    page.wait_for_function("() => document.querySelectorAll('.tabs [role=tab]').length === 6")
    _wait_ink(page, True)


# ── the page fade ─────────────────────────────────────────────────────────────


def test_a_page_fades_in_on_a_tab_change_and_not_on_load(phone, base_url):
    page = phone(375, 800)
    _open(page, base_url, "dashboard")
    page.wait_for_timeout(600)
    assert "page-in" not in page.evaluate("window.__fx")
    _go(page, "Days", True)
    page.wait_for_function("() => window.__fx.includes('page-in')", timeout=6000)
    page.wait_for_timeout(500)
    assert page.evaluate("window.__fx.filter(n => n === 'page-in').length") == 1
    assert page.evaluate("document.querySelector('main > section').getAnimations().length") == 0


def test_reduced_motion_turns_the_new_motion_off(phone, base_url):
    page = phone(375, 800, reduced=True)
    _open(page, base_url, "dashboard")
    ink = page.locator(".tabs-ink")
    assert ink.evaluate("e => getComputedStyle(e).transitionDuration") == "0s"
    _go(page, "Days", True)
    page.wait_for_selector("main .page-head h2:has-text('Days')", timeout=5000)
    assert "page-in" not in page.evaluate("window.__fx")
    assert page.evaluate("document.querySelector('main > section').getAnimations().length") == 0
    page.keyboard.press(".")
    page.wait_for_selector(".palette")
    assert (
        page.evaluate(
            "getComputedStyle(document.querySelector('.palette ul'), '::before').transitionDuration"
        )
        == "0s"
    )


# ── e. the dock ───────────────────────────────────────────────────────────────

DOCK = """() => {
  const bar = document.querySelector('.tabs').getBoundingClientRect();
  const el = document.querySelector('.log-col-rail'), d = el.getBoundingClientRect();
  const cs = getComputedStyle(el);
  const ok = cs.position === 'fixed' && d.top >= 0 && d.bottom <= innerHeight + 0.5
             && Math.abs(d.bottom - bar.top) <= 1.5 && d.width <= innerWidth + 0.5;
  return ok ? null : { pos: cs.position, top: d.top, bottom: d.bottom, barTop: bar.top,
                       h: innerHeight, w: d.width };
}"""


DELTA_IS = "t => document.querySelector('.log-col-rail .impact-delta').textContent.trim() === t"


def _dock_numbers(page) -> tuple[str, str]:
    cells = page.locator(".log-col-rail .impact-card")
    net = cells.locator(".impact-cell").first.locator(".impact-value").text_content()
    delta = cells.locator(".impact-delta").text_content()
    return net.strip(), delta.strip()


def test_the_dock_is_on_screen_at_the_top_and_at_the_end_of_the_page(phone, base_url):
    page = phone(375, 700)
    _open(page, base_url, "log")
    page.wait_for_selector(".log-col-rail .impact-card", state="visible")
    _until(page, DOCK, "the dock at the top of the page")
    assert page.evaluate("scrollY") == 0
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    _until(page, DOCK, "the dock at the end of the page")
    assert page.evaluate("scrollY") > 300
    # one result card, in the dock; the form's own column has none, and it has no second button
    assert page.locator(".impact-card").count() == 1
    assert page.locator(".log-col-rail .impact-card").is_visible()
    visible = page.locator(".impact-card").evaluate_all(
        "els => els.filter(e => e.offsetParent).length"
    )
    assert visible == 1
    assert page.locator("button.btn-action--block").count() == 1


def test_the_dock_shows_the_result_and_follows_the_end_time(phone, base_url):
    page = phone(375, 800)
    _open(page, base_url, "log")
    page.wait_for_selector(".log-col-rail .impact-card", state="visible")
    assert _dock_numbers(page) == ("8h", "±0.00h")
    end = page.locator(".log-times .grid input[type=time]").nth(1)
    end.fill("18:00")
    page.locator("main h2").first.tap()  # the keyboard goes away, the dock comes back
    expect(page.locator(".log-col-rail")).to_be_visible()
    page.wait_for_function(DELTA_IS, arg="+1.00h")
    assert _dock_numbers(page) == ("9h", "+1.00h")
    end.fill("16:00")
    page.locator("main h2").first.tap()
    page.wait_for_function(DELTA_IS, arg=f"{MINUS}1.00h")
    assert _dock_numbers(page) == ("7h", f"{MINUS}1.00h")
    assert page.locator(".log-col-rail .impact-cell:nth-child(2)").is_hidden()  # no "target" here


def test_pressing_the_docks_button_creates_the_entry(phone, base_url):
    page = phone(375, 800)
    _open(page, base_url, "log")
    button = page.locator(".log-col-rail button.btn-action")
    expect(button).to_have_text("Create entry")
    with httpx.Client(base_url=base_url) as c:
        assert c.get(f"/api/entries/{TODAY}").status_code == 404
        button.tap()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and c.get(f"/api/entries/{TODAY}").status_code != 200:
            time.sleep(0.2)
        r = c.get(f"/api/entries/{TODAY}")
        assert r.status_code == 200, r.text
        assert (r.json()["start_time"], r.json()["end_time"]) == ("09:00", "17:00")
    page.wait_for_selector(".save-ribbon.ribbon-show", timeout=5000)


def test_delete_stays_in_the_form_and_not_in_the_dock(phone, base_url):
    page = phone(375, 800)
    _open(page, base_url, "log")
    page.locator(".log-strip .plan-mini[aria-label='Oct 2026']").tap()  # a finger picks October
    day = page.locator("button.log-cal-day[aria-label='2026-10-27']")
    day.scroll_into_view_if_needed()
    day.tap()
    expect(page.locator(".log-col-rail button.btn-action")).to_have_text("Save changes")
    assert page.locator(".log-col-rail").get_by_role("button", name="Delete").count() == 0
    assert (
        page.locator(".log-form-card .log-delete").get_by_role("button", name="Delete").count() == 1
    )
    assert page.locator(".log-col-rail button").count() == 1


def test_the_toast_rides_above_the_bar_and_the_dock(phone, base_url):
    page = phone(375, 800)
    _open(page, base_url, "log")
    page.evaluate(f"() => {MAIN}.showToast('Saved', 'neutral')")
    page.wait_for_selector(".save-ribbon.ribbon-show", timeout=3000)
    _until(
        page,
        """() => {
          const r = document.querySelector('.save-ribbon').getBoundingClientRect();
          const dock = document.querySelector('.log-col-rail').getBoundingClientRect();
          return r.bottom <= dock.top + 0.5 && r.top >= 0 ? null : [r.top, r.bottom, dock.top];
        }""",
        "the toast is under the dock",
    )


# ── f. the year as twelve letters ─────────────────────────────────────────────

LETTERS = """() => [...document.querySelectorAll('.log-strip .plan-mini')].map(b => {
  const l = b.querySelector('.plan-mini-letter'), r = b.getBoundingClientRect();
  return { text: l.textContent, shown: getComputedStyle(l).display !== 'none',
           top: Math.round(r.top), w: r.width, h: r.height, colour: getComputedStyle(l).color,
           label: b.getAttribute('aria-label'), role: b.getAttribute('role'), cls: b.className };
})"""


def test_log_at_375_has_a_row_of_twelve_letters(phone, base_url):
    page = phone(375, 800)
    _open(page, base_url, "log")
    page.wait_for_selector(".log-strip .plan-mini")
    row = page.evaluate(LETTERS)
    assert "".join(m["text"] for m in row) == "JFMAMJJASOND"
    assert all(m["shown"] and m["role"] == "tab" for m in row), row
    assert len({m["top"] for m in row}) == 1, row  # one row
    assert all(m["w"] >= 24 and m["h"] >= 24 for m in row), row
    assert page.locator(".log-strip .plan-mini-grid").first.is_hidden()
    # the current month is lit (brass), the one with data is brighter than one without
    lit = [m for m in row if "active" in m["cls"].split()]
    assert [m["label"] for m in lit] == ["Nov 2026"], lit
    assert lit[0]["colour"] == "rgb(224, 179, 65)"  # --k-brass
    by = {m["label"]: m for m in row}
    assert "has-data" in by["Sep 2026"]["cls"] and "has-data" not in by["Mar 2026"]["cls"]
    assert by["Sep 2026"]["colour"] != by["Mar 2026"]["colour"]
    # a finger on a letter makes it the calendar's month
    assert _state(page, "calMonth") == 10
    page.locator(".log-strip .plan-mini[aria-label='Sep 2026']").tap()
    page.wait_for_function(f"() => {MAIN}.calMonth === 8")
    assert "active" in page.locator(".log-strip .plan-mini").nth(8).get_attribute("class")


def test_log_at_1280_keeps_its_mini_months_and_plan_keeps_them_on_a_phone(phone, base_url):
    page = phone(1280, 900, touch=False)
    _open(page, base_url, "log")
    page.wait_for_selector(".log-strip .plan-mini")
    assert page.locator(".log-strip .plan-mini-grid").first.is_visible()
    assert page.locator(".log-strip .plan-mini-letter").first.is_hidden()
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(f"{base_url}/#plan")
    page.wait_for_selector(".plan-strip .plan-mini")
    assert page.locator(".plan-strip .plan-mini").count() == 12
    assert page.locator(".plan-strip .plan-mini-grid").first.is_visible()
    assert page.locator(".plan-strip .plan-mini-title").first.is_visible()
    assert page.locator(".plan-strip .plan-mini-letter").first.is_hidden()


# ── g. the legend ─────────────────────────────────────────────────────────────


def test_the_legend_is_folded_on_a_phone_and_opens(phone, base_url):
    page = phone(375, 800)
    _open(page, base_url, "log")
    legend = page.locator("details.log-legend")
    assert legend.evaluate("e => e.open") is False
    assert page.locator(".log-legend .heatmap-legend").is_hidden()
    summary = legend.locator("summary")
    assert summary.inner_text().strip() == "Legend"
    summary.tap()
    assert legend.evaluate("e => e.open") is True
    expect(page.locator(".log-legend .heatmap-legend")).to_be_visible()
    assert page.locator(".log-legend .legend-item").first.is_visible()


@pytest.mark.parametrize("width", [1280, 641])
def test_from_641px_the_legend_is_open_and_has_no_summary(phone, base_url, width):
    page = phone(width, 900, touch=False)
    _open(page, base_url, "log")
    legend = page.locator("details.log-legend")
    assert legend.evaluate("e => e.open") is True
    assert legend.locator("summary").is_hidden()
    expect(page.locator(".log-legend .legend-item").first).to_be_visible()
    # crossing the breakpoint folds it and unfolds it again
    page.set_viewport_size({"width": 375, "height": 800})
    page.wait_for_function("() => !document.querySelector('details.log-legend').open")
    page.set_viewport_size({"width": width, "height": 900})
    page.wait_for_function("() => document.querySelector('details.log-legend').open")


# ── the two openers and the bulk button ───────────────────────────────────────


def test_add_break_and_add_note_sit_side_by_side_from_641px_and_stacked_below(phone, base_url):
    for width, side_by_side in ((1280, True), (641, True), (375, False)):
        page = phone(width, 900, touch=False)
        _open(page, base_url, "log")
        brk = page.get_by_role("button", name="+ Add break")
        note = page.get_by_role("button", name="+ Add note")
        brk.scroll_into_view_if_needed()
        a, b = brk.bounding_box(), note.bounding_box()
        if side_by_side:
            assert abs(a["y"] - b["y"]) <= 1 and b["x"] >= a["x"] + a["width"], (width, a, b)
        else:
            assert b["y"] >= a["y"] + a["height"], (width, a, b)
        assert page.get_by_role("button", name="+ Add note").count() == 1


@pytest.mark.parametrize("width", [1280, 375])
def test_log_multiple_days_is_the_size_of_a_head_button(phone, base_url, width):
    page = phone(width, 800, touch=False)
    _open(page, base_url, "log")
    page.locator(".bulk-trigger button").scroll_into_view_if_needed()
    got = page.evaluate(
        """() => {
          const sizes = el => { const cs = getComputedStyle(el), r = el.getBoundingClientRect();
            return [cs.fontSize, Math.round(r.height), cs.borderTopLeftRadius]; };
          const b = document.querySelector('.bulk-trigger button');
          const probe = document.createElement('button');
          probe.className = 'head-btn';
          probe.textContent = 'x';
          document.body.append(probe);
          const head = sizes(probe); probe.remove();
          return { bulk: sizes(b), head, cls: b.className };
        }"""
    )
    assert got["bulk"] == got["head"], got
    assert "head-btn" in got["cls"]


# ── h. the palette ────────────────────────────────────────────────────────────

PALETTE = """() => {
  const p = document.querySelector('.palette').getBoundingClientRect();
  const ul = document.querySelector('.palette ul'), u = ul.getBoundingClientRect();
  const first = ul.querySelector('li').getBoundingClientRect();
  const input = document.querySelector('.palette input').getBoundingClientRect();
  return { top: p.top, bottom: p.bottom, h: innerHeight, scrolls: ul.scrollHeight > ul.clientHeight,
           band: first.top - input.bottom,
           kbds: [...document.querySelectorAll('.palette kbd')].map(k => k.textContent.trim()),
           rows: ul.querySelectorAll('li[role=option]').length };
}"""


@pytest.mark.parametrize("size", [(375, 520), (320, 400), (375, 800)])
def test_the_palette_has_no_empty_key_no_blank_band_and_fits_the_screen(phone, base_url, size):
    page = phone(size[0], size[1])
    _open(page, base_url, "dashboard")
    page.keyboard.press(".")
    page.wait_for_selector(".palette li[role=option]")
    s = page.evaluate(PALETTE)
    assert s["rows"] == 10, s
    assert all(s["kbds"]), s["kbds"]  # no key chip without a key
    assert len(s["kbds"]) == 8, s["kbds"]  # PDF timesheet and Rate calculator have none
    assert s["band"] <= 6, s  # the list starts right under the field
    assert s["top"] >= 0 and s["bottom"] <= s["h"], s  # the panel is inside the visible screen
    if size[1] < 600:
        assert s["scrolls"], s  # the control: on this screen the list is longer than its room
    # the last row can be reached: ArrowUp from the first row wraps to it and brings it into view
    page.keyboard.press("ArrowUp")
    _until(
        page,
        """() => {
          const ul = document.querySelector('.palette ul'), u = ul.getBoundingClientRect();
          const last = [...ul.querySelectorAll('li[role=option]')].pop();
          const l = last.getBoundingClientRect();
          const reached = last.classList.contains('palette-selected')
            && l.top >= u.top - 1 && l.bottom <= u.bottom + 1;
          return reached ? null : { sel: last.className, u: [u.top, u.bottom], l: [l.top] };
        }""",
        "the last row is out of reach",
    )
    assert page.evaluate(PALETTE)["bottom"] <= size[1]


def test_the_palettes_brass_tick_slides_from_row_to_row(phone, base_url):
    page = phone(1280, 900, touch=False)
    _open(page, base_url, "dashboard")
    page.keyboard.press(".")
    page.wait_for_selector(".palette li[role=option]")
    TICK = """() => {
      const ul = document.querySelector('.palette ul'), tick = getComputedStyle(ul, '::before');
      const sel = ul.querySelector('li.palette-selected');
      const ty = new DOMMatrix(tick.transform).m42;
      const pad = parseFloat(tick.top);
      return { ty, pad, top: sel.offsetTop, left: tick.left, width: tick.width,
               bg: tick.backgroundColor, opacity: tick.opacity, sel: sel.textContent.trim() };
    }"""
    for want, presses in ((0, 0), (2, 2), (5, 3)):  # the row wanted, the presses to get there
        for _ in range(presses):
            page.keyboard.press("ArrowDown")
        deadline, got = time.monotonic() + 6, None
        while time.monotonic() < deadline:
            got = page.evaluate(TICK)
            if abs(got["ty"] + got["pad"] - got["top"]) <= 1.5:
                break
            time.sleep(0.1)
        assert abs(got["ty"] + got["pad"] - got["top"]) <= 1.5, (want, got)
        assert got["left"] == "0px" and got["width"] == "3px" and got["opacity"] == "1", got
        assert got["bg"] == "rgb(224, 179, 65)", got
    # the mouse moves it too: hovering a row selects it
    page.locator(".palette li[role=option]").nth(1).hover()
    _until(
        page,
        """() => {
          const ul = document.querySelector('.palette ul');
          const ty = new DOMMatrix(getComputedStyle(ul, '::before').transform).m42;
          const sel = ul.querySelector('li.palette-selected');
          const there = Math.abs(ty + 4 - sel.offsetTop) <= 1.5 && sel.textContent.includes('Plan');
          return there ? null : [ty, sel.textContent];
        }""",
        "the tick did not follow the mouse",
    )
