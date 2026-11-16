"""The suite's own waiting helpers (conftest.py): each of them can fail.

A helper that never raises would turn every wait that uses it into a pass, so these tests are the
control of all the others: a state that never comes raises with its name, a page that never stops
moving raises with what moves, and the three fixed times take at least what they were asked.
"""

from __future__ import annotations

import time

import pytest

from .conftest import hold, pace, settled, stays, wait_until

PAGE = """<!doctype html><meta charset="utf-8">
<style>
  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes once { to { transform: translateX(40px); } }
  #box { width: 20px; height: 20px; background: #333; }
  #box.once { animation: once 300ms linear forwards; }
  #box.forever { animation: spin 1s linear infinite; }
  #box.slide { transition: margin-left 300ms linear; margin-left: 60px; }
</style>
<main><div id="box"></div></main><aside><i id="other"></i></aside>"""


@pytest.fixture
def blank(page):
    page.set_content(PAGE)
    return page


def _running(page) -> int:
    return page.evaluate(
        "() => document.getAnimations().filter(a => a.playState === 'running').length"
    )


# ── wait_until ────────────────────────────────────────────────────────────────


def test_wait_until_returns_what_the_predicate_gave(blank):
    seen = []
    assert wait_until(blank, lambda: seen.append(1) or len(seen) >= 3 and "there", "three") == (
        "there"
    )
    assert len(seen) == 3


def test_wait_until_raises_with_its_what_when_the_state_never_comes(blank):
    began = time.monotonic()
    with pytest.raises(AssertionError, match="the answer that never arrives"):
        wait_until(blank, lambda: False, "the answer that never arrives", timeout=0.4)
    assert 0.4 <= time.monotonic() - began < 3


def test_wait_until_lets_the_events_of_the_page_reach_the_test(blank):
    said = []
    blank.on("console", lambda m: said.append(m.text))
    blank.evaluate("() => { setTimeout(() => console.log('late'), 200); }")
    assert said == []
    wait_until(blank, lambda: "late" in said, "the page's console line")


# ── settled ───────────────────────────────────────────────────────────────────


def test_settled_returns_on_a_page_where_nothing_moves(blank):
    settled(blank)
    settled(blank, "main")


def test_settled_waits_for_an_animation_to_end(blank):
    blank.evaluate("() => document.getElementById('box').classList.add('once')")
    blank.wait_for_function("() => document.getAnimations().length === 1")
    assert _running(blank) == 1
    settled(blank)
    assert _running(blank) == 0
    assert blank.evaluate("() => getComputedStyle(box).transform") == "matrix(1, 0, 0, 1, 40, 0)"


def test_settled_waits_for_a_transition_to_end(blank):
    blank.evaluate("() => document.getElementById('box').classList.add('slide')")
    blank.wait_for_function("() => document.getAnimations().length === 1")
    settled(blank, "main")
    assert blank.evaluate("() => getComputedStyle(box).marginLeft") == "60px"


def test_settled_raises_while_an_animation_that_never_ends_runs(blank):
    blank.evaluate("() => document.getElementById('box').classList.add('forever')")
    blank.wait_for_function("() => document.getAnimations().length === 1")
    with pytest.raises(AssertionError, match=r"main never settled in 0\.6s: spin on div\.forever"):
        settled(blank, "main", timeout=0.6)


def test_settled_only_looks_under_its_root(blank):
    blank.evaluate("() => document.getElementById('box').classList.add('forever')")
    blank.wait_for_function("() => document.getAnimations().length === 1")
    settled(blank, "aside")


def test_settled_raises_when_its_root_is_not_in_the_page(blank):
    with pytest.raises(AssertionError, match="no #nowhere in the page"):
        settled(blank, "#nowhere", timeout=0.3)


# ── the three fixed times ─────────────────────────────────────────────────────


@pytest.mark.parametrize("helper", [pace, hold])
def test_pace_and_hold_take_at_least_their_time(blank, helper):
    began = time.monotonic()
    helper(blank, 250)
    assert time.monotonic() - began >= 0.25


def test_stays_takes_at_least_its_time_and_wants_a_reason(blank):
    began = time.monotonic()
    stays(blank, 250, "nothing else is drawn")
    assert time.monotonic() - began >= 0.25
    with pytest.raises(AssertionError, match="say what must not happen"):
        stays(blank, 10, "")
