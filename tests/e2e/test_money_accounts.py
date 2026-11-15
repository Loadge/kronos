# ruff: noqa: E501
"""E2E: money in any currency, the UI half.

Miguel's case, by hand in the browser: a source that bills USD at 95/h, a week that billed
$1,059.25, and EUR 877.94 that landed in his Spanish bank. He creates the account, says the source
is paid into it, types the amount in Days > Freelance, and the row reads what he received and what
the exchange and the fees cost him.

The server of this module has its own ECB and CoinGecko: a small HTTP server of the test answers
for both, so nothing reaches the network and nothing depends on the day the suite runs ("now" is
frozen on the server and every week used here is a fixed one).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

BACKEND_DIR = Path(__file__).parent.parent.parent / "backend"


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"Server on port {port} did not start within {timeout}s")


NOW = "2026-11-04T10:12:00+01:00"
W44 = "2026-10-26"  # Monday of W44 2026; its Sunday is Nov 1
OLD_MONDAY = "2025-09-29"  # W40 2025: more than 365 days before NOW, so no coin price exists for it

ECB = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-11-01"><Cube currency="USD" rate="1.1172"/><Cube currency="JPY" rate="170.0"/></Cube>
    <Cube time="2026-10-30"><Cube currency="USD" rate="1.1172"/><Cube currency="JPY" rate="170.0"/></Cube>
    <Cube time="2026-10-29"><Cube currency="USD" rate="1.1172"/></Cube>
    <Cube time="2026-10-28"><Cube currency="USD" rate="1.1172"/></Cube>
    <Cube time="2026-10-27"><Cube currency="USD" rate="1.1172"/></Cube>
    <Cube time="2026-10-26"><Cube currency="USD" rate="1.1172"/></Cube>
  </Cube>
</gesmes:Envelope>
"""
EXPECTED_STORY = "€70.19 less than billed"
# the first account's 877.94 euros are 980.83 dollars at 1.1172 (877.94 * 1.1172), against the $1,059.25 billed
GAP_W44 = "-$78.42"


class _Stub(BaseHTTPRequestHandler):
    requests: list[str] = []

    def do_GET(self):  # noqa: N802
        type(self).requests.append(self.path)
        if self.path.endswith(".xml"):
            body, status = ECB.encode(), 200
        else:  # CoinGecko: nothing to say
            body, status = b"{}", 500
        self.send_response(status)
        self.send_header("Content-Type", "application/xml" if status == 200 else "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def stub():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", _Stub.requests
    finally:
        server.shutdown()


@pytest.fixture(scope="module")
def money_url(stub):
    """A Kronos of this module: its own database, the stub's ECB and CoinGecko, a frozen "now"."""
    root, _ = stub
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
        Path(db_path).unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def _clean(money_url):
    def wipe():
        with httpx.Client(base_url=money_url) as c:
            c.delete("/api/data")
            for p in c.get("/api/freelance/payouts").json():
                c.delete(f"/api/freelance/payouts/{p['id']}")
            for s in c.get("/api/freelance/sources").json():
                c.delete(f"/api/freelance/sources/{s['id']}")
            for a in c.get("/api/freelance/accounts").json():
                c.delete(f"/api/freelance/accounts/{a['id']}")

    wipe()
    yield
    wipe()


# ── helpers ───────────────────────────────────────────────────────────────────


def _post(base: str, path: str, **body) -> dict:
    with httpx.Client(base_url=base) as c:
        r = c.post(path, json=body)
        assert r.status_code == 201, r.text
        return r.json()


def _usd_source(base: str, name="Acme") -> int:
    return _post(base, "/api/freelance/sources", name=name, hourly_rate=95, currency="USD")["id"]


def _w44_block(base: str, source_id: int) -> None:
    # 09:00 to 20:09 is 669 minutes: 669 / 60 * 95 = $1,059.25
    _post(
        base,
        "/api/freelance/blocks",
        source_id=source_id,
        date=W44,
        start_time="09:00",
        end_time="20:09",
    )


def _payouts(base: str) -> list[dict]:
    return httpx.get(f"{base}/api/freelance/payouts").json()


def _wait_for(base: str, predicate, what: str, timeout=6.0) -> list[dict]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = _payouts(base)
        if predicate(got):
            return got
        time.sleep(0.1)
    raise AssertionError(f"{what}: the API has {_payouts(base)}")


@pytest.fixture
def page(browser, money_url):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-GB")
    page = ctx.new_page()
    page.set_default_timeout(8000)
    yield page
    ctx.close()


def _app(page, js: str):
    return page.evaluate(
        f"(() => {{ const d = Alpine.$data(document.querySelector('main')); {js} }})()"
    )


def _settle(page) -> None:
    """Wait for the entrance animations to end: a card sliding in is wider than the page for a moment."""
    page.wait_for_function(
        "() => document.getAnimations().every(a => a.effect.getTiming().iterations === Infinity"
        " || a.playState !== 'running')"
    )


def _open_settings_freelance(page, base: str) -> None:
    page.goto(f"{base}/#settings")
    page.wait_for_selector(".page-head")
    _app(page, "d.setSettingsGroup('freelance');")
    page.wait_for_selector("[data-testid='accounts-card']")


def _open_days_freelance(page, base: str, year: str = "all") -> None:
    page.goto(f"{base}/#weeks")
    page.wait_for_selector(".page-head .hm-switch")
    _app(page, f"d.daysYear = '{year}';")
    page.locator(".page-head .hm-switch button").nth(1).click()
    page.wait_for_selector("[data-testid='days-freelance']")


def _add_account_in_settings(page, name: str, code: str, kind: str = "bank") -> None:
    card = page.locator("[data-testid='accounts-card']")
    card.get_by_label("Account name").fill(name)
    picker = card.get_by_label("Account currency")
    picker.click()
    picker.fill(code)
    card.get_by_role("option", name=code, exact=False).first.click()
    if kind != "bank":
        card.get_by_label("Account kind").select_option(kind)
    card.get_by_role("button", name="Add", exact=True).click()
    expect(card.locator(".acct-item", has_text=name)).to_be_visible()


# ── Miguel's case ─────────────────────────────────────────────────────────────


def test_miguels_case_by_hand_in_the_ui(page, money_url):
    src = _usd_source(money_url)
    _w44_block(money_url, src)

    # 1. an account "Deutsche Bank" in EUR, made in Settings > Freelance
    _open_settings_freelance(page, money_url)
    card = page.locator("[data-testid='accounts-card']")
    assert "Add the bank accounts or wallets your clients pay into." in card.inner_text()
    _add_account_in_settings(page, "Deutsche Bank", "EUR")
    row = card.locator(".acct-item", has_text="Deutsche Bank")
    assert row.locator(".acct-cur").inner_text().strip() == "EUR"
    assert "Add the bank accounts" not in card.inner_text()

    # 2. the source is paid through it (its chain, set in Settings: here by the API)
    bank = next(
        a
        for a in httpx.get(f"{money_url}/api/freelance/accounts").json()
        if a["name"] == "Deutsche Bank"
    )
    r = httpx.put(f"{money_url}/api/freelance/sources/{src}", json={"chain": [bank["id"]]})
    assert r.status_code == 200, r.text
    assert httpx.get(f"{money_url}/api/freelance/sources").json()[0]["chain"] == [bank["id"]]
    page.reload()

    # 3. W44 in Days > Freelance: the field's mark follows the account, not the source
    _open_days_freelance(page, money_url)
    line = page.locator(f"tr.wk-row#wk-{W44} .wk-line.wk-main")
    assert line.locator(".cur").inner_text().strip() == "€"
    assert line.locator("select.payacct option:checked").inner_text() == "Deutsche Bank"

    # 4. he types what landed, and confirms it: nothing is saved before the button
    line.get_by_label("Deutsche Bank amount, Acme W44", exact=True).fill("877.94")
    expect(line.get_by_test_id("fx-chip")).to_be_visible()  # the preview already says what it costs
    assert _payouts(money_url) == []
    line.get_by_role("button", name="Confirm the payout of Acme W44").click()
    got = _wait_for(money_url, lambda p: len(p) == 1, "the payout is saved")[0]
    assert got["amount"] == 877.94 and got["currency"] == "EUR"
    assert got["account_name"] == "Deutsche Bank"
    assert got["billed_eur"] == 948.13 and got["fx_cost_eur"] == 70.19
    assert got["effective_rate"] == 1.2065

    expect(line.get_by_test_id("fx-chip")).to_be_visible()  # the payout is saved and drawn again
    assert (
        line.locator(".wk-conv").count() == 0
    )  # euros arrived: line 2 says it, there is no line 3
    assert line.get_by_label("Deutsche Bank amount, Acme W44", exact=True).input_value() == "877.94"
    assert line.locator(".cur").inner_text().strip() == "€"
    # the struck-through estimate stays as it was
    est = line.locator(".wk-est")
    assert est.inner_text().strip() == "$1,059.25"
    assert est.evaluate("e => getComputedStyle(e).textDecorationLine") == "line-through"
    # the gap is the first account minus billed, in the billed currency, and says so
    gap = line.locator(".wk-gap b")
    assert gap.inner_text().strip() == GAP_W44
    assert gap.get_attribute("title") == "First account minus billed"

    # 5. the DIFF chip tells the story: hover, focus and tap
    chip = line.get_by_test_id("fx-chip")
    assert chip.inner_text().strip() == "DIFF -7.4%"  # the share of what was billed
    tip = page.locator("#fx-tip")
    chip.hover()
    expect(tip).to_have_text(EXPECTED_STORY)
    page.mouse.move(5, 5)
    expect(tip).to_be_hidden()
    chip.focus()
    expect(tip).to_have_text(EXPECTED_STORY)
    page.keyboard.press("Escape")  # closes the tip and does not send the app home
    expect(tip).to_be_hidden()
    assert page.evaluate("() => location.hash") == "#weeks"
    chip.click()  # a tap pins it; a click elsewhere lets it go
    expect(tip).to_have_text(EXPECTED_STORY)
    page.mouse.move(5, 5)
    expect(tip).to_be_visible()
    page.mouse.click(5, 5)
    expect(tip).to_be_hidden()

    # 6. the Freelance tab carries the year's cost and where the money landed
    _app(page, "d.flYear = 2026; d.go('freelance');")
    lost = page.get_by_test_id("fl-fxlost")
    expect(lost).to_have_text("Difference from billed: €70.19")
    landed = page.get_by_test_id("fl-landed")
    assert "where it landed" in landed.inner_text().lower()
    assert "Deutsche Bank" in landed.inner_text() and "€877.94" in landed.inner_text()


# ── no exchange, no FX chip ───────────────────────────────────────────────────


def test_a_same_currency_payout_has_no_fx_chip(page, money_url):
    src = _usd_source(money_url)
    _w44_block(money_url, src)
    usd = _post(money_url, "/api/freelance/accounts", name="Mercury", currency="USD")
    payout = _post(
        money_url,
        "/api/freelance/payouts",
        source_id=src,
        week_start=W44,
        legs=[{"account_id": usd["id"], "amount": 1000}],
    )
    assert payout["currency"] == "USD" and payout["fx_cost_eur"] is None
    _open_days_freelance(page, money_url)
    line = page.locator(f"tr.wk-row#wk-{W44} .wk-line.wk-main")
    assert line.locator("select.payacct option:checked").inner_text() == "Mercury"
    assert line.locator(".cur").inner_text().strip() == "$"
    expect(line.locator(".wk-conv")).to_have_text("= €895.09")
    assert line.get_by_test_id("fx-chip").count() == 0
    assert (
        line.locator(".wk-gap b").inner_text().strip() == "-$59.25"
    )  # 1000 against the $1,059.25 billed


# ── an account's currency is locked once payouts went into it ─────────────────


def test_the_currency_of_a_used_account_is_locked(page, money_url):
    src = _usd_source(money_url)
    _w44_block(money_url, src)
    acct = _post(money_url, "/api/freelance/accounts", name="Deutsche Bank", currency="EUR")
    _open_settings_freelance(page, money_url)
    card = page.locator("[data-testid='accounts-card']")
    row = card.locator(".acct-item", has_text="Deutsche Bank")

    # unused: Edit opens the form with a currency you can change
    row.get_by_role("button", name="Edit Deutsche Bank").click()
    assert card.get_by_label("Account currency").is_enabled()
    card.get_by_role("button", name="Cancel").click()

    _post(
        money_url,
        "/api/freelance/payouts",
        source_id=src,
        week_start=W44,
        legs=[{"account_id": acct["id"], "amount": 877.94}],
    )
    _open_settings_freelance(page, money_url)
    page.reload()
    _open_settings_freelance(page, money_url)
    row = card.locator(".acct-item", has_text="Deutsche Bank")
    assert row.locator(".acct-cur").get_attribute("title") == "Used by 1 payout"
    assert row.locator(".acct-lock").is_visible()
    row.get_by_role("button", name="Edit Deutsche Bank").click()
    picker = card.get_by_label("Account currency")
    assert picker.is_disabled()
    assert picker.locator("xpath=..").get_attribute("title") == "Used by 1 payout"
    assert "EUR" in picker.input_value()
    # the name can still change, the currency is not sent
    card.get_by_label("Account name").fill("Deutsche Bank SL")
    card.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('main')).accounts[0].name === 'Deutsche Bank SL'"
    )
    # archive and restore
    row = card.locator(".acct-item", has_text="Deutsche Bank SL")
    row.get_by_role("button", name="Archive Deutsche Bank SL").click()
    archived = card.locator(".acct-item.is-archived", has_text="Deutsche Bank SL")
    expect(archived).to_be_visible()
    archived.get_by_role("button", name="Restore Deutsche Bank SL").click()
    expect(card.locator(".acct-item.is-archived")).to_have_count(0)


# ── a coin older than 365 days has no price: the user says what it was worth ──


def test_an_old_coin_payout_asks_for_worth_and_sends_it(page, money_url, stub):
    _, requests = stub
    requests.clear()
    src = _post(money_url, "/api/freelance/sources", name="Local", hourly_rate=60, currency="EUR")[
        "id"
    ]
    _post(money_url, "/api/freelance/blocks", source_id=src, date=OLD_MONDAY, hours=2)
    wallet = _post(
        money_url, "/api/freelance/accounts", name="Cold wallet", currency="BTC", kind="wallet"
    )
    httpx.put(f"{money_url}/api/freelance/sources/{src}", json={"chain": [wallet["id"]]})

    sent: list[dict] = []
    page.on(
        "request",
        lambda r: (
            sent.append({"m": r.method, "b": r.post_data})
            if "/api/freelance/payouts" in r.url and r.method in ("POST", "PUT")
            else None
        ),
    )
    _open_days_freelance(page, money_url)
    line = page.locator(f"tr.wk-row#wk-{OLD_MONDAY} .wk-line.wk-main")
    line.scroll_into_view_if_needed()
    assert line.locator(".cur").inner_text().strip() == "₿"
    # no price for the day: the line says so, and its amount is typed by hand
    amount = line.get_by_test_id("pay-amount")
    expect(amount).to_have_attribute("title", "no rate for that day")
    amount.fill("0.0105")
    # no rate: a second field asks for the euros
    worth = line.get_by_label("Worth in euros, Local W40")
    expect(worth).to_be_visible()
    assert "worth €" in line.locator(".worth").inner_text()
    assert _payouts(money_url) == []  # nothing is saved by typing
    worth.fill("650")
    expect(line.get_by_test_id("pay-conv")).to_have_text("= €650.00")
    assert _payouts(money_url) == []
    line.get_by_role("button", name="Confirm the payout of Local W40").click()
    got = _wait_for(money_url, lambda p: len(p) == 1, "the BTC payout is saved")[0]
    assert got["currency"] == "BTC" and got["amount"] == 0.0105
    assert not any("/coins/" in u for u in requests), requests  # a year old: no request is made
    assert got["amount_eur"] == 650.0 and got["rate_source"] == "manual" and got["amount"] == 0.0105
    posts = [json.loads(s["b"]) for s in sent if s["m"] == "POST"]
    assert posts and posts[-1]["eur_amount"] == 650
    assert posts[-1]["legs"] == [{"account_id": wallet["id"], "amount": 0.0105, "fixed": True}]

    page.wait_for_function(
        "(w) => document.querySelector('#wk-' + w + ' .wk-conv')?.textContent.includes('= €650.00')",
        arg=OLD_MONDAY,
    )
    assert line.get_by_test_id("pay-amount").input_value() == "0.0105"
    expect(line.get_by_label("Worth in euros, Local W40")).to_have_value("650")  # saved as typed

    # the Freelance tab of 2025 lists the coin as the wallet received it
    _app(page, "d.flYear = 2025; d.go('freelance');")
    landed = page.get_by_test_id("fl-landed")
    expect(landed).to_contain_text("Cold wallet")
    expect(landed).to_contain_text("0.0105 BTC")
    expect(landed).to_contain_text("= €650.00")


# ── the one money formatter ───────────────────────────────────────────────────


def test_crypto_amounts_trim_and_fiat_keeps_two_decimals(page, money_url):
    page.goto(f"{money_url}/#settings")
    page.wait_for_selector(".page-head")
    out = _app(
        page,
        "return ["
        "d.fmtMoney(0.0105, 'BTC'), d.fmtMoney(0.01050000, 'BTC', 2), d.fmtMoney(2, 'ETH'),"
        "d.fmtMoney(12345.5, 'USDC'), d.fmtMoney(0.123456789, 'SOL'), d.fmtMoney(-0.5, 'BTC'),"
        "d.fmtMoney(0.0105), d.fmtMoney(1289.7), d.fmtMoney(1000, 'USD'), d.fmtMoney(null, 'BTC'),"
        "d.curMark('EUR'), d.curMark('USD'), d.curMark('BTC'), d.curMark('JPY')];",
    )
    assert out == [
        "0.0105 BTC",
        "0.0105 BTC",
        "2 ETH",
        "12,345.5 USDC",
        "0.12345679 SOL",
        "-0.5 BTC",
        "€0.01",
        "€1,289.70",
        "$1,000.00",
        "—",
        "€",
        "$",
        "₿",
        "JPY",
    ]


# ── the currency picker ───────────────────────────────────────────────────────


def test_the_currency_picker_lists_fiat_by_code_then_coins_and_filters(page, money_url):
    _open_settings_freelance(page, money_url)
    card = page.locator("[data-testid='accounts-card']")
    picker = card.get_by_label("Account currency")
    picker.click()
    codes = card.locator("[role=option] b").all_inner_texts()
    assert codes[-5:] == ["BTC", "ETH", "SOL", "USDC", "USDT"]
    fiat = codes[:-5]
    assert fiat == sorted(fiat) and "EUR" in fiat and "USD" in fiat and len(fiat) >= 30
    assert "Euro" in card.locator("[role=option]", has_text="EUR").first.inner_text()
    picker.fill("bit")  # filters by name too
    assert card.locator("[role=option] b").all_inner_texts() == ["BTC"]
    picker.fill("zzz")
    expect(card.locator("#acct-curlist")).to_contain_text("No currency matches.")
    picker.fill("yen")
    picker.press("Enter")
    assert "JPY" in picker.input_value()


# ── geometry and aria of what this phase added ────────────────────────────────

MEASURE = """
() => {
  const bad = [];
  const visible = el => el.offsetParent !== null && el.getBoundingClientRect().width > 0;
  const oneLine = '.acct-cur, .fx-chip, .acct-item strong, .worth span, .pen-link, .fl-fxlost, .src-tag';
  for (const el of document.querySelectorAll(oneLine)) {
    if (!visible(el) || !el.innerText.trim()) continue;
    const r = document.createRange(); r.selectNodeContents(el);
    const m = [...r.getClientRects()].filter(x => x.width > 0).map(x => x.top + x.height / 2);
    if (m.length && Math.max(...m) - Math.min(...m) > 6) bad.push(['wraps', el.className, el.innerText.trim().slice(0, 30)]);
  }
  for (const el of document.querySelectorAll('.fx-chip')) {
    if (!visible(el)) continue;
    const r = document.createRange(); r.selectNodeContents(el);
    const t = r.getBoundingClientRect(), b = el.getBoundingClientRect();
    if (Math.abs((t.top + t.height / 2) - (b.top + b.height / 2)) > 2 || Math.abs((t.left + t.width / 2) - (b.left + b.width / 2)) > 3) bad.push(['off-centre', 'fx-chip']);
  }
  const small = '[data-testid=accounts-card] :is(button, select, input), .payacct, .worthin, .pen-link, .fx-chip';
  for (const el of document.querySelectorAll(small)) {
    if (!visible(el)) continue;
    const b = el.getBoundingClientRect();
    if (b.width < 24 || b.height < 24) bad.push(['too small', el.className || el.tagName, Math.round(b.width), Math.round(b.height)]);
  }
  if (document.documentElement.scrollWidth > window.innerWidth + 1) bad.push(['scrolls sideways', document.documentElement.scrollWidth]);
  return bad;
}
"""


@pytest.mark.parametrize("width", [1280, 375])
def test_the_new_controls_are_drawn_properly(browser, money_url, width):
    src = _usd_source(money_url)
    _w44_block(money_url, src)
    acct = _post(money_url, "/api/freelance/accounts", name="Deutsche Bank", currency="EUR")
    _post(
        money_url,
        "/api/freelance/payouts",
        source_id=src,
        week_start=W44,
        legs=[{"account_id": acct["id"], "amount": 877.94}],
    )
    _post(money_url, "/api/freelance/accounts", name="Cold wallet", currency="BTC", kind="wallet")
    ctx = browser.new_context(viewport={"width": width, "height": 900}, locale="en-GB")
    page = ctx.new_page()
    page.set_default_timeout(8000)
    try:
        _open_settings_freelance(page, money_url)
        _settle(page)
        assert page.evaluate(MEASURE) == []
        # the card, by role and name
        row = page.locator(".acct-item", has_text="Cold wallet")
        expect(row).to_match_aria_snapshot(
            """
            - img "wallet"
            - strong: Cold wallet
            - text: BTC
            - button "Make Cold wallet the default account" [pressed=false]
            - button "Edit Cold wallet"
            - button "Archive Cold wallet"
            """
        )
        _open_days_freelance(page, money_url)
        page.wait_for_selector(".fx-chip")
        _settle(page)
        assert page.evaluate(MEASURE) == []
        # the select, the chip and the field fit the box of their week
        box = page.locator(f"tr.wk-row#wk-{W44}").bounding_box()
        for sel in ("select.payacct", ".fx-chip", ".payin"):
            b = page.locator(f"tr.wk-row#wk-{W44} {sel}").first.bounding_box()
            assert b["x"] >= box["x"] - 1 and b["x"] + b["width"] <= box["x"] + box["width"] + 1, (
                sel
            )
    finally:
        ctx.close()


def test_the_geometry_measure_reports_a_broken_chip(page, money_url):
    """A positive control for the measure above: a chip with two lines of text is reported."""
    page.goto(f"{money_url}/#settings")
    page.wait_for_selector(".page-head")
    page.evaluate(
        "() => { const b = document.createElement('button'); b.className = 'fx-chip';"
        " b.style.width = '20px'; b.style.whiteSpace = 'normal'; b.textContent = 'FX FX FX';"
        " document.body.appendChild(b); }"
    )
    bad = page.evaluate(MEASURE)
    assert any(x[0] in ("wraps", "too small") for x in bad), bad
