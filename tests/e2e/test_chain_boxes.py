# ruff: noqa: E501
"""E2E: the four boxes of accounts of an income source (Settings > Freelance).

A box is filled from a list that opens on a click, a tap or a key; the X empties it; every change shows
at once and is saved with one PUT of the source's `chain`. Everything here is seeded through the API
under names of its own and uses fixed dates, so it does not depend on the day it runs or on the network.
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
LIVE = "sort-live"

A, B, C, D = "Bank Alpha", "Wallet Bravo", "Cash Charlie", "Other Delta"
ACCOUNTS = [(A, "bank", "EUR"), (B, "wallet", "USD"), (C, "cash", "EUR"), (D, "other", "GBP")]
S1, S2 = "Chain Src One", "Chain Src Two"
MONDAY = "2025-03-03"  # a fixed week, whatever day this runs


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


def _open(page, base_url: str, size=(1280, 1000)) -> None:
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.goto(f"{base_url}/#settings")
    page.wait_for_selector(".settings-content", state="attached", timeout=5000)
    page.evaluate(f"() => {MAIN}.setSettingsGroup('freelance')")
    page.wait_for_selector("[role=group] .slot", timeout=5000)
    page.wait_for_load_state(
        "networkidle"
    )  # the lists load after the page opens and move what is below


def _reload(page, base_url: str, size=(1280, 1000)) -> None:
    page.reload()
    _open(page, base_url, size)


def _group(page, source: str):
    return page.get_by_role("group", name=f"Accounts of {source}, in order")


def _box(page, source: str, n: int):
    """The button of box `n` (1 to 4) of a source."""
    return _group(page, source).locator(".slot").nth(n - 1).locator(".slot-main")


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


def _wait_puts(page, puts: list, n: int) -> None:
    wait_until(page, lambda: len(puts) >= n, lambda: f"{n} PUT(s) of a chain; the page sent {puts}")
    assert len(puts) == n, puts


def _option(page, account: str):
    return page.locator(".picker [role=option]").filter(
        has=page.locator(".pk-name", has_text=re.compile(rf"^{account}$"))
    )


def _choose(page, source: str, n: int, account: str) -> None:
    _box(page, source, n).click()
    _option(page, account).click()


def _focus_label(page) -> str | None:
    return page.evaluate(
        "() => document.activeElement && document.activeElement.getAttribute('aria-label')"
    )


# ── a: the boxes ────────────────────────────────────────────────────────────────────────────────────


def test_a_every_source_has_four_boxes_and_a_filled_one_draws_its_icon(page, base_url):
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [A, B])
    _open(page, base_url)
    for source in (S1, S2):
        expect(_group(page, source).locator(".slot")).to_have_count(4)
        expect(_group(page, source).locator(".link")).to_have_count(3)
        assert _group(page, source).locator(".link").first.get_attribute("aria-hidden") == "true"
    assert _shown(page, S1) == [A, B, "3", "4"]
    assert _shown(page, S2) == ["1", "2", "3", "4"]
    # the labels of the boxes
    expect(_box(page, S1, 1)).to_have_attribute("aria-label", f"Account 1 of {S1}: {A}. Change")
    expect(_box(page, S1, 3)).to_have_attribute("aria-label", f"Account 3 of {S1}: empty. Choose")
    assert _box(page, S1, 1).get_attribute("aria-haspopup") == "listbox"
    assert _box(page, S1, 1).get_attribute("aria-expanded") == "false"
    # the X of a filled box, and none on an empty one
    x = page.get_by_role("button", name=f"Remove {A} from {S1}")
    expect(x).to_have_attribute("title", "Remove")
    expect(_group(page, S1).locator(".slot-x")).to_have_count(2)
    # the kind icon is drawn: its <use> resolves to a symbol, so it has a size of its own
    sizes = _group(page, S1).evaluate(
        "el => [...el.querySelectorAll('.slot.filled use')].map(u => { const b = u.getBoundingClientRect(); return [b.width, b.height]; })"
    )
    assert len(sizes) == 2 and all(w > 4 and h > 4 for w, h in sizes), sizes


# ── b: a mouse ───────────────────────────────────────────────────────────────────────────────────────


def test_b_a_click_on_an_empty_box_and_on_an_account_fills_it(page, base_url):
    ids = _world(base_url)
    _open(page, base_url)
    puts = _watch_puts(page)
    _choose(page, S1, 1, B)
    expect(_group(page, S1).locator(".slot").first).to_have_class(re.compile(r"\bfilled\b"))
    assert _shown(page, S1) == [B, "2", "3", "4"]
    _wait_chain(page, base_url, ids, S1, [B])
    _wait_puts(page, puts, 1)
    assert puts == [{"chain": [ids[B]]}]
    # the list is closed again
    expect(page.locator(".picker")).to_have_count(0)
    _reload(page, base_url)
    assert _shown(page, S1) == [B, "2", "3", "4"]
    assert _shown(page, S2) == ["1", "2", "3", "4"]


# ── c: the keyboard ──────────────────────────────────────────────────────────────────────────────────


def test_c_the_keyboard_alone_fills_a_box_and_escape_and_tab_change_nothing(page, base_url):
    ids = _world(base_url)
    _open(page, base_url)
    puts = _watch_puts(page)
    _box(page, S1, 1).focus()
    page.keyboard.press("Enter")
    expect(page.locator(".picker")).to_have_count(1)
    assert _box(page, S1, 1).get_attribute("aria-expanded") == "true"
    # the focus went into the list: an empty box has no selected account, so the first option
    first = page.locator(".picker [role=option]").first
    expect(first).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(page.locator(".picker [role=option]").nth(1)).to_be_focused()
    page.keyboard.press("Enter")
    # the second account of the Accounts list, in the first box; the focus is on that box
    assert _shown(page, S1) == [B, "2", "3", "4"]
    expect(page.locator(".picker")).to_have_count(0)
    expect(_box(page, S1, 1)).to_be_focused()
    expect(page.get_by_test_id(LIVE)).to_have_text(f"{B} is account 1 of {S1}")
    _wait_chain(page, base_url, ids, S1, [B])
    _wait_puts(page, puts, 1)

    # Escape: closes, changes nothing, sends nothing, and the focus goes back to the box
    _box(page, S1, 2).focus()
    page.keyboard.press("Space")
    expect(page.locator(".picker")).to_have_count(1)
    expect(page.locator(".picker [role=option]").first).to_be_focused()
    page.keyboard.press("ArrowDown")
    expect(page.locator(".picker [role=option]").nth(1)).to_be_focused()
    page.keyboard.press("Escape")
    expect(page.locator(".picker")).to_have_count(0)
    expect(_box(page, S1, 2)).to_be_focused()
    assert _shown(page, S1) == [B, "2", "3", "4"]
    assert _api_chain(base_url, ids, S1) == [B]
    # Tab: closes the list as well, and the focus is not left inside it
    page.keyboard.press("Enter")
    expect(page.locator(".picker [role=option]").first).to_be_focused()
    page.keyboard.press("Tab")
    expect(page.locator(".picker")).to_have_count(0)
    assert page.locator(".picker [role=option]:focus").count() == 0
    assert _shown(page, S1) == [B, "2", "3", "4"]
    # a real choice after all that: the page is sending, so the silence above was the page's
    _box(page, S1, 2).focus()
    page.keyboard.press("Enter")
    expect(page.locator(".picker [role=option]").first).to_be_focused()
    page.keyboard.press("Enter")
    assert _shown(page, S1) == [B, A, "3", "4"]
    _wait_puts(page, puts, 2)
    _wait_chain(page, base_url, ids, S1, [B, A])


def test_c_the_arrows_wrap_and_home_and_end_jump(page, base_url):
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [C])
    _open(page, base_url)
    _box(page, S1, 1).focus()
    page.keyboard.press("Enter")
    # the selected account has the focus on opening
    expect(_option(page, C)).to_be_focused()
    options = page.locator(".picker [role=option]")
    n = options.count()
    assert n == 5  # four accounts and "Remove"
    page.keyboard.press("End")
    expect(options.nth(n - 1)).to_be_focused()
    page.keyboard.press("ArrowDown")  # wraps to the top
    expect(options.first).to_be_focused()
    page.keyboard.press("ArrowUp")  # and back to the bottom
    expect(options.nth(n - 1)).to_be_focused()
    page.keyboard.press("Home")
    expect(options.first).to_be_focused()
    page.keyboard.press("Escape")
    expect(_box(page, S1, 1)).to_be_focused()


def test_only_one_list_is_open_and_a_press_outside_closes_it(page, base_url):
    _world(base_url)
    _open(page, base_url)
    _box(page, S2, 1).click()  # a list opens below its box: the boxes above it stay in reach
    expect(page.locator(".picker")).to_have_count(1)
    _box(page, S1, 3).click()
    expect(page.locator(".picker")).to_have_count(1)
    expect(page.locator(".picker")).to_have_attribute("aria-label", f"Account 3 of {S1}")
    page.mouse.click(5, 300)
    expect(page.locator(".picker")).to_have_count(0)
    # the box that opened it closes it again
    _box(page, S1, 2).click()
    expect(page.locator(".picker")).to_have_count(1)
    _box(page, S1, 2).click()
    expect(page.locator(".picker")).to_have_count(0)


# ── d: the rule of a chain ───────────────────────────────────────────────────────────────────────────

CASES = [
    # (the chain at the start, the move, the chain after)
    ([A, B, C], ("choose", 3, A), [B, A]),
    ([A], ("choose", 4, D), [A, D]),
    ([A, B], ("choose", 1, D), [D, B]),
    ([A, B, C], ("clear", 2, None), [A, C]),
    ([A, B, C, D], ("choose", 1, B), [B, C, D]),
]


@pytest.mark.parametrize("start,move,want", CASES, ids=["move", "append", "replace", "x", "full"])
def test_d_the_rule_of_a_chain(page, base_url, start, move, want):
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, start)
    _open(page, base_url)
    assert _shown(page, S1) == _expected_boxes(start)
    what, n, account = move
    if what == "choose":
        _choose(page, S1, n, account)
    else:
        page.get_by_role("button", name=f"Remove {start[n - 1]} from {S1}").click()
    expect(_group(page, S1).locator(".slot-x")).to_have_count(len(want))
    assert _shown(page, S1) == _expected_boxes(want)
    _wait_chain(page, base_url, ids, S1, want)
    # the other source did not move
    assert _shown(page, S2) == ["1", "2", "3", "4"]
    # where the focus is: the box where the account landed, or the box at the place that was emptied
    landed = want.index(account) + 1 if what == "choose" else n
    expect(_box(page, S1, landed)).to_be_focused()
    live = (
        f"{account} is account {landed} of {S1}"
        if what == "choose"
        else f"{start[n - 1]} removed from {S1}"
    )
    expect(page.get_by_test_id(LIVE)).to_have_text(live)


def test_choosing_the_account_a_box_already_holds_saves_nothing(page, base_url):
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [A, B])
    _open(page, base_url)
    puts = _watch_puts(page)
    _choose(page, S1, 1, A)
    expect(page.locator(".picker")).to_have_count(0)
    assert _shown(page, S1) == [A, B, "3", "4"]
    expect(page.get_by_test_id(LIVE)).to_have_text(f"{A} is account 1 of {S1}")
    # a real change sends exactly one PUT, so the silence before it was the page's
    _choose(page, S1, 3, C)
    _wait_chain(page, base_url, ids, S1, [A, B, C])
    _wait_puts(page, puts, 1)
    assert puts == [{"chain": [ids[A], ids[B], ids[C]]}]


# ── e: "Remove" in the list ──────────────────────────────────────────────────────────────────────────


def test_e_remove_in_the_list_does_what_the_x_does(page, base_url):
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [A, B, C])
    _open(page, base_url)
    _box(page, S1, 2).click()
    # an empty box has no "Remove"; a filled one does, after the accounts
    options = page.locator(".picker [role=option]")
    assert options.last.inner_text().strip() == "Remove"
    options.last.click()
    assert _shown(page, S1) == [A, C, "3", "4"]
    expect(_box(page, S1, 2)).to_be_focused()
    expect(page.get_by_test_id(LIVE)).to_have_text(f"{B} removed from {S1}")
    _wait_chain(page, base_url, ids, S1, [A, C])
    _box(page, S1, 3).click()
    assert page.get_by_role("option", name="Remove").count() == 0


# ── f: a save that fails ─────────────────────────────────────────────────────────────────────────────


def test_f_a_failed_save_puts_the_boxes_back_and_shows_the_banner(page, base_url):
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
    _choose(page, S1, 3, C)
    expect(page.locator(".error-banner")).to_be_visible()
    expect(page.locator(".error-banner")).to_have_text("Could not save the accounts")
    assert len(refused) == 1
    assert _shown(page, S1) == [A, B, "3", "4"]
    assert _api_chain(base_url, ids, S1) == [A, B]
    # the X, the same
    page.get_by_role("button", name=f"Remove {A} from {S1}").click()
    wait_until(page, lambda: len(refused) >= 2, lambda: f"the second refused PUT; got {refused}")
    assert len(refused) == 2
    # the answer of the refused request is still on its way
    wait_until(
        page,
        lambda: _shown(page, S1) == [A, B, "3", "4"],
        lambda: f"the boxes put back; they show {_shown(page, S1)}",
    )
    assert _shown(page, S1) == [A, B, "3", "4"]


# ── g: archiving an account ──────────────────────────────────────────────────────────────────────────


def test_g_an_archived_account_is_not_offered(page, base_url):
    ids = _world(base_url)
    r = httpx.put(f"{base_url}/api/freelance/accounts/{ids[B]}", json={"archived": True})
    assert r.status_code == 200, r.text
    _open(page, base_url)
    _box(page, S1, 1).click()
    names = page.evaluate(
        "() => [...document.querySelectorAll('.picker .pk-name')].map(e => e.textContent.trim())"
    )
    assert names == [A, C, D]
    page.keyboard.press("Escape")
    # and it is not offered by the server either: a chain with it is refused
    r = httpx.put(f"{base_url}/api/freelance/sources/{ids[S1]}", json={"chain": [ids[B]]})
    assert r.status_code == 422


def test_g_archiving_an_account_that_sits_in_boxes_empties_them_and_undo_puts_them_back(
    page, base_url
):
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [A, B])
    _set_chain(base_url, ids, S2, [B, C, D])
    _open(page, base_url)
    page.get_by_role("button", name=f"Archive {B}").click()
    page.wait_for_function("() => document.querySelectorAll('[role=group] .slot-x').length === 3")
    assert _shown(page, S1) == _expected_boxes([A])
    assert _shown(page, S2) == _expected_boxes([C, D])
    assert _api_chain(base_url, ids, S1) == [A]
    assert _api_chain(base_url, ids, S2) == [C, D]
    ribbon = page.locator(".save-ribbon")
    expect(ribbon).to_contain_text(f"{B} archived. Saved payouts keep it")
    page.locator(".ribbon-action").click()
    expect(page.locator(".ribbon-msg")).to_have_text(f"{B} restored")
    assert _shown(page, S1) == _expected_boxes([A, B])
    assert _shown(page, S2) == _expected_boxes([B, C, D])
    assert _api_chain(base_url, ids, S1) == [A, B]
    assert _api_chain(base_url, ids, S2) == [B, C, D]
    rows = httpx.get(f"{base_url}/api/freelance/accounts").json()
    assert next(a for a in rows if a["id"] == ids[B])["archived"] is False


def test_g_archiving_an_account_that_sits_in_no_box_says_nothing_more(page, base_url):
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [A])
    _open(page, base_url)
    page.get_by_role("button", name=f"Archive {D}").click()
    expect(page.get_by_role("button", name=f"Restore {D}")).to_be_visible()
    assert page.locator(".ribbon-action").is_visible() is False
    assert _shown(page, S1) == _expected_boxes([A])


# ── h: no account at all ─────────────────────────────────────────────────────────────────────────────


def test_h_without_accounts_the_list_sends_you_to_add_one(page, base_url):
    _world(base_url, accounts=())
    _open(page, base_url)
    _box(page, S1, 1).click()
    options = page.locator(".picker [role=option]")
    expect(options).to_have_count(1)
    expect(options.first).to_have_text("Add an account first")
    options.first.click()
    expect(page.locator(".picker")).to_have_count(0)
    expect(page.get_by_label("Account name")).to_be_focused()
    assert _shown(page, S1) == ["1", "2", "3", "4"]


# ── i: the order of the Accounts list ────────────────────────────────────────────────────────────────


def test_i_the_list_follows_the_order_of_the_accounts(page, base_url):
    ids = _world(base_url)
    new = [D, B, A, C]
    r = httpx.put(f"{base_url}/api/freelance/accounts/order", json={"ids": [ids[n] for n in new]})
    assert r.status_code == 200, r.text
    _open(page, base_url)
    _box(page, S2, 1).click()
    names = page.evaluate(
        "() => [...document.querySelectorAll('.picker .pk-name')].map(e => e.textContent.trim())"
    )
    assert names == new
    # the currency is at the right of each
    currencies = page.evaluate(
        "() => [...document.querySelectorAll('.picker .pk-cur')].map(e => e.textContent.trim())"
    )
    assert currencies == ["GBP", "USD", "EUR", "EUR"]


# ── j: the selects are gone ──────────────────────────────────────────────────────────────────────────


def test_j_no_select_is_left_in_a_source_row_or_an_account_row(page, base_url):
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [A])
    _open(page, base_url)
    assert page.locator("#settings-sources .src-item").count() == 2
    assert page.locator("#settings-sources .src-item select").count() == 0
    assert page.locator("[data-testid=accounts-card] .acct-item").count() == 4
    assert page.locator("[data-testid=accounts-card] .acct-item select").count() == 0


# ── k: a saved payout does not move ──────────────────────────────────────────────────────────────────


def test_k_changing_a_chain_changes_no_saved_payout(page, base_url):
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [A])
    with httpx.Client(base_url=base_url) as c:
        body = {"date": MONDAY, "source_id": ids[S1], "start_time": "09:00", "end_time": "11:00"}
        assert c.post("/api/freelance/blocks", json=body).status_code == 201
        body = {
            "source_id": ids[S1],
            "week_start": MONDAY,
            "legs": [{"account_id": ids[A]}, {"account_id": ids[C]}],
        }
        r = c.post("/api/freelance/payouts", json=body)
        assert r.status_code in (200, 201), r.text
        before = c.get("/api/freelance/payouts").json()
    assert len(before) == 1 and len(before[0]["legs"]) == 2
    _open(page, base_url)
    _choose(page, S1, 2, C)
    _choose(page, S1, 1, D)
    _wait_chain(page, base_url, ids, S1, [D, C])
    assert httpx.get(f"{base_url}/api/freelance/payouts").json() == before


# ── l: reduced motion ────────────────────────────────────────────────────────────────────────────────

POP = "() => getComputedStyle(document.querySelector('.slot.filled')).animationName"


def test_l_reduced_motion_still_chooses_and_the_filled_box_does_not_animate(page, base_url):
    ids = _world(base_url)
    page.emulate_media(reduced_motion="reduce")
    _open(page, base_url)
    _choose(page, S1, 1, A)
    assert _shown(page, S1) == [A, "2", "3", "4"]
    _wait_chain(page, base_url, ids, S1, [A])
    assert page.locator(".slot.pop").count() == 0
    # even a box that carries the class has no animation: the list as well
    page.evaluate("() => document.querySelector('.slot.filled').classList.add('pop')")
    assert page.evaluate(POP) == "none"
    _box(page, S1, 2).click()
    assert (
        page.evaluate("() => getComputedStyle(document.querySelector('.picker')).animationName")
        == "none"
    )


def test_a_filled_box_does_pop_without_reduced_motion(page, base_url):
    """A positive control for l: the same box, motion allowed, has its animation."""
    ids = _world(base_url)
    _set_chain(base_url, ids, S1, [A])
    _open(page, base_url)
    page.evaluate("() => document.querySelector('.slot.filled').classList.add('pop')")
    assert page.evaluate(POP) == "slot-pop"
    # and a real choice makes it pop
    _choose(page, S1, 2, B)
    page.wait_for_selector(".slot.pop", timeout=3000)


# ── m: a finger ──────────────────────────────────────────────────────────────────────────────────────


def _touch(cdp, kind: str, x: float | None = None, y: float | None = None) -> None:
    points = [] if kind == "touchEnd" else [{"x": x, "y": y, "id": 1}]
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})


def _tap(page, cdp, loc) -> None:
    loc.scroll_into_view_if_needed()
    b = loc.bounding_box()
    x, y = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
    _touch(cdp, "touchStart", x, y)
    _touch(cdp, "touchEnd")


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


def test_m_a_tap_opens_the_list_and_a_second_tap_chooses(base_url, phone):
    page, cdp = phone
    ids = _world(base_url)
    _open(page, base_url, size=(375, 800))
    _tap(page, cdp, _box(page, S1, 1))
    expect(page.locator(".picker")).to_have_count(1)
    listbox = page.locator(".picker").bounding_box()
    assert listbox["x"] >= 0 and listbox["x"] + listbox["width"] <= 375, listbox
    _tap(page, cdp, _option(page, C))
    expect(page.locator(".picker")).to_have_count(0)
    assert _shown(page, S1) == [C, "2", "3", "4"]
    _wait_chain(page, base_url, ids, S1, [C])
    # the X by a finger
    _tap(page, cdp, page.get_by_role("button", name=f"Remove {C} from {S1}"))
    assert _shown(page, S1) == ["1", "2", "3", "4"]
    _wait_chain(page, base_url, ids, S1, [])
