"""E2E: the notes on v50 that make the dial, the logo and the ribbon findable.

The tab title is just "Kronos"; the logo says it opens the year dial (a title, a wind on hover and a
brass callout once per browser); the ribbon in Log explains itself behind a "?" chip. The crown's
label and the coins and the bead are in test_year_dial.py and test_brass_surprises.py.

Every context of this suite has the callout's key set (conftest.py); the callout tests take it away
once per tab, so a reload keeps what the page itself wrote.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.e2e

TEXT = "New: press the logo to spin through your year"
KEY = "localStorage.getItem('k-dial-hint')"

# The key is absent on the first load of the tab and untouched after it: the page's own writes
# survive a reload. (The suite's init script sets it on every load, so this one removes it, once.)
ABSENT_ONCE = """
try {
  if (!sessionStorage.getItem('test-hint-removed')) {
    sessionStorage.setItem('test-hint-removed', '1');
    localStorage.removeItem('k-dial-hint');
  }
} catch (e) {}
"""

HINT = ".dial-hint"
SHOWN = (
    "() => { const h = document.querySelector('.dial-hint');"
    " return !!h && h.offsetParent !== null; }"
)
WINDING = "a => a.animationName === 'logo-tease'"


def _fresh(page, base_url, size=(1280, 900), *, calm=False, tab="dashboard"):
    """The app with the callout's key absent, on the real clock."""
    page.set_viewport_size({"width": size[0], "height": size[1]})
    if calm:
        page.emulate_media(reduced_motion="reduce")
    page.add_init_script(ABSENT_ONCE)
    page.goto(f"{base_url}/#{tab}")
    page.wait_for_selector(".brand-btn", state="attached", timeout=5000)


def _shown(page) -> bool:
    return page.evaluate(SHOWN)


# ── 1. the title ──────────────────────────────────────────────────────────────


def test_the_tab_is_called_kronos_and_the_ios_name_stays(page, base_url):
    page.goto(base_url)
    page.wait_for_selector(".brand-btn", state="attached")
    assert page.evaluate("document.title") == "Kronos"
    assert page.title() == "Kronos"
    ios = page.locator("meta[name='apple-mobile-web-app-title']").get_attribute("content")
    assert ios == "Kronos"


# ── 3. the logo ────────────────────────────────────────────────────────────────


def test_the_logo_says_what_it_opens_and_winds_on_hover_and_on_focus(page, base_url):
    page.goto(f"{base_url}/#dashboard")
    logo = page.locator(".brand-btn")
    assert logo.get_attribute("title") == "Your year as a dial (Y)"
    assert logo.get_attribute("aria-label") == "Open the year dial"  # the name stays plain
    img = ".brand-btn .brand-logo"
    assert page.evaluate(f"document.querySelector('{img}').getAnimations().length") == 0
    logo.hover()
    page.wait_for_function(f"() => document.querySelector('{img}').getAnimations().some({WINDING})")
    page.mouse.move(600, 500)  # away: the wind is over, nothing keeps turning
    page.wait_for_function(
        f"() => document.querySelector('{img}').getAnimations().length === 0", timeout=4000
    )
    # the keyboard gets the same: focus by Tab, not by a press
    page.evaluate("document.querySelector('.brand-btn').focus()")
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    page.wait_for_function(f"() => document.querySelector('{img}').getAnimations().some({WINDING})")
    # the wind is a quarter back and a spring: its keyframes go through -90 degrees
    quarter = page.evaluate(
        f"""() => document.querySelector('{img}').getAnimations()[0].effect.getKeyframes()
              .map(k => k.transform)"""
    )
    assert "rotate(-90deg)" in quarter, quarter
    spring = page.evaluate(
        f"getComputedStyle(document.querySelector('{img}')).animationTimingFunction"
    )
    assert spring == "cubic-bezier(0.34, 1.56, 0.64, 1)"


def test_reduced_motion_does_not_wind_the_logo(page, base_url):
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{base_url}/#dashboard")
    page.locator(".brand-btn").hover()
    page.wait_for_timeout(200)
    img = ".brand-btn .brand-logo"
    assert page.evaluate(f"document.querySelector('{img}').getAnimations().length") == 0


# ── 3. the callout ─────────────────────────────────────────────────────────────


def test_the_callout_shows_once_when_the_key_is_absent(page, base_url):
    _fresh(page, base_url)
    assert not _shown(page)  # not at once: ~1.2 s after the load
    page.wait_for_selector(HINT, state="visible", timeout=6000)
    box = page.locator(HINT)
    assert box.get_attribute("role") == "status"
    assert box.inner_text().replace("✕", "").strip() == TEXT
    assert page.get_by_role("button", name="Dismiss").is_visible()
    assert page.evaluate("document.activeElement === document.body")  # focus is not taken
    # the logo turns a quarter once, as the callout appears
    names = page.evaluate(
        "document.querySelector('.brand-logo').getAnimations().map(a => a.animationName)"
    )
    assert names == ["logo-quarter"], names
    quarter = page.evaluate(
        "document.querySelector('.brand-logo').getAnimations()[0]"
        ".effect.getKeyframes().map(k => k.transform)"
    )
    assert "rotate(-90deg)" in quarter, quarter
    # under the logo
    logo = page.locator(".brand-btn").bounding_box()
    cbox = box.bounding_box()
    assert cbox["y"] >= logo["y"] + logo["height"]
    assert abs(cbox["x"] - logo["x"]) < 6


def test_closing_it_keeps_it_closed_for_good(page, base_url):
    _fresh(page, base_url)
    page.wait_for_selector(HINT, state="visible", timeout=6000)
    assert page.evaluate(KEY) is None  # showing it writes nothing
    page.get_by_role("button", name="Dismiss").click()
    page.wait_for_selector(HINT, state="hidden")
    assert page.evaluate(KEY) == "1"
    page.reload()
    page.wait_for_selector(".brand-btn", state="attached")
    page.wait_for_timeout(2000)  # past the 1.2 s it takes to appear
    assert not _shown(page)
    assert page.evaluate(KEY) == "1"


def test_with_the_key_set_it_never_shows(page, base_url):
    page.goto(f"{base_url}/#dashboard")  # the suite's own context has the key
    page.wait_for_selector(".brand-btn", state="attached")
    assert page.evaluate(KEY) == "1"
    page.wait_for_timeout(2000)
    assert not _shown(page)
    # not in the page at all: a hidden copy would still match a test's `text=Log`
    assert page.locator(HINT).count() == 0


def test_escape_closes_it(page, base_url):
    _fresh(page, base_url)
    page.wait_for_selector(HINT, state="visible", timeout=6000)
    page.keyboard.press("Escape")
    page.wait_for_selector(HINT, state="hidden")
    assert page.evaluate(KEY) == "1"
    assert page.evaluate("location.hash") == "#dashboard"


def test_escape_on_another_tab_closes_the_callout_and_stays_there(page, base_url):
    _fresh(page, base_url, tab="plan")
    page.wait_for_selector(HINT, state="visible", timeout=6000)
    page.keyboard.press("Escape")
    page.wait_for_selector(HINT, state="hidden")
    assert page.evaluate("location.hash") == "#plan"  # the callout took that Escape, not the tab


def test_pressing_the_logo_closes_it_and_opens_the_dial(page, base_url):
    _fresh(page, base_url)
    page.wait_for_selector(HINT, state="visible", timeout=6000)
    page.locator(".brand-btn").click()
    page.wait_for_selector("#yd", timeout=5000)
    assert not _shown(page)
    assert page.evaluate(KEY) == "1"


def test_opening_the_dial_first_means_it_never_shows(page, base_url):
    _fresh(page, base_url)
    page.keyboard.press("y")  # before the callout's 1.2 s are up
    # the dial takes Escape once it has read its day; before that a slow runner keeps it open
    page.wait_for_selector("#yd [data-yd=stage][data-day]:not([data-day=''])", timeout=8000)
    assert page.evaluate(KEY) == "1"  # written by opening, not by the callout
    page.keyboard.press("Escape")
    page.wait_for_selector("#yd", state="detached")
    page.wait_for_timeout(2000)
    assert not _shown(page)


def test_it_closes_by_itself_after_ten_seconds(page, base_url):
    page.clock.install()
    page.set_viewport_size({"width": 1280, "height": 900})
    page.add_init_script(ABSENT_ONCE)
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("main:not([x-cloak])", timeout=5000)
    page.clock.run_for(1300)
    page.wait_for_selector(HINT, state="visible")
    page.clock.run_for(9000)  # 9 s after it appeared: still there
    assert _shown(page)
    page.clock.run_for(1500)
    page.wait_for_selector(HINT, state="hidden")
    assert page.evaluate(KEY) == "1"


def test_without_storage_nothing_is_shown(page, base_url):
    page.add_init_script(
        "Storage.prototype.getItem = function () { throw new Error('blocked'); };"
        "Storage.prototype.setItem = function () { throw new Error('blocked'); };"
    )
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector(".brand-btn", state="attached")
    page.wait_for_timeout(2000)
    assert not _shown(page)


@pytest.mark.parametrize("size", [(320, 700), (375, 812), (1280, 900)], ids=["320", "375", "1280"])
def test_the_callout_stays_on_the_screen_and_the_page_does_not_scroll_sideways(
    page, base_url, size
):
    _fresh(page, base_url, size)
    page.wait_for_selector(HINT, state="visible", timeout=6000)
    page.wait_for_timeout(600)  # the pop-in is over
    got = page.evaluate(
        """() => { const r = document.querySelector('.dial-hint').getBoundingClientRect();
          return { left: r.left, right: r.right, bottom: r.bottom, w: innerWidth,
                   sw: document.documentElement.scrollWidth };
        }"""
    )
    assert got["left"] >= 0 and got["right"] <= got["w"], got
    assert got["sw"] <= got["w"], got
    if size[0] < 640:  # above the tab bar of a phone: it hangs from the top of the screen
        bar = page.locator(".tabs").bounding_box()
        assert got["bottom"] < bar["y"], (got, bar)


def test_the_callout_is_still_there_with_reduced_motion_and_the_logo_stays_still(page, base_url):
    _fresh(page, base_url, calm=True)
    page.wait_for_selector(HINT, state="visible", timeout=6000)
    assert page.evaluate("document.querySelector('.brand-logo').getAnimations().length") == 0
    assert page.evaluate("document.querySelector('.dial-hint').getAnimations().length") == 0


# ── 4. the ribbon's "?" chip ────────────────────────────────────────────────────

CHIP = ".log-form-card .q-chip"
AFTER = "(c) => getComputedStyle(c, '::after').content"
BOX = """(c) => { const s = getComputedStyle(c, '::after');
  const h = c.closest('.q-host').getBoundingClientRect();
  const left = h.left + parseFloat(s.left), right = left + parseFloat(s.width);
  return { left, right, w: innerWidth, sw: document.documentElement.scrollWidth }; }"""


@pytest.fixture
def screen(browser, page):
    """A page of the given size: a touch screen under 640px (a tap, not a mouse click)."""
    made = []

    def make(size):
        if size[0] >= 640:
            page.set_viewport_size({"width": size[0], "height": size[1]})
            return page
        ctx = browser.new_context(
            viewport={"width": size[0], "height": size[1]}, has_touch=True, locale="en-GB"
        )
        made.append(ctx)
        return ctx.new_page()

    yield make
    for ctx in made:
        ctx.close()


def _log(page, base_url, size):
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.goto(f"{base_url}/#log")
    page.wait_for_selector(CHIP)
    return page.locator(CHIP)


def _tap(chip, size):
    chip.tap() if size[0] < 640 else chip.click()


def test_the_chip_sits_next_to_the_employee_title_and_is_shut_at_rest(page, base_url):
    chip = _log(page, base_url, (1280, 900))
    assert chip.inner_text().strip() == "?"
    assert chip.get_attribute("aria-label") == "How the day bar works"
    assert page.get_by_role("button", name="How the day bar works").count() == 1
    title = page.locator(".log-form-card > .card-title h3").bounding_box()
    box = chip.bounding_box()
    assert box["x"] > title["x"] + title["width"] - 1  # after the title, on its line
    assert abs((box["y"] + box["height"] / 2) - (title["y"] + title["height"] / 2)) < 8
    assert chip.evaluate(AFTER) == "none"
    # the app's existing "?" chip, not a second pattern
    assert chip.evaluate("c => c.classList.contains('q-chip')")


@pytest.mark.parametrize("size", [(375, 812), (320, 700), (1280, 900)], ids=["375", "320", "1280"])
def test_the_chip_opens_on_a_tap_inside_the_screen_and_says_to_press_create_entry(
    screen, base_url, size
):
    chip = _log(screen(size), base_url, size)
    _tap(chip, size)
    text = chip.evaluate(AFTER)
    assert "Create entry" in text, text
    assert text.startswith('"The bar above the times is your day.')
    box = chip.evaluate(BOX)
    assert box["left"] >= 0 and box["right"] <= box["w"], box
    assert box["sw"] <= box["w"], box
    assert chip.get_attribute("title") == chip.get_attribute(
        "data-tip"
    )  # the mouse gets it as a tooltip


def test_the_chip_text_is_the_full_explanation(page, base_url):
    chip = _log(page, base_url, (1280, 900))
    tip = chip.get_attribute("data-tip")
    assert tip == (
        "The bar above the times is your day. Drag its ends to change when you started and "
        "finished, or drag the middle to move the whole day. Double-click the bar (double-tap on "
        "a phone) to add a break, drag a break to move it, and pull it off the bar to remove it. "
        "The flag marks when you reach your target. Freelance blocks have their own row: click "
        "one to edit it, or drag along the empty row to add one. Nothing is saved until you "
        "press Create entry."
    )


def test_the_chip_closes_on_escape_and_on_a_tap_outside(screen, base_url):
    size = (375, 812)
    page = screen(size)
    chip = _log(page, base_url, size)
    chip.tap()
    assert chip.evaluate(AFTER) != "none"
    page.keyboard.press("Escape")
    assert chip.evaluate(AFTER) == "none"
    assert (
        page.evaluate("location.hash") == "#log"
    )  # Escape shut the bubble, it did not leave the tab
    chip.tap()
    assert chip.evaluate(AFTER) != "none"
    page.locator(".log-form-card > .card-title h3").tap()
    assert chip.evaluate(AFTER) == "none"


def test_the_app_starts_once(page, base_url):
    """Alpine calls the component's init() by itself; an x-init calling it again doubled every
    request of the first load and every document listener."""
    seen = []
    page.on("request", lambda r: seen.append(r.url.split("?")[0]) if "/api/" in r.url else None)
    page.goto(f"{base_url}/#dashboard", wait_until="networkidle")
    page.wait_for_timeout(500)
    for path in ("/api/dashboard", "/api/config", "/api/entries", "/api/version"):
        assert sum(u.endswith(path) for u in seen) == 1, (path, seen)
