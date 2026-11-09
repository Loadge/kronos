"""E2E: the year line on the Plan page, and the compact row of figure cards under it.

Every number is read from the demo server on its frozen day (2026-11-04), with five drafts made
for the test (three vacation days, a flex day and a holiday). The line is drawn in pixels over the
measured columns of the twelve minis, so these tests compare boxes: a month of the line sits over
the mini of that month, to within 4px.
"""

# ruff: noqa: E501
# (the long lines are the JavaScript that runs in the page: one read of the page per call)

from __future__ import annotations

import re

import httpx
import pytest

from .conftest import DEMO_NOW, HASH_OF

pytestmark = pytest.mark.e2e

DESKTOP = (1280, 900)
PHONE = (375, 800)
SMALL_PHONE = (320, 640)

# Where the calendar's top sat on this page at 1280 x 900 (the demo data, the same frozen day) before
# the cards became a row and the year line moved into the strip: 753.9px from the top of the page.
OLD_CALENDAR_TOP = 754
DRAFTS = [
    (["2026-11-23", "2026-11-24", "2026-11-25"], "vacation"),
    (["2026-11-27"], "flex"),
    (["2026-12-24"], "holiday"),
]

# The line's geometry, read from the page: the solid path's points in page coordinates, and the
# boxes of the minis.
GEOMETRY = r"""
() => {
  const box = document.querySelector('.plan-line').getBoundingClientRect();
  const d = document.querySelector('.pl-real').getAttribute('d') || '';
  const nums = d.match(/-?\d+\.?\d*/g).map(Number);
  const points = [];
  for (let i = 0; i < nums.length; i += 2) points.push([box.left + nums[i], box.top + nums[i + 1]]);
  const minis = [...document.querySelectorAll('.plan-year-card .plan-mini')].map(m => {
    const r = m.getBoundingClientRect();
    return [r.left, r.right];
  });
  const end = document.querySelector('[data-testid=plan-line-end]').getBoundingClientRect();
  return { points, minis, endX: end.left + end.width / 2, box: [box.left, box.top, box.width, box.height] };
}
"""


def _data(page, expr: str):
    return page.evaluate(
        f"() => {{ const d = Alpine.$data(document.querySelector('main')); {expr} }}"
    )


@pytest.fixture
def drafted(demo_url):
    """Drafts on the demo server for the length of one test, and none after it."""
    dates = []
    with httpx.Client(base_url=demo_url) as c:
        for days, kind in DRAFTS:
            assert c.post("/api/plans", json={"dates": days, "day_type": kind}).status_code == 200
            dates += days
    yield dates
    with httpx.Client(base_url=demo_url) as c:
        for day in dates:
            c.delete(f"/api/plans/{day}")


@pytest.fixture
def make_page(browser, demo_url, drafted):
    contexts: list = []

    def make(size=DESKTOP, reduced=True, tab="plan"):
        context = browser.new_context(
            viewport={"width": size[0], "height": size[1]},
            locale="en-GB",
            timezone_id="Europe/Madrid",
            color_scheme="dark",
            reduced_motion="reduce" if reduced else "no-preference",
        )
        context.add_init_script("localStorage.setItem('k-milestone-seen', '100000')")
        contexts.append(context)
        page = context.new_page()
        page.clock.set_fixed_time(DEMO_NOW)
        page.goto(f"{demo_url}/#{HASH_OF.get(tab, tab)}", wait_until="networkidle")
        page.wait_for_selector("main .page-head", timeout=5000)
        if tab == "plan":
            page.wait_for_selector("[data-testid=plan-line-today]", timeout=5000)
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(300)
        return page

    yield make
    for context in contexts:
        context.close()


def _card_figure(page) -> str:
    return page.locator(".plan-stat").first.locator(".metric").inner_text().strip()


def _end_label(page) -> str:
    return page.locator("[data-testid=plan-line-end-label]").inner_text().strip()


def test_each_month_of_the_line_sits_over_its_mini(make_page):
    page = make_page()
    g = page.evaluate(GEOMETRY)
    assert len(g["minis"]) == 12
    # day 152 of 2026 is Jun 1; Jan 1 and the last real point (Nov 4, day 308) too
    assert abs(g["points"][151][0] - g["minis"][5][0]) <= 4, (g["points"][151], g["minis"][5])
    assert abs(g["points"][0][0] - g["minis"][0][0]) <= 4
    assert (
        abs(
            g["points"][307][0]
            - (g["minis"][10][0] + (g["minis"][10][1] - g["minis"][10][0]) * 3 / 29)
        )
        <= 4
    )
    # Dec 31 is the right edge of the December mini
    assert abs(g["endX"] - g["minis"][11][1]) <= 4, (g["endX"], g["minis"][11])
    # one real point per day from Jan 1 to today, no more
    assert len(g["points"]) == 308


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["1280", "375"])
def test_the_dec_31_label_never_covers_today(make_page, size):
    page = make_page(size)
    for mode in ("On target", "At my pace"):
        page.get_by_role("radio", name=mode).click()
        page.wait_for_timeout(100)
        label, pip, line = page.evaluate(
            "() => ['[data-testid=plan-line-end-label]', '[data-testid=plan-line-today]', '.plan-year-card']"
            ".map(s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; })"
        )
        apart = label[2] <= pip[0] or pip[2] <= label[0] or label[3] <= pip[1] or pip[3] <= label[1]
        assert apart, (mode, label, pip)
        assert line[1] - 2 <= label[1] and label[3] <= line[3] + 2, (mode, label, line)


def test_the_today_pip_reads_the_dashboard_balance(make_page):
    page = make_page()
    pip = page.locator("[data-testid=plan-line-today]").get_attribute("data-value")
    assert re.fullmatch(r"[+−±]\d+\.\d\dh", pip), pip
    page.goto(page.url.replace("#plan", "#dashboard"))
    page.wait_for_selector(".hero-num .odo", timeout=5000)
    page.wait_for_function(
        "t => document.querySelector('.hero-num').innerText.trim() === t", arg=pip, timeout=5000
    )
    assert page.locator(".hero-num").inner_text().strip() == pip


def test_the_dec_31_label_is_the_balance_card_figure_in_both_modes(make_page):
    page = make_page()
    first = _end_label(page)
    assert first == _card_figure(page)
    page.get_by_role("radio", name="At my pace").click()
    page.wait_for_function(
        "t => document.querySelector('[data-testid=plan-line-end-label]').innerText.trim() !== t",
        arg=first,
        timeout=3000,
    )
    second = _end_label(page)
    assert second == _card_figure(page)
    assert second != first  # the toggle moved the figure, so equal labels are not a coincidence
    page.get_by_role("radio", name="On target").click()
    page.wait_for_function(
        "t => document.querySelector('[data-testid=plan-line-end-label]').innerText.trim() === t",
        arg=first,
        timeout=3000,
    )


def test_the_toggle_moves_the_dashed_tail_and_its_end_dot(make_page):
    page = make_page()
    read = """() => {
      const top = el => el.getBoundingClientRect().top + el.getBoundingClientRect().height / 2;
      const end = document.querySelector('[data-testid=plan-line-end]');
      const chosen = document.querySelector('.pl-tail.is-chosen');
      const box = document.querySelector('.plan-line').getBoundingClientRect();
      const lastY = box.top + Number(chosen.getAttribute('d').match(/-?\\d+\\.?\\d*/g).pop());
      return { mode: chosen.dataset.mode, dot: top(end), tailEnd: lastY,
               faint: document.querySelectorAll('.pl-tail:not(.is-chosen)').length };
    }"""
    a = page.evaluate(read)
    assert a["mode"] == "on_target" and a["faint"] == 1
    assert abs(a["dot"] - a["tailEnd"]) <= 1.5, a
    page.get_by_role("radio", name="At my pace").click()
    page.wait_for_timeout(200)
    b = page.evaluate(read)
    assert b["mode"] == "at_pace" and abs(b["dot"] - b["tailEnd"]) <= 1.5, b
    assert abs(a["dot"] - b["dot"]) > 3, (a, b)  # the two assumptions end at different heights


def test_one_mark_per_drafted_day_in_the_colour_of_its_type(make_page, drafted):
    page = make_page()
    got = page.evaluate(
        """() => [...document.querySelectorAll('[data-testid=plan-line-mark]')].map(i => {
          const type = ['vacation', 'holiday', 'flex'].find(t => i.classList.contains(t));
          const probe = document.createElement('i');
          probe.style.color = `var(--k-${type})`;
          document.body.append(probe);
          const want = getComputedStyle(probe).color;
          probe.remove();
          return [i.title, getComputedStyle(i).backgroundColor, want];
        })"""
    )
    assert [t.split(" · ")[0] for t, _, _ in got] == drafted, got
    assert len(got) == 5 and all(bg == want for _, bg, want in got), got


def test_the_aria_label_says_the_start_today_and_dec_31(make_page):
    page = make_page()
    line = page.locator("[data-testid=plan-line]")
    assert line.get_attribute("role") == "img"
    label = line.get_attribute("aria-label")
    m = re.fullmatch(
        r"Balance 2026: starts at ([+−±]\d+\.\d\dh), ([+−±]\d+\.\d\dh) today, ([+−±]\d+\.\d\dh) on Dec 31 on target",
        label,
    )
    assert m, label
    start = _data(page, "return d.formatSurplus(d.dialBalanceAt('2026-01-01'));")
    assert m[1] == start
    assert m[2] == page.locator("[data-testid=plan-line-today]").get_attribute("data-value")
    assert m[3] == _card_figure(page)
    # and in the other mode the label names it and carries that figure
    page.get_by_role("radio", name="At my pace").click()
    page.wait_for_function(
        "() => document.querySelector('[data-testid=plan-line]').getAttribute('aria-label').endsWith('at my pace')",
        timeout=3000,
    )
    assert _card_figure(page) in line.get_attribute("aria-label")


def test_hovering_the_line_shows_the_date_and_the_balance(make_page):
    page = make_page()
    g = page.evaluate(GEOMETRY)
    x = g["points"][273][0]  # Oct 1
    page.mouse.move(x, g["box"][1] + 20)
    tip = page.locator(".pl-tip")
    tip.wait_for(state="visible", timeout=3000)
    want = _data(page, "return d.formatSurplus(d.dialBalanceAt('2026-10-01'));")
    text = tip.inner_text()
    assert "Oct 1, 2026" in text and want in text, text
    # Dec 31 is after today: it reads "projected" with the chosen assumption
    page.mouse.move(g["endX"] - 1, g["box"][1] + 20)
    page.wait_for_function(
        "() => document.querySelector('.pl-tip').innerText.includes('projected')", timeout=3000
    )
    page.mouse.move(5, 5)
    tip.wait_for(state="hidden", timeout=3000)


def test_the_figure_cards_are_a_compact_row(make_page):
    page = make_page()
    cards = page.evaluate(
        """() => [...document.querySelectorAll('.plan-stat')].map(c => {
          const r = c.getBoundingClientRect();
          const bottoms = [...c.children].map(k => k.getBoundingClientRect().bottom);
          return { top: Math.round(r.top), left: Math.round(r.left), width: Math.round(r.width),
                   height: r.height, spare: r.bottom - Math.max(...bottoms) };
        })"""
    )
    assert len(cards) == 3
    assert all(c["height"] <= 170 for c in cards), cards
    assert max(c["top"] for c in cards) - min(c["top"] for c in cards) <= 1, cards
    assert (
        cards[0]["width"] > cards[1]["width"] * 1.4
        and abs(cards[1]["width"] - cards[2]["width"]) <= 1
    ), cards
    # nothing inside a card is a block of empty space: what is left under the last child is its padding
    assert all(c["spare"] <= 24 for c in cards), cards
    # the balance caption sits to the right of the figure, in the same card
    pos = page.evaluate(
        """() => {
          const c = document.querySelector('.plan-stat');
          const m = c.querySelector('.metric').getBoundingClientRect();
          const s = c.querySelector('.sub').getBoundingClientRect();
          return { metricRight: m.right, subLeft: s.left, metricTop: m.top, subBottom: s.bottom };
        }"""
    )
    assert pos["subLeft"] >= pos["metricRight"], pos
    # the pips fill the space to the right of the figure on the two other cards
    for sel in ("vacation", "drafted"):
        box = page.evaluate(
            f"""() => {{
              const el = document.querySelector('[data-testid=plan-pips-{sel}]');
              const p = el.getBoundingClientRect();
              const m = el.parentElement.querySelector('.metric').getBoundingClientRect();
              return {{ pipsLeft: p.left, metricRight: m.right, pipsWidth: p.width }};
            }}"""
        )
        assert box["pipsLeft"] >= box["metricRight"] and box["pipsWidth"] > 100, (sel, box)


def test_the_calendar_comes_up_the_page(make_page):
    page = make_page()
    top = page.evaluate(
        "() => document.querySelector('.plan-cal').getBoundingClientRect().top + scrollY"
    )
    assert top <= OLD_CALENDAR_TOP - 200, (top, OLD_CALENDAR_TOP)
    ledger = page.evaluate(
        "() => document.querySelector('.plan-ledger').getBoundingClientRect().top + scrollY"
    )
    assert abs(ledger - top) <= 1  # the calendar | ledger layout below is as it was


@pytest.mark.parametrize(
    "size",
    [DESKTOP, (1440, 900), (768, 1024), PHONE, SMALL_PHONE],
    ids=["1280", "1440", "768", "375", "320"],
)
def test_no_sideways_scroll_and_every_card_is_no_taller_than_its_content(make_page, size):
    page = make_page(size)
    wide = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert wide <= 0, wide
    cards = page.evaluate(
        """() => [...document.querySelectorAll('.plan-stat')].map(c => {
          const r = c.getBoundingClientRect();
          const bottoms = [...c.children].map(k => k.getBoundingClientRect().bottom);
          return { height: r.height, spare: r.bottom - Math.max(...bottoms), width: r.width };
        })"""
    )
    # a card holds nothing but its content and its padding, at every width
    assert all(c["spare"] <= 24 for c in cards), cards
    if size[0] >= 1024:
        assert all(c["height"] <= 170 for c in cards), cards
    line = page.evaluate(
        """() => {
          const l = document.querySelector('.plan-line').getBoundingClientRect();
          const i = document.querySelector('.pl-initials');
          return { width: l.width, height: l.height, left: l.left, right: l.right,
                   initials: i && getComputedStyle(i).display !== 'none' ? i.innerText.replace(/\\s+/g, '') : '' };
        }"""
    )
    assert line["left"] >= 0 and line["right"] <= size[0], line
    assert 60 <= line["height"] <= 100, line
    if size[0] <= 900:
        assert line["initials"] == "JFMAMJJASOND", (
            line
        )  # no alignment on a phone or a tablet: the initials say which month
    else:
        assert line["initials"] == ""


def test_a_phone_draws_the_line_full_width_under_the_strip(make_page):
    page = make_page(PHONE)
    g = page.evaluate(GEOMETRY)
    box = g["box"]
    strip = page.evaluate(
        "() => { const r = document.querySelector('.plan-year-card .plan-strip').getBoundingClientRect(); return [r.left, r.right, r.bottom]; }"
    )
    assert abs(box[0] - strip[0]) <= 1 and abs(box[0] + box[2] - strip[1]) <= 1, (box, strip)
    assert box[1] >= strip[2] - 1, (box, strip)  # under the minis, not beside them
    # the twelve months take twelve equal slots: Jun 1 is five twelfths across
    assert abs((g["points"][151][0] - box[0]) - box[2] * 5 / 12) <= 3, g["points"][151]


def test_a_future_year_shows_only_the_projection(make_page):
    page = make_page()
    page.get_by_role("button", name="Next year").click()
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('main')).projection?.year === 2027", timeout=5000
    )
    page.wait_for_function(
        "() => document.querySelector('.pl-tail.is-chosen')?.getAttribute('d')", timeout=3000
    )
    state = page.evaluate(
        """() => ({
          real: document.querySelector('.pl-real').getAttribute('d'),
          today: !!document.querySelector('[data-testid=plan-line-today]'),
          tails: [...document.querySelectorAll('.pl-tail')].map(t => !!t.getAttribute('d')),
          label: document.querySelector('[data-testid=plan-line]').getAttribute('aria-label'),
        })"""
    )
    assert state["real"] is None and state["today"] is False and state["tails"] == [True, True], (
        state
    )
    assert (
        state["label"].startswith("Balance 2027: starts at ") and "today" not in state["label"]
    ), state
    assert _end_label(page) == _card_figure(page)


def test_a_past_year_shows_its_real_line_only(make_page):
    page = make_page()
    page.get_by_role("button", name="Previous year").click()
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('main')).projection?.year === 2025", timeout=5000
    )
    page.wait_for_function(
        "() => document.querySelector('.plan-line').getAttribute('aria-label')?.startsWith('Balance 2025')",
        timeout=3000,
    )
    state = page.evaluate(
        """() => ({
          points: document.querySelector('.pl-real').getAttribute('d').split('L').length,
          today: !!document.querySelector('[data-testid=plan-line-today]'),
          tailsShown: getComputedStyle(document.querySelector('.pl-tails')).display !== 'none',
          label: document.querySelector('[data-testid=plan-line]').getAttribute('aria-label'),
          marks: document.querySelectorAll('[data-testid=plan-line-mark]').length,
        })"""
    )
    assert state["points"] == 365 and state["today"] is False and state["tailsShown"] is False, (
        state
    )
    assert re.fullmatch(
        r"Balance 2025: starts at [+−±]\d+\.\d\dh, ends at [+−±]\d+\.\d\dh on Dec 31",
        state["label"],
    ), state
    assert state["marks"] == 0, state
    assert _end_label(page) == _data(page, "return d.formatSurplus(d.dialBalanceAt('2025-12-31'));")


def test_the_line_draws_itself_once_and_stands_still_when_motion_is_reduced(make_page):
    still = make_page()
    got = still.evaluate(
        "() => { const c = getComputedStyle(document.querySelector('.pl-real')); return [c.animationName, getComputedStyle(document.querySelector('.pl-tails')).animationName]; }"
    )
    assert got == ["none", "none"], got
    moving = make_page(reduced=False)
    got = moving.evaluate(
        """() => { const c = getComputedStyle(document.querySelector('.pl-real'));
                  const t = getComputedStyle(document.querySelector('.pl-tails'));
                  return [c.animationName, c.animationDuration, c.animationIterationCount, t.animationName, t.animationDelay]; }"""
    )
    assert got == ["pl-draw", "0.6s", "1", "pl-fade", "0.5s"], got
