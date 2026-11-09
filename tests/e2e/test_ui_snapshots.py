"""E2E: the key screens, compared pixel by pixel with an approved picture.

The other UI tests check rules; this one notices what nobody wrote a rule for. Every screen is
drawn from the demo data on a frozen day, so the only thing that can move it is a change to the
code. Baselines are made in the CI image, because text renders differently on Windows: run
`make snapshots` to compare and `make snapshots-update` to approve a change, then look at the new
pictures in the diff before committing them.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from .conftest import DEMO_NOW, HASH_OF

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        sys.platform != "linux", reason="baselines are Linux pictures: run `make snapshots`"
    ),
]

DESKTOP = (1280, 800)
PHONE = (375, 800)
SCREENS = [
    ("dashboard", DESKTOP),
    ("plan", DESKTOP),
    ("log", DESKTOP),
    ("days", DESKTOP),
    ("analytics", DESKTOP),
    ("freelance", DESKTOP),
    ("settings", DESKTOP),
    ("dashboard", PHONE),
    ("days", PHONE),
    ("log", PHONE),
    ("analytics", PHONE),
]
# Days runs to thousands of pixels of the same rows: the first screen says enough.
FIRST_SCREEN_ONLY = {"days"}


@pytest.mark.parametrize("tab,size", SCREENS, ids=[f"{tab}-{size[0]}" for tab, size in SCREENS])
def test_screen_matches_its_baseline(browser, demo_url, assert_snapshot, tab, size):
    context = browser.new_context(
        viewport={"width": size[0], "height": size[1]},
        locale="en-GB",
        timezone_id="Europe/Madrid",
        color_scheme="dark",
        reduced_motion="reduce",  # no half-finished transition in a picture
    )
    # the milestone toast belongs to a first visit
    context.add_init_script("localStorage.setItem('k-milestone-seen', '100000')")
    page = context.new_page()
    page.clock.set_fixed_time(DEMO_NOW)
    try:
        page.goto(f"{demo_url}/#{HASH_OF.get(tab, tab)}", wait_until="networkidle")
        page.wait_for_selector("main .page-head", timeout=5000)
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(800)  # the charts settle
        picture = page.screenshot(
            full_page=tab not in FIRST_SCREEN_ONLY,
            animations="disabled",
            # the version moves with every phase, and it says nothing about the layout
            mask=[page.locator(".brand-ver")],
            mask_color="#17140f",
        )
        assert_snapshot(picture, name=f"{tab}-{size[0]}.png")
    finally:
        context.close()


def test_the_baselines_are_all_there():
    """A guard for the guard: a screen with no picture would be created, not compared."""
    folder = Path(__file__).parent / "__snapshots__"
    pictures = {p.name for p in folder.rglob("*.png")}
    assert pictures == {f"{tab}-{size[0]}.png" for tab, size in SCREENS}
