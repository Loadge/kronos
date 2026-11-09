# ruff: noqa: E501, F811
"""E2E: Miguel's notes on v55 (2026-11-09).

Interface text got short (the day bar's help is four gestures), the header hairline has the working hours on
it, the FX chip says its share, payouts can be typed from the page where days are logged, the calculator's
labels sit next to their values, and three tabs have new names and addresses (Days, Weeks, Year).
"""

from __future__ import annotations

import datetime

import httpx
import pytest
from playwright.sync_api import expect

from .conftest import HASH_OF  # noqa: F401  (the address of each tab id)

# The FX chip tests need a server with its own ECB: those fixtures belong to the money module.
from .test_money_accounts import (  # noqa: F401
    W44,
    _app,
    _clean,
    _open_days_freelance,
    _post,
    _usd_source,
    _w44_block,
    money_url,
    stub,
)

pytestmark = pytest.mark.e2e

TODAY = datetime.date.today()
MONDAY = TODAY - datetime.timedelta(days=TODAY.weekday())
LAST_MONDAY = MONDAY - datetime.timedelta(days=7)


def _wk(monday: datetime.date) -> str:
    return f"W{monday.isocalendar()[1]:02d}"


@pytest.fixture
def page(browser):
    """A page of its own (the money module's fixtures bring their own `page`, aimed at its server)."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="en-GB")
    page = ctx.new_page()
    page.set_default_timeout(8000)
    yield page
    ctx.close()


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        for p in c.get("/api/freelance/payouts").json():
            c.delete(f"/api/freelance/payouts/{p['id']}")
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


@pytest.fixture
def clean(base_url):
    _wipe(base_url)
    yield
    _wipe(base_url)
    httpx.put(
        f"{base_url}/api/config", json={"default_start_time": "09:00", "default_end_time": "17:00"}
    )


def _source(base_url, name="Local", rate=60, currency="EUR") -> int:
    r = httpx.post(
        f"{base_url}/api/freelance/sources",
        json={"name": name, "hourly_rate": rate, "currency": currency},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _block(base_url, source_id, day: datetime.date, hours=2) -> None:
    r = httpx.post(
        f"{base_url}/api/freelance/blocks",
        json={"date": day.isoformat(), "source_id": source_id, "hours": hours},
    )
    assert r.status_code == 201, r.text


# ── 1. the day bar's help ────────────────────────────────────────────────────────

CHIP = ".log-form-card .q-chip"
TIP = "[data-testid=day-bar-help]"


def test_the_day_bar_help_is_four_gestures_with_an_icon_each(page, base_url):
    page.goto(f"{base_url}/#days")
    page.locator(CHIP).click()
    expect(page.locator(TIP)).to_be_visible()
    lines = page.locator(f"{TIP} > li")
    assert lines.count() == 4
    assert [t.strip() for t in lines.all_inner_texts()] == [
        "Drag bar to adjust work time",
        "Double-click bar to add a break",
        "Drag a break to move it",
        "Pull a break off to remove it",
    ]
    for i in range(4):
        icon = lines.nth(i).locator("svg")
        box = icon.bounding_box()
        assert (round(box["width"]), round(box["height"])) == (16, 16), box
        assert icon.evaluate("e => getComputedStyle(e).stroke") == icon.evaluate(
            "e => getComputedStyle(e).color"
        )  # stroke currentColor, in brass
    brass = page.evaluate(
        "getComputedStyle(document.documentElement).getPropertyValue('--k-brass').trim()"
    )
    rgb = page.evaluate(
        "(c) => { const d = document.createElement('i'); d.style.color = c; document.body.append(d);"
        " const v = getComputedStyle(d).color; d.remove(); return v; }",
        brass,
    )
    assert lines.nth(0).locator("svg").evaluate("e => getComputedStyle(e).color") == rgb
    # nothing else in the tip, and no native tooltip on the chip
    assert page.locator(f"{TIP} > *").count() == 4
    assert page.locator(CHIP).get_attribute("title") is None


def test_on_a_touch_screen_the_second_line_says_double_tap(browser, base_url):
    ctx = browser.new_context(
        viewport={"width": 375, "height": 812}, has_touch=True, is_mobile=True, locale="en-GB"
    )
    page = ctx.new_page()
    try:
        page.goto(f"{base_url}/#days")
        assert page.evaluate("matchMedia('(hover: none)').matches") is True
        page.locator(CHIP).tap()
        lines = page.locator(f"{TIP} > li")
        assert [t.strip() for t in lines.all_inner_texts()] == [
            "Drag bar to adjust work time",
            "Double-tap bar to add a break",
            "Drag a break to move it",
            "Pull a break off to remove it",
        ]
    finally:
        ctx.close()


# ── 2. the hairline's marks ──────────────────────────────────────────────────────

BAR = "header.app-header"


def _marks(page):
    return page.evaluate(
        """() => {
          const h = document.querySelector('header.app-header').getBoundingClientRect();
          const out = {};
          for (const m of document.querySelectorAll('.day-mark')) {
            const r = m.getBoundingClientRect(), b = m.querySelector('b').getBoundingClientRect();
            out[m.dataset.mark] = { x: r.left + r.width / 2, label: m.querySelector('b').textContent,
                                    labelTop: b.top, line: h.bottom, labelShown: b.width > 0 };
          }
          return { left: h.left, width: h.width, marks: out };
        }"""
    )


def _x_at(box, minutes):  # the bead's scale: 06:00 at the left edge, 24:00 at the right
    return box["left"] + (minutes - 360) / 1080 * (box["width"] - 7) + 3.5


def test_the_hairline_has_a_notch_at_each_working_hour_and_one_at_noon(page, base_url, clean):
    httpx.put(
        f"{base_url}/api/config", json={"default_start_time": "09:00", "default_end_time": "17:00"}
    )
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector(".day-mark")
    got = _marks(page)
    marks = got["marks"]
    assert set(marks) == {"start", "end", "noon"}
    assert abs(marks["start"]["x"] - _x_at(got, 9 * 60)) < 1.0, got
    assert abs(marks["end"]["x"] - _x_at(got, 17 * 60)) < 1.0, got
    assert abs(marks["noon"]["x"] - _x_at(got, 12 * 60)) < 1.0, got
    assert [marks[k]["label"] for k in ("start", "end", "noon")] == ["09:00", "17:00", "12:00"]
    # the same scale as the bead: with the clock at 09:00 the bead sits on the start's notch
    _app(page, "d.nowDisplay = '09:00';")
    page.wait_for_function(
        "() => { const b = document.querySelector('.day-bead').getBoundingClientRect();"
        " const m = document.querySelector('.day-mark[data-mark=start]').getBoundingClientRect();"
        " return Math.abs((b.left + b.width / 2) - (m.left + m.width / 2)) < 1; }"
    )
    # the labels sit under the line, in 11px tabular figures, muted
    lab = page.locator(".day-mark[data-mark=start] b")
    style = lab.evaluate(
        "e => { const s = getComputedStyle(e); return [s.fontSize, s.fontVariantNumeric]; }"
    )
    assert style == ["11px", "tabular-nums"], style
    assert marks["start"]["labelTop"] >= marks["start"]["line"] - 1, marks
    # the noon notch is the fainter and the shorter one
    heights = page.evaluate(
        "() => ['start', 'noon'].map(k => document.querySelector('.day-mark[data-mark=' + k + ']')"
        ".getBoundingClientRect().height)"
    )
    assert heights[1] < heights[0], heights


def test_noon_is_dropped_when_a_working_hour_is_within_90_minutes_of_it(page, base_url, clean):
    httpx.put(
        f"{base_url}/api/config", json={"default_start_time": "11:00", "default_end_time": "17:00"}
    )
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector(".day-mark")
    got = _marks(page)
    assert set(got["marks"]) == {"start", "end"}, got
    assert got["marks"]["start"]["label"] == "11:00"
    assert abs(got["marks"]["start"]["x"] - _x_at(got, 11 * 60)) < 1.0, got
    # exactly 90 minutes away is still too close; 91 is not
    httpx.put(
        f"{base_url}/api/config", json={"default_start_time": "10:30", "default_end_time": "17:00"}
    )
    page.reload()
    page.wait_for_selector(".day-mark")
    assert "noon" not in _marks(page)["marks"]  # 90 minutes: "within 90" includes it
    httpx.put(
        f"{base_url}/api/config", json={"default_start_time": "10:29", "default_end_time": "17:00"}
    )
    page.reload()
    page.wait_for_selector(".day-mark")
    assert "noon" in _marks(page)["marks"]  # 91 minutes away: it fits


def test_the_marks_follow_the_saved_hours_and_not_a_half_typed_field(page, base_url, clean):
    page.goto(f"{base_url}/#settings")
    page.wait_for_selector(".page-head")
    _app(page, "d.settingsForm.default_start_time = '08:00';")  # typed, not saved
    assert _marks(page)["marks"]["start"]["label"] == "09:00"


# ── 3. the FX chip ───────────────────────────────────────────────────────────────


def _fx_page(page, money_url, amount):
    src = _usd_source(money_url)
    _w44_block(money_url, src)
    eur = _post(money_url, "/api/freelance/accounts", name="Deutsche Bank", currency="EUR")
    _post(
        money_url,
        "/api/freelance/payouts",
        source_id=src,
        week_start=W44,
        amount=amount,
        account_id=eur["id"],
    )
    _open_days_freelance(page, money_url)
    return page.get_by_test_id("fx-chip")


def test_the_fx_chip_says_what_the_exchange_cost(page, money_url):
    chip = _fx_page(page, money_url, 877.94)  # billed $1,059.25 = EUR 948.13: 70.19 lost
    assert chip.inner_text().strip() == "FX -7.4%"
    chip.hover()
    expect(page.locator("#fx-tip")).to_have_text("Exchange and fees cost you €70.19")
    box = chip.bounding_box()
    assert box["height"] <= 34 and box["width"] < 120, box  # one line


def test_the_fx_chip_says_what_it_gave(page, money_url):
    chip = _fx_page(page, money_url, 1000)  # EUR 1,000 against 948.13: 51.87 ahead
    assert chip.inner_text().strip() == "FX +5.5%"
    chip.hover()
    expect(page.locator("#fx-tip")).to_have_text("Exchange and fees left you €51.87 ahead")


def test_the_fx_chip_stays_one_line_at_375(browser, money_url):
    ctx = browser.new_context(
        viewport={"width": 375, "height": 812}, locale="en-GB", has_touch=True
    )
    page = ctx.new_page()
    page.set_default_timeout(8000)
    try:
        chip = _fx_page(page, money_url, 877.94)
        box = chip.bounding_box()
        assert box["height"] <= 34, box
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        chip.tap()  # a tap pins the tip
        expect(page.locator("#fx-tip")).to_have_text("Exchange and fees cost you €70.19")
    finally:
        ctx.close()


# ── 4. payouts from the page where days are logged ───────────────────────────────

WAIT = "[data-testid=pay-wait]"
CHIPS = "[data-testid=pay-wait-chip]"


def _open_days(page, base_url):
    page.goto(f"{base_url}/#days")
    page.wait_for_selector("[data-testid=freelance-panel]")


def _payouts(base_url):
    return httpx.get(f"{base_url}/api/freelance/payouts").json()


def _chip_state(page):
    return page.evaluate(
        f"""() => [...document.querySelectorAll('{CHIPS}')].map(c => ({{
          text: c.textContent.trim(), on: c.classList.contains('on'), title: c.title, week: c.dataset.week }}))"""
    )


def test_a_week_without_a_payout_has_a_chip_newest_first_and_the_newest_is_selected(
    page, base_url, clean
):
    src = _source(base_url)
    older = LAST_MONDAY - datetime.timedelta(days=7)
    _block(base_url, src, LAST_MONDAY + datetime.timedelta(days=1), hours=2)
    _block(base_url, src, older + datetime.timedelta(days=1), hours=3.5)
    _open_days(page, base_url)
    chips = _chip_state(page)
    assert [c["text"] for c in chips] == [_wk(LAST_MONDAY), _wk(older)]
    assert [c["on"] for c in chips] == [True, False]
    assert [c["title"] for c in chips] == ["2h · €120.00 billed", "3.5h · €210.00 billed"]
    # selected: teal outline and text; the other one muted
    colors = page.evaluate(
        f"""() => [...document.querySelectorAll('{CHIPS}')].map(c => {{
          const s = getComputedStyle(c); return [s.color, s.borderTopColor]; }})"""
    )
    teal = page.evaluate(
        "(() => { const d = document.createElement('i'); d.style.color = getComputedStyle("
        "document.documentElement).getPropertyValue('--paid').trim(); document.body.append(d);"
        " const v = getComputedStyle(d).color; d.remove(); return v; })()"
    )
    assert colors[0] == [teal, teal], (colors, teal)
    assert colors[1][0] != teal


def test_a_week_with_two_sources_gets_a_chip_per_source(page, base_url, clean):
    a, b = _source(base_url, "Northwind"), _source(base_url, "Local", 50)
    day = LAST_MONDAY + datetime.timedelta(days=2)
    _block(base_url, a, day)
    _block(base_url, b, day)
    _open_days(page, base_url)
    assert [c["text"] for c in _chip_state(page)] == [
        f"{_wk(LAST_MONDAY)} Northwind",
        f"{_wk(LAST_MONDAY)} Local",
    ]


def test_more_than_six_weeks_show_six_chips_and_a_link_to_weeks(page, base_url, clean):
    src = _source(base_url)
    for i in range(9):
        _block(base_url, src, LAST_MONDAY - datetime.timedelta(days=7 * i), hours=1)
    _open_days(page, base_url)
    assert page.locator(CHIPS).count() == 6
    more = page.get_by_test_id("pay-wait-more")
    assert more.inner_text() == "+3"
    more.click()
    page.wait_for_url("**/#weeks")


def test_no_waiting_row_without_weeks_waiting(page, base_url, clean):
    src = _source(base_url)
    _block(base_url, src, MONDAY, hours=2)  # this week is not over
    _open_days(page, base_url)
    assert page.locator(WAIT).count() == 0


def test_saving_from_the_row_makes_the_same_payout_as_the_weeks_page(page, base_url, clean):
    src = _source(base_url)
    older = LAST_MONDAY - datetime.timedelta(days=7)
    _block(base_url, src, LAST_MONDAY + datetime.timedelta(days=1), hours=2)
    _block(base_url, src, older + datetime.timedelta(days=1), hours=2)
    # the Weeks page: the older week, typed in its row
    page.goto(f"{base_url}/#weeks")
    page.wait_for_selector(".page-head .hm-switch")
    _app(page, "d.daysYear = 'all';")
    page.locator(".page-head .hm-switch button").nth(1).click()
    page.wait_for_selector("[data-testid='days-freelance']")
    page.locator(f"input[aria-label='Payout Local {_wk(older)}']").fill("150")
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('main')).payouts.length === 1"
    )
    # the waiting row: the newest week, typed and saved
    _open_days(page, base_url)
    assert [c["text"] for c in _chip_state(page)] == [_wk(LAST_MONDAY)]
    page.get_by_test_id("pay-wait-amount").fill("150")
    page.get_by_test_id("pay-wait-save").click()
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('main')).payouts.length === 2"
    )
    got = {p["week_start"]: p for p in _payouts(base_url)}
    assert set(got) == {older.isoformat(), LAST_MONDAY.isoformat()}
    skip = {"id", "week_start", "week_end", "created_at", "updated_at"}
    a, b = got[older.isoformat()], got[LAST_MONDAY.isoformat()]
    assert {k: v for k, v in a.items() if k not in skip} == {
        k: v for k, v in b.items() if k not in skip
    }
    assert (
        b["amount"] == 150 and b["source_id"] == src and b["week_start"] == LAST_MONDAY.isoformat()
    )


def test_saving_removes_the_chip_and_selects_the_next(page, base_url, clean):
    src = _source(base_url)
    weeks = [LAST_MONDAY - datetime.timedelta(days=7 * i) for i in range(3)]
    for w in weeks:
        _block(base_url, src, w + datetime.timedelta(days=1))
    _open_days(page, base_url)
    # pick the middle one: saving it selects the one after it (the oldest), and the newest stays
    page.locator(f"{CHIPS}[data-week='{weeks[1].isoformat()}']").click()
    assert [c["on"] for c in _chip_state(page)] == [False, True, False]
    page.get_by_test_id("pay-wait-amount").fill("99")
    page.get_by_test_id("pay-wait-save").click()
    page.wait_for_function(f"() => document.querySelectorAll('{CHIPS}').length === 2", timeout=6000)
    state = _chip_state(page)
    assert [c["text"] for c in state] == [_wk(weeks[0]), _wk(weeks[2])]
    assert [c["on"] for c in state] == [False, True]
    assert [p["week_start"] for p in _payouts(base_url)] == [weeks[1].isoformat()]
    # the amount field is empty again for the week now picked
    assert page.get_by_test_id("pay-wait-amount").input_value() == ""


def test_an_invalid_amount_reads_as_on_the_weeks_page(page, base_url, clean):
    src = _source(base_url)
    _block(base_url, src, LAST_MONDAY + datetime.timedelta(days=1))
    _open_days(page, base_url)
    page.get_by_test_id("pay-wait-amount").fill("abc")
    page.get_by_test_id("pay-wait-save").click()
    expect(page.locator(f"{WAIT} .wk-status")).to_have_text("check the value")
    assert _payouts(base_url) == []
    assert page.locator(CHIPS).count() == 1


# ── 5. the calculator's parameters ───────────────────────────────────────────────

CALC_ROWS = """() => [...document.querySelectorAll('[data-testid=fl-calc] .calc-p')].map(p => {
  const l = p.querySelector('.fl-lbl').getBoundingClientRect(), i = p.querySelector('input').getBoundingClientRect();
  return { gap: i.left - l.right, label: p.querySelector('.fl-lbl').textContent.trim(), w: i.width,
           left: Math.round(p.getBoundingClientRect().left), top: Math.round(p.getBoundingClientRect().top),
           align: getComputedStyle(p.querySelector('.fl-lbl')).textAlign };
})"""


def _open_calc(page, base_url, size):
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.goto(f"{base_url}/#freelance")
    page.wait_for_selector("[data-testid=fl-calc] .calc-p")
    page.wait_for_timeout(300)
    return page.evaluate(CALC_ROWS)


@pytest.mark.parametrize(
    "size,columns", [((1280, 900), 3), ((800, 900), 2), ((375, 812), 1)], ids=["1280", "800", "375"]
)
def test_each_calculator_parameter_has_its_label_beside_its_value(
    page, base_url, clean, size, columns
):
    _source(base_url)
    rows = _open_calc(page, base_url, size)
    assert [r["label"] for r in rows] == [
        "Hours a day",
        "Billable days",
        "Salary €/y",
        "Gestoría €/y",
        "Other €/y",
    ]
    for r in rows:
        assert 0 <= r["gap"] <= 10, r
        assert r["align"] == "right", r
        assert 60 <= r["w"] <= 90, r
    assert len({r["left"] for r in rows}) == columns, rows
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_the_parameters_block_is_at_least_60px_shorter_than_it_was(page, base_url, clean):
    _source(base_url)
    _open_calc(page, base_url, (1280, 900))
    h = page.locator("[data-testid=fl-calc] .calc-assume").bounding_box()["height"]
    assert h <= 224.5 - 60, h  # it was 224.5px with the dollar rate shown


def test_the_dollar_rate_keeps_its_ecb_date_and_the_toggles_still_work(page, base_url, clean):
    _source(base_url)
    _open_calc(page, base_url, (1280, 900))
    calc = page.locator("[data-testid=fl-calc]")
    calc.locator(".seg-toggle[aria-label=Currency] button", has_text="USD").click()
    row = calc.locator(".calc-p", has_text="$ per €")
    expect(row).to_be_visible()
    row.locator(".calc-p-note").wait_for()
    rows = page.evaluate(CALC_ROWS)
    fx = next(r for r in rows if r["label"].startswith("$ per"))
    assert 0 <= fx["gap"] <= 10, fx
    # the ECB date sits on the value's line, not floating above it
    note, field = row.locator(".calc-p-note").bounding_box(), row.locator("input").bounding_box()
    middle = lambda b: b["y"] + b["height"] / 2  # noqa: E731
    assert abs(middle(note) - middle(field)) <= 4, (note, field)
    # a 76px field has no room for the browser's spin arrows: with them "1.1165" loses its last digit
    assert row.locator("input").evaluate("e => getComputedStyle(e).appearance") == "textfield"
    calc.locator(".seg-toggle[aria-label='Billable days'] button", has_text="220").click()
    assert calc.locator("input[aria-label='Billable days']").input_value() == "220"
    # the options sit on one line above the grid
    tops = page.evaluate(
        """() => [...document.querySelectorAll('[data-testid=fl-calc] .calc-opts > *')]
          .filter(e => e.getBoundingClientRect().height).map(e => Math.round(e.getBoundingClientRect().top))"""
    )
    assert max(tops) - min(tops) < 12, tops


# ── 6. the tabs: new names, new addresses, new keys ──────────────────────────────


@pytest.mark.parametrize(
    "start,final,heading",
    [
        ("log", "days", "Days"),  # the old address of the page where days are logged
        ("analytics", "year", "Year"),
        ("days", "days", "Days"),  # an old #days link opens the new Days page, on purpose
        ("weeks", "weeks", "Weeks"),
        ("year", "year", "Year"),
    ],
)
def test_the_addresses_open_the_right_page_and_old_ones_are_rewritten(
    page, base_url, start, final, heading
):
    page.goto(f"{base_url}/#{start}")
    page.wait_for_selector("main .page-head h2")
    page.wait_for_function(f"() => location.hash === '#{final}'")
    assert page.locator("main .page-head h2").first.inner_text().strip() == heading
    tab = page.evaluate("Alpine.$data(document.querySelector('main')).tab")
    assert tab == {"Days": "log", "Weeks": "days", "Year": "analytics"}[heading]


def test_an_old_address_typed_while_the_app_is_open_is_rewritten_too(page, base_url):
    page.goto(f"{base_url}/#weeks")
    page.wait_for_selector("main .page-head h2")
    page.evaluate("location.hash = 'analytics'")
    page.wait_for_function("() => location.hash === '#year'")
    assert page.locator("main .page-head h2").first.inner_text().strip() == "Year"
    page.evaluate("location.hash = 'log'")
    page.wait_for_function("() => location.hash === '#days'")
    assert page.locator("main .page-head h2").first.inner_text().strip() == "Days"


def test_the_tabs_are_named_for_what_a_person_reads(page, base_url):
    page.goto(f"{base_url}/#dashboard")
    names = page.locator(".tabs [role=tab] .tab-label").all_inner_texts()
    assert names[:5] == ["Dashboard", "Plan", "Days", "Weeks", "Year"]
    keys = page.locator(".tabs .tab-key").all_inner_texts()
    assert keys[:4] == ["P", "D", "W", "Y"]


@pytest.mark.parametrize(
    "key,hash_,heading",
    [("d", "#days", "Days"), ("w", "#weeks", "Weeks"), ("y", "#year", "Year")],
)
def test_the_keys_d_w_and_y_open_days_weeks_and_year(page, base_url, key, hash_, heading):
    page.goto(f"{base_url}/#settings")
    page.wait_for_selector(".page-head")
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press(key)
    page.wait_for_function(f"() => location.hash === '{hash_}'")
    assert page.locator("main .page-head h2").first.inner_text().strip() == heading


def test_k_opens_the_year_dial_and_l_and_a_no_longer_go_anywhere(page, base_url):
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector(".hero-num")
    page.keyboard.press("l")
    page.keyboard.press("a")
    page.wait_for_timeout(200)
    assert page.evaluate("location.hash") == "#dashboard"
    page.keyboard.press("k")
    page.wait_for_selector("#yd", state="visible")
    assert page.evaluate("Alpine.$data(document.querySelector('main')).dialOpen") is True
    assert page.locator(".brand-btn").get_attribute("title") == "Your year as a dial (K)"


def test_typing_kronos_still_runs_the_egg_although_k_opens_the_dial(page, base_url):
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector(".hero-num")
    page.evaluate("document.activeElement.blur()")
    page.keyboard.type("kronos", delay=30)
    page.wait_for_selector(".brand-logo.logo-wind", timeout=3000)
    page.wait_for_selector(".egg-emoji.egg-go", state="attached", timeout=3000)
    # the dial that "k" opened is closed again, and the s did not leave for Settings
    assert page.evaluate("Alpine.$data(document.querySelector('main')).dialOpen") is False
    assert page.evaluate("location.hash") == "#dashboard"


def test_the_palette_and_the_shortcuts_sheet_say_the_new_keys(page, base_url):
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector(".hero-num")
    sheet = page.locator(".shortcut-tooltip").inner_text()
    rows = [r.split("\n") for r in sheet.strip().split("\n\n")] if "\n\n" in sheet else None
    pairs = page.evaluate(
        "() => [...document.querySelectorAll('.shortcut-row')].map(r => [r.querySelector('kbd').textContent, r.querySelector('span').textContent])"
    )
    assert ["D", "Days"] in pairs and ["W", "Weeks"] in pairs and ["Y", "Year"] in pairs
    assert ["K", "Year dial"] in pairs
    assert not any(k in ("L", "A") for k, _ in pairs), (pairs, rows)
    page.keyboard.press(".")
    page.wait_for_selector(".palette")
    cmds = page.evaluate(
        "() => [...document.querySelectorAll('.palette li[role=option]')].map(li => [li.firstElementChild.textContent, (li.querySelector('kbd') || {}).textContent])"
    )
    assert ["Log new entry", "D"] in cmds and ["Weeks", "W"] in cmds
    assert ["Year", "Y"] in cmds and ["Year dial", "K"] in cmds


# ── 7. short tooltips ────────────────────────────────────────────────────────────


def test_no_tooltip_or_help_is_a_paragraph(page, base_url, clean):
    _source(base_url)
    seen = {}
    for tab in ("dashboard", "plan", "days", "weeks", "year", "freelance", "settings"):
        page.goto(f"{base_url}/#{tab}")
        page.wait_for_selector("main .page-head")
        page.wait_for_timeout(400)
        for _kind, text in page.evaluate(
            """() => [...document.querySelectorAll('[title], [data-tip]')].flatMap(e =>
              [['title', e.getAttribute('title')], ['tip', e.getAttribute('data-tip')]]).filter(x => x[1])"""
        ):
            for line in text.split("\n"):  # a tip is one short line, or one line per action
                if len(line) > 90:
                    seen[line] = tab
    assert seen == {}, seen


# ── 8. the year dial: a ring around the logo and a tile on the Dashboard ───────────────


def _year_facts(day: datetime.date):
    """What the ring must show, worked out here and not by the app: the ticks (a plain one about every
    five days, a long one on each first of the month), how many are brass, and the dot's angle."""
    n = 366 if day.year % 4 == 0 and (day.year % 100 or day.year % 400 == 0) else 365
    doy = day.timetuple().tm_yday
    firsts = {datetime.date(day.year, m, 1).timetuple().tm_yday - 1 for m in range(1, 13)}
    ticks = [
        i
        for i in range(n)
        if i in firsts or (i % 5 == 0 and i - 1 not in firsts and i + 1 not in firsts)
    ]
    return {
        "n": n,
        "doy": doy,
        "ticks": len(ticks),
        "brass": sum(1 for i in ticks if i < doy),
        "angle": (doy - 1) / n * 360,
        "long": len(firsts),
    }


def _at_day(page, base_url, iso: str, tab="dashboard"):
    page.clock.set_fixed_time(f"{iso}T12:00:00")
    page.goto(f"{base_url}/#{tab}")
    page.wait_for_selector(".brand-ring .rd", state="attached")


DOT_ANGLE = """(sel) => {
  const svg = document.querySelector(sel), r = svg.getBoundingClientRect();
  const d = svg.querySelector('.rd').getBoundingClientRect();
  const dx = d.left + d.width / 2 - (r.left + r.width / 2), dy = d.top + d.height / 2 - (r.top + r.height / 2);
  return ((Math.atan2(dx, -dy) * 180 / Math.PI) + 360) % 360;
}"""


def _tile_text(page):
    return (
        page.get_by_test_id("dial-tile-day").inner_text().strip(),
        page.get_by_test_id("dial-tile-sub").inner_text().strip(),
    )


def _css_colour(page, token):
    return page.evaluate(
        "(t) => { const v = getComputedStyle(document.documentElement).getPropertyValue(t).trim();"
        " const d = document.createElement('i'); d.style.color = v; document.body.append(d);"
        " const c = getComputedStyle(d).color; d.remove(); return c; }",
        token,
    )


def test_the_tile_says_which_day_of_the_year_it_is_and_the_balance_of_the_hero(
    page, base_url, clean
):
    r = httpx.post(
        f"{base_url}/api/entries",
        json={"date": "2026-11-04", "day_type": "work", "start_time": "09:00", "end_time": "19:00"},
    )
    assert r.status_code == 201, r.text
    _at_day(page, base_url, "2026-11-09")
    page.wait_for_selector("[data-testid=dial-tile-balance]")
    day, sub = _tile_text(page)
    assert day == "Day 313 of 365", day
    assert sub.startswith("52 days left · "), sub
    page.wait_for_function("() => document.querySelector('.hero-num').innerText.trim().length > 4")
    balance = page.get_by_test_id("dial-tile-balance")
    assert balance.inner_text() == page.locator(".hero-num").inner_text().strip() == "+2.00h"
    assert "surplus" in balance.get_attribute("class")
    brass = page.locator("[data-testid=dial-tile-day] b")
    assert brass.inner_text() == "Day 313"
    assert brass.evaluate("e => getComputedStyle(e).color") == _css_colour(page, "--k-brass")


@pytest.mark.parametrize(
    "iso,day,left",
    [
        ("2026-12-30", "Day 364 of 365", "1 day left"),
        ("2026-12-31", "Day 365 of 365", "0 days left"),  # on purpose: true, and the same sentence
        ("2028-02-29", "Day 60 of 366", "306 days left"),
        ("2028-12-31", "Day 366 of 366", "0 days left"),
        ("2026-01-01", "Day 1 of 365", "364 days left"),
    ],
)
def test_the_tile_counts_the_end_of_the_year_and_leap_years(page, base_url, clean, iso, day, left):
    _at_day(page, base_url, iso)
    page.wait_for_selector("[data-testid=dial-tile]")
    assert _tile_text(page) == (day, left)  # an empty database: no balance


@pytest.mark.parametrize(
    "iso", ["2026-11-09", "2026-01-01", "2026-12-31", "2028-02-29", "2028-12-31"]
)
def test_the_ring_has_the_expected_ticks_and_the_dot_where_today_is(page, base_url, clean, iso):
    facts = _year_facts(datetime.date.fromisoformat(iso))
    _at_day(page, base_url, iso)
    page.wait_for_selector("[data-testid=dial-tile]")
    for sel in (".brand-ring .ring", ".dial-ring .ring"):  # the logo's and the tile's: one function
        ring = page.locator(sel)
        assert ring.locator("line.rt").count() == facts["ticks"], (sel, facts)
        assert ring.locator("line.rt.rm").count() == facts["long"] == 12
        assert ring.locator("line.rt.on").count() == facts["brass"], (sel, facts)
        got = page.evaluate(DOT_ANGLE, sel)
        diff = abs((got - facts["angle"] + 180) % 360 - 180)
        assert diff <= 2, (sel, got, facts)
    on = page.locator(".brand-ring line.rt.on")
    off = page.locator(".brand-ring line.rt:not(.on)")
    if on.count():
        assert on.first.evaluate("e => getComputedStyle(e).stroke") == _css_colour(
            page, "--k-brass"
        )
    if off.count():
        assert off.first.evaluate("e => getComputedStyle(e).stroke") == _css_colour(
            page, "--k-border-strong"
        )


def test_the_ring_counts_366_days_in_a_leap_year(page, base_url, clean):
    assert _year_facts(datetime.date(2028, 6, 1))["n"] == 366
    assert _year_facts(datetime.date(2026, 6, 1))["n"] == 365
    assert _year_facts(datetime.date(2100, 6, 1))["n"] == 365  # not a leap year
    _at_day(page, base_url, "2028-12-31")
    assert page.locator(".dial-ring .rd").get_attribute("data-angle") == f"{365 / 366 * 360:.2f}"


# The dial listens for Escape once it has read its day: pressed before that, on a loaded runner, the key is lost.
DIAL_READY = "#yd [data-yd=stage][data-day]:not([data-day=''])"


def test_the_tile_and_the_logo_both_open_the_dial(page, base_url, clean):
    _at_day(page, base_url, "2026-11-09")
    page.wait_for_selector("[data-testid=dial-tile]")
    assert page.get_by_test_id("dial-tile").get_attribute("aria-label") == "Open the year dial"
    page.get_by_test_id("dial-tile").click()
    page.wait_for_selector(DIAL_READY, timeout=8000)
    page.keyboard.press("Escape")
    page.wait_for_selector("#yd", state="detached")
    page.locator(".brand-btn").click()
    page.wait_for_selector(DIAL_READY, timeout=8000)
    page.keyboard.press("Escape")
    page.wait_for_selector("#yd", state="detached")
    for key in ("Enter", " "):  # a button: the keyboard opens it too
        page.get_by_test_id("dial-tile").focus()
        page.keyboard.press(key)
        page.wait_for_selector(DIAL_READY, timeout=8000)
        page.keyboard.press("Escape")
        page.wait_for_selector("#yd", state="detached")


def test_the_tile_loses_its_key_cap_on_a_touch_screen(browser, base_url, clean):
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 900}, locale="en-GB", has_touch=True, is_mobile=True
    )
    page = ctx.new_page()
    try:
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector("[data-testid=dial-tile]")
        assert page.evaluate("matchMedia('(hover: none)').matches") is True
        assert page.locator(".dial-tile-key").is_hidden()
    finally:
        ctx.close()


def test_the_tile_shows_open_dial_and_a_k_key_on_a_pointer_screen(page, base_url, clean):
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("[data-testid=dial-tile]")
    assert page.locator(".dial-tile-go").inner_text().split() == ["Open", "dial", "K"]
    assert page.locator(".dial-tile-key").is_visible()


def test_the_ring_turns_once_on_hover_and_not_under_reduced_motion(page, base_url, clean):
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("[data-testid=dial-tile]")
    page.get_by_test_id("dial-tile").hover()
    names = page.evaluate(
        "document.querySelector('.dial-ring').getAnimations().map(a => a.animationName)"
    )
    assert names == ["ring-turn"], names
    page.mouse.move(2, 600)
    page.locator(".brand-btn").hover()
    got = page.evaluate(
        "(() => { const a = document.querySelector('.brand-ring').getAnimations()[0];"
        " return [a.animationName, a.effect.getTiming().duration, a.effect.getTiming().iterations]; })()"
    )
    assert got == ["ring-turn", 1100, 1], got
    # the keyboard's focus turns it too
    page.mouse.move(2, 600)
    page.wait_for_timeout(1400)
    page.keyboard.press("Tab")  # from the top of the page: the first stop is the logo
    page.wait_for_function(
        "() => document.activeElement.classList.contains('brand-btn')"
        " && document.querySelector('.brand-ring').getAnimations().length === 1"
    )
    page.emulate_media(reduced_motion="reduce")
    page.mouse.move(2, 600)
    page.wait_for_timeout(1400)
    page.get_by_test_id("dial-tile").hover()
    assert page.evaluate("document.querySelector('.dial-ring').getAnimations().length") == 0
    page.locator(".brand-btn").hover()
    assert page.evaluate("document.querySelector('.brand-ring').getAnimations().length") == 0


@pytest.mark.parametrize("size", [(1280, 900), (375, 800), (320, 700)], ids=["1280", "375", "320"])
def test_no_sideways_scroll_and_the_ring_clears_the_name(page, base_url, clean, size):
    page.set_viewport_size({"width": size[0], "height": size[1]})
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("[data-testid=dial-tile]")
    got = page.evaluate(
        """() => { const ring = document.querySelector('.brand-ring').getBoundingClientRect();
          const h1 = document.querySelector('.brand h1').getBoundingClientRect();
          const logo = document.querySelector('.brand-logo').getBoundingClientRect();
          const tile = document.querySelector('[data-testid=dial-tile]').getBoundingClientRect();
          return { ringRight: ring.right, ringLeft: ring.left, ringTop: ring.top, h1Left: h1.left,
                   logo: [logo.width, logo.height], tile: [tile.left, tile.right], w: innerWidth,
                   sw: document.documentElement.scrollWidth }; }"""
    )
    assert got["sw"] <= got["w"], got
    assert got["ringRight"] < got["h1Left"], got  # it does not touch "Kronos"
    assert got["ringLeft"] >= 0 and got["ringTop"] >= 0, got  # nor is it clipped by the screen
    assert got["logo"] == ([48, 48] if size[0] > 480 else [36, 36]), got  # the disc keeps its size
    assert got["tile"][0] >= 0 and got["tile"][1] <= got["w"], got
    if size[0] <= 640:  # full width on a phone
        assert got["tile"][1] - got["tile"][0] >= got["w"] - 40, got


def test_the_hero_figure_is_still_in_the_first_screen_at_375_x_800(page, base_url, clean):
    page.set_viewport_size({"width": 375, "height": 800})
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("[data-testid=dial-tile]")
    hero = page.locator(".hero-num").bounding_box()
    assert hero["y"] + hero["height"] <= 800, hero


def test_the_tile_pushes_the_hero_down_by_less_than_its_own_height(page, base_url, clean):
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector("[data-testid=dial-tile]")
    tile = page.get_by_test_id("dial-tile").bounding_box()
    assert tile["y"] + tile["height"] <= 900  # in the first screen at 1280 x 900
    with_tile = page.locator(".hero-num").bounding_box()["y"]
    page.evaluate("document.querySelector('[data-testid=dial-tile]').style.display = 'none'")
    page.wait_for_timeout(100)
    without = page.locator(".hero-num").bounding_box()["y"]
    assert 0 <= with_tile - without <= tile["height"], (with_tile, without, tile)
