# ruff: noqa: E501
"""E2E: the dotted handle puts Day templates, Income sources and Accounts in the order the user wants.

The order is the API's (`PUT .../order`) and every picker follows because the lists arrive ordered and
are reordered in place. Everything here is seeded through the API under names of its own and uses
fixed dates, so it does not depend on the day it runs or on the network.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

MAIN = "Alpine.$data(document.querySelector('main'))"

LISTS = {
    "templates": {
        "api": "/api/templates",
        "group": "employee",
        "list": "#settings-templates .sort-list",
        "names": ["Tpl Alpha", "Tpl Bravo", "Tpl Charlie", "Tpl Delta"],
    },
    "sources": {
        "api": "/api/freelance/sources",
        "group": "freelance",
        "list": "#settings-sources .sort-list",
        "names": ["Src Alpha", "Src Bravo", "Src Charlie"],
    },
    "accounts": {
        "api": "/api/freelance/accounts",
        "group": "freelance",
        "list": "[data-testid=accounts-card] .sort-list",
        "names": ["Acct Alpha", "Acct Bravo", "Acct Charlie", "Acct Delta"],
    },
}
KINDS = list(LISTS)
HANDLE_FOCUSED = (
    "n => { const a = document.activeElement, r = a && a.closest('[data-sort-id]');"
    " return !!r && a.classList.contains('grip') && r.textContent.includes(n); }"
)
# the names of the rows in the order the DOM has them, archived rows included
ROW_NAMES = (
    "el => [...el.querySelectorAll(':scope > .template-item, :scope > .src-item')]"
    ".map(r => r.querySelector('strong').textContent.trim())"
)
TEXTS = (
    "s => [...document.querySelectorAll(s)].map(e => e.textContent.split(/\\s+/).join(' ').trim())"
)


def _create(c: httpx.Client, kind: str, name: str) -> dict:
    if kind == "templates":
        body = {"name": name, "start_time": "09:00", "end_time": "17:00", "breaks": []}
    elif kind == "sources":
        body = {"name": name, "hourly_rate": 50, "currency": "EUR"}
    else:
        body = {"name": name, "currency": "EUR", "kind": "bank"}
    r = c.post(LISTS[kind]["api"], json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        for kind in KINDS:
            for row in c.get(LISTS[kind]["api"]).json():
                c.delete(f"{LISTS[kind]['api']}/{row['id']}")


@pytest.fixture(autouse=True)
def _clean(base_url):
    _wipe(base_url)
    yield
    _wipe(base_url)


@pytest.fixture
def seeded(base_url):
    """The three lists with their rows, in creation order; the ids by kind."""
    ids = {}
    with httpx.Client(base_url=base_url) as c:
        for kind in KINDS:
            ids[kind] = [_create(c, kind, n)["id"] for n in LISTS[kind]["names"]]
    return ids


def _api_names(base_url: str, kind: str) -> list[str]:
    return [r["name"] for r in httpx.get(base_url + LISTS[kind]["api"]).json()]


def _wait_api(base_url: str, kind: str, want: list[str]) -> None:
    """Until the API's list is `want`: the save is a request that may still be on its way."""
    for _ in range(60):
        if _api_names(base_url, kind) == want:
            return
        time.sleep(0.1)
    assert _api_names(base_url, kind) == want


def _wait_puts(page, puts: list, n: int) -> None:
    for _ in range(60):
        if len(puts) >= n:
            break
        page.wait_for_timeout(100)  # also lets the page's events reach `puts`
    assert len(puts) == n, puts


def _open(page, base_url: str, kind: str, size=(1280, 1000)) -> None:
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.goto(f"{base_url}/#settings")
    page.wait_for_selector(".settings-content", state="attached", timeout=5000)
    page.evaluate(f"() => {MAIN}.setSettingsGroup('{LISTS[kind]['group']}')")
    page.wait_for_selector(LISTS[kind]["list"] + " .grip", timeout=5000)
    # in the middle of the window: the page scrolls by itself near an edge, and these drags are not about that
    page.locator(LISTS[kind]["list"]).evaluate("el => el.scrollIntoView({ block: 'center' })")


def _names(page, kind: str) -> list[str]:
    return page.locator(LISTS[kind]["list"]).evaluate(ROW_NAMES)


def _grip(page, kind: str, name: str):
    row = page.locator(LISTS[kind]["list"] + " > [data-sort-id]").filter(has_text=name)
    return row.locator(".grip")


def _centre(loc) -> tuple[float, float]:
    b = loc.bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def _watch_puts(page) -> list[dict]:
    """The body of every PUT to an /order address that the page sends."""
    puts: list[dict] = []

    def seen(req):
        if req.method == "PUT" and req.url.endswith("/order"):
            puts.append(json.loads(req.post_data))

    page.on("request", seen)
    return puts


def _top_of(page, kind: str) -> float:
    return page.locator(LISTS[kind]["list"] + " > [data-sort-id]").first.bounding_box()["y"]


def _drag_last_above_first(page, kind: str, release: bool = True) -> None:
    names = LISTS[kind]["names"]
    x, y = _centre(_grip(page, kind, names[-1]))
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 4, y - 6, steps=3)
    page.mouse.move(x, _top_of(page, kind) + 4, steps=14)
    if release:
        page.mouse.up()


@pytest.mark.parametrize("kind", KINDS)
def test_a_mouse_drag_moves_the_row_and_saves_the_order(page, base_url, seeded, kind):
    names = LISTS[kind]["names"]
    new = [names[-1], *names[:-1]]
    _open(page, base_url, kind)
    puts = _watch_puts(page)
    assert _names(page, kind) == names
    _drag_last_above_first(page, kind, release=False)
    # while the button is down: the row is lifted, a neighbour stepped aside, nothing moved in the DOM
    lifted = page.locator(LISTS[kind]["list"] + " > .sorting")
    expect(lifted).to_have_count(1)
    assert lifted.locator("strong").first.inner_text().strip() == names[-1]
    stepped = page.locator(LISTS[kind]["list"]).evaluate(
        "el => [...el.querySelectorAll(':scope > [data-sort-id]:not(.sorting)')]"
        ".filter(r => getComputedStyle(r).transform !== 'none').length"
    )
    assert stepped >= 1
    assert _names(page, kind) == names
    assert puts == []
    page.mouse.up()
    expect(page.locator(LISTS[kind]["list"] + " > .sorting")).to_have_count(0)
    assert _names(page, kind) == new
    _wait_api(base_url, kind, new)
    _wait_puts(page, puts, 1)
    assert puts[0]["ids"] == [r["id"] for r in httpx.get(base_url + LISTS[kind]["api"]).json()]
    # every transform is gone
    assert page.locator(LISTS[kind]["list"] + " [style*=transform]").count() == 0
    page.reload()
    _open(page, base_url, kind)
    assert _names(page, kind) == new


@pytest.mark.parametrize("kind", KINDS)
def test_b_the_arrow_keys_move_the_row_one_place(page, base_url, seeded, kind):
    names = LISTS[kind]["names"]
    n = len(names)
    middle = names[1]
    new = [middle, names[0], *names[2:]]
    _open(page, base_url, kind)
    puts = _watch_puts(page)
    _grip(page, kind, middle).focus()
    page.keyboard.press("ArrowUp")
    expect(page.get_by_test_id("sort-live")).to_have_text(f"{middle}, 1 of {n}")
    assert _names(page, kind) == new
    # the focus is on that row's handle
    focus = page.evaluate(
        "() => { const a = document.activeElement; const r = a.closest('[data-sort-id]');"
        " return [a.classList.contains('grip'), r && r.querySelector('strong').textContent.trim()]; }"
    )
    assert focus == [True, middle]
    _wait_api(base_url, kind, new)
    # at the top the key does nothing and sends nothing
    page.keyboard.press("ArrowUp")
    assert _names(page, kind) == new
    # a move that does send proves the page was being watched: two PUTs in all, none for the key at the top
    page.keyboard.press("ArrowDown")
    expect(page.get_by_test_id("sort-live")).to_have_text(f"{middle}, 2 of {n}")
    assert _names(page, kind) == names
    _wait_api(base_url, kind, names)
    _wait_puts(page, puts, 2)
    # and at the bottom the same
    _grip(page, kind, names[-1]).focus()
    page.keyboard.press("ArrowDown")
    assert _names(page, kind) == names
    page.keyboard.press("ArrowUp")
    expect(page.get_by_test_id("sort-live")).to_have_text(f"{names[-1]}, {n - 1} of {n}")
    _wait_puts(page, puts, 3)


def _touch(cdp, kind: str, x: float | None = None, y: float | None = None) -> None:
    points = [] if kind == "touchEnd" else [{"x": x, "y": y, "id": 1}]
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})


@pytest.fixture
def phone(browser):
    ctx = browser.new_context(
        viewport={"width": 375, "height": 800}, has_touch=True, locale="en-GB"
    )
    page = ctx.new_page()
    try:
        yield page, ctx.new_cdp_session(page)
    finally:
        ctx.close()


@pytest.mark.parametrize("kind", KINDS)
def test_c_a_finger_drags_by_the_handle_and_scrolls_by_the_name(base_url, seeded, phone, kind):
    page, cdp = phone
    names = LISTS[kind]["names"]
    new = [names[-1], *names[:-1]]
    _open(page, base_url, kind, size=(375, 800))
    puts = _watch_puts(page)
    # the handle: the finger moves up past the first row; the page stays where it was
    scroll0 = page.evaluate("window.scrollY")
    x, y = _centre(_grip(page, kind, names[-1]))
    top = _top_of(page, kind)
    _touch(cdp, "touchStart", x, y)
    # down a little first and then up, so that a page that could scroll either way would show it
    path = [y + 20 * i for i in range(1, 4)] + [
        y + 60 + (top + 6 - y - 60) * i / 12 for i in range(1, 13)
    ]
    for ty in path:
        _touch(cdp, "touchMove", x, ty)
        page.wait_for_timeout(16)  # the gesture's own pace: a finger is not instantaneous
    assert page.locator(LISTS[kind]["list"] + " > .sorting").count() == 1
    assert page.evaluate("window.scrollY") == scroll0
    _touch(cdp, "touchEnd")
    expect(page.locator(LISTS[kind]["list"] + " > .sorting")).to_have_count(0)
    assert _names(page, kind) == new
    assert page.evaluate("window.scrollY") == scroll0
    _wait_puts(page, puts, 1)
    _wait_api(base_url, kind, new)
    # a swipe that starts on a row's name scrolls the page and reorders nothing
    puts.clear()
    name = page.locator(LISTS[kind]["list"] + " > [data-sort-id] strong").nth(1)
    nx, ny = _centre(name)
    before = page.evaluate("window.scrollY")
    _touch(cdp, "touchStart", nx, ny)
    for i in range(1, 11):
        _touch(cdp, "touchMove", nx, ny + i * 18)
        page.wait_for_timeout(16)
    _touch(cdp, "touchEnd")
    page.wait_for_function("y => window.scrollY < y", arg=before, timeout=5000)
    assert page.locator(LISTS[kind]["list"] + " > .sorting").count() == 0
    assert _names(page, kind) == new
    assert puts == []


@pytest.mark.parametrize("how", ["mouse", "keyboard"])
@pytest.mark.parametrize("kind", KINDS)
def test_d_a_failed_save_puts_the_old_order_back(page, base_url, seeded, kind, how):
    names = LISTS[kind]["names"]
    _open(page, base_url, kind)
    refused = []

    def fail(route):
        if route.request.method == "PUT":
            refused.append(route.request.url)
            route.fulfill(status=500, json={"detail": "Could not save the order"})
        else:
            route.continue_()

    page.route("**/order", fail)
    if how == "mouse":
        _drag_last_above_first(page, kind)
    else:
        _grip(page, kind, names[-1]).focus()
        page.keyboard.press("ArrowUp")
    expect(page.locator(".error-banner")).to_be_visible()
    expect(page.locator(".error-banner")).to_have_text("Could not save the order")
    assert len(refused) == 1
    assert _names(page, kind) == names
    assert _api_names(base_url, kind) == names


@pytest.mark.parametrize("kind", KINDS)
def test_e_a_drop_where_it_started_sends_nothing(page, base_url, seeded, kind):
    names = LISTS[kind]["names"]
    _open(page, base_url, kind)
    puts = _watch_puts(page)
    x, y = _centre(_grip(page, kind, names[1]))
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 6, y - 5, steps=4)
    expect(page.locator(LISTS[kind]["list"] + " > .sorting")).to_have_count(1)
    page.mouse.move(x, y, steps=3)
    page.mouse.up()
    expect(page.locator(LISTS[kind]["list"] + " > .sorting")).to_have_count(0)
    assert _names(page, kind) == names
    # the page does see a real move: this one is sent, so the earlier silence was the page's
    _grip(page, kind, names[1]).focus()
    page.keyboard.press("ArrowUp")
    _wait_puts(page, puts, 1)


def test_f_an_archived_account_has_no_handle_and_stays_below(page, base_url):
    with httpx.Client(base_url=base_url) as c:
        a = _create(c, "accounts", "Acct Alpha")["id"]
        old = _create(c, "accounts", "Acct Old")["id"]
        b = _create(c, "accounts", "Acct Bravo")["id"]
        d = _create(c, "accounts", "Acct Charlie")["id"]
        assert c.put(f"/api/freelance/accounts/{old}", json={"archived": True}).status_code == 200
    _open(page, base_url, "accounts")
    puts = _watch_puts(page)
    assert _names(page, "accounts") == ["Acct Alpha", "Acct Bravo", "Acct Charlie", "Acct Old"]
    rows = page.locator(LISTS["accounts"]["list"] + " > .src-item")
    archived = rows.filter(has_text="Acct Old")
    assert archived.locator(".grip").count() == 0
    assert archived.get_attribute("data-sort-id") is None
    assert rows.locator(".grip").count() == 3
    x, y = _centre(_grip(page, "accounts", "Acct Charlie"))
    first = _top_of(page, "accounts")
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x, y - 8, steps=3)
    page.mouse.move(x, first + 4, steps=12)
    page.mouse.up()
    _wait_puts(page, puts, 1)
    assert puts[0]["ids"] == [d, a, b, old]
    assert [r["id"] for r in httpx.get(base_url + "/api/freelance/accounts").json()] == [
        d,
        a,
        b,
        old,
    ]
    assert _names(page, "accounts") == ["Acct Charlie", "Acct Alpha", "Acct Bravo", "Acct Old"]


def _move_to_top(page, base_url: str, kind: str, name: str) -> None:
    """The keyboard, one key per place, until the row is first and the server knows it."""
    _grip(page, kind, name).focus()
    want = [name, *[n for n in LISTS[kind]["names"] if n != name]]
    for _ in range(len(want)):
        page.keyboard.press("ArrowUp")
        page.wait_for_function(HANDLE_FOCUSED, arg=name)  # the redraw has given the focus back
    expect(page.locator(LISTS[kind]["list"] + " > [data-sort-id]").first).to_contain_text(name)
    _wait_api(base_url, kind, want)


def test_g_the_order_reaches_every_picker(page, base_url):
    monday = "2025-03-03"  # a fixed week, whatever day this runs
    with httpx.Client(base_url=base_url) as c:
        for n in LISTS["templates"]["names"]:
            _create(c, "templates", n)
        sources = [_create(c, "sources", n)["id"] for n in LISTS["sources"]["names"]]
        for n in LISTS["accounts"]["names"]:
            _create(c, "accounts", n)
        for s in sources:  # one block each, all in the same week
            body = {"date": monday, "source_id": s, "start_time": "09:00", "end_time": "10:00"}
            r = c.post("/api/freelance/blocks", json=body)
            assert r.status_code == 201, r.text

    # templates: the picker in Days and the quick-log buttons of the Dashboard
    _open(page, base_url, "templates")
    _move_to_top(page, base_url, "templates", "Tpl Delta")
    want = ["Tpl Delta", "Tpl Alpha", "Tpl Bravo", "Tpl Charlie"]
    page.goto(f"{base_url}/#days")
    page.reload()
    page.wait_for_selector(".template-pill", state="attached", timeout=5000)
    pills = page.evaluate(TEXTS, ".template-dropdown .template-pill")
    assert [p.split(" 09:00")[0] for p in pills] == want
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector(".quick-log-btn.ql-work", state="attached", timeout=5000)
    assert page.evaluate(TEXTS, ".quick-log-btn.ql-work") == want

    # sources: the picker of the Days form, the filter of Days > Freelance, the rows of one week
    _open(page, base_url, "sources")
    _move_to_top(page, base_url, "sources", "Src Charlie")
    want_s = ["Src Charlie", "Src Alpha", "Src Bravo"]
    page.goto(f"{base_url}/#days")
    page.reload()
    page.wait_for_selector("select[aria-label='Income source']", state="attached", timeout=5000)
    options = page.evaluate(TEXTS, "select[aria-label='Income source'] option")
    assert [o.split(" · ")[0] for o in options] == want_s
    page.goto(f"{base_url}/#weeks")
    page.reload()
    page.wait_for_selector("main .page-head", timeout=5000)
    page.evaluate(f"() => {{ {MAIN}.daysYear = 'all'; }}")
    page.get_by_role("radio", name="Freelance").click()
    page.wait_for_selector(".frow-name", state="attached", timeout=5000)
    assert page.evaluate(TEXTS, ".frow:not(.frow-head) .frow-name") == want_s
    page.wait_for_selector("tr.wk-lines .wk-line", state="attached", timeout=5000)
    in_a_week = page.evaluate(
        "() => { const rows = [...document.querySelectorAll('tr.wk-lines')]"
        ".find(t => t.querySelectorAll('.wk-line').length === 3);"
        " return rows ? [...rows.querySelectorAll('.wk-line')].map(l => l.dataset.source) : null; }"
    )
    assert in_a_week == want_s

    # accounts: the list that opens under a box of a source in Settings > Income sources
    _open(page, base_url, "accounts")
    _move_to_top(page, base_url, "accounts", "Acct Delta")
    want_a = ["Acct Delta", "Acct Alpha", "Acct Bravo", "Acct Charlie"]
    page.reload()
    box = page.get_by_role("button", name="Account 1 of Src Charlie: empty. Choose")
    box.click()
    page.wait_for_selector(".picker [role=option]", timeout=5000)
    assert page.evaluate(TEXTS, ".picker .pk-name") == want_a


@pytest.mark.parametrize("kind", KINDS)
def test_h_reduced_motion_still_reorders_and_the_neighbours_do_not_animate(
    page, base_url, seeded, kind
):
    names = LISTS[kind]["names"]
    new = [names[-1], *names[:-1]]
    page.emulate_media(reduced_motion="reduce")
    _open(page, base_url, kind)
    _drag_last_above_first(page, kind, release=False)
    expect(page.locator(LISTS[kind]["list"] + " > .sorting")).to_have_count(1)
    transitions = page.locator(LISTS[kind]["list"]).evaluate(
        "el => [...el.querySelectorAll(':scope > [data-sort-id]:not(.sorting)')]"
        ".map(r => getComputedStyle(r).transitionDuration)"
    )
    assert transitions
    assert all(set(t.replace(" ", "").split(",")) <= {"0s"} for t in transitions), transitions
    page.mouse.up()
    expect(page.locator(LISTS[kind]["list"] + " > .sorting")).to_have_count(0)
    assert _names(page, kind) == new
    animations = page.locator(LISTS[kind]["list"] + " > .landed").evaluate_all(
        "rs => rs.map(r => getComputedStyle(r).animationName)"
    )
    assert set(animations) <= {"none"}, animations
    _wait_api(base_url, kind, new)


def test_the_neighbours_do_animate_without_reduced_motion(page, base_url, seeded):
    """A positive control for h: the same drag, motion allowed, gives the neighbours a transition."""
    _open(page, base_url, "templates")
    _drag_last_above_first(page, "templates", release=False)
    transitions = page.locator(LISTS["templates"]["list"]).evaluate(
        "el => [...el.querySelectorAll(':scope > [data-sort-id]:not(.sorting)')]"
        ".map(r => getComputedStyle(r).transitionDuration)"
    )
    page.mouse.up()
    assert transitions
    assert all(t != "0s" for t in transitions), transitions


# ── what the first review found missing ─────────────────────────────────────────────────────────────

SRC_COLOURS = (
    "el => Object.fromEntries([...el.querySelectorAll(':scope > .src-item')]"
    ".map(r => [r.querySelector('strong').textContent.trim(),"
    " getComputedStyle(r).getPropertyValue('--src').trim()]))"
)
STRAY = (
    "el => [...el.querySelectorAll(':scope > [data-sort-id]')]"
    ".filter(r => r.style.transform || r.classList.contains('sorting')).length"
)


def _press_and_move(page, kind: str, name: str, to_y: float, steps: int = 14, button="left"):
    """Button down on a row's handle and the pointer carried to `to_y`; the button stays down."""
    x, y = _centre(_grip(page, kind, name))
    page.mouse.move(x, y)
    page.mouse.down(button=button)
    page.mouse.move(x + 3, y + (6 if to_y > y else -6), steps=3)
    page.mouse.move(x, to_y, steps=steps)
    return x, y


def _rows_box(page, kind: str) -> dict:
    return page.locator(LISTS[kind]["list"]).evaluate(
        "el => { const r = el.getBoundingClientRect(); return { top: r.top, bottom: r.bottom }; }"
    )


def test_a_source_keeps_its_colour_when_it_is_moved(page, base_url, seeded):
    _open(page, base_url, "sources")
    before = page.locator(LISTS["sources"]["list"]).evaluate(SRC_COLOURS)
    assert len(set(before.values())) == len(before) == 3, before
    names = LISTS["sources"]["names"]
    _drag_last_above_first(page, "sources")
    expect(page.locator(LISTS["sources"]["list"] + " > [data-sort-id]").first).to_contain_text(
        names[-1]
    )
    assert page.locator(LISTS["sources"]["list"]).evaluate(SRC_COLOURS) == before
    _wait_api(base_url, "sources", [names[-1], *names[:-1]])
    page.reload()
    _open(page, base_url, "sources")
    assert _names(page, "sources")[0] == names[-1]
    assert page.locator(LISTS["sources"]["list"]).evaluate(SRC_COLOURS) == before


@pytest.mark.parametrize("kind", KINDS)
def test_a_drag_downwards_puts_the_first_row_last(page, base_url, seeded, kind):
    names = LISTS[kind]["names"]
    new = [*names[1:], names[0]]
    _open(page, base_url, kind)
    last = page.locator(LISTS[kind]["list"] + " > [data-sort-id]").last.bounding_box()
    _press_and_move(page, kind, names[0], last["y"] + last["height"] - 4)
    page.mouse.up()
    expect(page.locator(LISTS[kind]["list"] + " > .sorting")).to_have_count(0)
    assert _names(page, kind) == new
    _wait_api(base_url, kind, new)
    page.reload()
    _open(page, base_url, kind)
    assert _names(page, kind) == new


@pytest.mark.parametrize("kind", KINDS)
def test_the_window_listeners_are_gone_after_a_drop(page, base_url, seeded, kind):
    names = LISTS[kind]["names"]
    _open(page, base_url, kind)
    puts = _watch_puts(page)
    _drag_last_above_first(page, kind)
    _wait_puts(page, puts, 1)
    # the button is up: a pointer wandering about moves nothing
    page.mouse.move(900, 150, steps=6)
    page.mouse.move(600, 900, steps=6)
    assert page.locator(LISTS[kind]["list"]).evaluate(STRAY) == 0
    # and the next drag, of another row, still works and saves
    now = _names(page, kind)
    assert now == [names[-1], *names[:-1]]
    _press_and_move(page, kind, now[-1], _top_of(page, kind) + 4)
    page.mouse.up()
    again = [now[-1], *now[:-1]]
    expect(page.locator(LISTS[kind]["list"] + " > .sorting")).to_have_count(0)
    assert _names(page, kind) == again
    _wait_puts(page, puts, 2)
    _wait_api(base_url, kind, again)


@pytest.mark.parametrize("kind", KINDS)
def test_a_cancelled_pointer_drops_nothing(page, base_url, seeded, kind):
    names = LISTS[kind]["names"]
    _open(page, base_url, kind)
    puts = _watch_puts(page)
    _press_and_move(page, kind, names[-1], _top_of(page, kind) + 4)
    stepped = page.locator(LISTS[kind]["list"]).evaluate(
        "el => [...el.querySelectorAll(':scope > [data-sort-id]:not(.sorting)')]"
        ".filter(r => getComputedStyle(r).transform !== 'none').length"
    )
    assert stepped >= 1
    page.evaluate("() => window.dispatchEvent(new PointerEvent('pointercancel'))")
    expect(page.locator(LISTS[kind]["list"] + " > .sorting")).to_have_count(0)
    assert page.locator(LISTS[kind]["list"]).evaluate(STRAY) == 0
    assert _names(page, kind) == names
    page.mouse.up()
    assert _names(page, kind) == names
    # the page does send when it should: this keyboard move is the first and only PUT
    _grip(page, kind, names[1]).focus()
    page.keyboard.press("ArrowUp")
    _wait_puts(page, puts, 1)
    assert _api_names(base_url, kind) in ([names[1], names[0], *names[2:]], names)


@pytest.mark.parametrize("where", ["above", "below"])
@pytest.mark.parametrize("kind", KINDS)
def test_the_dragged_row_stays_inside_its_list(page, base_url, seeded, kind, where):
    names = LISTS[kind]["names"]
    _open(page, base_url, kind)
    box = _rows_box(page, kind)
    if where == "above":
        name, to_y = names[-1], box["top"] - 40
        gap = box["top"] - to_y
    else:
        # not closer to the window's edge than the page's own auto-scroll starts (72px)
        name, to_y = names[0], min(box["bottom"] + 40, 1000 - 90)
        gap = to_y - box["bottom"]
    assert 80 < to_y < 1000 - 72 and gap >= 10, (to_y, gap)
    _press_and_move(page, kind, name, to_y, steps=20)
    lifted = page.locator(LISTS[kind]["list"] + " > .sorting")
    expect(lifted).to_have_count(1)
    row = lifted.bounding_box()
    box = _rows_box(page, kind)
    assert row["y"] >= box["top"] - 10, (row, box)
    assert row["y"] + row["height"] <= box["bottom"] + 10, (row, box)
    page.mouse.up()
    expect(page.locator(LISTS[kind]["list"] + " > .sorting")).to_have_count(0)
    want = [names[-1], *names[:-1]] if where == "above" else [*names[1:], names[0]]
    assert _names(page, kind) == want


@pytest.mark.parametrize("kind", KINDS)
def test_the_right_button_does_not_start_a_drag(page, base_url, seeded, kind):
    names = LISTS[kind]["names"]
    _open(page, base_url, kind)
    puts = _watch_puts(page)
    _press_and_move(page, kind, names[-1], _top_of(page, kind) + 4, button="right")
    assert page.locator(LISTS[kind]["list"] + " > .sorting").count() == 0
    assert page.locator(LISTS[kind]["list"]).evaluate(STRAY) == 0
    page.mouse.up(button="right")
    assert _names(page, kind) == names
    # the page does send when it should: this keyboard move is the first and only PUT
    _grip(page, kind, names[1]).focus()
    page.keyboard.press("ArrowUp")
    _wait_puts(page, puts, 1)


# ── rows of unequal height: the leading edge of the dragged row decides, not its centre ─────────────


def _tall(page, ids: list[int], px: int = 160) -> None:
    """Make some rows of the templates list taller on purpose, so that nothing depends on fonts."""
    rules = " ".join(f'.sort-list > [data-sort-id="{i}"] {{ min-height: {px}px; }}' for i in ids)
    page.add_style_tag(content=rules)
    page.locator(LISTS["templates"]["list"]).evaluate(
        "el => el.scrollIntoView({ block: 'center' })"
    )


def _box(page, name: str) -> dict:
    row = page.locator(LISTS["templates"]["list"] + " > [data-sort-id]").filter(has_text=name)
    return row.bounding_box()


def _settled(page, base_url: str, want: list[str]) -> None:
    expect(page.locator(LISTS["templates"]["list"] + " > .sorting")).to_have_count(0)
    assert _names(page, "templates") == want
    _wait_api(base_url, "templates", want)
    page.reload()
    _open(page, base_url, "templates")
    assert _names(page, "templates") == want


def test_a_tall_first_row_dragged_to_the_bottom_lands_last(page, base_url, seeded):
    names = LISTS["templates"]["names"]
    _open(page, base_url, "templates")
    _tall(page, seeded["templates"][:1])
    last = _box(page, names[-1])
    _press_and_move(page, "templates", names[0], last["y"] + last["height"] - 4)
    page.mouse.up()
    _settled(page, base_url, [*names[1:], names[0]])


def test_a_short_last_row_dragged_to_the_top_lands_first(page, base_url, seeded):
    names = LISTS["templates"]["names"]
    _open(page, base_url, "templates")
    _tall(page, seeded["templates"][:1])
    _press_and_move(page, "templates", names[-1], _box(page, names[0])["y"] + 4)
    page.mouse.up()
    _settled(page, base_url, [names[-1], *names[:-1]])


def test_a_tall_last_row_dragged_to_the_top_lands_first(page, base_url, seeded):
    names = LISTS["templates"]["names"]
    _open(page, base_url, "templates")
    _tall(page, seeded["templates"][-1:])
    _press_and_move(page, "templates", names[-1], _box(page, names[0])["y"] + 4)
    page.mouse.up()
    _settled(page, base_url, [names[-1], *names[:-1]])


def test_a_tall_row_dragged_one_place_lands_one_place_lower(page, base_url, seeded):
    names = LISTS["templates"]["names"]
    _open(page, base_url, "templates")
    _tall(page, seeded["templates"][:1])
    first, nxt = _box(page, names[0]), _box(page, names[1])
    # its bottom edge just past the middle of the next row, far short of the one after
    delta = (nxt["y"] + nxt["height"] / 2 + 6) - (first["y"] + first["height"])
    x, y = _centre(_grip(page, "templates", names[0]))
    _press_and_move(page, "templates", names[0], y + delta)
    page.mouse.up()
    _settled(page, base_url, [names[1], names[0], *names[2:]])
