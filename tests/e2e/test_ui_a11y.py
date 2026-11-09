"""E2E: an axe accessibility scan of every tab, at desktop and phone width.

The scan runs against the demo server (same data and the same frozen "now" every day) and never
writes to it. Violations of impact serious or critical that exist today are recorded in
a11y_known.json. A new one fails the suite, and so does an entry that is no longer found (the
list only shrinks). Regenerate the list with
`KRONOS_A11Y_UPDATE=1 pytest tests/e2e/test_ui_a11y.py`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from axe_playwright_python.sync_playwright import Axe

from .conftest import DEMO_NOW, HASH_OF

pytestmark = pytest.mark.e2e

TABS = ["dashboard", "plan", "log", "days", "analytics", "freelance", "settings"]
VIEWPORTS = [(1280, 900), (375, 800)]
BLOCKING = {"serious", "critical"}
KNOWN_FILE = Path(__file__).with_name("a11y_known.json")
UPDATE = os.environ.get("KRONOS_A11Y_UPDATE") == "1"
# Attribute values are copy or amounts ([title="..."], [aria-label="..."]): they must not churn.
ATTR_VALUE = re.compile(r'\[[\w@:.\\-]+="[^"]*"\]')


@pytest.fixture
def demo_page(browser, demo_url):
    def make(width: int, height: int):
        context = browser.new_context(
            viewport={"width": width, "height": height},
            locale="en-GB",
            timezone_id="Europe/Madrid",
            color_scheme="dark",
            reduced_motion="reduce",
        )
        context.add_init_script("localStorage.setItem('k-milestone-seen', '100000')")
        contexts.append(context)
        page = context.new_page()
        page.clock.set_fixed_time(DEMO_NOW)
        return page

    contexts: list = []
    yield make
    for context in contexts:
        context.close()


def _known() -> dict[str, list[str]]:
    return json.loads(KNOWN_FILE.read_text(encoding="utf-8"))


def _scan(page) -> list[dict]:
    return Axe().run(page).response["violations"]


def _blocking(violations: list[dict]) -> list[str]:
    found = set()
    for v in violations:
        if v.get("impact") in BLOCKING:
            for node in v["nodes"]:
                target = ATTR_VALUE.sub("", " ".join(str(t) for t in node["target"]))
                found.add(f"{v['id']} {target}")
    return sorted(found)


def _open(page, demo_url, tab):
    page.goto(f"{demo_url}/#{HASH_OF.get(tab, tab)}", wait_until="networkidle")
    page.wait_for_selector("main .page-head", timeout=5000)
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(300)  # let the entry animations settle before measuring contrast


@pytest.mark.parametrize("width,height", VIEWPORTS)
@pytest.mark.parametrize("tab", TABS)
def test_no_new_accessibility_violations(demo_page, demo_url, tab, width, height):
    page = demo_page(width, height)
    _open(page, demo_url, tab)
    if tab == "days":
        # the week lines are always there; open them all so the scan still covers the day rows
        page.get_by_test_id("wk-expand-all").click()
        page.wait_for_selector("tr.day-row", timeout=5000)
        page.wait_for_timeout(300)
    key = f"{tab}@{width}"
    found = _blocking(_scan(page))
    if UPDATE:
        data = _known() if KNOWN_FILE.exists() else {}
        if found:
            data[key] = found
        else:
            data.pop(key, None)
        text = json.dumps(dict(sorted(data.items())), indent=2, ensure_ascii=False) + "\n"
        KNOWN_FILE.write_text(text, encoding="utf-8", newline="\n")
        return
    allowed = set(_known().get(key, []))
    new = sorted(set(found) - allowed)
    stale = sorted(allowed - set(found))
    assert not new, f"{key}: new serious or critical violations: {new}"
    assert not stale, (
        f"{key}: entries in a11y_known.json that axe no longer finds, delete them: {stale}"
    )


def test_the_scan_can_fail(demo_page, demo_url):
    """A positive control: an unlabelled button must be reported, so the scan cannot pass empty."""
    page = demo_page(1280, 900)
    _open(page, demo_url, "dashboard")
    page.evaluate(
        """() => {
          const b = document.createElement('button');
          b.id = 'planted-unlabelled';
          document.querySelector('main').prepend(b);
        }"""
    )
    violations = _scan(page)
    ids = {
        v["id"]
        for v in violations
        if any("planted-unlabelled" in str(n["target"]) for n in v["nodes"])
    }
    assert "button-name" in ids, ids


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_the_open_year_dial_has_no_serious_violations(demo_page, demo_url, width, height):
    """The dial open over the Dashboard, scanned on its own (the page behind it has its own
    entries in the list). It has no entry of its own: it must have no serious violation at all."""
    page = demo_page(width, height)
    _open(page, demo_url, "dashboard")
    page.locator(".brand-btn").click()
    page.wait_for_selector("#yd [data-yd=stage][data-day]:not([data-day=''])", timeout=5000)
    page.wait_for_timeout(300)
    violations = Axe().run(page, context="#yd").response["violations"]
    assert _blocking(violations) == []
    # the control: the scan did look at the dial, and an unlabelled button in it would be found
    page.evaluate(
        """() => {
          const b = document.createElement('button');
          b.id = 'planted-unlabelled';
          document.querySelector('#yd .yd-bar').append(b);
        }"""
    )
    found = Axe().run(page, context="#yd").response["violations"]
    assert "button-name" in {v["id"] for v in found}
