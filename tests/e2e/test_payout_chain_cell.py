# ruff: noqa: E501
"""E2E: the payout cell of a source and a week is its chain of accounts.

One line per account of the chain: the account's mark, an amount, a small X and a select of accounts. A typed
amount stays as typed and the lines after it follow; the figures come from the server's preview; nothing is
saved while typing, the Confirm button saves the row. The week is Miguel's W45: $2,029.50 billed, $999 sent
through Stripe, EUR 894.76 arrived at 1.1165.

The server of this module has its own ECB and CoinGecko (a small HTTP server of the test answers for both, so
nothing reaches the network), a frozen "now" after W45, and every week used here is a fixed one. The ECB says
1.1172 for W44 (the week of the old money tests) and 1.1165 for the rest; January 2026 has no rate at all.

Each test here replaces what an old test of the cell proved (tests/e2e/test_sent_and_arrived.py, now gone, and
parts of test_money_accounts.py): the figures are the same ones.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect

from .test_money_accounts import BACKEND_DIR, _app, _find_free_port, _wait_for_server

pytestmark = pytest.mark.e2e

NOW = "2026-11-10T10:00:00+01:00"
W45 = "2026-11-02"  # Mon Nov 2 - Sun Nov 8
W44 = "2026-10-26"  # Mon Oct 26 - Sun Nov 1
W2 = "2026-01-05"  # no rate that week
RATE = 1.1165
RATE_W44 = 1.1172


def _ecb() -> str:
    cubes, day = [], date(2026, 11, 10)
    while day >= date(2026, 9, 1):
        if day.weekday() < 5:
            rate = RATE_W44 if date(2026, 10, 26) <= day <= date(2026, 11, 1) else RATE
            cubes.append(f'<Cube time="{day}"><Cube currency="USD" rate="{rate}"/></Cube>')
        day -= timedelta(days=1)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"'
        ' xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"><Cube>'
        + "".join(cubes)
        + "</Cube></gesmes:Envelope>"
    )


class _Stub(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.endswith(".xml"):
            body, status = _ecb().encode(), 200
        else:  # CoinGecko: nothing to say
            body, status = b"{}", 500
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def chain_url():
    stub = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    root = f"http://127.0.0.1:{stub.server_address[1]}"
    port = _find_free_port()
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_file:
        db_path = db_file.name
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path}",
        "PYTHONPATH": str(BACKEND_DIR),
        "KRONOS_NOW": NOW,
        "TZ": "Europe/Madrid",
        "KRONOS_FX_URL": f"{root}/daily.xml",
        "KRONOS_FX_HIST90_URL": f"{root}/90d.xml",
        "KRONOS_FX_HIST_URL": f"{root}/all.xml",
        "KRONOS_CRYPTO_URL": root,
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_DIR.parent),
        env=env,
        check=True,
        capture_output=True,
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1"]
        + ["--port", str(port), "--no-access-log"],
        cwd=str(BACKEND_DIR),
        env=env,
    )
    try:
        _wait_for_server(port)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        stub.shutdown()
        Path(db_path).unlink(missing_ok=True)


def _wipe(base: str) -> None:
    with httpx.Client(base_url=base) as c:
        c.delete("/api/data")
        for p in c.get("/api/freelance/payouts").json():
            c.delete(f"/api/freelance/payouts/{p['id']}")
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")
        for a in c.get("/api/freelance/accounts").json():
            c.delete(f"/api/freelance/accounts/{a['id']}")


@pytest.fixture(autouse=True)
def _clean(chain_url):
    _wipe(chain_url)
    yield
    _wipe(chain_url)


class Wire:
    """What the page sends to /api/freelance/payouts: the saves (POST, PUT, DELETE) and the previews."""

    def __init__(self, page):
        self.saves: list[tuple[str, dict | None]] = []
        self.previews: list[dict] = []
        page.on("request", self._seen)

    def _seen(self, request):
        path = request.url.split("?")[0]
        if "/api/freelance/payouts" not in path or request.method == "GET":
            return
        body = json.loads(request.post_data) if request.post_data else None
        if path.endswith("/payouts/preview"):
            self.previews.append(body)
        else:
            self.saves.append((request.method, body))

    def bodies(self):
        return [b for _, b in self.saves if b is not None] + self.previews


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-GB")
    page = ctx.new_page()
    page.set_default_timeout(8000)
    page.wire = Wire(page)
    yield page
    # decision 7: the page never sends the old shape (an `amount` without `legs`)
    for body in page.wire.bodies():
        assert "legs" in body and "amount" not in body, body
    ctx.close()


def _post(base: str, path: str, **body) -> dict:
    r = httpx.post(f"{base}{path}", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _payouts(base: str) -> list[dict]:
    return httpx.get(f"{base}/api/freelance/payouts").json()


def _wait_for(base: str, predicate, what: str, timeout=8.0) -> list[dict]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = _payouts(base)
        if predicate(got):
            return got
        time.sleep(0.1)
    raise AssertionError(f"{what}: the API has {_payouts(base)}")


def _world(
    base: str,
    *,
    chain=("Stripe", "Deutsche Bank"),
    days=("2026-11-03",),
    name="Acme",
    rate=90,
    hours=22.55,
) -> dict:
    """Acme bills $90 an hour; W45 billed 22.55 h = $2,029.50. Five accounts: Stripe (USD), Deutsche Bank
    (EUR), Wise (EUR), Mercury (USD), Cold wallet (BTC). The source is paid through `chain`."""
    accts = {
        "Stripe": _post(base, "/api/freelance/accounts", name="Stripe", currency="USD"),
        "Deutsche Bank": _post(
            base, "/api/freelance/accounts", name="Deutsche Bank", currency="EUR"
        ),
        "Wise": _post(base, "/api/freelance/accounts", name="Wise", currency="EUR", kind="wallet"),
        "Mercury": _post(base, "/api/freelance/accounts", name="Mercury", currency="USD"),
        "Cold wallet": _post(
            base, "/api/freelance/accounts", name="Cold wallet", currency="BTC", kind="wallet"
        ),
    }
    ids = {k: v["id"] for k, v in accts.items()}
    body = {"name": name, "hourly_rate": rate, "currency": "USD", "chain": [ids[n] for n in chain]}
    src = _post(base, "/api/freelance/sources", **body)["id"]
    for day in days:
        _post(base, "/api/freelance/blocks", source_id=src, date=day, hours=hours)
    return {"src": src, **ids}


def _save(base: str, w: dict, legs: list[dict], week=W45, **extra) -> dict:
    return _post(
        base, "/api/freelance/payouts", source_id=w["src"], week_start=week, legs=legs, **extra
    )


def _open_weeks(page, base: str) -> None:
    page.goto(f"{base}/#weeks")
    page.wait_for_selector(".page-head .hm-switch")
    _app(page, "d.daysYear = 'all';")
    page.locator(".page-head .hm-switch button").nth(1).click()
    page.wait_for_selector("[data-testid='days-freelance']")


def _row(page, monday=W45):
    return page.locator(f"tr.wk-row#wk-{monday} .wk-line.wk-main")


def _amounts(row):
    return row.get_by_test_id("pay-amount")


def _confirm(row, label="Acme W45"):
    return row.get_by_role("button", name=f"Confirm the payout of {label}")


def _legs(p: dict) -> list[tuple]:
    return [(leg["account_name"], leg["amount"], leg["fixed"]) for leg in p["legs"]]


def _token(page, name: str) -> str:
    return page.evaluate(
        "(n) => { const d = document.createElement('i'); d.style.color = `var(${n})`;"
        " document.body.appendChild(d); const c = getComputedStyle(d).color; d.remove(); return c; }",
        name,
    )


SUG = re.compile(r"\bis-sug\b")


# ── (a) Miguel's week ─────────────────────────────────────────────────────────


def test_w45_999_typed_in_the_first_line_follows_in_the_second_and_confirm_saves_it(
    page, chain_url
):
    w = _world(chain_url)
    _open_weeks(page, chain_url)
    row = _row(page)
    first, second = _amounts(row).nth(0), _amounts(row).nth(1)
    # two lines, the billed amount suggested in the first and its euros in the second
    expect(_amounts(row)).to_have_count(2)
    expect(first).to_have_value("2029.5")
    expect(first).to_have_class(SUG)
    expect(second).to_have_value("1817.73")  # 2029.50 / 1.1165
    expect(second).to_have_class(SUG)
    expect(_confirm(row)).to_be_enabled()
    assert row.locator(".payc-l .cur").all_inner_texts() == ["$", "€"]

    first.fill("999")
    expect(second).to_have_value("894.76")  # 999 / 1.1165, a suggestion
    expect(second).to_have_class(SUG)
    expect(first).not_to_have_class(SUG)
    gap = row.locator(".wk-gap b")
    expect(gap).to_have_text("-$1,030.50")  # 999 - 2029.50, in the billed currency
    assert gap.evaluate("e => getComputedStyle(e).color") == _token(page, "--k-deficit")
    assert gap.get_attribute("title") == "First account minus billed"
    # billed 2029.50 USD is 1817.73 EUR at 1.1165, and 894.76 arrived: 922.97 lost, 922.97 / 1817.73 = 50.8%
    chip = row.get_by_test_id("fx-chip")
    expect(chip).to_have_text("DIFF -50.8%")
    chip.hover()
    expect(page.locator("#fx-tip")).to_have_text("€922.97 less than billed")
    page.mouse.move(5, 5)
    expect(row.locator(".wk-eph")).to_have_text("€39.68")  # 894.76 / 22.55 h
    assert page.wire.saves == [] and _payouts(chain_url) == []  # nothing saved by typing

    _confirm(row).click()
    got = _wait_for(chain_url, lambda p: len(p) == 1, "the payout is saved")[0]
    assert _legs(got) == [("Stripe", 999.0, True), ("Deutsche Bank", 894.76, False)]
    assert (got["amount"], got["currency"], got["amount_eur"], got["fx_cost_eur"]) == (
        894.76,
        "EUR",
        894.76,
        922.97,
    )
    assert page.wire.saves == [
        (
            "POST",
            {
                "source_id": w["src"],
                "week_start": W45,
                "note": None,
                "legs": [
                    {"account_id": w["Stripe"], "amount": 999, "fixed": True},
                    {"account_id": w["Deutsche Bank"], "amount": 894.76, "fixed": False},
                ],
            },
        )
    ]
    expect(page.get_by_test_id("days-fl-total")).to_contain_text("€894.76")  # the week's income
    expect(_confirm(row)).to_have_count(0)
    expect(row.get_by_test_id("pay-delete")).to_have_count(1)
    expect(row.locator(".wk-tag")).to_have_text("paid out")
    expect(first).to_have_value("999")
    expect(second).to_have_value("894.76")


# ── (b) three accounts ────────────────────────────────────────────────────────


def test_three_accounts_a_typed_amount_is_what_the_lines_after_it_follow(page, chain_url):
    _world(chain_url, chain=("Stripe", "Wise", "Deutsche Bank"))
    _open_weeks(page, chain_url)
    row = _row(page)
    a, b, c = (_amounts(row).nth(i) for i in range(3))
    expect(c).to_have_value("1817.73")
    a.fill("999")
    expect(b).to_have_value("894.76")
    expect(c).to_have_value("894.76")
    b.fill("890")  # typed in the second: the third follows it and the first does not move
    expect(c).to_have_value("890")
    expect(a).to_have_value("999")
    expect(b).not_to_have_class(SUG)
    expect(c).to_have_class(SUG)
    a.fill("1000")  # typed in the first: a second that was typed stays
    expect(row.locator(".wk-gap b")).to_have_text("-$1,029.50")
    expect(b).to_have_value("890")
    expect(c).to_have_value("890")
    row.get_by_role("button", name="Clear Wise amount, Acme W45").click()
    expect(b).to_have_value("895.66")  # 1000 / 1.1165 again, a suggestion
    expect(b).to_have_class(SUG)
    expect(c).to_have_value("895.66")  # and the third follows it
    expect(a).to_have_value("1000")
    assert page.wire.saves == []


# ── (c) writing saves nothing ─────────────────────────────────────────────────


def test_writing_in_two_rows_saves_nothing_and_no_coins_fly(page, chain_url):
    _world(chain_url, days=("2026-11-03", "2026-10-27"))
    _open_weeks(page, chain_url)
    page.evaluate(
        "() => { window.__coins = 0; new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => {"
        " if (n.classList && n.classList.contains('coin-fly')) window.__coins++; })))"
        ".observe(document.body, { childList: true }); }"
    )
    before = _payouts(chain_url)
    r45, r44 = _row(page, W45), _row(page, W44)
    _amounts(r45).nth(0).fill("999")
    _amounts(r44).nth(0).fill("500")
    expect(_amounts(r45).nth(1)).to_have_value("894.76")
    expect(_amounts(r44).nth(1)).to_have_value("447.55")  # 500 / 1.1172
    assert page.wire.saves == []
    assert _payouts(chain_url) == before == []
    assert page.evaluate("window.__coins") == 0 and page.locator(".coin-fly").count() == 0


# ── (d) the X ─────────────────────────────────────────────────────────────────


def test_the_x_clears_one_line_and_never_deletes_a_payout(page, chain_url):
    w = _world(chain_url)
    _open_weeks(page, chain_url)
    row = _row(page)
    first, second = _amounts(row).nth(0), _amounts(row).nth(1)
    x1 = row.get_by_role("button", name="Clear Stripe amount, Acme W45")
    x2 = row.get_by_role("button", name="Clear Deutsche Bank amount, Acme W45")
    expect(x1).to_be_disabled()
    expect(x2).to_be_disabled()
    assert x1.get_attribute("title") == "Clear, back to the calculated amount"
    first.fill("999")
    expect(x1).to_be_enabled()
    expect(x2).to_be_disabled()  # a suggestion has nothing typed to clear
    x1.click()
    expect(first).to_have_value("2029.5")  # back to what was billed
    expect(first).to_have_class(SUG)
    expect(first).to_be_focused()
    expect(second).to_have_value("1817.73")
    expect(x1).to_be_disabled()

    # on a saved payout the X only clears the line: the payout stays
    _save(
        chain_url,
        w,
        [
            {"account_id": w["Stripe"], "amount": 999, "fixed": True},
            {"account_id": w["Deutsche Bank"]},
        ],
    )
    page.reload()
    _open_weeks(page, chain_url)
    row = _row(page)
    expect(_amounts(row).nth(0)).to_have_value("999")
    expect(_amounts(row).nth(0)).not_to_have_class(SUG)
    row.get_by_role("button", name="Clear Stripe amount, Acme W45").click()
    expect(_amounts(row).nth(0)).to_have_value("2029.5")
    expect(_amounts(row).nth(1)).to_have_value("1817.73")
    expect(_confirm(row)).to_be_enabled()  # it is a change to confirm
    assert len(_payouts(chain_url)) == 1 and page.wire.saves == []
    assert not any(m == "DELETE" for m, _ in page.wire.saves)


# ── (e) the select ────────────────────────────────────────────────────────────


def _selected(row, i) -> str:
    return row.locator("select.payacct").nth(i).locator("option:checked").inner_text()


def test_choosing_another_account_changes_the_mark_and_the_suggestion(page, chain_url):
    _world(chain_url)
    _open_weeks(page, chain_url)
    row = _row(page)
    second = _amounts(row).nth(1)
    expect(second).to_have_value("1817.73")
    row.locator("select.payacct").nth(1).select_option(label="Mercury")
    expect(second).to_have_value("2029.5")  # dollars to dollars
    assert row.locator(".payc-l .cur").all_inner_texts() == ["$", "$"]
    assert page.wire.saves == []
    expect(row.get_by_test_id("pay-conv")).to_have_text(
        "= €1,817.73"
    )  # the last account is in dollars


def test_choosing_the_account_of_the_other_line_swaps_the_two(page, chain_url):
    _world(chain_url)
    _open_weeks(page, chain_url)
    row = _row(page)
    assert (_selected(row, 0), _selected(row, 1)) == ("Stripe", "Deutsche Bank")
    row.locator("select.payacct").nth(1).select_option(label="Stripe")
    assert (_selected(row, 0), _selected(row, 1)) == ("Deutsche Bank", "Stripe")
    assert row.locator(".payc-l .cur").all_inner_texts() == ["€", "$"]
    expect(_amounts(row).nth(0)).to_have_value("1817.73")  # euros first now
    expect(_amounts(row).nth(1)).to_have_value("2029.5")  # and back to dollars: 1817.73 at 1.1165


def test_an_archived_account_of_a_saved_payout_is_listed_on_its_own_line_only(page, chain_url):
    w = _world(chain_url)
    _save(
        chain_url,
        w,
        [{"account_id": w["Stripe"], "amount": 999}, {"account_id": w["Deutsche Bank"]}],
    )
    httpx.put(f"{chain_url}/api/freelance/accounts/{w['Stripe']}", json={"archived": True})
    _open_weeks(page, chain_url)
    row = _row(page)
    first = row.locator("select.payacct").nth(0).locator("option").all_inner_texts()
    second = row.locator("select.payacct").nth(1).locator("option").all_inner_texts()
    assert (
        first == ["Deutsche Bank", "Wise", "Mercury", "Cold wallet", "Stripe"] or "Stripe" in first
    )
    assert "Stripe" in first and _selected(row, 0) == "Stripe"
    assert "Stripe" not in second
    assert second == ["Deutsche Bank", "Wise", "Mercury", "Cold wallet"]


def test_a_source_with_no_chain_has_one_line_with_no_account_until_one_is_chosen(page, chain_url):
    w = _world(chain_url, chain=())
    _open_weeks(page, chain_url)
    row = _row(page)
    expect(_amounts(row)).to_have_count(1)
    assert _selected(row, 0) == "Choose account"
    expect(_confirm(row)).to_be_disabled()
    row.locator("select.payacct").select_option(label="Deutsche Bank")
    expect(_amounts(row).nth(0)).to_have_value("1817.73")
    expect(_confirm(row)).to_be_enabled()
    assert (
        httpx.get(f"{chain_url}/api/freelance/sources").json()[0]["chain"] == []
    )  # nothing saved yet
    _confirm(row).click()
    got = _wait_for(chain_url, lambda p: len(p) == 1, "saved")[0]
    assert _legs(got) == [("Deutsche Bank", 1817.73, False)]
    assert httpx.get(f"{chain_url}/api/freelance/sources").json()[0]["chain"] == [
        w["Deutsche Bank"]
    ]
    expect(page.locator(".wk-main .wk-tag")).to_have_text("paid out")
    # the source was given its chain by the server and the page knows it: after Delete the row offers that account
    row.get_by_role("button", name="Delete the payout of Acme W45").click()
    _wait_for(chain_url, lambda p: p == [], "deleted")
    expect(_amounts(row)).to_have_count(1)
    assert _selected(row, 0) == "Deutsche Bank"


# ── (f) no live account ───────────────────────────────────────────────────────


def test_with_no_account_the_select_is_a_link_to_the_accounts_card(page, chain_url):
    src = _post(chain_url, "/api/freelance/sources", name="Acme", hourly_rate=90, currency="USD")[
        "id"
    ]
    _post(chain_url, "/api/freelance/blocks", source_id=src, date="2026-11-03", hours=22.55)
    _open_weeks(page, chain_url)
    row = _row(page)
    assert row.locator("select.payacct").count() == 0
    link = row.get_by_role("link", name="Add an account")
    expect(link).to_be_visible()
    expect(_confirm(row)).to_be_disabled()
    link.click()
    expect(page.get_by_test_id("accounts-card")).to_be_in_viewport()
    assert page.evaluate("location.hash") == "#settings"
    expect(page.locator(".settings-group-btn", has_text="Freelance")).to_have_attribute(
        "aria-expanded", "true"
    )


# ── (g) a last account that is not in euros ───────────────────────────────────


def test_a_last_account_in_dollars_shows_its_euro_value_and_a_typed_one_waits_for_confirm(
    page, chain_url
):
    w = _world(chain_url, chain=("Stripe", "Mercury"))
    _open_weeks(page, chain_url)
    row = _row(page)
    first = _amounts(row).nth(0)
    first.fill("999")
    conv = row.get_by_test_id("pay-conv")
    expect(conv).to_have_text("= €894.76")  # 999 USD at 1.1165
    row.get_by_role("button", name="Set the € value of Acme W45").click()
    worth = row.get_by_label("Worth in euros, Acme W45")
    expect(worth).to_be_focused()
    worth.fill("890")
    expect(conv).to_have_text("= €890.00")
    assert page.wire.saves == [] and _payouts(chain_url) == []
    expect(_confirm(row)).to_be_enabled()
    _confirm(row).click()
    got = _wait_for(chain_url, lambda p: len(p) == 1, "saved")[0]
    assert got["amount_eur"] == 890.0 and got["rate_source"] == "manual"
    assert _legs(got) == [("Stripe", 999.0, True), ("Mercury", 999.0, False)]
    ((method, body),) = page.wire.saves
    assert method == "POST" and body["eur_amount"] == 890
    assert [leg["account_id"] for leg in body["legs"]] == [w["Stripe"], w["Mercury"]]
    expect(row.get_by_label("Worth in euros, Acme W45")).to_have_value("890")  # saved as typed


# ── (h) a day with no rate ────────────────────────────────────────────────────


def test_a_day_with_no_rate_shows_its_problem_and_needs_an_amount_typed(page, chain_url):
    _world(chain_url, days=("2026-01-06",))
    _open_weeks(page, chain_url)
    row = _row(page, W2)
    first, second = _amounts(row).nth(0), _amounts(row).nth(1)
    expect(first).to_have_value("2029.5")  # billed dollars into a dollar account need no rate
    expect(second).to_have_value("")
    expect(second).to_have_attribute("title", "no rate for that day")
    expect(second).to_have_attribute("placeholder", "no rate")
    expect(_confirm(row, "Acme W02")).to_be_disabled()
    second.fill("450")
    expect(_confirm(row, "Acme W02")).to_be_enabled()
    expect(second).not_to_have_attribute("title", "no rate for that day")
    _confirm(row, "Acme W02").click()
    got = _wait_for(chain_url, lambda p: len(p) == 1, "saved")[0]
    assert _legs(got) == [("Stripe", 2029.5, False), ("Deutsche Bank", 450.0, True)]


# ── (i) not a number ──────────────────────────────────────────────────────────


def test_not_a_number_marks_the_field_and_no_preview_is_sent_with_it(page, chain_url):
    _world(chain_url)
    _open_weeks(page, chain_url)
    row = _row(page)
    first, second = _amounts(row).nth(0), _amounts(row).nth(1)
    expect(second).to_have_value("1817.73")
    first.fill("999")
    expect(second).to_have_value("894.76")
    asked = len(page.wire.previews)
    first.fill("12abc")
    expect(first).to_have_class(re.compile(r"\bbad\b"))
    expect(first).to_have_attribute("aria-invalid", "true")
    expect(_confirm(row)).to_be_disabled()
    first.fill(
        "1000"
    )  # a number again: exactly one more preview, and none was asked for the bad text
    expect(second).to_have_value("895.66")
    assert len(page.wire.previews) == asked + 1
    for body in page.wire.previews:
        assert all(
            leg["amount"] is None or isinstance(leg["amount"], (int, float)) for leg in body["legs"]
        )
    expect(first).not_to_have_class(re.compile(r"\bbad\b"))
    expect(_confirm(row)).to_be_enabled()


# ── (j) a late answer ─────────────────────────────────────────────────────────


def test_a_late_preview_never_draws_over_a_newer_one(page, chain_url):
    _world(chain_url)
    held: list = []

    def handler(route):
        body = json.loads(route.request.post_data)
        if body["legs"][0]["amount"] == 100 and not held:
            held.append(route)  # the first answer waits
        else:
            route.continue_()

    page.route("**/api/freelance/payouts/preview", handler)
    _open_weeks(page, chain_url)
    row = _row(page)
    first, second = _amounts(row).nth(0), _amounts(row).nth(1)
    expect(second).to_have_value("1817.73")
    first.fill("100")
    end = time.monotonic() + 8
    while not held and time.monotonic() < end:
        page.wait_for_timeout(50)
    assert held, "the first preview was never asked"
    first.fill("200")
    expect(second).to_have_value("179.13")  # 200 / 1.1165, the second one's figures
    with page.expect_response(lambda r: r.url.endswith("/payouts/preview")):
        held[0].continue_()  # now the first one (100 -> 89.57) arrives
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    # read once, with no retry: a row that drew the late answer would show its figures until it asked again
    assert second.input_value() == "179.13"
    assert _confirm(row).is_enabled()
    expect(row.locator(".wk-gap b")).to_have_text("-$1,829.50")


def test_the_row_keeps_its_figures_while_the_saved_payout_is_read_back(page, chain_url):
    """Between the save and the payouts being read again the fields used to go blank for a moment."""
    _world(chain_url)
    _open_weeks(page, chain_url)
    row = _row(page)
    first, second = _amounts(row).nth(0), _amounts(row).nth(1)
    expect(first).to_have_value("2029.5")
    first.fill("999")
    expect(second).to_have_value("894.76")
    held: list = []

    def handler(route):
        if route.request.method == "GET" and not held:
            held.append(route)  # the payouts read after the save waits
        else:
            route.continue_()

    page.route(re.compile(r"/api/freelance/payouts$"), handler)
    _confirm(row).click()
    end = time.monotonic() + 8
    while not held and time.monotonic() < end:
        page.wait_for_timeout(50)
    assert held, "the payouts were never read again"
    assert (first.input_value(), second.input_value()) == ("999", "894.76")
    held[0].continue_()
    expect(row.locator(".wk-tag")).to_have_text("paid out")
    expect(first).to_have_value("999")
    expect(second).to_have_value("894.76")


def test_a_suggestion_that_lands_in_a_focused_field_is_typed_over_not_added_to(page, chain_url):
    """The field has the focus before its suggestion arrives; what is typed next replaces the suggestion. It
    used to be added to it: 999 typed made "2029.5999", and the row worked out 1817.82 euros."""
    _world(chain_url)
    held: list = []

    def handler(route):
        if held:
            route.continue_()
        else:
            held.append(route)  # the row's first preview waits

    page.route("**/api/freelance/payouts/preview", handler)
    _open_weeks(page, chain_url)
    row = _row(page)
    first, second = _amounts(row).nth(0), _amounts(row).nth(1)
    end = time.monotonic() + 8
    while not held and time.monotonic() < end:
        page.wait_for_timeout(50)
    assert held, "the row never asked for its preview"
    first.focus()  # an empty field with the caret in it
    assert first.input_value() == ""
    with page.expect_response(lambda r: r.url.endswith("/payouts/preview")):
        held[0].continue_()
    expect(first).to_have_value("2029.5")  # the suggestion landed under the caret
    page.keyboard.type("999")
    expect(first).to_have_value("999")
    expect(second).to_have_value("894.76")


# ── (k) changing a saved payout ───────────────────────────────────────────────


def test_changing_a_saved_payout_sends_one_put_with_its_legs(page, chain_url):
    w = _world(chain_url)
    saved = _save(
        chain_url,
        w,
        [
            {"account_id": w["Stripe"], "amount": 999, "fixed": True},
            {"account_id": w["Deutsche Bank"]},
        ],
    )
    assert _legs(saved) == [("Stripe", 999.0, True), ("Deutsche Bank", 894.76, False)]
    _open_weeks(page, chain_url)
    row = _row(page)
    first, second = _amounts(row).nth(0), _amounts(row).nth(1)
    expect(first).to_have_value("999")
    expect(first).not_to_have_class(SUG)  # a fixed leg shows as typed
    expect(second).to_have_value("894.76")
    expect(second).to_have_class(SUG)
    expect(_confirm(row)).to_have_count(0)
    first.fill("1000")
    expect(second).to_have_value("895.66")
    expect(_confirm(row)).to_be_enabled()
    _confirm(row).click()
    got = _wait_for(chain_url, lambda p: p and p[0]["legs"][0]["amount"] == 1000, "the new figures")
    assert len(got) == 1 and got[0]["id"] == saved["id"]
    assert _legs(got[0]) == [("Stripe", 1000.0, True), ("Deutsche Bank", 895.66, False)]
    ((method, body),) = page.wire.saves
    assert method == "PUT" and [leg["amount"] for leg in body["legs"]] == [1000, 895.66]
    expect(_confirm(row)).to_have_count(0)


def test_a_dollar_payout_is_worth_what_was_typed_and_changing_it_is_confirmed(page, chain_url):
    """The old test of the rate pen, in its figures: $100 worth 80 euros against $60 billed (+$40), then worth 62.50."""
    src = _post(
        chain_url, "/api/freelance/sources", name="Northwind", hourly_rate=60, currency="USD"
    )["id"]
    _post(chain_url, "/api/freelance/blocks", source_id=src, date="2026-11-03", hours=1)
    mercury = _post(chain_url, "/api/freelance/accounts", name="Mercury", currency="USD")["id"]
    _post(
        chain_url,
        "/api/freelance/payouts",
        source_id=src,
        week_start=W45,
        legs=[{"account_id": mercury, "amount": 100}],
        eur_amount=80,
    )
    _open_weeks(page, chain_url)
    row = _row(page)
    expect(row.get_by_test_id("pay-conv")).to_have_text("= €80.00")
    expect(row.locator(".wk-gap b")).to_have_text("+$40")  # 100 against the $60 billed
    expect(page.get_by_test_id("days-fl-total")).to_contain_text("€80.00")
    worth = row.get_by_label("Worth in euros, Northwind W45")
    expect(worth).to_have_value("80")  # typed by hand, so it shows as typed
    worth.fill("62.5")
    expect(row.get_by_test_id("pay-conv")).to_have_text("= €62.50")
    assert len(_payouts(chain_url)) == 1 and page.wire.saves == []
    expect(page.get_by_test_id("days-fl-total")).to_contain_text("€80.00")  # not before Confirm
    _confirm(row, "Northwind W45").click()
    _wait_for(chain_url, lambda p: p and p[0]["amount_eur"] == 62.5, "the new value")
    expect(page.get_by_test_id("days-fl-total")).to_contain_text("€62.50")
    ((method, body),) = page.wire.saves
    assert method == "PUT" and body["eur_amount"] == 62.5


# ── (l) the save fails ────────────────────────────────────────────────────────


def test_a_failed_save_keeps_the_draft_and_says_so(page, chain_url):
    _world(chain_url)
    page.route(
        "**/api/freelance/payouts",
        lambda route: (
            route.fulfill(status=500, json={"detail": "boom"})
            if route.request.method == "POST"
            else route.continue_()
        ),
    )
    _open_weeks(page, chain_url)
    row = _row(page)
    first, second = _amounts(row).nth(0), _amounts(row).nth(1)
    first.fill("999")
    expect(second).to_have_value("894.76")
    _confirm(row).click()
    expect(row.locator(".wk-status")).to_have_text("not saved")
    expect(row.locator(".wk-status")).to_have_class(re.compile("is-error"))
    expect(first).to_have_value("999")
    expect(second).to_have_value("894.76")
    expect(_confirm(row)).to_be_enabled()  # it can be tried again
    assert _payouts(chain_url) == []


# ── (m) delete ────────────────────────────────────────────────────────────────


def test_delete_removes_the_payout_and_undo_brings_it_back_with_its_legs(page, chain_url):
    w = _world(chain_url)
    saved = _save(
        chain_url,
        w,
        [
            {"account_id": w["Stripe"], "amount": 999, "fixed": True},
            {"account_id": w["Deutsche Bank"]},
        ],
    )
    _open_weeks(page, chain_url)
    row = _row(page)
    delete = row.get_by_role("button", name="Delete the payout of Acme W45")
    expect(delete).to_be_visible()
    delete.click()
    _wait_for(chain_url, lambda p: p == [], "the payout is deleted")
    expect(page.locator(".save-ribbon.ribbon-show")).to_contain_text("Payout deleted")
    expect(_amounts(row)).to_have_count(2)  # the source's chain again
    expect(_amounts(row).nth(0)).to_have_value("2029.5")
    expect(_amounts(row).nth(0)).to_have_class(SUG)
    expect(_confirm(row)).to_be_enabled()
    expect(row.locator(".wk-tag")).to_have_count(0)  # Confirm stands where the tag was
    expect(page.get_by_test_id("days-fl-total")).to_contain_text(
        "€1,817.73"
    )  # the estimate counts again
    page.locator(".ribbon-action").click()
    got = _wait_for(chain_url, lambda p: len(p) == 1, "the payout is back")[0]
    assert _legs(got) == _legs(saved) == [("Stripe", 999.0, True), ("Deutsche Bank", 894.76, False)]
    assert page.wire.saves[-1][1]["legs"] == [
        {"account_id": w["Stripe"], "amount": 999, "fixed": True},
        {"account_id": w["Deutsche Bank"], "amount": 894.76, "fixed": False},
    ]
    expect(row.get_by_test_id("pay-delete")).to_have_count(1)
    expect(page.get_by_test_id("days-fl-total")).to_contain_text("€894.76")  # and the payout again


# ── (n) Payouts waiting ───────────────────────────────────────────────────────


def test_payouts_waiting_is_the_same_cell_and_its_button_confirms(page, chain_url):
    w = _world(chain_url, days=("2026-11-03", "2026-10-27"))
    # W45 from its Weeks row
    _open_weeks(page, chain_url)
    _amounts(_row(page)).nth(0).fill("999")
    expect(_amounts(_row(page)).nth(1)).to_have_value("894.76")
    _confirm(_row(page)).click()
    _wait_for(chain_url, lambda p: len(p) == 1, "the row saves")
    # W44 from the form of the page where days are logged
    page.goto(f"{chain_url}/#days")
    page.wait_for_selector("[data-testid=pay-wait]")
    chips = page.get_by_test_id("pay-wait-chip")
    expect(chips).to_have_text(["W44"])
    form = page.locator(".fl-wait-form")
    amounts = form.get_by_test_id("pay-amount")
    expect(amounts).to_have_count(2)
    expect(amounts.nth(0)).to_have_value("2029.5")
    expect(amounts.nth(1)).to_have_value("1816.6")  # at W44's 1.1172
    amounts.nth(0).fill("999")
    expect(amounts.nth(1)).to_have_value("894.2")  # 999 / 1.1172
    button = page.get_by_test_id("pay-wait-save")
    expect(button).to_have_text("Confirm")
    expect(button).to_be_enabled()
    assert len(page.wire.saves) == 1  # the Weeks row's POST: typing here saved nothing
    assert len(_payouts(chain_url)) == 1
    button.click()
    both = _wait_for(chain_url, lambda p: len(p) == 2, "the form saves")
    row, wait = (next(p for p in both if p["week_start"] == wk) for wk in (W45, W44))
    assert _legs(row) == [("Stripe", 999.0, True), ("Deutsche Bank", 894.76, False)]
    assert _legs(wait) == [("Stripe", 999.0, True), ("Deutsche Bank", 894.2, False)]
    assert row["source_id"] == wait["source_id"] == w["src"]
    expect(page.locator("[data-testid=pay-wait]")).to_have_count(0)  # the week left the list


def test_the_waiting_form_has_no_save_without_a_ready_row(page, chain_url):
    _world(chain_url, chain=())
    page.goto(f"{chain_url}/#days")
    page.wait_for_selector("[data-testid=pay-wait]")
    button = page.get_by_test_id("pay-wait-save")
    expect(button).to_be_disabled()
    page.locator(".fl-wait-form select.payacct").select_option(label="Deutsche Bank")
    expect(button).to_be_enabled()
    button.click()
    _wait_for(chain_url, lambda p: len(p) == 1, "saved")
    expect(page.locator("[data-testid=pay-wait]")).to_have_count(0)


# ── (o) the old shape never goes out ──────────────────────────────────────────


def test_every_request_to_payouts_has_legs_and_none_has_an_amount(page, chain_url):
    w = _world(chain_url, days=("2026-11-03", "2026-10-27"))
    _save(
        chain_url,
        w,
        [
            {"account_id": w["Stripe"], "amount": 999, "fixed": True},
            {"account_id": w["Deutsche Bank"]},
        ],
    )
    _open_weeks(page, chain_url)
    _amounts(_row(page, W44)).nth(0).fill("500")
    expect(_amounts(_row(page, W44)).nth(1)).to_have_value("447.55")
    _confirm(_row(page, W44), "Acme W44").click()
    _wait_for(chain_url, lambda p: len(p) == 2, "saved")
    _row(page).get_by_role("button", name="Delete the payout of Acme W45").click()
    _wait_for(chain_url, lambda p: len(p) == 1, "deleted")
    page.locator(".ribbon-action").click()
    _wait_for(chain_url, lambda p: len(p) == 2, "restored")
    wire = page.wire
    assert wire.previews and [m for m, _ in wire.saves] == ["POST", "DELETE", "POST"]
    for body in wire.previews + [b for _, b in wire.saves if b is not None]:
        assert "legs" in body and "amount" not in body and body["legs"], body


# ── (p) reduced motion ────────────────────────────────────────────────────────


def test_with_reduced_motion_confirm_saves_and_no_coin_is_made(page, chain_url):
    _world(chain_url)
    page.emulate_media(reduced_motion="reduce")
    _open_weeks(page, chain_url)
    page.evaluate(
        "() => { window.__coins = 0; new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => {"
        " if (n.classList && n.classList.contains('coin-fly')) window.__coins++; })))"
        ".observe(document.body, { childList: true }); }"
    )
    row = _row(page)
    _amounts(row).nth(0).fill("999")
    expect(_amounts(row).nth(1)).to_have_value("894.76")
    _confirm(row).click()
    _wait_for(chain_url, lambda p: len(p) == 1, "saved")
    expect(row.locator(".wk-tag")).to_have_text("paid out")
    assert page.evaluate("window.__coins") == 0 and page.locator(".coin-fly").count() == 0


def test_without_reduced_motion_confirm_makes_coins(page, chain_url):
    """A positive control for the test above: the same save does fly coins when motion is allowed."""
    _world(chain_url)
    _open_weeks(page, chain_url)
    page.evaluate(
        "() => { window.__coins = 0; new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => {"
        " if (n.classList && n.classList.contains('coin-fly')) window.__coins++; })))"
        ".observe(document.body, { childList: true }); }"
    )
    row = _row(page)
    _amounts(row).nth(0).fill("999")
    expect(_amounts(row).nth(1)).to_have_value("894.76")
    _confirm(row).click()
    page.wait_for_function("() => window.__coins > 0")


# ── a preview that fails: the row says so and asks again, once ────────────────

PREVIEW = "**/api/freelance/payouts/preview"


def test_a_preview_that_fails_once_says_no_answer_and_asks_again_by_itself(page, chain_url):
    _world(chain_url)
    asked = {"n": 0}

    def handler(route):
        asked["n"] += 1
        if asked["n"] == 1:
            route.fulfill(status=500, json={"detail": "boom"})
        else:
            route.continue_()

    page.route(PREVIEW, handler)
    _open_weeks(page, chain_url)
    row = _row(page)
    status = row.locator(".wk-status")
    expect(status).to_have_text("no answer")
    expect(status).to_have_class(re.compile("is-noanswer"))
    expect(_confirm(row)).to_be_disabled()
    # no key is pressed: the row asks again on its own and the answer clears the status
    expect(_amounts(row).nth(1)).to_have_value("1817.73")
    expect(_confirm(row)).to_be_enabled()
    expect(status).to_have_text("")
    assert len(page.wire.previews) == 2


def test_a_preview_the_server_refuses_says_no_answer_and_is_not_asked_again(page, chain_url):
    _world(chain_url)
    page.route(
        PREVIEW,
        lambda route: route.fulfill(status=422, json={"detail": "that account is archived"}),
    )
    _open_weeks(page, chain_url)
    row = _row(page)
    expect(row.locator(".wk-status")).to_have_text("no answer")
    expect(_confirm(row)).to_be_disabled()
    assert len(page.wire.previews) == 1
    # nothing arrives to wait for when nothing is asked: a fixed wait is the only way to see that it stays so
    page.wait_for_timeout(3000)
    assert len(page.wire.previews) == 1
    expect(row.locator(".wk-status")).to_have_text("no answer")


# ── what a draft is, who may be confirmed, how many are asked at once ─────────


def test_a_draft_that_equals_the_row_is_dropped(page, chain_url):
    w = _world(chain_url, days=("2026-11-03", "2026-10-27"))
    _save(
        chain_url,
        w,
        [
            {"account_id": w["Stripe"], "amount": 999, "fixed": True},
            {"account_id": w["Deutsche Bank"]},
        ],
    )
    _open_weeks(page, chain_url)
    drafts = "Object.keys(Alpine.$data(document.querySelector('main')).payDrafts).length"
    # a saved payout: another amount, then the saved one again: no Confirm, Delete is back
    row = _row(page)
    first = _amounts(row).nth(0)
    first.fill("1000")
    expect(_confirm(row)).to_be_enabled()
    expect(row.get_by_test_id("pay-delete")).to_have_count(0)
    first.fill("999")
    expect(_confirm(row)).to_have_count(0)
    expect(row.get_by_test_id("pay-delete")).to_have_count(1)
    page.wait_for_function(f"() => ({drafts}) === 0")
    # an unsaved row: typed, then cleared with the X: no draft is left
    other = _row(page, W44)
    _amounts(other).nth(0).fill("500")
    page.wait_for_function(f"() => ({drafts}) === 1")
    other.get_by_role("button", name="Clear Stripe amount, Acme W44").click()
    page.wait_for_function(f"() => ({drafts}) === 0")


def test_the_diff_chip_waits_for_a_key_on_an_untouched_row(page, chain_url):
    _world(chain_url)  # dollars billed, paid into a euro account
    _open_weeks(page, chain_url)
    row = _row(page)
    expect(_amounts(row).nth(1)).to_have_value("1817.73")
    expect(_confirm(row)).to_be_enabled()  # the preview is in
    expect(row.get_by_test_id("fx-chip")).to_have_count(0)
    _amounts(row).nth(0).fill("999")
    expect(row.get_by_test_id("fx-chip")).to_have_count(1)


def test_no_more_than_four_previews_are_in_flight_and_every_row_gets_its_figures(page, chain_url):
    days = ("2026-11-03", "2026-10-27", "2026-10-20", "2026-10-13", "2026-10-06", "2026-09-29")
    mondays = ("2026-11-02", "2026-10-26", "2026-10-19", "2026-10-12", "2026-10-05", "2026-09-28")
    _world(chain_url, days=days)
    held: list = []
    flight = {"now": 0, "peak": 0}

    def handler(route):
        flight["now"] += 1
        flight["peak"] = max(flight["peak"], flight["now"])
        held.append(route)  # every answer waits until it is let go

    page.route(PREVIEW, handler)
    _open_weeks(page, chain_url)
    end = time.monotonic() + 8
    while len(held) < 4 and time.monotonic() < end:
        page.wait_for_timeout(50)
    assert len(held) == 4
    # a fifth request that must not come cannot be waited for: give it time to (wrongly) arrive
    page.wait_for_timeout(1000)
    assert len(held) == 4 and flight["peak"] == 4
    rows = [_row(page, m) for m in mondays]
    end = time.monotonic() + 30
    while time.monotonic() < end:
        if held:
            flight["now"] -= 1
            held.pop(0).continue_()
        elif all(r.get_by_test_id("pay-amount").nth(1).input_value() for r in rows):
            break
        else:
            page.wait_for_timeout(50)
    assert flight["peak"] <= 4
    for r in rows:
        expect(_amounts(r).nth(1)).not_to_have_value("")


def test_changing_a_saved_payout_keeps_its_note(page, chain_url):
    w = _world(chain_url)
    legs = [
        {"account_id": w["Stripe"], "amount": 999, "fixed": True},
        {"account_id": w["Deutsche Bank"]},
    ]
    saved = _save(chain_url, w, legs, note="paid late")
    assert saved["note"] == "paid late"
    _open_weeks(page, chain_url)
    row = _row(page)
    _amounts(row).nth(0).fill("1000")
    _confirm(row).click()
    got = _wait_for(
        chain_url, lambda p: p and p[0]["legs"][0]["amount"] == 1000, "the new figures"
    )[0]
    assert got["note"] == "paid late"


def test_confirm_pressed_twice_sends_one_post(page, chain_url):
    _world(chain_url)
    _open_weeks(page, chain_url)
    row = _row(page)
    _amounts(row).nth(0).fill("999")
    expect(_amounts(row).nth(1)).to_have_value("894.76")
    expect(_confirm(row)).to_be_enabled()
    _confirm(row).dblclick()
    _wait_for(chain_url, lambda p: len(p) == 1, "saved")
    expect(row.locator(".wk-tag")).to_have_text("paid out")
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => requestAnimationFrame(r))))"
    )
    assert [m for m, _ in page.wire.saves] == ["POST"]


def test_zero_is_not_an_amount(page, chain_url):
    _world(chain_url)
    _open_weeks(page, chain_url)
    row = _row(page)
    first = _amounts(row).nth(0)
    expect(_confirm(row)).to_be_enabled()
    first.fill("0")
    expect(first).to_have_class(re.compile(r"\bbad\b"))
    expect(_confirm(row)).to_be_disabled()


def test_the_waiting_form_stays_on_its_week_when_the_save_fails(page, chain_url):
    _world(chain_url, days=("2026-11-03", "2026-10-27"))
    page.route(
        "**/api/freelance/payouts",
        lambda route: (
            route.fulfill(status=500, json={"detail": "boom"})
            if route.request.method == "POST"
            else route.continue_()
        ),
    )
    page.goto(f"{chain_url}/#days")
    page.wait_for_selector("[data-testid=pay-wait]")
    form = page.locator(".fl-wait-form")
    amounts = form.get_by_test_id("pay-amount")
    amounts.nth(0).fill("999")
    expect(amounts.nth(1)).to_have_value("894.76")
    button = page.get_by_test_id("pay-wait-save")
    expect(button).to_be_enabled()
    button.click()
    expect(form.locator(".wk-status")).to_have_text("not saved")
    chip = page.locator("[data-testid=pay-wait-chip][data-week='2026-11-02']")
    expect(chip).to_have_attribute("aria-checked", "true")  # the same week is still picked
    expect(amounts.nth(0)).to_have_value("999")  # and its draft is still in the fields
    expect(button).to_be_enabled()
    assert _payouts(chain_url) == []


def test_a_preview_that_always_fails_is_asked_twice_and_no_more(page, chain_url):
    _world(chain_url)
    page.route(PREVIEW, lambda route: route.fulfill(status=500, json={"detail": "boom"}))
    _open_weeks(page, chain_url)
    row = _row(page)
    expect(row.locator(".wk-status")).to_have_text("no answer")
    end = time.monotonic() + 8
    while len(page.wire.previews) < 2 and time.monotonic() < end:
        page.wait_for_timeout(50)
    assert len(page.wire.previews) == 2  # the first, and the one retry 2 s later
    # nothing arrives to wait for when nothing is asked: a fixed wait is the only way to see that it stays so
    page.wait_for_timeout(5000)
    assert len(page.wire.previews) == 2
    expect(row.locator(".wk-status")).to_have_text("no answer")
    expect(_confirm(row)).to_be_disabled()


# ── a draft is kept in the browser until Confirm or the arrow ─────────────────
# Each test has a browser context of its own, so its storage starts empty (the ones that put something there do it
# with an init script before the page loads).

DRAFTS = "k-pay-drafts"
BRASS_TOKEN = "--k-brass"


def _stored(page) -> dict:
    return json.loads(page.evaluate(f"localStorage.getItem('{DRAFTS}') || '{{}}'"))


def _stored_without(page, key):
    page.wait_for_function(
        f"(k) => !(k in JSON.parse(localStorage.getItem('{DRAFTS}') || '{{}}'))", arg=key
    )


def _undo(row):
    return row.get_by_test_id("pay-discard")


def test_a_draft_survives_a_reload_and_confirm_saves_what_it_shows(page, chain_url):
    w = _world(chain_url)
    key = f"{w['src']}|{W45}"
    _open_weeks(page, chain_url)
    row = _row(page)
    _amounts(row).nth(0).fill("999")
    expect(_amounts(row).nth(1)).to_have_value("894.76")
    assert key in _stored(page)
    page.reload()  # the page loads again
    _open_weeks(page, chain_url)
    row = _row(page)
    first, second = _amounts(row).nth(0), _amounts(row).nth(1)
    expect(first).to_have_value("999")
    expect(first).not_to_have_class(SUG)
    expect(second).to_have_value("894.76")
    expect(second).to_have_class(SUG)
    expect(_confirm(row)).to_be_enabled()
    expect(_confirm(row)).not_to_have_class(re.compile("calm"))
    expect(_undo(row)).to_have_count(1)
    assert _payouts(chain_url) == []
    _confirm(row).click()
    got = _wait_for(chain_url, lambda p: len(p) == 1, "saved")[0]
    assert _legs(got) == [("Stripe", 999.0, True), ("Deutsche Bank", 894.76, False)]
    assert [m for m, _ in page.wire.saves] == ["POST"]
    _stored_without(page, key)


def test_the_arrow_discards_a_draft_of_an_unsaved_row_and_of_a_saved_one(page, chain_url):
    w = _world(chain_url, days=("2026-11-03", "2026-10-27"))
    key = f"{w['src']}|{W44}"
    _save(
        chain_url,
        w,
        [
            {"account_id": w["Stripe"], "amount": 999, "fixed": True},
            {"account_id": w["Deutsche Bank"]},
        ],
    )
    _open_weeks(page, chain_url)
    # an unsaved row
    other = _row(page, W44)
    first = _amounts(other).nth(0)
    first.fill("999")
    expect(_undo(other)).to_have_count(1)
    assert key in _stored(page)
    _undo(other).click()
    expect(first).to_have_value("2029.5")
    expect(first).to_have_class(SUG)
    expect(_undo(other)).to_have_count(0)
    expect(other.get_by_test_id("pay-confirm")).to_have_class(re.compile("calm"))
    _stored_without(page, key)
    expect(first).to_be_focused()
    # a saved payout: the badge gives way to a solid Confirm and the arrow; Delete is gone
    row = _row(page)
    a = _amounts(row).nth(0)
    expect(row.locator(".wk-tag")).to_have_text("paid out")
    a.fill("1000")
    expect(_confirm(row)).to_be_enabled()
    expect(_confirm(row)).not_to_have_class(re.compile("calm"))
    expect(_undo(row)).to_have_count(1)
    expect(row.get_by_test_id("pay-delete")).to_have_count(0)
    expect(row.locator(".wk-tag")).to_have_count(0)
    _undo(row).click()
    expect(a).to_have_value("999")
    expect(_amounts(row).nth(1)).to_have_value("894.76")
    expect(row.locator(".wk-tag")).to_have_text("paid out")
    expect(row.get_by_test_id("pay-delete")).to_have_count(1)
    assert page.wire.saves == []


def test_the_stored_draft_goes_when_the_row_is_back_to_what_it_was(page, chain_url):
    w = _world(chain_url, chain=("Stripe", "Mercury"), days=("2026-11-03", "2026-10-27"))
    _save(
        chain_url,
        w,
        [{"account_id": w["Stripe"], "amount": 999, "fixed": True}, {"account_id": w["Mercury"]}],
    )
    key45, key44 = f"{w['src']}|{W45}", f"{w['src']}|{W44}"
    _open_weeks(page, chain_url)
    # the saved amount typed back
    saved = _row(page)
    _amounts(saved).nth(0).fill("1000")
    assert key45 in _stored(page)
    _amounts(saved).nth(0).fill("999")
    _stored_without(page, key45)
    # the X on the only typed line
    other = _row(page, W44)
    _amounts(other).nth(0).fill("500")
    assert key44 in _stored(page)
    other.get_by_role("button", name="Clear Stripe amount, Acme W44").click()
    _stored_without(page, key44)
    # a euro value typed and then emptied
    other.get_by_role("button", name="Set the € value of Acme W44").click()
    worth = other.get_by_label("Worth in euros, Acme W44")
    worth.fill("890")
    assert key44 in _stored(page)
    worth.fill("")
    _stored_without(page, key44)


@pytest.mark.parametrize(
    "case",
    [
        "not json",
        "other shape",
        "a source that is gone",
        "an account that is gone",
        "lines of the wrong shape",
        "a typed amount that is a number",
        "a line that is null",
        "five lines",
    ],
)
def test_what_is_stored_is_not_trusted(page, chain_url, case):
    w = _world(chain_url)
    line = {
        "lines": [{"acc": w["Stripe"], "typed": "5"}, {"acc": w["Deutsche Bank"], "typed": None}],
        "eur": None,
    }
    bad = {
        "not json": "this is {not json",
        "other shape": json.dumps({"x": 1}),
        "a source that is gone": json.dumps({f"9999|{W45}": line}),
        "an account that is gone": json.dumps(
            {f"{w['src']}|{W45}": {"lines": [{"acc": 99999, "typed": "5"}], "eur": None}}
        ),
        "lines of the wrong shape": json.dumps(
            {f"{w['src']}|{W45}": {"lines": [{"acc": "1", "typed": 5}], "eur": None}}
        ),
        "a typed amount that is a number": json.dumps(
            {f"{w['src']}|{W45}": {"lines": [{"acc": None, "typed": 5}], "eur": None}}
        ),
        "a line that is null": json.dumps({f"{w['src']}|{W45}": {"lines": [None], "eur": None}}),
        "five lines": json.dumps(
            {
                f"{w['src']}|{W45}": {
                    "lines": [{"acc": w["Stripe"], "typed": "5"}] * 5,
                    "eur": None,
                }
            }
        ),
    }[case]
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(f"localStorage.setItem('{DRAFTS}', {json.dumps(bad)})")
    _open_weeks(page, chain_url)
    row = _row(page)
    expect(_amounts(row)).to_have_count(2)  # the page draws its rows
    expect(_amounts(row).nth(0)).to_have_value("2029.5")
    page.wait_for_function(
        f"() => {{ try {{ return JSON.stringify(JSON.parse(localStorage.getItem('{DRAFTS}'))) === '{{}}'; }} catch (e) {{ return false; }} }}"
    )
    assert _stored(page) == {}
    assert errors == []


def test_storage_that_throws_changes_nothing_for_the_row(page, chain_url):
    _world(chain_url)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(
        f"""(() => {{ const get = Storage.prototype.getItem, set = Storage.prototype.setItem;
        Storage.prototype.getItem = function (k) {{ if (k === '{DRAFTS}') throw new Error('blocked'); return get.call(this, k); }};
        Storage.prototype.setItem = function (k, v) {{ if (k === '{DRAFTS}') throw new Error('blocked'); return set.call(this, k, v); }}; }})()"""
    )
    _open_weeks(page, chain_url)
    row = _row(page)
    first = _amounts(row).nth(0)
    first.fill("999")
    expect(_amounts(row).nth(1)).to_have_value("894.76")
    expect(_undo(row)).to_have_count(1)
    _undo(row).click()
    expect(first).to_have_value("2029.5")
    first.fill("999")
    expect(_amounts(row).nth(1)).to_have_value("894.76")
    _confirm(row).click()
    got = _wait_for(chain_url, lambda p: len(p) == 1, "saved")[0]
    assert _legs(got) == [("Stripe", 999.0, True), ("Deutsche Bank", 894.76, False)]
    assert errors == []


def test_confirm_is_calm_until_something_changes(page, chain_url):
    _world(chain_url)
    _open_weeks(page, chain_url)
    row = _row(page)
    button = _confirm(row)
    expect(button).to_have_class(re.compile("calm"))
    expect(button).to_have_css("background-color", "rgba(0, 0, 0, 0)")
    _amounts(row).nth(0).fill("999")
    expect(button).not_to_have_class(re.compile("calm"))
    expect(button).to_have_css(
        "background-color", _bg_of(page, BRASS_TOKEN)
    )  # after its transition
    _undo(row).click()
    expect(button).to_have_class(re.compile("calm"))
    expect(button).to_have_css("background-color", "rgba(0, 0, 0, 0)")


def _bg_of(page, token: str) -> str:
    return page.evaluate(
        "(n) => { const d = document.createElement('i'); d.style.backgroundColor = `var(${n})`;"
        " document.body.appendChild(d); const c = getComputedStyle(d).backgroundColor; d.remove(); return c; }",
        token,
    )


def test_each_source_line_of_a_week_has_its_own_badge_and_the_week_tag_follows(page, chain_url):
    w = _world(chain_url)
    side = _post(
        chain_url,
        "/api/freelance/sources",
        name="Side",
        hourly_rate=50,
        currency="USD",
        chain=[w["Stripe"]],
    )["id"]
    _post(chain_url, "/api/freelance/blocks", source_id=side, date="2026-11-03", hours=1)
    _open_weeks(page, chain_url)
    acme = page.locator(".wk-line[data-source='Acme']")
    other = page.locator(".wk-line[data-source='Side']")
    tag = page.locator(f"tr.wk-row#wk-{W45} .wk-main .wk-tag")
    expect(acme.get_by_test_id("pay-confirm")).to_have_count(1)
    expect(other.get_by_test_id("pay-confirm")).to_have_count(1)
    expect(tag).to_have_text("estimated")
    expect(acme.get_by_test_id("pay-confirm")).to_be_enabled()
    acme.get_by_test_id("pay-confirm").click()
    expect(acme.locator(".wk-tag")).to_have_text("paid out")
    expect(acme.get_by_test_id("pay-delete")).to_have_count(1)
    expect(other.locator(".wk-tag")).to_have_count(0)
    expect(tag).to_have_text("part paid out")
    expect(other.get_by_test_id("pay-confirm")).to_be_enabled()
    other.get_by_test_id("pay-confirm").click()
    expect(other.locator(".wk-tag")).to_have_text("paid out")
    expect(tag).to_have_text("paid out")
    acme.get_by_role("button", name="Delete the payout of Acme W45").click()
    expect(acme.get_by_test_id("pay-confirm")).to_have_count(1)
    expect(acme.locator(".wk-tag")).to_have_count(0)
    expect(tag).to_have_text("part paid out")
    assert side and w


def test_a_draft_typed_in_payouts_waiting_is_the_one_of_the_weeks_row(page, chain_url):
    w = _world(chain_url, days=("2026-11-03", "2026-10-27"))
    key = f"{w['src']}|{W45}"
    page.goto(f"{chain_url}/#days")
    page.wait_for_selector("[data-testid=pay-wait]")
    form = page.locator(".fl-wait-form")
    amounts = form.get_by_test_id("pay-amount")
    amounts.nth(0).fill("999")
    expect(amounts.nth(1)).to_have_value("894.76")
    expect(form.get_by_test_id("pay-discard")).to_have_count(1)
    _open_weeks(page, chain_url)  # the same figures in the Weeks row
    row = _row(page)
    expect(_amounts(row).nth(0)).to_have_value("999")
    expect(_amounts(row).nth(1)).to_have_value("894.76")
    page.reload()  # and it survives a reload there
    _open_weeks(page, chain_url)
    expect(_amounts(_row(page)).nth(0)).to_have_value("999")
    page.goto(f"{chain_url}/#days")
    page.wait_for_selector("[data-testid=pay-wait]")
    amounts = page.locator(".fl-wait-form").get_by_test_id("pay-amount")
    expect(amounts.nth(0)).to_have_value("999")
    page.locator(".fl-wait-form").get_by_test_id("pay-discard").click()
    expect(amounts.nth(0)).to_have_value("2029.5")
    _stored_without(page, key)
    assert page.wire.saves == []


def test_with_reduced_motion_the_arrow_and_confirm_have_no_animation_or_transition(page, chain_url):
    _world(chain_url)
    page.emulate_media(reduced_motion="reduce")
    _open_weeks(page, chain_url)
    row = _row(page)
    _amounts(row).nth(0).fill("999")
    expect(_undo(row)).to_have_count(1)
    for loc in (_confirm(row), _undo(row)):
        style = loc.evaluate(
            "e => { const s = getComputedStyle(e); return [s.animationName, s.transitionDuration]; }"
        )
        assert style == ["none", "0s"], style


def test_a_stored_draft_that_equals_its_saved_row_is_dropped_at_load(page, chain_url):
    w = _world(chain_url)
    _save(
        chain_url,
        w,
        [
            {"account_id": w["Stripe"], "amount": 999, "fixed": True},
            {"account_id": w["Deutsche Bank"]},
        ],
    )
    key = f"{w['src']}|{W45}"
    same = {
        "lines": [{"acc": w["Stripe"], "typed": "999"}, {"acc": w["Deutsche Bank"], "typed": None}],
        "eur": None,
    }
    page.add_init_script(f"localStorage.setItem('{DRAFTS}', {json.dumps(json.dumps({key: same}))})")
    _open_weeks(page, chain_url)
    row = _row(page)
    expect(row.locator(".wk-tag")).to_have_text("paid out")
    expect(row.get_by_test_id("pay-delete")).to_have_count(1)
    expect(_confirm(row)).to_have_count(0)
    _stored_without(page, key)


def test_a_stored_draft_is_not_judged_while_the_payouts_could_not_be_read(page, chain_url):
    """The week has a saved payout (999 typed) and a stored draft that clears it: the chain with nothing typed.
    When the payouts cannot be read the page takes the week for an unpaid one, where that draft says nothing new;
    it must not drop it for that."""
    w = _world(chain_url)
    _save(
        chain_url,
        w,
        [
            {"account_id": w["Stripe"], "amount": 999, "fixed": True},
            {"account_id": w["Deutsche Bank"]},
        ],
    )
    key = f"{w['src']}|{W45}"
    cleared = {
        "lines": [{"acc": w["Stripe"], "typed": None}, {"acc": w["Deutsche Bank"], "typed": None}],
        "eur": None,
    }
    page.add_init_script(
        f"if (!localStorage.getItem('{DRAFTS}')) localStorage.setItem('{DRAFTS}', {json.dumps(json.dumps({key: cleared}))})"
    )
    page.route(
        re.compile(r"/api/freelance/payouts$"),
        lambda r: (
            r.fulfill(status=500, content_type="application/json", body='{"detail": "down"}')
            if r.request.method == "GET"
            else r.continue_()
        ),
    )
    _open_weeks(page, chain_url)
    expect(_amounts(_row(page))).to_have_count(2)
    page.wait_for_load_state("networkidle")
    assert key in json.loads(page.evaluate(f"() => localStorage.getItem('{DRAFTS}')"))


def test_the_arrow_closes_a_worth_field_that_was_opened_by_hand(page, chain_url):
    _world(chain_url, chain=("Stripe", "Mercury"))
    _open_weeks(page, chain_url)
    row = _row(page)
    row.get_by_role("button", name="Set the € value of Acme W45").click()
    worth = row.get_by_label("Worth in euros, Acme W45")
    worth.fill("890")
    expect(_undo(row)).to_have_count(1)
    _undo(row).click()
    expect(worth).to_have_count(0)
    expect(row.get_by_role("button", name="Set the € value of Acme W45")).to_have_count(1)


def test_a_draft_typed_in_one_tab_shows_in_the_other_and_neither_loses_the_other_s(page, chain_url):
    w = _world(chain_url, days=("2026-11-03", "2026-10-27"))
    key45, key44 = f"{w['src']}|{W45}", f"{w['src']}|{W44}"
    other = page.context.new_page()
    other.set_default_timeout(8000)
    try:
        _open_weeks(page, chain_url)
        _open_weeks(other, chain_url)
        _amounts(_row(page)).nth(0).fill("999")
        # the second tab shows it without a reload: the value, and a solid Confirm
        expect(_amounts(_row(other)).nth(0)).to_have_value("999")
        expect(_confirm(_row(other))).not_to_have_class(re.compile("calm"))
        # a draft typed in the second tab does not replace the first's
        _amounts(_row(other, W44)).nth(0).fill("500")
        page.wait_for_function(
            f"() => {{ const s = JSON.parse(localStorage.getItem('{DRAFTS}')); return '{key45}' in s && '{key44}' in s; }}"
        )
        assert set(_stored(page)) == {key45, key44}
        expect(_amounts(_row(page, W44)).nth(0)).to_have_value(
            "500"
        )  # and the first tab got it too
        # the arrow in the first tab clears its row in the second
        _undo(_row(page)).click()
        expect(_amounts(_row(other)).nth(0)).to_have_value("2029.5")
        expect(_undo(_row(other))).to_have_count(0)
        assert set(_stored(page)) == {key44}
    finally:
        other.close()


# ── the seal of a confirmed payout ────────────────────────────────────────────
# Confirm in Weeks: a seal falls where the button was, the coins fly from it once, it leaves and the badge inks in.
# The page is watched from inside (a MutationObserver and one frame loop), so the tests wait for states, never for time.

SEAL_WATCH = """() => {
  const w = window.__seal = { seals: [], coins: [] };
  const rec = new Map();
  const shown = (e) => !!e && getComputedStyle(e).visibility !== 'hidden' && e.offsetParent !== null;
  const see = (s) => {
    if (rec.has(s)) return;
    const tr = s.closest('tr'), line = s.closest('.wk-line');
    const r = { row: tr ? tr.id : null, source: line ? line.dataset.source : null, added: performance.now(),
                log: [], hit: null, out: null, removed: null, leaked: 0, api: null };
    rec.set(s, r);
    w.seals.push(r);
    fetch('/api/freelance/payouts').then((x) => x.json()).then((a) => { r.api = { n: a.length, left: r.out !== null }; });
  };
  new MutationObserver((ms) => ms.forEach((m) => {
    if (m.type === 'childList') {
      m.addedNodes.forEach((n) => {
        if (n.nodeType !== 1) return;
        if (n.classList.contains('seal')) see(n);
        if (n.classList.contains('coin-fly')) w.coins.push(performance.now());
      });
      m.removedNodes.forEach((n) => { const r = rec.get(n); if (r && r.removed === null) r.removed = performance.now(); });
    } else if (m.target.classList && m.target.classList.contains('seal')) {
      const r = rec.get(m.target);
      if (!r) return;
      for (const c of ['hit', 'out']) {
        if (m.target.classList.contains(c) && r[c] === null) { r[c] = performance.now(); r.log.push(c); }
      }
    }
  })).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  const look = () => {
    for (const [s, r] of rec) {
      if (r.removed !== null) continue;
      if (!s.isConnected) { r.removed = performance.now(); r.orphaned = true; continue; }
      const tail = s.closest('.wk-tail');
      if (tail && (shown(tail.querySelector('.wk-tag')) || shown(tail.querySelector('.pay-del')))) r.leaked++;
    }
    requestAnimationFrame(look);
  };
  look();
}"""


def _watch_seals(page) -> None:
    page.evaluate(SEAL_WATCH)


def _seals_gone(page, n: int) -> dict:
    """Wait until `n` seals were added and every one of them has been taken out; the watcher's record."""
    page.wait_for_function(
        "(n) => window.__seal.seals.length >= n && window.__seal.seals.every((s) => s.removed !== null)",
        arg=n,
        timeout=10000,
    )
    return page.evaluate("window.__seal")


def _bursts(times: list[float]) -> list[int]:
    """The coins of one payout are all made in one go: times closer than 30 ms are one burst."""
    out: list[list[float]] = []
    for t in sorted(times):
        if out and t - out[-1][-1] < 30:
            out[-1].append(t)
        else:
            out.append([t])
    return [len(b) for b in out]


def _check_seal(s: dict, monday: str) -> None:
    assert s["row"] == f"wk-{monday}", s
    assert s["log"] == ["hit", "out"], s  # it landed, then it left, in that order
    assert s["added"] + 250 <= s["hit"] <= s["out"] <= s["removed"], s
    assert s["removed"] - s["added"] >= 1200, s  # it ran to its end
    assert s["leaked"] == 0, s  # the badge and Delete stayed hidden while it was there
    assert s["api"] and s["api"]["n"] >= 1 and not s["api"]["left"], s  # saved before it left


def _ends_with_badge(row, label="Acme W45") -> None:
    expect(row.locator(".wk-tag")).to_have_text("paid out")
    expect(row.locator(".wk-tag")).to_be_visible()
    expect(row.get_by_role("button", name=f"Delete the payout of {label}")).to_be_visible()
    expect(row.locator(".seal")).to_have_count(0)
    expect(row.locator(".wk-tail.stamping")).to_have_count(0)
    expect(row).not_to_have_class(re.compile(r"\bthud\b"))


def test_confirm_of_a_new_payout_drops_one_seal_that_becomes_the_badge(page, chain_url):
    _world(chain_url)
    _open_weeks(page, chain_url)
    row = _row(page)
    _amounts(row).nth(0).fill("999")
    expect(_amounts(row).nth(1)).to_have_value("894.76")
    _watch_seals(page)
    _confirm(row).click()
    got = _seals_gone(page, 1)
    assert len(got["seals"]) == 1
    _check_seal(got["seals"][0], W45)
    assert _bursts(got["coins"]) == [9], got["coins"]  # 894.76 euros: nine coins, one burst
    assert got["coins"][0] >= got["seals"][0]["hit"] - 5  # they fly from the seal, once it landed
    _ends_with_badge(row)
    assert len(_payouts(chain_url)) == 1


def test_confirm_of_a_change_to_a_saved_payout_drops_the_seal_too(page, chain_url):
    w = _world(chain_url)
    _save(
        chain_url,
        w,
        [
            {"account_id": w["Stripe"], "amount": 999, "fixed": True},
            {"account_id": w["Deutsche Bank"]},
        ],
    )
    _open_weeks(page, chain_url)
    row = _row(page)
    _amounts(row).nth(0).fill("1000")
    expect(_amounts(row).nth(1)).to_have_value("895.66")
    expect(row.get_by_test_id("pay-delete")).to_have_count(0)  # a draft: Confirm stands there
    _watch_seals(page)
    _confirm(row).click()
    got = _seals_gone(page, 1)
    assert len(got["seals"]) == 1
    _check_seal(got["seals"][0], W45)
    assert _bursts(got["coins"]) == [9], got["coins"]
    _ends_with_badge(row)
    assert _payouts(chain_url)[0]["legs"][0]["amount"] == 1000


def test_two_confirms_in_a_row_cut_neither_seal_and_both_bursts_land(page, chain_url):
    _world(chain_url, days=("2026-11-03", "2026-10-27"))
    _open_weeks(page, chain_url)
    r45, r44 = _row(page, W45), _row(page, W44)
    _amounts(r45).nth(0).fill("999")
    _amounts(r44).nth(0).fill("500")
    expect(_amounts(r45).nth(1)).to_have_value("894.76")
    expect(_amounts(r44).nth(1)).to_have_value("447.55")
    expect(_confirm(r44, "Acme W44")).to_be_enabled()
    _watch_seals(page)
    _confirm(r45).click()
    page.wait_for_function(
        "() => window.__seal.seals.length === 1 && window.__seal.seals[0].removed === null"
    )
    _confirm(r44, "Acme W44").click()  # the first seal is still there
    got = _seals_gone(page, 2)
    first, second = got["seals"]
    assert (first["row"], second["row"]) == (f"wk-{W45}", f"wk-{W44}")
    assert second["added"] < first["removed"], got  # they overlapped
    _check_seal(first, W45)
    _check_seal(second, W44)
    assert _bursts(got["coins"]) == [9, 4], got["coins"]  # 894.76 and 447.55 euros
    _ends_with_badge(r45)
    _ends_with_badge(r44, "Acme W44")
    assert len(_payouts(chain_url)) == 2


def test_with_reduced_motion_no_seal_is_made_and_the_badge_is_there_when_saved(page, chain_url):
    _world(chain_url)
    page.emulate_media(reduced_motion="reduce")
    _open_weeks(page, chain_url)
    row = _row(page)
    _amounts(row).nth(0).fill("999")
    expect(_amounts(row).nth(1)).to_have_value("894.76")
    _watch_seals(page)
    _confirm(row).click()
    _wait_for(chain_url, lambda p: len(p) == 1, "saved")
    _ends_with_badge(row)
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    got = page.evaluate("window.__seal")
    assert got["seals"] == [] and got["coins"] == []
    assert page.locator(".seal").count() == 0 and page.locator(".coin-fly").count() == 0


def test_payouts_waiting_has_no_seal_and_its_coins_fly_from_its_button(page, chain_url):
    _world(chain_url)
    page.goto(f"{chain_url}/#days")
    page.wait_for_selector("[data-testid=pay-wait]")
    amounts = page.locator(".fl-wait-form").get_by_test_id("pay-amount")
    amounts.nth(0).fill("999")
    expect(amounts.nth(1)).to_have_value("894.76")
    button = page.get_by_test_id("pay-wait-save")
    expect(button).to_be_enabled()
    _watch_seals(page)
    button.click()
    page.wait_for_function("() => window.__seal.coins.length >= 9")
    _wait_for(chain_url, lambda p: len(p) == 1, "saved")
    expect(page.locator("[data-testid=pay-wait]")).to_have_count(0)  # the week left the list
    got = page.evaluate("window.__seal")
    assert got["seals"] == [] and _bursts(got["coins"]) == [9], got
    assert page.locator(".seal").count() == 0


def _spy_toasts(page) -> None:
    _app(
        page,
        "const o = d.showToast.bind(d); window.__toasts = [];"
        " d.showToast = (...a) => { window.__toasts.push(a[0]); return o(...a); };",
    )


def test_the_first_payout_of_a_source_with_no_chain_says_which_account_it_became(page, chain_url):
    w = _world(chain_url, chain=())
    _open_weeks(page, chain_url)
    _spy_toasts(page)
    row = _row(page)
    row.locator("select.payacct").select_option(label="Deutsche Bank")
    expect(_confirm(row)).to_be_enabled()
    _confirm(row).click()
    expect(page.locator(".save-ribbon.ribbon-show")).to_have_text(
        re.compile(r"Deutsche Bank is now the first account of Acme")
    )
    assert httpx.get(f"{chain_url}/api/freelance/sources").json()[0]["chain"] == [
        w["Deutsche Bank"]
    ]
    assert page.evaluate("window.__toasts") == ["Deutsche Bank is now the first account of Acme"]


def test_the_notice_shows_with_reduced_motion_too(page, chain_url):
    _world(chain_url, chain=())
    page.emulate_media(reduced_motion="reduce")
    _open_weeks(page, chain_url)
    row = _row(page)
    row.locator("select.payacct").select_option(label="Wise")
    _confirm(row).click()
    expect(page.locator(".save-ribbon.ribbon-show")).to_contain_text(
        "Wise is now the first account of Acme"
    )


def test_a_source_that_had_a_chain_gets_no_such_notice(page, chain_url):
    _world(chain_url)
    _open_weeks(page, chain_url)
    _spy_toasts(page)
    row = _row(page)
    _watch_seals(page)
    _confirm(row).click()
    got = _seals_gone(page, 1)  # by now the notice, if there were one, has been asked for
    assert page.evaluate("window.__toasts") == [], got
    _ends_with_badge(row)


def test_a_seal_whose_image_is_missing_still_gives_way_to_the_badge(page, chain_url):
    _world(chain_url)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/static/icon-96.png", lambda route: route.fulfill(status=404, body="no"))
    _open_weeks(page, chain_url)
    row = _row(page)
    _amounts(row).nth(0).fill("999")
    expect(_amounts(row).nth(1)).to_have_value("894.76")
    _watch_seals(page)
    _confirm(row).click()
    got = _seals_gone(page, 1)
    _check_seal(got["seals"][0], W45)
    _ends_with_badge(row)
    assert errors == []


def test_the_diff_chip_needs_a_difference_of_at_least_005_percent_of_the_bill(page, chain_url):
    """$2,029.50 billed is 1817.73 euros at 1.1165. The threshold is 0.05% of that, 0.91 euros: arriving as
    1816.73 loses 1.00 euros (0.055%, "DIFF -0.1%") and shows its chip; 1817.00 loses 0.73 (0.040%) and shows none;
    the suggested amounts lose nothing, so a confirmed row has no chip ("DIFF 0.0%" never shows)."""
    _world(chain_url)
    _open_weeks(page, chain_url)
    row = _row(page)
    chip = row.get_by_test_id("fx-chip")
    second = _amounts(row).nth(1)
    expect(second).to_have_value("1817.73")
    second.fill("1817")
    expect(row.locator(".wk-eph")).to_have_text("€80.58")  # the row has asked again: 1817 / 22.55 h
    expect(chip).to_have_count(0)
    second.fill("1816.73")
    expect(chip).to_have_text("DIFF -0.1%")
    _undo(row).click()  # the suggestions again
    expect(second).to_have_value("1817.73")
    _confirm(row).click()
    _wait_for(chain_url, lambda p: len(p) == 1, "saved")
    expect(row.locator(".wk-tag")).to_have_text("paid out")
    expect(chip).to_have_count(0)
    _amounts(row).nth(0).fill("999")
    expect(chip).to_have_text("DIFF -50.8%")


def test_the_seal_does_not_wait_for_the_sources_to_be_read_again(page, chain_url):
    """The first payout of a source with no chain makes the page read the sources again. The seal is in the row
    before that answer comes, and from the click until then the row never shows its badge or Delete."""
    _world(chain_url, chain=())
    _open_weeks(page, chain_url)
    row = _row(page)
    row.locator("select.payacct").select_option(label="Deutsche Bank")
    expect(_confirm(row)).to_be_enabled()
    held: list = []
    armed = {"on": False}

    def handler(route):
        if armed["on"] and route.request.method == "GET" and not held:
            held.append(route)  # the sources read after the save wait
        else:
            route.continue_()

    page.route(re.compile(r"/api/freelance/sources$"), handler)
    _watch_seals(page)
    page.evaluate(
        """(monday) => {
          const e = window.__early = { leaked: 0, sealed: false };
          const tail = document.querySelector(`tr.wk-row#wk-${monday} .wk-tail`);
          const shown = (x) => !!x && getComputedStyle(x).visibility !== 'hidden' && x.offsetParent !== null;
          const look = () => {
            if (document.querySelector('.seal')) { e.sealed = true; return; }
            if (shown(tail.querySelector('.wk-tag')) || shown(tail.querySelector('.pay-del'))) e.leaked++;
            requestAnimationFrame(look);
          };
          look();
        }""",
        W45,
    )
    armed["on"] = True
    _confirm(row).click()
    end = time.monotonic() + 8
    while not held and time.monotonic() < end:
        page.wait_for_timeout(50)
    assert held, "the sources were never read again"
    page.wait_for_function(
        "() => window.__early.sealed"
    )  # the seal is there while the request is held
    expect(row.locator(".seal")).to_have_count(1)
    assert page.evaluate("window.__early.leaked") == 0
    held[0].continue_()
    got = _seals_gone(page, 1)
    _check_seal(got["seals"][0], W45)
    _ends_with_badge(row)


def test_the_line_thuds_with_each_seal_and_keeps_no_thud_after_it(page, chain_url):
    _world(chain_url)
    _open_weeks(page, chain_url)
    row = _row(page)
    page.evaluate(
        """(monday) => {
          const line = document.querySelector(`tr.wk-row#wk-${monday} .wk-line.wk-main`);
          const w = window.__thud = { starts: 0, on: false };
          new MutationObserver(() => {
            const now = line.classList.contains('thud');
            if (now && !w.on) w.starts++;
            w.on = now;
          }).observe(line, { attributes: true, attributeFilter: ['class'] });
        }""",
        W45,
    )
    _confirm(row).click()
    page.wait_for_function("() => window.__thud.starts === 1")
    expect(row).to_have_class(re.compile(r"\bthud\b"))
    expect(row.locator(".seal")).to_have_count(0, timeout=5000)
    _ends_with_badge(row)  # no seal, no `stamping`, no `thud`
    # a change to the saved payout: its seal makes the line thud again
    _amounts(row).nth(0).fill("1000")
    expect(_confirm(row)).to_be_enabled()
    _confirm(row).click()
    page.wait_for_function("() => window.__thud.starts === 2")
    expect(row.locator(".seal")).to_have_count(0, timeout=5000)
    _ends_with_badge(row)


# ── a row asks for its figures again only when its own week moved ─────────────

THREE_DAYS = ("2026-11-03", "2026-10-27", "2026-10-20")
W43 = "2026-10-19"


def _three_weeks_with_figures(page, base: str, **world) -> dict:
    """Acme billed W45, W44 and W43; Weeks is open and every unpaid row has its figures."""
    w = _world(base, days=THREE_DAYS, **world)
    _open_weeks(page, base)
    for monday, label in ((W45, "W45"), (W44, "W44"), (W43, "W43")):
        if not page.locator(f"tr.wk-row#wk-{monday} [data-testid=pay-delete]").count():
            expect(_confirm(_row(page, monday), f"Acme {label}")).to_be_enabled()
    page.wait_for_load_state("networkidle")
    return w


def _weeks_asked(page, since: int) -> list[str]:
    """The weeks of the previews sent after the first `since`, once the page has gone quiet."""
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(700)  # espera-fija: a request that must not come cannot be awaited
    return [body["week_start"] for body in page.wire.previews[since:]]


def test_a_confirm_asks_nothing_of_the_other_rows(page, chain_url):
    _three_weeks_with_figures(page, chain_url)
    asked = len(page.wire.previews)
    assert asked == 3
    row = _row(page)
    _confirm(row).click()
    _wait_for(chain_url, lambda p: len(p) == 1, "the row saves")
    expect(row.get_by_test_id("pay-delete")).to_have_count(1)  # the payouts were read again
    assert _weeks_asked(page, asked) == []
    for monday, label in ((W44, "W44"), (W43, "W43")):  # and the other rows kept their figures
        expect(_confirm(_row(page, monday), f"Acme {label}")).to_be_enabled()
        expect(_amounts(_row(page, monday)).nth(1)).not_to_have_value("")


def test_a_delete_and_its_undo_ask_only_for_the_row_they_change(page, chain_url):
    w = _world(chain_url, days=THREE_DAYS)
    _save(chain_url, w, [{"account_id": w["Stripe"]}, {"account_id": w["Deutsche Bank"]}])
    _open_weeks(page, chain_url)
    for monday, label in ((W44, "W44"), (W43, "W43")):
        expect(_confirm(_row(page, monday), f"Acme {label}")).to_be_enabled()
    assert sorted(_weeks_asked(page, 0)) == [W43, W44]  # the saved row asked nothing
    asked = len(page.wire.previews)
    row = _row(page)
    row.get_by_role("button", name="Delete the payout of Acme W45").click()
    _wait_for(chain_url, lambda p: p == [], "the payout is deleted")
    expect(_confirm(row)).to_be_enabled()  # W45 has no payout now: it asked for its own figures
    assert _weeks_asked(page, asked) == [W45]
    asked = len(page.wire.previews)
    page.locator(".ribbon-action").click()
    _wait_for(chain_url, lambda p: len(p) == 1, "the payout is back")
    expect(row.get_by_test_id("pay-delete")).to_have_count(1)
    assert _weeks_asked(page, asked) == []


def test_a_block_that_changes_asks_again_for_its_week_only_and_its_figures_follow(page, chain_url):
    w = _three_weeks_with_figures(page, chain_url)
    expect(_amounts(_row(page, W44)).nth(0)).to_have_value("2029.5")
    asked = len(page.wire.previews)
    # W44's block, opened from its row in Weeks, gets a quarter of an hour more in the form of Days
    _app(page, "d.daysWeeksSetAll(true);")
    page.locator("tr.blk", has_text="2026-10-27").click()
    page.wait_for_selector(".fl-card--editing")
    page.locator(".fl-step[aria-label='Quarter hour more']").click()
    page.locator(".fl-submit").click()
    page.wait_for_selector(".save-ribbon.ribbon-show:has-text('Block saved')")
    blocks = httpx.get(f"{chain_url}/api/freelance/blocks").json()
    billed = next(b["amount"] for b in blocks if b["date"] == "2026-10-27")
    assert billed > 2029.5 and all(b["source_id"] == w["src"] for b in blocks)
    page.evaluate("location.hash = '#weeks'")
    page.wait_for_selector("[data-testid='days-freelance']")
    expect(_amounts(_row(page, W44)).nth(0)).to_have_value(f"{billed:g}")  # not the old figure
    expect(_confirm(_row(page, W44), "Acme W44")).to_be_enabled()
    again = _weeks_asked(page, asked)
    assert again and set(again) == {W44}, again
    for monday in (W45, W43):
        expect(_amounts(_row(page, monday)).nth(0)).to_have_value("2029.5")


def test_an_account_that_changes_currency_makes_its_rows_ask_again(page, chain_url):
    w = _three_weeks_with_figures(page, chain_url)
    expect(_amounts(_row(page)).nth(1)).to_have_value("1817.73")
    asked = len(page.wire.previews)
    r = httpx.put(
        f"{chain_url}/api/freelance/accounts/{w['Deutsche Bank']}", json={"currency": "USD"}
    )
    assert r.status_code == 200, r.text
    _app(page, "d.loadAccounts();")
    for monday in (
        W45,
        W44,
        W43,
    ):  # dollars into a dollar account: the same figure as the line before
        expect(_amounts(_row(page, monday)).nth(1)).to_have_value("2029.5")
    assert sorted(_weeks_asked(page, asked)) == [W43, W44, W45]
