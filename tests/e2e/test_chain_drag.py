# ruff: noqa: E501
"""E2E: an account is dragged by its name into a box of an income source (Settings > Freelance).

With a mouse the drag begins once the pointer has moved 5px; with a finger after holding the name 300 ms,
so that a swipe on a name still scrolls the page. The drop does what choosing the account in the box's
list does: `chainSet`, one PUT of the source's `chain`. Everything here is seeded through the API under
names of its own and uses fixed dates, so it does not depend on the day it runs or on the network.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
from playwright.sync_api import expect

from .conftest import wait_until

pytestmark = pytest.mark.e2e

MAIN = "Alpine.$data(document.querySelector('main'))"

A, B, C, D = "Bank Alpha", "Wallet Bravo", "Cash Charlie", "Other Delta"
ACCOUNTS = [(A, "bank", "EUR"), (B, "wallet", "USD"), (C, "cash", "EUR"), (D, "other", "GBP")]
S1, S2 = "Drag Src One", "Drag Src Two"
CARD = "[data-testid=accounts-card]"
HOLD = 350  # ms: a finger that holds this long carries the name
QUICK = 150  # ms: a finger that moves after this long is scrolling

# What the page did, whatever the moment the test looked at it: the copies of a name that were ever
# drawn, and whether one ever flew (the fly is a class on the copy, set when the drag ends).
SPY = """() => {
  window.__spy = { ghosts: 0, fly: false };
  new MutationObserver(ms => {
    for (const m of ms) {
      for (const n of m.addedNodes) if (n.classList && n.classList.contains('acct-ghost')) window.__spy.ghosts++;
      const t = m.target;
      if (m.type === 'attributes' && t.classList && t.classList.contains('acct-ghost') && t.classList.contains('fly')) window.__spy.fly = true;
    }
  }).observe(document.body, { childList: true, attributes: true, attributeFilter: ['class'], subtree: true });
}"""


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")
        for a in c.get("/api/freelance/accounts").json():
            c.delete(f"/api/freelance/accounts/{a['id']}")


@pytest.fixture(autouse=True)
def _clean(base_url):
    _wipe(base_url)
    yield
    _wipe(base_url)


def _world(base_url: str, sources=(S1, S2), accounts=ACCOUNTS) -> dict[str, int]:
    """The accounts and the sources, by name, with no chain; the ids by name."""
    ids: dict[str, int] = {}
    with httpx.Client(base_url=base_url) as c:
        for name, kind, cur in accounts:
            r = c.post(
                "/api/freelance/accounts", json={"name": name, "currency": cur, "kind": kind}
            )
            assert r.status_code == 201, r.text
            ids[name] = r.json()["id"]
        for name in sources:
            body = {"name": name, "hourly_rate": 50, "currency": "EUR"}
            r = c.post("/api/freelance/sources", json=body)
            assert r.status_code == 201, r.text
            ids[name] = r.json()["id"]
    return ids


def _set_chain(base_url: str, ids: dict[str, int], source: str, names: list[str]) -> None:
    r = httpx.put(
        f"{base_url}/api/freelance/sources/{ids[source]}",
        json={"chain": [ids[n] for n in names]},
    )
    assert r.status_code == 200, r.text


def _api_chain(base_url: str, ids: dict[str, int], source: str) -> list[str]:
    by_id = {a["id"]: a["name"] for a in httpx.get(f"{base_url}/api/freelance/accounts").json()}
    rows = httpx.get(f"{base_url}/api/freelance/sources").json()
    return [by_id[i] for i in next(s for s in rows if s["id"] == ids[source])["chain"]]


def _wait_chain(page, base_url: str, ids: dict[str, int], source: str, want: list[str]) -> None:
    """Until the API's chain is `want`: the save is a request that may still be on its way."""
    wait_until(
        page,
        lambda: _api_chain(base_url, ids, source) == want,
        lambda: f"the chain of {source} is {_api_chain(base_url, ids, source)}, not {want}",
    )


def _open(page, base_url: str, size=(1280, 1500)) -> None:
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.goto(f"{base_url}/#settings")
    page.wait_for_selector(".settings-content", state="attached", timeout=5000)
    page.evaluate(f"() => {MAIN}.setSettingsGroup('freelance')")
    page.wait_for_selector(f"{CARD} .acct-chip", timeout=5000)
    page.wait_for_selector("[role=group] .slot", timeout=5000)
    page.wait_for_load_state(
        "networkidle"
    )  # the lists load after the page opens and move what is below
    page.evaluate(SPY)


def _group(page, source: str):
    return page.get_by_role("group", name=f"Accounts of {source}, in order")


def _slot(page, source: str, n: int):
    """Box `n` (1 to 4) of a source."""
    return _group(page, source).locator(".slot").nth(n - 1)


def _shown(page, source: str) -> list[str]:
    """What the four boxes show: the account's name, or the number of an empty box."""
    return _group(page, source).evaluate(
        "el => [...el.querySelectorAll('.slot')].map(s => s.querySelector('.slot-name')"
        " ? s.querySelector('.slot-name').textContent.trim() : s.querySelector('.slot-n').textContent.trim())"
    )


def _expected_boxes(names: list[str]) -> list[str]:
    return [*names, *[str(i) for i in range(len(names) + 1, 5)]]


def _watch_puts(page) -> list[dict]:
    """The body of every PUT to a source that the page sends."""
    puts: list[dict] = []

    def seen(req):
        if req.method == "PUT" and re.search(r"/api/freelance/sources/\d+$", req.url):
            puts.append(json.loads(req.post_data))

    page.on("request", seen)
    return puts


def _watch_orders(page) -> list[dict]:
    """The body of every PUT to an /order address that the page sends."""
    puts: list[dict] = []

    def seen(req):
        if req.method == "PUT" and req.url.endswith("/order"):
            puts.append(json.loads(req.post_data))

    page.on("request", seen)
    return puts


def _wait_puts(page, puts: list, n: int) -> None:
    wait_until(page, lambda: len(puts) >= n, lambda: f"{n} PUT(s); the page sent {puts}")
    assert len(puts) == n, puts


def _chip(page, name: str):
    return page.locator(f"{CARD} .acct-chip").filter(has_text=re.compile(rf"^\s*{name}\s*$"))


def _ghosts(page):
    return page.locator(".acct-ghost")


def _lit(page):
    return page.locator(".slot.over")


def _centre(loc) -> tuple[float, float]:
    b = loc.bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def _spied(page) -> dict:
    return page.evaluate("() => window.__spy")


def _calm(page) -> None:
    """Nothing is left of a drag: no copy, no lit or breathing box, no dimmed name, no list."""
    expect(_ghosts(page)).to_have_count(0)
    expect(_lit(page)).to_have_count(0)
    expect(page.locator(f"{CARD} .acct-chip.lifted")).to_have_count(0)
    expect(page.locator(f"{CARD} .acct-chip.held")).to_have_count(0)
    assert page.evaluate("() => document.body.classList.contains('dragging-acct')") is False
    assert page.locator(".picker").count() == 0
    names = page.evaluate(
        "() => [...document.querySelectorAll('.slot')].map(s => getComputedStyle(s).animationName)"
    )
    assert "slot-breathe" not in names, names  # (the box that was filled may still be popping)


def _grab(page, name: str) -> tuple[float, float]:
    """Mouse down in the middle of an account's name."""
    x, y = _centre(_chip(page, name))
    page.mouse.move(x, y)
    page.mouse.down()
    return x, y


def _begin(page, x: float, y: float) -> None:
    """Past the 5px the drag needs, a little up and to the right."""
    page.mouse.move(x + 8, y - 8, steps=3)
    expect(_ghosts(page)).to_have_count(1)


def _carry(page, name: str, to_xy: tuple[float, float], release: bool = True) -> None:
    x, y = _grab(page, name)
    page.mouse.move(x + 8, y - 8, steps=3)
    page.mouse.move(to_xy[0], to_xy[1], steps=14)
    if release:
        page.mouse.up()


def _carry_to_box(page, name: str, source: str, n: int, release: bool = True) -> None:
    _carry(page, name, _centre(_slot(page, source, n)), release)


# ── a: a mouse onto an empty box ────────────────────────────────────────────────────────────────────


def test_a_the_mouse_drags_a_name_onto_an_empty_box(page, base_url):
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [A])
    _open(page, base_url)
    puts = _watch_puts(page)
    x, y = _grab(page, D)
    # pressed, not moved: nothing yet
    expect(_ghosts(page)).to_have_count(0)
    _begin(page, x, y)
    # a copy of the name, the name itself dimmed, every box of every source breathing
    assert _ghosts(page).inner_text().strip() == D
    assert _ghosts(page).locator("svg").bounding_box()["width"] > 8  # its icon is drawn
    expect(_chip(page, D)).to_have_class(re.compile(r"\blifted\b"))
    assert page.evaluate("() => document.body.classList.contains('dragging-acct')") is True
    names = page.evaluate(
        "() => [...document.querySelectorAll('.slot')].map(s => getComputedStyle(s).animationName)"
    )
    assert len(names) == 8 and set(names) == {"slot-breathe"}, names
    # the box under the pointer is lit, and only that one; the copy is above the pointer
    tx, ty = _centre(_slot(page, S1, 2))
    page.mouse.move(tx, ty, steps=14)
    expect(_lit(page)).to_have_count(1)
    assert _lit(page).get_attribute("data-sid") == str(ids[S1])
    assert _lit(page).get_attribute("data-i") == "1"
    g = _ghosts(page).bounding_box()
    assert abs(g["x"] + g["width"] / 2 - tx) < 6 and g["y"] + g["height"] / 2 < ty, (g, tx, ty)
    assert puts == []
    page.mouse.up()
    _calm(page)
    assert _shown(page, S1) == _expected_boxes([A, D])
    _wait_chain(page, base_url, ids, S1, [A, D])
    _wait_puts(page, puts, 1)
    page.wait_for_load_state("networkidle")
    assert puts == [{"chain": [ids[A], ids[D]]}]
    # the copy flew into the box
    assert _spied(page) == {"ghosts": 1, "fly": True}
    # nothing else changed
    assert _api_chain(base_url, ids, S2) == []


# ── b: a mouse onto a filled box, and an account that is already in the chain ────────────────────────


@pytest.mark.parametrize(
    "start,dragged,box,want",
    [
        ([A, B], D, 1, [D, B]),
        ([A, B, C], A, 3, [B, A]),
        ([A], A, 1, [A]),
    ],
    ids=["replaces", "moves", "same"],
)
def test_b_a_drop_on_a_filled_box_replaces_it_and_an_account_in_the_chain_moves(
    page, base_url, start, dragged, box, want
):
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, start)
    _open(page, base_url)
    puts = _watch_puts(page)
    _carry_to_box(page, dragged, S1, box)
    _calm(page)
    assert _shown(page, S1) == _expected_boxes(want)
    _wait_chain(page, base_url, ids, S1, want)
    page.wait_for_load_state("networkidle")
    assert len(puts) == (0 if want == start else 1), puts
    # a drop is the same move as choosing the account in the box's list
    assert _shown(page, S1) == _expected_boxes(want)


def test_b_a_drop_on_the_second_source_leaves_the_first_alone(page, base_url):
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [A])
    _open(page, base_url)
    puts = _watch_puts(page)
    _carry_to_box(page, B, S2, 1)
    _calm(page)
    _wait_chain(page, base_url, ids, S2, [B])
    _wait_puts(page, puts, 1)
    assert _shown(page, S1) == _expected_boxes([A])
    assert _shown(page, S2) == _expected_boxes([B])
    assert puts == [{"chain": [ids[B]]}]


# ── c: a drop elsewhere, a press without moving, a drag that has not gone 5px ────────────────────────


def test_c_a_drop_outside_a_box_changes_nothing_and_a_press_without_moving_does_nothing(
    page, base_url
):
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [A])
    _open(page, base_url)
    puts = _watch_puts(page)
    orders = _watch_orders(page)
    # a press and a release in the same place
    _grab(page, D)
    expect(_ghosts(page)).to_have_count(0)
    page.mouse.up()
    _calm(page)
    # 3px is not a drag yet
    x, y = _grab(page, D)
    page.mouse.move(x + 3, y, steps=2)
    expect(_ghosts(page)).to_have_count(0)
    page.mouse.up()
    _calm(page)
    assert _spied(page)["ghosts"] == 0
    # carried, and let go over the heading of the card: not a box
    out = _centre(page.locator(f"{CARD} h3"))
    x, y = _grab(page, C)
    page.mouse.move(x + 8, y - 8, steps=3)
    page.mouse.move(out[0], out[1], steps=12)
    expect(_ghosts(page)).to_have_count(1)
    expect(_lit(page)).to_have_count(0)
    page.mouse.up()
    _calm(page)
    assert _spied(page) == {"ghosts": 1, "fly": True}
    assert _shown(page, S1) == _expected_boxes([A])
    assert _shown(page, S2) == _expected_boxes([])
    # the name never reorders the list
    assert orders == []
    assert puts == []
    # a box that was lit on the way and is left again before the drop is not the drop
    x, y = _grab(page, C)
    page.mouse.move(x + 8, y - 8, steps=3)
    page.mouse.move(*_centre(_slot(page, S2, 1)), steps=12)
    expect(_lit(page)).to_have_count(1)
    page.mouse.move(out[0], out[1], steps=12)
    expect(_lit(page)).to_have_count(0)
    page.mouse.up()
    _calm(page)
    assert _shown(page, S2) == _expected_boxes([])
    assert puts == []
    # the same watcher sees a real drop: the silence above was the page's
    _carry_to_box(page, D, S1, 2)
    _wait_puts(page, puts, 1)
    _wait_chain(page, base_url, ids, S1, [A, D])


# ── d: only a live account's name can be taken ──────────────────────────────────────────────────────


def test_d_an_archived_accounts_name_cannot_be_dragged(page, base_url):
    ids = _world(base_url)
    assert (
        httpx.put(
            f"{base_url}/api/freelance/accounts/{ids[D]}", json={"archived": True}
        ).status_code
        == 200
    )
    _open(page, base_url)
    puts = _watch_puts(page)
    row = page.locator(f"{CARD} .acct-item").filter(has_text=D)
    expect(row).to_have_count(1)
    assert row.locator(".acct-chip").count() == 0
    assert row.locator(".acct-who").get_attribute("title") is None
    # the live ones are chips with their tip
    chips = page.locator(f"{CARD} .acct-chip")
    expect(chips).to_have_count(3)
    for i in range(3):
        assert chips.nth(i).get_attribute("title") == "Drag into a box above"
    # pressed and moved, a name that is archived drags nothing
    x, y = _centre(row.locator(".acct-who"))
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 8, y - 8, steps=3)
    page.mouse.move(*_centre(_slot(page, S1, 1)), steps=12)
    assert _spied(page)["ghosts"] == 0
    expect(_lit(page)).to_have_count(0)
    page.mouse.up()
    _calm(page)
    assert _spied(page)["ghosts"] == 0
    assert puts == []
    assert _shown(page, S1) == _expected_boxes([])
    # the control: the same gesture on a live name carries it
    _carry_to_box(page, A, S1, 1)
    _wait_chain(page, base_url, ids, S1, [A])
    assert _spied(page)["ghosts"] == 1


def test_d_a_name_is_not_a_control_and_a_long_press_or_a_right_click_opens_no_menu(page, base_url):
    _world(base_url)
    _open(page, base_url)
    chip = _chip(page, A)
    # not focusable, no role, no touch-action that would stop a swipe, text not selectable
    facts = chip.evaluate(
        "el => { const s = getComputedStyle(el); return [el.tabIndex, el.getAttribute('role'), el.getAttribute('tabindex'), s.touchAction, s.userSelect]; }"
    )
    assert facts == [-1, None, None, "auto", "none"], facts
    # the context menu is prevented on a name, and not on the heading beside it (the control)
    menu = "el => { const e = new MouseEvent('contextmenu', { bubbles: true, cancelable: true }); el.dispatchEvent(e); return e.defaultPrevented; }"
    assert chip.evaluate(menu) is True
    assert page.locator(f"{CARD} h3").evaluate(menu) is False
    # Tab never lands on a name
    page.locator(f"{CARD} h3").evaluate("el => { el.tabIndex = -1; el.focus(); }")
    for _ in range(8):
        page.keyboard.press("Tab")
        assert page.evaluate("() => !!document.activeElement.closest('.acct-chip')") is False


# ── e: the dotted handle still reorders, and does not carry ──────────────────────────────────────────


def test_e_pressing_the_handle_reorders_and_carries_nothing(page, base_url):
    ids = _world(base_url)
    _open(page, base_url)
    puts = _watch_puts(page)
    orders = _watch_orders(page)
    rows = page.locator(f"{CARD} .sort-list > [data-sort-id]")
    grip = rows.filter(has_text=D).locator(".grip")
    x, y = _centre(grip)
    top = rows.first.bounding_box()["y"]
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 4, y - 6, steps=3)
    page.mouse.move(x, top + 4, steps=14)
    # the row is lifted; no copy of a name, no box breathing
    expect(page.locator(f"{CARD} .sort-list > .sorting")).to_have_count(1)
    assert _spied(page)["ghosts"] == 0
    assert page.evaluate("() => document.body.classList.contains('dragging-acct')") is False
    page.mouse.up()
    expect(page.locator(f"{CARD} .sort-list > .sorting")).to_have_count(0)

    def names():
        return [a["name"] for a in httpx.get(f"{base_url}/api/freelance/accounts").json()]

    wait_until(page, lambda: names()[0] == D, lambda: f"{D} first in the API; it has {names()}")
    got = names()
    assert got == [D, A, B, C], got
    assert orders == [{"ids": [ids[D], ids[A], ids[B], ids[C]]}]
    assert _spied(page)["ghosts"] == 0
    assert puts == []


# ── f: a finger: a swipe scrolls, a hold carries ─────────────────────────────────────────────────────


def _touch(cdp, kind: str, x: float | None = None, y: float | None = None) -> None:
    points = [] if kind in ("touchEnd", "touchCancel") else [{"x": x, "y": y, "id": 1}]
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


def _bring(page, loc, y: float) -> tuple[float, float]:
    """Scroll the page so that the middle of `loc` is at `y` from the top of the window."""
    loc.evaluate(
        "(el, y) => { const r = el.getBoundingClientRect(); window.scrollBy(0, r.top + r.height / 2 - y); }",
        y,
    )
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame(() => r()))"
    )  # the frame that draws it
    return _centre(loc)


def _hold(page, cdp, name: str, y: float = 600) -> tuple[float, float]:
    x, y = _bring(page, _chip(page, name), y)
    _touch(cdp, "touchStart", x, y)
    return x, y


def _scroll_y(page) -> float:
    return page.evaluate("window.scrollY")


def test_f_a_swipe_on_a_name_scrolls_the_page_and_drags_nothing(base_url, phone):
    page, cdp = phone
    _world(base_url)
    _open(page, base_url, size=(375, 800))
    puts = _watch_puts(page)
    orders = _watch_orders(page)
    x, y = _bring(page, _chip(page, B), 500)
    before = _scroll_y(page)
    _touch(cdp, "touchStart", x, y)
    for i in range(1, 11):
        _touch(cdp, "touchMove", x, y - i * 18)
        page.wait_for_timeout(16)  # the gesture's own pace: a finger is not instantaneous
    _touch(cdp, "touchEnd")
    page.wait_for_function("y => window.scrollY > y", arg=before, timeout=5000)
    _calm(page)
    assert _spied(page)["ghosts"] == 0
    assert puts == [] and orders == []


def test_f_a_hold_of_150_ms_and_then_a_move_is_a_scroll_too(base_url, phone):
    page, cdp = phone
    _world(base_url)
    _open(page, base_url, size=(375, 800))
    puts = _watch_puts(page)
    x, y = _bring(page, _chip(page, B), 500)
    before = _scroll_y(page)
    _touch(cdp, "touchStart", x, y)
    # the name shows it is held while it waits (looked at at once: the 300 ms are already running)
    expect(_chip(page, B)).to_have_class(re.compile(r"\bheld\b"))
    page.wait_for_timeout(QUICK)
    _touch(cdp, "touchMove", x, y - 20)  # one move of 20px: well before the 300 ms are up
    expect(_chip(page, B)).not_to_have_class(re.compile(r"\bheld\b"))
    # the 300 ms pass with the finger down: still nothing
    page.wait_for_timeout(HOLD)
    assert _spied(page)["ghosts"] == 0
    for i in range(5, 14):  # and the finger goes on: the page follows it
        _touch(cdp, "touchMove", x, y - i * 5)
        page.wait_for_timeout(16)
    _touch(cdp, "touchEnd")
    page.wait_for_function("y => window.scrollY > y", arg=before, timeout=5000)
    _calm(page)
    assert _spied(page)["ghosts"] == 0
    assert puts == []


def test_f_a_hold_of_350_ms_carries_the_name_and_the_page_does_not_scroll(base_url, phone):
    page, cdp = phone
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [A])
    _open(page, base_url, size=(375, 800))
    puts = _watch_puts(page)
    x, y = _hold(page, cdp, C, 640)
    target = _slot(page, S2, 1)
    tx, ty = _centre(target)
    assert 100 < ty < 560, f"the box is not on the screen with the name: {ty}"
    page.wait_for_timeout(HOLD)  # the hold is the behaviour under test
    expect(_ghosts(page)).to_have_count(1)
    expect(_chip(page, C)).to_have_class(re.compile(r"\blifted\b"))
    assert _ghosts(page).inner_text().strip() == C
    s0 = _scroll_y(page)
    # the finger moves down and sideways, then up: the page stays
    for dx, dy in ((10, 20), (20, 40), (20, -30), (0, -60)):
        _touch(cdp, "touchMove", x + dx, y + dy)
        page.wait_for_timeout(40)
    assert _scroll_y(page) == s0
    # the copy is above the finger
    g = _ghosts(page).bounding_box()
    assert g["y"] + g["height"] <= y - 60 + 4, (g, y)
    # onto the box, in small steps
    for i in range(1, 13):
        _touch(cdp, "touchMove", x + (tx - x) * i / 12, y - 60 + (ty - y + 60) * i / 12)
        page.wait_for_timeout(16)
    expect(_lit(page)).to_have_count(1)
    assert _lit(page).get_attribute("data-sid") == str(ids[S2])
    assert _scroll_y(page) == s0
    _touch(cdp, "touchEnd")
    _calm(page)
    assert _shown(page, S2) == _expected_boxes([C])
    _wait_chain(page, base_url, ids, S2, [C])
    _wait_puts(page, puts, 1)
    page.wait_for_load_state("networkidle")
    assert puts == [{"chain": [ids[C]]}]
    assert _scroll_y(page) == s0
    # no list opened by the touch that ended on the box
    assert page.locator(".picker").count() == 0
    assert _spied(page)["ghosts"] == 1


def test_f_a_sideways_slide_of_more_than_10px_is_not_a_hold_and_one_of_4px_is(base_url, phone):
    """The 10px rule itself: a slide to the side cannot scroll the page, so only the rule stops the
    drag. The control beside it moves 4px and does carry."""
    page, cdp = phone
    ids = _world(base_url)
    _open(page, base_url, size=(375, 800))
    puts = _watch_puts(page)
    # Chromium cancels the pointer at any slide, even one that cannot scroll, and that would stop the
    # drag by itself. With the browser's panning off for this test, only the page's own rule is left.
    page.add_style_tag(content=".acct-chip { touch-action: none !important; }")
    x, y = _bring(page, _chip(page, B), 500)
    _touch(cdp, "touchStart", x, y)
    expect(_chip(page, B)).to_have_class(re.compile(r"\bheld\b"))
    page.wait_for_timeout(QUICK)
    _touch(cdp, "touchMove", x + 20, y)  # one move of 20px to the side, same y
    expect(_chip(page, B)).not_to_have_class(re.compile(r"\bheld\b"))
    page.wait_for_timeout(450 - QUICK)  # the hold's own time is the behaviour under test
    assert _spied(page)["ghosts"] == 0
    expect(_ghosts(page)).to_have_count(0)
    _touch(cdp, "touchEnd")
    _calm(page)
    assert _spied(page)["ghosts"] == 0
    assert puts == []
    # the control: 4px to the side is still a hold, and it carries
    x, y = _centre(_chip(page, B))
    _touch(cdp, "touchStart", x, y)
    page.wait_for_timeout(QUICK)
    _touch(cdp, "touchMove", x + 4, y)
    page.wait_for_timeout(HOLD - QUICK)
    expect(_ghosts(page)).to_have_count(1)
    _touch(cdp, "touchEnd")
    _calm(page)
    assert _spied(page)["ghosts"] == 1
    assert _api_chain(base_url, ids, S1) == []


# ── g: the edge ────────────────────────────────────────────────────────────────────────────────────


def test_g_near_the_edge_the_page_scrolls_by_itself_and_holds_still_over_a_box(base_url, phone):
    page, cdp = phone
    ids = _world(base_url)
    _open(page, base_url, size=(375, 800))
    sx, _ = _centre(_slot(page, S2, 1))
    x, y = _hold(page, cdp, A, 150)
    assert _centre(_slot(page, S2, 1))[1] < 0, "the box should start above the screen"
    page.wait_for_timeout(HOLD)
    expect(_ghosts(page)).to_have_count(1)
    s0 = _scroll_y(page)
    # along the line of the boxes' first column, up to the top edge
    for i in range(1, 11):
        _touch(cdp, "touchMove", x + (sx - x) * i / 10, y + (36 - y) * i / 10)
        page.wait_for_timeout(16)
    # nothing is under the finger yet: the page scrolls up by itself, and then a box comes under it
    page.wait_for_function("y => window.scrollY < y", arg=s0, timeout=5000)
    page.wait_for_selector(".slot.over", timeout=8000)
    s1 = _scroll_y(page)
    page.wait_for_timeout(300)  # time for the page to move, if it were going to
    s2 = _scroll_y(page)
    assert s1 == s2, (s1, s2)
    expect(_lit(page)).to_have_count(1)
    # the drop sets the box it was over, and the page has not moved
    sid = int(_lit(page).get_attribute("data-sid"))
    _touch(cdp, "touchEnd")
    _calm(page)
    assert _scroll_y(page) == s2
    source = S1 if sid == ids[S1] else S2
    _wait_chain(page, base_url, ids, source, [A])


# ── h: the browser takes the gesture; i: Escape ──────────────────────────────────────────────────────


def test_h_a_cancelled_pointer_drops_nothing_and_the_page_scrolls_again(base_url, phone):
    page, cdp = phone
    ids = _world(base_url)
    _open(page, base_url, size=(375, 800))
    puts = _watch_puts(page)
    x, y = _hold(page, cdp, C, 600)
    page.wait_for_timeout(HOLD)
    expect(_ghosts(page)).to_have_count(1)
    tx, ty = _centre(_slot(page, S2, 1))
    for i in range(1, 9):
        _touch(cdp, "touchMove", x + (tx - x) * i / 8, y + (ty - y) * i / 8)
        page.wait_for_timeout(16)
    expect(_lit(page)).to_have_count(1)
    _touch(cdp, "touchCancel")
    _calm(page)
    assert _spied(page) == {"ghosts": 1, "fly": True}
    assert _shown(page, S1) == _expected_boxes([])
    assert puts == []
    # the page follows a swipe again
    x, y = _bring(page, _chip(page, B), 500)
    before = _scroll_y(page)
    _touch(cdp, "touchStart", x, y)
    for i in range(1, 11):
        _touch(cdp, "touchMove", x, y - i * 18)
        page.wait_for_timeout(16)
    _touch(cdp, "touchEnd")
    page.wait_for_function("y => window.scrollY > y", arg=before, timeout=5000)
    assert _api_chain(base_url, ids, S1) == []


def test_i_escape_while_carrying_drops_nothing(page, base_url):
    ids = _world(base_url)
    _open(page, base_url)
    puts = _watch_puts(page)
    x, y = _grab(page, C)
    page.mouse.move(x + 8, y - 8, steps=3)
    page.mouse.move(*_centre(_slot(page, S1, 1)), steps=12)
    expect(_ghosts(page)).to_have_count(1)
    expect(_lit(page)).to_have_count(1)
    page.keyboard.press("Escape")
    _calm(page)
    # Escape did not also take the page home
    assert page.evaluate("() => location.hash") == "#settings"
    expect(page.locator(".settings-content")).to_be_visible()
    # the button is still down; moving and letting go change nothing
    page.mouse.move(*_centre(_slot(page, S1, 2)), steps=6)
    page.mouse.up()
    _calm(page)
    assert _shown(page, S1) == _expected_boxes([])
    assert puts == []
    assert _spied(page)["ghosts"] == 1
    # and a drag after it works
    _carry_to_box(page, C, S1, 1)
    _wait_chain(page, base_url, ids, S1, [C])
    # Escape with nothing carried is the page's own: it goes home
    page.keyboard.press("Escape")
    page.wait_for_function("() => location.hash !== '#settings'", timeout=5000)


# ── j: a save that fails ─────────────────────────────────────────────────────────────────────────────


def test_j_a_failed_save_puts_the_boxes_back_and_shows_the_banner(page, base_url):
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [A, B])
    _open(page, base_url)
    refused = []

    def fail(route):
        if route.request.method == "PUT":
            refused.append(route.request.url)
            route.fulfill(status=500, json={"detail": "Could not save the accounts"})
        else:
            route.continue_()

    page.route("**/api/freelance/sources/*", fail)
    _carry_to_box(page, C, S1, 3)
    expect(page.locator(".error-banner")).to_be_visible()
    expect(page.locator(".error-banner")).to_have_text("Could not save the accounts")
    assert len(refused) == 1
    assert _shown(page, S1) == _expected_boxes([A, B])
    assert _api_chain(base_url, ids, S1) == [A, B]
    _calm(page)


# ── k: reduced motion ────────────────────────────────────────────────────────────────────────────────


def test_k_reduced_motion_still_drops_and_nothing_breathes_flies_or_tilts(page, base_url):
    ids = _world(base_url)
    page.emulate_media(reduced_motion="reduce")
    _open(page, base_url)
    x, y = _grab(page, D)
    _begin(page, x, y)
    names = page.evaluate(
        "() => [...document.querySelectorAll('.slot')].map(s => getComputedStyle(s).animationName)"
    )
    assert len(names) == 8 and set(names) == {"none"}, names
    page.mouse.move(*_centre(_slot(page, S1, 1)), steps=12)
    expect(_lit(page)).to_have_count(1)
    over = page.evaluate("() => getComputedStyle(document.querySelector('.slot.over')).transform")
    assert over == "none", over
    # the copy follows the pointer, flat: no rotation, no scale
    m = _ghosts(page).evaluate("el => getComputedStyle(el).transform")
    assert m.startswith("matrix(1, 0, 0, 1,"), m
    assert _ghosts(page).evaluate("el => getComputedStyle(el).transitionProperty") == "none"
    page.mouse.up()
    _calm(page)
    assert _shown(page, S1) == _expected_boxes([D])
    _wait_chain(page, base_url, ids, S1, [D])
    # it did not fly, and the box did not pop
    assert _spied(page) == {"ghosts": 1, "fly": False}
    assert page.locator(".slot.pop").count() == 0


def test_k_with_motion_the_copy_tilts_flies_and_the_boxes_breathe(page, base_url):
    """The positive control for the test above: the same drag, motion allowed."""
    _world(base_url)
    _open(page, base_url)
    x, y = _grab(page, D)
    _begin(page, x, y)
    m = _ghosts(page).evaluate("el => getComputedStyle(el).transform")
    assert not m.startswith("matrix(1, 0, 0, 1,"), m
    page.mouse.up()
    _calm(page)
    assert _spied(page)["fly"] is True


# ── l: nothing is left listening ─────────────────────────────────────────────────────────────────────


def test_l_after_a_drag_nothing_listens_and_the_next_drag_works(page, base_url):
    ids = _world(base_url)
    _open(page, base_url)
    puts = _watch_puts(page)
    _carry_to_box(page, D, S1, 1)
    _wait_chain(page, base_url, ids, S1, [D])
    _calm(page)
    # the button is up: moving over the boxes lights none and draws no copy
    for n in (1, 2, 3):
        page.mouse.move(*_centre(_slot(page, S2, n)), steps=4)
    page.mouse.move(*_centre(_chip(page, A)), steps=4)
    _calm(page)
    assert _spied(page)["ghosts"] == 1
    # a second drag, from another name onto the other source
    _carry_to_box(page, A, S2, 1)
    _wait_chain(page, base_url, ids, S2, [A])
    _calm(page)
    assert _spied(page)["ghosts"] == 2
    # and a third drag that is let go outside: still nothing left behind
    _carry(page, B, _centre(page.locator(f"{CARD} h3")))
    _calm(page)
    page.wait_for_load_state("networkidle")
    assert len(puts) == 2, puts
    assert _shown(page, S1) == _expected_boxes([D])
    assert _shown(page, S2) == _expected_boxes([A])


# ── n: the listener that keeps the page still under a finger ────────────────────────────────────────


def _touchmove_listeners(page) -> list[dict]:
    cdp = page.context.new_cdp_session(page)
    doc = cdp.send("Runtime.evaluate", {"expression": "document"})["result"]["objectId"]
    found = cdp.send("DOMDebugger.getEventListeners", {"objectId": doc})["listeners"]
    return [li for li in found if li["type"] == "touchmove"]


def test_n_the_touchmove_listener_is_on_the_document_before_any_press_and_is_not_passive(
    page, base_url
):
    """On Android a listener added during the gesture is too late, and a passive one cannot say no:
    the one that stops the page scrolling under a carried name is there from the start, and active."""
    _world(base_url)
    _open(page, base_url)
    before = _touchmove_listeners(page)
    assert len(before) >= 1 and all(li["passive"] is False for li in before), before
    # a drag adds and removes none
    x, y = _grab(page, D)
    _begin(page, x, y)
    assert len(_touchmove_listeners(page)) == len(before)
    page.mouse.up()
    _calm(page)
    assert len(_touchmove_listeners(page)) == len(before)


# ── m: the click that follows a drop ─────────────────────────────────────────────────────────────────


def test_m_no_click_reaches_the_box_after_a_drop(page, base_url):
    """The browser may send a click to the element under the pointer when the button goes up. A click
    sent by the page in the same breath as the pointer's release stands for it: it must not open the
    list of the box (or reach its X)."""
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [A])
    _open(page, base_url)
    x, y = _grab(page, D)
    page.mouse.move(x + 8, y - 8, steps=3)
    page.mouse.move(*_centre(_slot(page, S1, 2)), steps=12)
    expect(_lit(page)).to_have_count(1)
    # registered after the page's own, so it runs after the drop: a click on the lit box, as the browser would
    page.evaluate(
        """() => {
          window.addEventListener('pointerup', () => queueMicrotask(() => {
            document.querySelector('.slot[data-i="1"] .slot-main').click();
            document.querySelector('.slot[data-i="0"] .slot-x').click();
          }), { once: true });
        }"""
    )
    page.mouse.up()
    _wait_chain(page, base_url, ids, S1, [A, D])
    _calm(page)
    assert _shown(page, S1) == _expected_boxes([A, D])
    # and the box answers a click as before once the breath has passed (the control)
    _slot(page, S1, 3).locator(".slot-main").click()
    expect(page.locator(".picker")).to_have_count(1)
