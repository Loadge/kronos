"""E2E: the country and the number format (Settings > General), the one formatting path and the one
parsing path, and the tax module that follows the country.

The demo server has the same data and the same frozen day every time, so a figure read under
en-US is the figure to expect under es-ES with its two marks swapped. Every test that changes a
setting puts it back, because the server is shared by the tests of a worker.
"""

# ruff: noqa: E501
# (the long lines are the JavaScript that runs in the page: one read of the page per call)

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
import pytest

from .conftest import BACKEND_DIR, DEMO_NOW, HASH_OF, _find_free_port, _wait_for_server

pytestmark = pytest.mark.e2e

CASES = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "number_cases.json").read_text(encoding="utf-8")
)
HERO = ".hero .hero-num"
BALANCE = "main .hero-num .odo"


@pytest.fixture
def make_page(browser, demo_url):
    contexts: list = []

    def make(tab="dashboard", *, size=(1280, 900), url=None, locale="en-GB", hint=False):
        context = browser.new_context(
            viewport={"width": size[0], "height": size[1]},
            locale=locale,
            timezone_id="Europe/Madrid",
            color_scheme="dark",
            reduced_motion="reduce",
        )
        context.add_init_script("localStorage.setItem('k-milestone-seen', '100000')")
        if hint:  # the suite's contexts have seen the suggestion; this one has not
            context.add_init_script(
                "localStorage.setItem('k-locale-hint-test', '1'); "
                "if (!sessionStorage.getItem('k-hint-cleared')) { localStorage.removeItem('k-locale-hint'); sessionStorage.setItem('k-hint-cleared', '1'); }"
            )
        contexts.append(context)
        page = context.new_page()
        page.clock.set_fixed_time(DEMO_NOW)
        page.goto(f"{url or demo_url}/#{HASH_OF.get(tab, tab)}", wait_until="networkidle")
        page.wait_for_selector("main .page-head", timeout=5000)
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(300)
        return page

    yield make
    for context in contexts:
        context.close()


@pytest.fixture
def put_config(demo_url):
    """Change the demo server's settings; whatever a test changed is put back afterwards."""
    was = httpx.get(f"{demo_url}/api/config").json()

    def put(**body):
        httpx.put(f"{demo_url}/api/config", json=body).raise_for_status()

    yield put
    httpx.put(
        f"{demo_url}/api/config",
        json={"country": was["country"], "number_format": was["number_format"]},
    ).raise_for_status()


@pytest.fixture
def fresh_url():
    """A server with an empty database: nothing logged, no country chosen."""
    port = _find_free_port()
    with tempfile.TemporaryDirectory() as data_dir:
        env = {
            **os.environ,
            "KRONOS_DATA_DIR": data_dir,
            "KRONOS_FX_URL": "",
            "PYTHONPATH": str(BACKEND_DIR),
        }
        env.pop("DATABASE_URL", None)
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


def _text(page, selector: str) -> str:
    return page.locator(selector).first.inner_text().strip()


def _loaded(page):
    page.wait_for_function(
        "() => { const d = Alpine.$data(document.querySelector('main')); return !!d._settingsSaved && !!d.dashboard; }",
        timeout=8000,
    )


# ── the formatting path ─────────────────────────────────────────────────────────────────────


def test_the_dashboard_balance_follows_the_format_and_goes_back(make_page, put_config):
    page = make_page()
    _loaded(page)
    en = _text(page, BALANCE)
    assert en == "+119.25h", en
    put_config(number_format="es-ES")
    page = make_page()
    _loaded(page)
    page.wait_for_function(
        "(en) => document.querySelector('main .hero-num .odo').innerText.trim() !== en",
        arg=en,
        timeout=5000,
    )
    es = _text(page, BALANCE)
    assert es == "+119,25h", es
    # The long dates follow the format's order too: "Sat 7 Nov" here, "Sat, Nov 7" in en-US.
    chip = page.locator("main .today-chip").first.inner_text()
    assert re.match(r"^[A-Z][a-z]{2},? \d{1,2} [A-Z][a-z]{2}\b", chip), chip
    put_config(number_format="en-US")
    page = make_page()
    _loaded(page)
    page.wait_for_function(
        "(en) => document.querySelector('main .hero-num .odo').innerText.trim() === en",
        arg=en,
        timeout=5000,
    )


def test_switching_in_settings_re_prints_the_page_at_once(make_page, put_config):
    page = make_page("settings")
    page.locator(".settings-group-btn", has_text="General").click()
    page.wait_for_selector("#set-number-format", timeout=5000)
    options = page.locator("#set-number-format option")
    assert [o.inner_text() for o in options.all()] == [
        "1,234.56",
        "1.234,56",
        "1 234,56",
        "1’234.56",
    ]
    page.locator("#set-number-format").select_option("es-ES")
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('main'))._settingsSaved.number_format === 'es-ES'",
        timeout=5000,
    )
    assert httpx.get(page.url.split("#")[0] + "api/config").json()["number_format"] == "es-ES"
    shown = page.evaluate("() => Alpine.$data(document.querySelector('main')).fmtMoney(1234.56)")
    assert shown == "€1.234,56"
    hours = page.evaluate("() => Alpine.$data(document.querySelector('main')).formatSurplus(25)")
    assert hours == "+25,00h"
    page.locator("#set-number-format").select_option("en-US")
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('main'))._settingsSaved.number_format === 'en-US'",
        timeout=5000,
    )
    assert (
        page.evaluate("() => Alpine.$data(document.querySelector('main')).fmtMoney(1234.56)")
        == "€1,234.56"
    )


@pytest.mark.parametrize(
    "tag,money,hours,fx,pct,rounded",
    [
        ("en-US", "€1,234.56", "+25.00h", "1.1172", "12.5%", "€1,290"),
        ("es-ES", "€1.234,56", "+25,00h", "1,1172", "12,5%", "€1.290"),
        ("fr-FR", "€1 234,56", "+25,00h", "1,1172", "12,5%", "€1 290"),
        ("de-CH", "€1’234.56", "+25.00h", "1.1172", "12.5%", "€1’290"),
    ],
)
def test_every_formatter_writes_the_four_formats(
    make_page, put_config, tag, money, hours, fx, pct, rounded
):
    put_config(number_format=tag)
    page = make_page()
    _loaded(page)
    got = page.evaluate(
        """() => { const a = Alpine.$data(document.querySelector('main'));
          return [a.fmtMoney(1234.56), a.formatSurplus(25), a.fmtFx(1.1172), a.pct(0.125), a.fmtHours(3.5), a.fmtMoney(-5, 'USD'), a.fmtMoney0(1290.4)]; }"""
    )
    assert got[:4] == [money, hours, fx, pct]
    sep = {"en-US": ".", "es-ES": ",", "fr-FR": ",", "de-CH": "."}[tag]
    assert got[4] == f"3{sep}5h"
    assert got[5] == "-$5" + sep + "00"
    assert got[6] == rounded


def test_a_money_figure_of_the_freelance_tab_reads_in_the_chosen_format(make_page, put_config):
    page = make_page("freelance")
    page.wait_for_selector("[data-testid=fl-gross] .odo", timeout=8000)
    en = _text(page, "[data-testid=fl-gross] .odo")
    assert en == "€9,062.49", en
    put_config(number_format="es-ES")
    page = make_page("freelance")
    page.wait_for_selector("[data-testid=fl-gross] .odo", timeout=8000)
    page.wait_for_function(
        "(en) => document.querySelector('[data-testid=fl-gross] .odo').innerText.trim() !== en",
        arg=en,
        timeout=5000,
    )
    es = _text(page, "[data-testid=fl-gross] .odo")
    assert es == "€9.062,49", es


def test_the_odometer_and_the_dial_roll_with_a_decimal_comma(make_page, put_config):
    put_config(number_format="es-ES")
    page = make_page()
    _loaded(page)
    page.wait_for_function(
        "() => /,\\d\\d/.test(document.querySelector('main .hero-num .odo')?.innerText || '')",
        timeout=5000,
    )
    # the reels: one per digit, the comma drawn from data-ch
    reels = page.evaluate(
        """() => { const o = document.querySelector('main .hero-num .odo');
          return { reels: o.querySelectorAll('.odo-reel').length, marks: [...o.querySelectorAll('.odo-ch')].map(c => c.dataset.ch).join('') }; }"""
    )
    assert reels["reels"] >= 3 and "," in reels["marks"], reels
    page.keyboard.press("k")
    page.wait_for_selector("#yd [data-yd=stage][data-day]:not([data-day=''])", timeout=8000)
    assert re.search(r"[+−±]\d+,\d{2}h", page.locator("[data-yd=balv]").first.text_content()), (
        page.locator("[data-yd=balv]").first.text_content()
    )


# ── the parsing path ────────────────────────────────────────────────────────────────────────


def test_the_calculator_reads_55_000_by_the_chosen_format(make_page, put_config):
    for tag, typed, value in [
        ("es-ES", "55.000", 55000),
        ("en-US", "55.000", 55),
        ("en-US", "12,5", 12.5),
        ("es-ES", "1.234,56", 1234.56),
    ]:
        put_config(number_format=tag)
        page = make_page("freelance")
        salary = page.locator("[data-testid=fl-calc] input[aria-label=Salary]")
        salary.wait_for(timeout=8000)
        salary.fill(typed)
        page.wait_for_function(
            "(v) => Alpine.$data(document.querySelector('main')).calc.salary_annual === v",
            arg=value,
            timeout=5000,
        )


def test_the_payout_field_reads_by_the_chosen_format(make_page, put_config):
    put_config(number_format="es-ES")
    page = make_page("freelance")
    got = page.evaluate(
        "() => { const a = Alpine.$data(document.querySelector('main')); return [a.num('1.234,5'), a.num('12,5'), a.fmtPlain(1234.5)]; }"
    )
    assert got == [1234.5, 12.5, "1234,5"]


@pytest.mark.parametrize("case", CASES["parse"], ids=lambda c: f"{c['format']}:{c['text']!r}")
def test_the_browser_parses_what_the_server_parses(make_page, case):
    page = make_page()
    got = page.evaluate("([t, f]) => parseNum(t, f)", [case["text"], case["format"]])
    if case["value"] is None:
        assert got is None or got != got  # NaN crosses as nan or null
    else:
        assert got == pytest.approx(case["value"])


# ── the tax module follows the country ──────────────────────────────────────────────────────


def test_germany_hides_the_130_rail_and_shows_the_set_aside_line(make_page, put_config):
    page = make_page("freelance")
    page.wait_for_selector("[data-testid=fl-quarters]", timeout=8000)  # Spain: the rail is there
    assert page.locator("[data-testid=fl-aside]").count() == 0
    put_config(country="DE")
    try:
        page = make_page("freelance")
        page.wait_for_selector("[data-testid=fl-aside]", timeout=8000)
        assert page.locator("[data-testid=fl-quarters]").count() == 0
        assert page.locator("text=Modelo 130").count() == 0
        line = page.locator("[data-testid=fl-aside] .fl-aside-line").inner_text()
        assert re.fullmatch(
            r"Set aside: €[\d,]+\.\d{2} of €[\d,]+\.\d{2} received this year", line
        ), line
        body = page.locator("section[aria-label=Freelance]").inner_text()
        for word in ("RETA", "IRPF", "Gestoría", "Tarifa plana", "Renta"):
            assert word not in body, word
        # the calculator: one extra input, no Spanish ones
        assert page.locator("[data-testid=fl-calc] input[aria-label='Set aside']").is_visible()
        assert page.locator("[data-testid=fl-calc] input[aria-label=Gestoría]").count() == 0
        page.wait_for_function(
            "() => !!Alpine.$data(document.querySelector('main')).calc.result", timeout=8000
        )
        gross = page.evaluate(
            "() => Alpine.$data(document.querySelector('main')).calc.result.figures"
        )
        assert gross["irpf"] == 0 and gross["reta_annual"] == 0
        assert gross["net"] == pytest.approx(
            gross["gross"] - gross["expenses"] - gross["set_aside"], abs=0.01
        )
    finally:
        put_config(country="ES")


def test_germany_shows_one_tax_input_in_settings(make_page, put_config):
    put_config(country="DE")
    page = make_page("settings")
    page.locator(".settings-group-btn", has_text="Freelance").click()
    page.wait_for_selector("#tax-aside", timeout=5000)
    assert (
        page.locator("#tax-salary, #tax-plana, #tax-startup, #tax-gestoria, #tax-other").count()
        == 0
    )
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('main')).taxForm?.set_aside_pct === 30",
        timeout=5000,
    )


def test_spain_keeps_its_rail_and_its_inputs(make_page):
    page = make_page("freelance")
    page.wait_for_selector("[data-testid=fl-quarters]", timeout=8000)
    assert page.locator("[data-testid=fl-quarters] .fl-q").count() == 4
    assert "Modelo 130" in page.locator("section[aria-label=Freelance]").inner_text()
    assert page.locator("[data-testid=fl-calc] input[aria-label=Gestoría]").is_visible()


def test_the_holidays_card_starts_on_the_country(make_page, put_config):
    put_config(country="DE")
    page = make_page("settings")
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('main')).settingsForm.holiday_country === 'DE'",
        timeout=8000,
    )
    # Spain keeps asking: the button needs a country
    put_config(country="ES")
    page = make_page("settings")
    page.wait_for_selector("#settings-holidays .settings-card-head button", timeout=5000)
    assert (
        page.locator("#settings-holidays .settings-card-head button").get_attribute("title")
        == "Pick a country first"
    )


# ── the suggestion from the browser's language ─────────────────────────────────────────────


def _hint(page):
    page.locator(".settings-group-btn", has_text="General").click()
    page.wait_for_selector("#settings-locale", timeout=5000)
    page.wait_for_timeout(500)
    return page.locator("[data-testid=locale-hint]")


def test_a_german_browser_on_a_new_database_is_offered_germany_once(browser, fresh_url, make_page):
    page = make_page("settings", url=fresh_url, locale="de-DE", hint=True)
    hint = _hint(page)
    hint.wait_for(timeout=5000)
    assert (
        hint.locator("p").inner_text()
        == "Looks like you're in Germany. Use Germany's holidays and formats?"
    )
    assert (
        httpx.get(f"{fresh_url}/api/config").json()["country"] == "ES"
    )  # nothing changed by itself
    hint.get_by_role("button", name="Not now").click()
    assert hint.count() == 0
    page.reload()
    assert _hint(page).count() == 0  # once


def test_accepting_the_suggestion_sets_the_country_and_the_format(browser, fresh_url, make_page):
    page = make_page("settings", url=fresh_url, locale="de-DE", hint=True)
    hint = _hint(page)
    hint.wait_for(timeout=5000)
    hint.get_by_role("button", name="Use them").click()
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('main'))._settingsSaved.country === 'DE'",
        timeout=5000,
    )
    cfg = httpx.get(f"{fresh_url}/api/config").json()
    assert (cfg["country"], cfg["number_format"], cfg["new_database"]) == ("DE", "es-ES", False)


@pytest.mark.parametrize("locale", ["en-US", "es-ES"])
def test_an_english_or_spanish_browser_is_never_offered_anything(
    browser, fresh_url, make_page, locale
):
    page = make_page("settings", url=fresh_url, locale=locale, hint=True)
    assert _hint(page).count() == 0


def test_a_database_with_days_is_never_offered_a_country(make_page):
    page = make_page("settings", locale="de-DE", hint=True)  # the demo server has a year of days
    assert _hint(page).count() == 0


# ── the printed sheet and the look ──────────────────────────────────────────────────────────


def test_the_printed_timesheet_follows_the_format(make_page, put_config, demo_url):
    en = httpx.get(f"{demo_url}/timesheet?from=2026-11-02&to=2026-11-06&today=2026-11-06").text
    put_config(number_format="es-ES")
    es = httpx.get(f"{demo_url}/timesheet?from=2026-11-02&to=2026-11-06&today=2026-11-06").text
    assert re.search(r">\d+\.\d{2}<", en) and not re.search(r">\d+,\d{2}<", en)
    assert re.search(r">\d+,\d{2}<", es) and not re.search(r">\d+\.\d{2}<", es)


# ── the look: the new card and the simple module at both widths ─────────────────────────────


@pytest.mark.parametrize("width", [1280, 375])
def test_the_country_card_and_the_simple_module_fit_at_both_widths(make_page, put_config, width):
    put_config(country="DE")
    page = make_page("settings", size=(width, 812))
    page.evaluate("() => Alpine.$data(document.querySelector('main')).setSettingsGroup('general')")
    page.wait_for_selector("#settings-locale", timeout=5000)
    page.wait_for_timeout(300)
    got = page.evaluate(
        """() => {
          const card = document.querySelector('#settings-locale').getBoundingClientRect();
          const boxes = [...document.querySelectorAll('#settings-locale select')].map(s => s.getBoundingClientRect());
          const links = [...document.querySelectorAll('.settings-group-sections a')].filter(a => a.offsetParent)
            .map(a => a.getBoundingClientRect().height / parseFloat(getComputedStyle(a).lineHeight));
          return { sideways: document.scrollingElement.scrollWidth - innerWidth, inside: boxes.every(b => b.left >= card.left && b.right <= card.right + 0.5),
                   lines: Math.max(0, ...links), selects: boxes.length };
        }"""
    )
    assert got["selects"] == 2 and got["inside"], got
    assert got["sideways"] <= 0, got
    assert got["lines"] <= 1.6, got  # a section name of the index is one line
    page = make_page("freelance", size=(width, 812))
    page.wait_for_selector("[data-testid=fl-aside]", timeout=8000)
    got = page.evaluate(
        """() => ({ sideways: document.scrollingElement.scrollWidth - innerWidth,
          clipped: [...document.querySelectorAll('.fl-tile, .calc-field input')].filter(e => e.scrollWidth > e.clientWidth + 1).length,
          tiles: document.querySelectorAll('.fl-tiles--simple .fl-tile').length })"""
    )
    assert got["sideways"] <= 0 and got["clipped"] == 0 and got["tiles"] == 6, got


def test_the_country_picker_works_offline_from_the_static_list(make_page, put_config):
    put_config(country="DE")
    page = make_page("settings", size=(1280, 900))
    # Nager.Date does not answer: the picker still has every country it covers, by name
    page.route("**/api/holidays/countries", lambda route: route.abort())
    page.evaluate(
        "() => { const d = Alpine.$data(document.querySelector('main')); d.holidayCountries = []; d.setSettingsGroup('general'); }"
    )
    page.wait_for_selector("#set-home-country", timeout=5000)
    page.wait_for_function(
        "() => document.querySelectorAll('#set-home-country option').length > 50", timeout=5000
    )
    options = page.locator("#set-home-country option").all_inner_texts()
    assert "Germany" in options and "Spain" in options and "United States" in options
    assert (
        page.locator("#set-home-country").evaluate("s => s.selectedOptions[0].textContent")
        == "Germany"
    )
