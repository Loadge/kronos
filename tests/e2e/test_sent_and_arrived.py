# ruff: noqa: E501
"""E2E: a payout has two sides (Miguel's mock of 2026-11-09).

Line 1 of the payout cell is what was sent (a mark, an amount, where from), line 2 is what arrived, and
line 3 only exists when the money arrived in a currency other than the euro. The week is Miguel's W45:
$2,029.50 billed, $999 sent through a dollar account at 1.1165, EUR 894.76 arrived.

The server of this module has its own ECB and CoinGecko (a small HTTP server of the test answers for
both, so nothing reaches the network) and a frozen "now" after W45.
"""

from __future__ import annotations

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
from .test_ui_geometry import CENTRED, MEASURE, ONE_LINE, TAP_MIN, TAPPABLE

pytestmark = pytest.mark.e2e

NOW = "2026-11-10T10:00:00+01:00"
W45 = "2026-11-02"
W44 = "2026-10-26"
RATE = 1.1165


def _ecb() -> str:
    cubes, day = [], date(2026, 11, 10)
    while day >= date(2026, 9, 1):
        if day.weekday() < 5:
            cubes.append(f'<Cube time="{day}"><Cube currency="USD" rate="{RATE}"/></Cube>')
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
def sent_url():
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
def _clean(sent_url):
    _wipe(sent_url)
    yield
    _wipe(sent_url)


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-GB")
    page = ctx.new_page()
    page.set_default_timeout(8000)
    yield page
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


def _world(base: str, *, into="Deutsche Bank", from_="Stripe", extra_blocks=()) -> dict:
    """Acme bills $90 an hour; W45 billed 22.55 h = $2,029.50. Four accounts: Stripe (USD, sends),
    Deutsche Bank (EUR, receives), Mercury (USD, receives), Wise (EUR, either), Cold wallet (BTC,
    receives). The source is paid from `from_` into `into`."""
    accts = {
        "Stripe": _post(
            base, "/api/freelance/accounts", name="Stripe", currency="USD", role="origin"
        ),
        "Deutsche Bank": _post(
            base,
            "/api/freelance/accounts",
            name="Deutsche Bank",
            currency="EUR",
            role="destination",
        ),
        "Mercury": _post(
            base, "/api/freelance/accounts", name="Mercury", currency="USD", role="destination"
        ),
        "Wise": _post(base, "/api/freelance/accounts", name="Wise", currency="EUR", role="both"),
        "Cold wallet": _post(
            base, "/api/freelance/accounts", name="Cold wallet", currency="BTC", role="destination"
        ),
    }
    body = {"name": "Acme", "hourly_rate": 90, "currency": "USD"}
    if into:
        body["default_account_id"] = accts[into]["id"]
    if from_:
        body["default_from_account_id"] = accts[from_]["id"]
    src = _post(base, "/api/freelance/sources", **body)["id"]
    for day in ("2026-11-03", *extra_blocks):
        _post(base, "/api/freelance/blocks", source_id=src, date=day, hours=22.55, fx_rate=RATE)
    return {"src": src, **{k: v["id"] for k, v in accts.items()}}


def _open_weeks(page, base: str) -> None:
    page.goto(f"{base}/#weeks")
    page.wait_for_selector(".page-head .hm-switch")
    _app(page, "d.daysYear = 'all';")
    page.locator(".page-head .hm-switch button").nth(1).click()
    page.wait_for_selector("[data-testid='days-freelance']")


def _row(page, monday=W45):
    return page.locator(f"tr.wk-row#wk-{monday} .wk-line.wk-main")


def _fields(line, week="W45"):
    return (
        line.get_by_label(f"Sent Acme {week}"),
        line.get_by_label(f"Payout Acme {week}"),
    )


def _colour(loc) -> str:
    return loc.evaluate("e => getComputedStyle(e).color")


SUG = re.compile(r"\bis-sug\b")


# ── Miguel's W45 ──────────────────────────────────────────────────────────────


def test_w45_999_sent_through_stripe_arrives_as_894_76(page, sent_url):
    _world(sent_url)
    _open_weeks(page, sent_url)
    line = _row(page)
    sent, arrived = _fields(line)

    # the defaults: line 1 is the source's "Paid from" with the week's billed amount, line 2 its "Paid into"
    # with the suggestion; both muted while they are only that
    assert line.locator("select.payfrom option:checked").inner_text() == "Stripe"
    assert line.locator("select.payacct option:checked").inner_text() == "Deutsche Bank"
    assert line.locator(".cur-from").inner_text().strip() == "$"
    assert line.locator(".cur").inner_text().strip() == "€"
    expect(sent).to_have_value("2029.5")
    expect(sent).to_have_class(SUG)
    expect(arrived).to_have_value("1817.73")
    expect(arrived).to_have_class(SUG)
    muted = _colour(arrived)
    assert _payouts(sent_url) == []  # a suggestion is not a payout

    sent.fill("999")
    expect(arrived).to_have_value("894.76")  # it follows line 1
    got = _wait_for(sent_url, lambda p: len(p) == 1, "the payout is saved")[0]
    assert (got["amount"], got["currency"], got["account_name"]) == (894.76, "EUR", "Deutsche Bank")
    assert (got["sent_amount"], got["sent_currency"], got["from_account_name"]) == (
        999.0,
        "USD",
        "Stripe",
    )
    assert got["sent_gap"] == -1030.5 and got["fx_cost_eur"] == 922.97

    expect(line.locator(".wk-gap")).to_have_text("-$1,030.50")
    chip = line.get_by_test_id("fx-chip")
    expect(chip).to_have_text("DIFF -50.8%")
    chip.hover()
    expect(page.locator("#fx-tip")).to_have_text("€922.97 less than billed")
    page.mouse.move(5, 5)
    # saved: the arrived amount is in the normal colour, and there is no euro line (it arrived in euros)
    expect(arrived).not_to_have_class(SUG)
    assert _colour(arrived) != muted
    expect(arrived).to_have_value("894.76")
    assert line.locator(".wk-conv").count() == 0
    # the chip stands on line 2's height, the gap on line 1's
    c = chip.bounding_box()
    l2 = line.locator(".payc-to").bounding_box()
    l1 = line.locator(".payc-from").bounding_box()
    g = line.locator(".wk-gap").bounding_box()
    assert abs((c["y"] + c["height"] / 2) - (l2["y"] + l2["height"] / 2)) <= 2
    assert abs((g["y"] + g["height"] / 2) - (l1["y"] + l1["height"] / 2)) <= 3


def test_typing_the_arrived_amount_wins_and_changing_the_sent_one_leaves_it(page, sent_url):
    w = _world(sent_url)
    _open_weeks(page, sent_url)
    line = _row(page)
    sent, arrived = _fields(line)
    sent.fill("999")
    _wait_for(sent_url, lambda p: len(p) == 1 and p[0]["amount"] == 894.76, "999 saved")

    arrived.fill("900")  # he overwrites the suggestion
    _wait_for(sent_url, lambda p: p[0]["amount"] == 900, "900 saved")
    sent.fill("1000")  # and then changes the sent amount
    got = _wait_for(sent_url, lambda p: p[0]["sent_amount"] == 1000, "1000 sent saved")[0]
    assert got["amount"] == 900 and got["from_account_id"] == w["Stripe"]
    expect(arrived).to_have_value("900")
    expect(arrived).not_to_have_class(SUG)


def test_a_saved_row_that_still_follows_goes_on_following(page, sent_url):
    w = _world(sent_url)
    _post(
        sent_url,
        "/api/freelance/payouts",
        source_id=w["src"],
        week_start=W45,
        amount=894.76,
        account_id=w["Deutsche Bank"],
        sent_amount=999,
        from_account_id=w["Stripe"],
    )
    _open_weeks(page, sent_url)
    sent, arrived = _fields(_row(page))
    expect(arrived).to_have_value("894.76")
    sent.fill("1000")  # 1000 / 1.1165 = 895.66
    expect(arrived).to_have_value("895.66")
    got = _wait_for(sent_url, lambda p: p[0]["sent_amount"] == 1000, "the new sent amount")[0]
    assert got["amount"] == 895.66


def test_emptying_the_arrived_amount_brings_the_suggestion_back(page, sent_url):
    w = _world(sent_url)
    _open_weeks(page, sent_url)
    line = _row(page)
    sent, arrived = _fields(line)
    expect(arrived).to_have_value("1817.73")
    arrived.fill("5")
    arrived.fill("")  # before anything is saved
    expect(arrived).to_have_value("1817.73")
    expect(arrived).to_have_class(SUG)
    page.wait_for_timeout(900)  # longer than the autosave's wait
    assert _payouts(sent_url) == []
    # a saved payout: emptying what arrived brings back the suggestion for what was sent, and saves it
    _post(
        sent_url,
        "/api/freelance/payouts",
        source_id=w["src"],
        week_start=W45,
        amount=900,
        account_id=w["Deutsche Bank"],
        sent_amount=999,
        from_account_id=w["Stripe"],
    )
    page.reload()
    _open_weeks(page, sent_url)
    line = _row(page)
    sent, arrived = _fields(line)
    expect(arrived).to_have_value("900")
    arrived.fill("")
    expect(arrived).to_have_value("894.76")
    got = _wait_for(sent_url, lambda p: len(p) == 1 and p[0]["amount"] == 894.76, "re-saved")[0]
    assert got["sent_amount"] == 999
    # emptying what was sent is what deletes the payout
    sent.fill("")
    _wait_for(sent_url, lambda p: p == [], "the payout is deleted")
    expect(arrived).to_have_value("1817.73")
    expect(arrived).to_have_class(SUG)


def test_the_same_currency_on_both_sides_suggests_the_sent_amount(page, sent_url):
    _world(sent_url, into="Mercury")
    _open_weeks(page, sent_url)
    line = _row(page)
    sent, arrived = _fields(line)
    expect(arrived).to_have_value("2029.5")  # dollars to dollars
    sent.fill("999")
    expect(arrived).to_have_value("999")
    got = _wait_for(sent_url, lambda p: len(p) == 1, "saved")[0]
    assert (got["currency"], got["amount"], got["fx_cost_eur"]) == ("USD", 999, None)
    assert line.get_by_test_id("fx-chip").count() == 0  # no exchange: no chip


def test_a_bare_currency_on_line_1_takes_its_mark_and_converts_the_billed_amount(page, sent_url):
    _world(sent_url)
    _open_weeks(page, sent_url)
    line = _row(page)
    sent, arrived = _fields(line)
    line.locator("select.payfrom").select_option(label="EUR")
    assert line.locator(".cur-from").inner_text().strip() == "€"
    expect(sent).to_have_value("1817.73")  # $2,029.50 at the day's rate
    expect(arrived).to_have_value("1817.73")  # euros to euros
    arrived.fill("1800")
    got = _wait_for(sent_url, lambda p: len(p) == 1, "saved")[0]
    assert (got["sent_currency"], got["from_account_id"], got["sent_amount"]) == (
        "EUR",
        None,
        1817.73,
    )
    assert got["amount"] == 1800
    expect(line.locator(".wk-gap")).to_have_text("+$0")  # EUR 1,817.73 is the $2,029.50 billed


def test_with_no_rate_line_2_stays_empty_and_the_row_waits(page, sent_url):
    _world(sent_url, into="Cold wallet")  # no coin price: CoinGecko answers nothing
    _open_weeks(page, sent_url)
    line = _row(page)
    sent, arrived = _fields(line)
    expect(line.locator("select.payacct option:checked")).to_have_text("Cold wallet")
    expect(arrived).to_have_value("")
    sent.fill("999")
    expect(line.locator(".wk-status.is-invalid")).to_be_visible()
    expect(arrived).to_have_value("")
    assert _payouts(sent_url) == []
    arrived.fill("0.01")  # typed by hand it goes through
    got = _wait_for(sent_url, lambda p: len(p) == 1, "saved")[0]
    assert (got["currency"], got["sent_amount"]) == ("BTC", 999)


def test_a_destination_that_is_not_in_euros_shows_line_3(page, sent_url):
    _world(sent_url, into="Mercury")
    _open_weeks(page, sent_url)
    line = _row(page)
    sent, arrived = _fields(line)
    assert line.locator(".wk-conv").count() == 0  # nothing saved yet
    sent.fill("999")
    expect(line.locator(".wk-conv")).to_have_text("= €894.76")
    expect(line.get_by_role("button", name="Set the € value of Acme W45")).to_be_visible()


def test_the_selects_offer_only_the_accounts_that_can_play_each_part(page, sent_url):
    _world(sent_url)
    _open_weeks(page, sent_url)
    line = _row(page)
    from_ = line.locator("select.payfrom")
    from_.wait_for()
    options = from_.locator("option").all_inner_texts()
    assert options[:3] == ["As billed (USD)", "Stripe", "Wise"]  # no receiving-only account
    assert (
        "Deutsche Bank" not in options and "Mercury" not in options and "Cold wallet" not in options
    )
    assert {"EUR", "USD", "BTC"} <= set(
        options[3:]
    )  # the bare currencies, one per currency Kronos knows
    assert from_.locator("optgroup").get_attribute("label") == "Currency"
    into = line.locator("select.payacct").locator("option").all_inner_texts()
    assert into == [
        "Deutsche Bank",
        "Mercury",
        "Wise",
        "Cold wallet",
        "As billed (USD)",
    ]  # no Stripe


def test_a_row_keeps_offering_the_account_it_already_uses(page, sent_url):
    w = _world(sent_url)
    _post(
        sent_url,
        "/api/freelance/payouts",
        source_id=w["src"],
        week_start=W45,
        amount=999,
        account_id=w["Wise"],
        sent_amount=999,
        from_account_id=w["Wise"],
    )
    httpx.put(f"{sent_url}/api/freelance/accounts/{w['Wise']}", json={"role": "origin"})
    _open_weeks(page, sent_url)
    line = _row(page)
    expect(line.locator("select.payacct option:checked")).to_have_text(
        "Wise"
    )  # no longer a destination
    assert "Wise" in line.locator("select.payacct").locator("option").all_inner_texts()


# ── Settings ──────────────────────────────────────────────────────────────────


def _settings(page, base):
    page.goto(f"{base}/#settings")
    page.wait_for_selector(".page-head")
    _app(page, "d.setSettingsGroup('freelance');")
    page.wait_for_selector("[data-testid='accounts-card']")


def test_settings_set_each_accounts_use_and_the_sources_paid_from(page, sent_url):
    w = _world(sent_url, into=None, from_=None)
    _settings(page, sent_url)
    paid_from = page.get_by_label("Paid from, Acme")
    paid_into = page.get_by_label("Paid into, Acme")
    expect(paid_from.locator("option")).to_have_text(["As billed (USD)", "Stripe", "Wise"])
    expect(paid_into.locator("option")).to_have_text(
        ["As billed (USD)", "Deutsche Bank", "Mercury", "Wise", "Cold wallet"]
    )
    paid_from.select_option(label="Stripe")
    end = time.monotonic() + 6
    while time.monotonic() < end:
        src = httpx.get(f"{sent_url}/api/freelance/sources").json()[0]
        if src["default_from_account_id"] == w["Stripe"]:
            break
        time.sleep(0.1)
    assert src["default_from_account_id"] == w["Stripe"]
    # the Use of an account autosaves, and changes what the other lists offer
    page.get_by_label("Use, Stripe").select_option(label="Both")
    end = time.monotonic() + 6
    while time.monotonic() < end:
        roles = {
            a["name"]: a["role"] for a in httpx.get(f"{sent_url}/api/freelance/accounts").json()
        }
        if roles["Stripe"] == "both":
            break
        time.sleep(0.1)
    assert roles["Stripe"] == "both"
    expect(paid_into.locator("option")).to_have_text(
        ["As billed (USD)", "Stripe", "Deutsche Bank", "Mercury", "Wise", "Cold wallet"]
    )
    # a new payout then starts from that default
    _open_weeks(page, sent_url)
    assert _row(page).locator("select.payfrom option:checked").inner_text() == "Stripe"


# ── the waiting form is the same cell ─────────────────────────────────────────


def test_the_waiting_form_saves_the_same_payout_as_the_weeks_row(page, sent_url):
    w = _world(sent_url, extra_blocks=("2026-10-27",))  # W44 billed the same 22.55 h
    # W45 from the Weeks row
    _open_weeks(page, sent_url)
    _fields(_row(page))[0].fill("999")
    _wait_for(sent_url, lambda p: len(p) == 1, "the row saves")
    # W44 from the form of the page where days are logged
    page.goto(f"{sent_url}/#days")
    page.wait_for_selector("[data-testid=pay-wait]")
    page.get_by_test_id("pay-wait-chip").filter(has_text="W44").click()
    cell = page.locator(".fl-wait-form")
    assert cell.locator("select.payfrom option:checked").inner_text() == "Stripe"
    expect(cell.get_by_label("Sent Acme W44")).to_have_value("2029.5")
    expect(page.get_by_test_id("pay-wait-amount")).to_have_value("1817.73")
    cell.get_by_label("Sent Acme W44").fill("999")
    expect(page.get_by_test_id("pay-wait-amount")).to_have_value("894.76")
    page.wait_for_timeout(900)
    assert len(_payouts(sent_url)) == 1  # the form saves with its button, not by itself
    page.get_by_test_id("pay-wait-save").click()
    both = _wait_for(sent_url, lambda p: len(p) == 2, "the form saves")
    row, form = (next(p for p in both if p["week_start"] == w_) for w_ in (W45, W44))
    keys = (
        "amount",
        "currency",
        "account_id",
        "sent_amount",
        "sent_currency",
        "from_account_id",
        "billed_amount",
        "fx_cost_eur",
        "sent_gap",
        "amount_eur",
    )
    assert {k: row[k] for k in keys} == {k: form[k] for k in keys}
    assert row["from_account_id"] == w["Stripe"] and row["amount"] == 894.76


# ── geometry: the two lines at 1280 and 375 ───────────────────────────────────

ALIGN = """
() => {
  const bad = [];
  const mid = r => r.top + r.height / 2;
  for (const line of document.querySelectorAll('.wk-line.two')) {
    const l1 = line.querySelector('.payc-from'), l2 = line.querySelector('.payc-to');
    if (!l1 || !l2 || line.offsetParent === null) continue;
    const r1 = l1.getBoundingClientRect(), r2 = l2.getBoundingClientRect();
    if (r2.top < r1.bottom - 1) bad.push(['lines overlap', line.id]);
    for (const l of [l1, l2]) {
      const items = [...l.children].map(e => e.getBoundingClientRect()).filter(r => r.width > 0);
      if (Math.max(...items.map(mid)) - Math.min(...items.map(mid)) > 3) bad.push(['line not level', l.className]);
      if (items.some(r => r.right > line.getBoundingClientRect().right + 1)) bad.push(['past the row', l.className]);
    }
    const left1 = l1.querySelector('input').getBoundingClientRect(), left2 = l2.querySelector('input').getBoundingClientRect();
    if (Math.abs(left1.right - left2.right) > 1 || Math.abs(left1.width - left2.width) > 1) bad.push(['amounts not aligned']);
    const gap = line.querySelector('.wk-gap b'), chip = line.querySelector('.wk-chip .fx-chip');
    if (gap && Math.abs(mid(gap.getBoundingClientRect()) - mid(r1)) > 3) bad.push(['gap off line 1']);
    if (chip && Math.abs(mid(chip.getBoundingClientRect()) - mid(r2)) > 3) bad.push(['chip off line 2']);
  }
  return bad;
}
"""


@pytest.mark.parametrize("width,height", [(1280, 900), (900, 800), (700, 800), (375, 812)])
def test_the_two_lines_fit_at_every_width(browser, sent_url, width, height):
    w = _world(sent_url, extra_blocks=("2026-10-27",))
    _post(
        sent_url,
        "/api/freelance/payouts",
        source_id=w["src"],
        week_start=W45,
        amount=894.76,
        account_id=w["Deutsche Bank"],
        sent_amount=999,
        from_account_id=w["Stripe"],
    )
    _post(
        sent_url,
        "/api/freelance/payouts",
        source_id=w["src"],
        week_start=W44,
        amount=880,
        account_id=w["Mercury"],
        sent_amount=900,
        from_account_id=w["Stripe"],
    )  # an unpaid week would show the suggestions; this one shows line 3 too
    ctx = browser.new_context(viewport={"width": width, "height": height}, locale="en-GB")
    page = ctx.new_page()
    page.set_default_timeout(8000)
    try:
        _open_weeks(page, sent_url)
        page.wait_for_selector(".wk-line.two .fx-chip")
        page.wait_for_timeout(400)
        phone = width <= 640
        assert not (
            found := page.evaluate(MEASURE, [CENTRED, ONE_LINE, TAPPABLE, TAP_MIN, phone])
        ), "\n".join(map(str, found))
        assert not (found := page.evaluate(ALIGN)), found
        assert page.locator(".wk-line.two .payc-from").count() == 2
        assert (
            page.locator(".wk-line.two .wk-conv").count() == 1
        )  # Mercury is in dollars: line 3 there only
    finally:
        ctx.close()


def test_the_alignment_check_can_fail(page, sent_url):
    """A positive control: a chip pushed off line 2 must be reported."""
    w = _world(sent_url)
    _post(
        sent_url,
        "/api/freelance/payouts",
        source_id=w["src"],
        week_start=W45,
        amount=894.76,
        account_id=w["Deutsche Bank"],
        sent_amount=999,
        from_account_id=w["Stripe"],
    )
    _open_weeks(page, sent_url)
    page.wait_for_selector(".wk-line.two .fx-chip")
    page.wait_for_timeout(300)
    assert page.evaluate(ALIGN) == []
    page.add_style_tag(content=".wk-chip { align-self: start; margin-top: 20px; }")
    assert any("chip" in x[0] for x in page.evaluate(ALIGN))
