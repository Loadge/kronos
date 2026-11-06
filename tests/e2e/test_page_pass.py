"""E2E: the page pass: every page reaches the level of the best one.

One group of tests per decision of the pass, each with concrete numbers: computed colours, boxes
and contrasts, read from the demo server (same data and the same frozen day every time). A test
that reads short-lived state reads it in one `page.evaluate`, or waits for it, so a slow runner
cannot make it flaky.
"""

# ruff: noqa: E501
# (the long lines are the JavaScript that runs in the page: one read of the page per call)

from __future__ import annotations

import datetime
import re

import httpx
import pytest

from .conftest import DEMO_NOW

pytestmark = pytest.mark.e2e

TABS = ["dashboard", "plan", "log", "days", "analytics", "freelance", "settings"]
DESKTOP = (1280, 900)
PHONE = (375, 800)
BRASS = "rgb(224, 179, 65)"
TRANSPARENT = "rgba(0, 0, 0, 0)"


@pytest.fixture
def make_page(browser, demo_url):
    contexts: list = []

    def make(size=DESKTOP, tab="dashboard", reduced=True):
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
        page.goto(f"{demo_url}/#{tab}", wait_until="networkidle")
        page.wait_for_selector("main .page-head", timeout=5000)
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(400)
        return page

    yield make
    for context in contexts:
        context.close()


def _rgb(css: str) -> tuple[float, float, float]:
    """The red, green, blue of a computed colour, in 0-255, from `rgb(...)` or `color(srgb ...)`
    (what a colour-mix() computes to)."""
    m = re.match(r"rgba?\((\d+), (\d+), (\d+)", css)
    if m:
        return float(m[1]), float(m[2]), float(m[3])
    m = re.match(r"color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)", css)
    assert m, css
    return tuple(float(v) * 255 for v in m.groups())


def _data(page, expr: str):
    """Evaluate `expr` against the app's Alpine data (one evaluate, one consistent read)."""
    return page.evaluate(
        f"() => {{ const d = Alpine.$data(document.querySelector('main')); {expr} }}"
    )


# ── 1. Pico's blue-grey is gone ─────────────────────────────────────────────────────────────

# What Pico's dark theme paints with: its secondary, its link hover, its primary blue, its
# contrast greys and the navy of its form states. The palette has none of these RGB triples.
PICO_BLUES = [
    (150, 158, 175), (179, 185, 197), (121, 192, 255), (82, 95, 122), (93, 107, 137),
    (72, 83, 107), (1, 114, 173), (1, 170, 255), (1, 127, 192), (1, 88, 135), (144, 158, 190),
    (223, 227, 235), (207, 213, 226), (194, 199, 208), (164, 172, 186), (136, 145, 164),
    (51, 60, 78), (42, 49, 64), (26, 31, 40), (24, 28, 37), (32, 38, 50),
]  # fmt: skip

FIND_BLUES = """
(blues) => {
  const bad = new Set(blues.map(b => b.join(',')));
  const props = ['color', 'backgroundColor', 'borderTopColor', 'borderRightColor',
                 'borderBottomColor', 'borderLeftColor', 'outlineColor', 'textDecorationColor',
                 'caretColor', 'boxShadow'];
  const found = [];
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    for (const p of props) {
      // a colour-mix() computes to color(srgb 0.5 0.4 0.3): read both spellings
      const text = String(cs[p]);
      const triples = [...text.matchAll(/rgba?\\((\\d+), (\\d+), (\\d+)/g)].map(m => [m[1], m[2], m[3]]);
      for (const m of text.matchAll(/color\\(srgb ([\\d.]+) ([\\d.]+) ([\\d.]+)/g)) {
        triples.push([m[1], m[2], m[3]].map(v => String(Math.round(Number(v) * 255))));
      }
      for (const t of triples) {
        if (bad.has(t.join(','))) {
          found.push(`${el.tagName.toLowerCase()}.${String(el.className).split(' ')[0]} ${p} ${cs[p]}`);
        }
      }
    }
  }
  // Pico's own variables, resolved: nothing blue-grey may be left to a hover or a focus ring
  const probe = document.createElement('span');
  document.body.append(probe);
  const names = new Set();
  for (const sheet of document.styleSheets) {
    for (const rule of sheet.cssRules) {
      if (rule.style) for (const n of rule.style) if (n.startsWith('--pico-')) names.add(n);
    }
  }
  for (const n of names) {
    probe.style.color = '';
    probe.style.color = `var(${n})`;
    const text = getComputedStyle(probe).color;
    let m = text.match(/rgba?\\((\\d+), (\\d+), (\\d+)/);
    if (!m) {
      m = text.match(/color\\(srgb ([\\d.]+) ([\\d.]+) ([\\d.]+)/);
      if (m) m = [m[0], m[1] * 255, m[2] * 255, m[3] * 255];
    }
    if (!m) continue;
    const [r, g, b] = [+m[1], +m[2], +m[3]];
    if (b > r + 8 && b >= g - 4) found.push(`${n} ${getComputedStyle(probe).color}`);
  }
  probe.remove();
  return found;
}
"""


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["1280", "375"])
@pytest.mark.parametrize("tab", TABS)
def test_no_pico_blue_on_any_tab(make_page, tab, size):
    page = make_page(size, tab)
    if tab == "days":
        page.get_by_test_id("wk-expand-all").click()
        page.wait_for_selector("tr.day-row", timeout=5000)
    page.wait_for_timeout(300)
    assert page.evaluate(FIND_BLUES, [list(b) for b in PICO_BLUES]) == []


def test_the_blue_check_can_fail(make_page):
    """A positive control: a link painted with Pico's secondary must be reported."""
    page = make_page(DESKTOP, "plan")
    page.evaluate(
        """() => {
          const a = document.createElement('a');
          a.id = 'planted-blue';
          a.textContent = 'planted';
          a.style.color = '#969eaf';
          document.querySelector('main').prepend(a);
        }"""
    )
    found = page.evaluate(FIND_BLUES, [list(b) for b in PICO_BLUES])
    assert any(f.startswith("a.") and "color rgb(150, 158, 175)" in f for f in found), found


# The secondary buttons and the plain links the review named, by their computed colour
@pytest.mark.parametrize(
    "tab,selector",
    [
        ("log", "button.secondary.outline"),
        ("freelance", ".fl-ystrip a, .fl-awaiting a"),
        ("days", ".fbar a"),
    ],
)
def test_named_buttons_and_links_are_warm(make_page, tab, selector):
    page = make_page(DESKTOP, tab)
    if tab == "log":
        _data(page, "d.openDayInLog('2026-11-07');")
        page.wait_for_selector("button.secondary.outline", timeout=5000)
    if tab == "days":
        page.locator(".hm-switch button", has_text="Freelance").click()
        page.wait_for_selector(".fbar a", timeout=5000)
    colours = page.evaluate(
        """(sel) => [...document.querySelectorAll(sel)].map(el => {
             const cs = getComputedStyle(el);
             return [cs.color, cs.borderTopColor, cs.textDecorationColor];
           })""",
        selector,
    )
    assert colours, f"{selector} matched nothing on {tab}"
    for triple in colours:
        for c in triple:
            r, _, b = _rgb(c)
            assert r >= b, (selector, c)  # warm: red at least as strong as blue


# ── 2 and 3. Log: one filled primary, the freelance chip ─────────────────────────────────────

FILLED_BUTTONS = """
() => [...document.querySelectorAll('button.btn-action')]
  .filter(b => b.offsetParent !== null && getComputedStyle(b).backgroundColor !== 'rgba(0, 0, 0, 0)')
  .map(b => b.innerText.trim())
"""


def test_log_has_one_filled_primary_and_add_block_is_an_outline(make_page):
    page = make_page(DESKTOP, "log")
    _data(page, "d.openDayInLog('2026-11-07');")
    page.wait_for_selector("button.fl-submit", timeout=5000)
    assert page.evaluate(FILLED_BUTTONS) == ["Create entry"]
    add = page.locator("button.fl-submit")
    assert add.inner_text().strip() == "+ Add block"
    style = add.evaluate(
        "el => { const c = getComputedStyle(el); return [c.backgroundColor, c.borderTopColor, c.color]; }"
    )
    assert style == [TRANSPARENT, BRASS, BRASS]


def test_save_block_while_editing_stays_filled(make_page):
    page = make_page(DESKTOP, "log")
    _data(page, "d.openDayInLog('2026-11-07');")
    page.wait_for_selector("button.fl-submit", timeout=5000)
    # the form's own state, as the block editor sets it: an id means "editing this block"
    _data(page, "d.flForm.id = 1; d.flForm.source_id = d.flForm.source_id || 1;")
    page.wait_for_function(
        "() => document.querySelector('button.fl-submit')?.innerText.trim() === 'Save block'",
        timeout=3000,
    )
    filled = page.evaluate(
        "() => { const c = getComputedStyle(document.querySelector('button.fl-submit'));"
        " return [c.backgroundColor, c.color]; }"
    )
    assert filled[0] != TRANSPARENT and filled[1] != BRASS, filled


def test_the_head_chip_reads_add_freelance_in_sentence_case(make_page):
    page = make_page(DESKTOP, "log")
    _data(page, "d.openDayInLog('2026-11-07');")
    page.wait_for_function(
        "() => document.querySelector('.fl-jump')?.innerText.trim() === '⚡ Add freelance'",
        timeout=5000,
    )
    # and with blocks on the day it keeps the amount form: "⚡ 3h · €270"
    _data(page, "d.openDayInLog(d.blocks[0].date);")
    page.wait_for_function(
        "() => /^⚡ [\\d.]+h · [€$]/.test(document.querySelector('.fl-jump')?.innerText.trim() || '')",
        timeout=5000,
    )


# ── 4 and 5. Plan: three cards, one row, a drawing each; Commit; no hole ─────────────────────
# These run on the live server, which they may write to: the demo has no drafts.

CARDS = """
() => [...document.querySelectorAll('.plan-stat')].map(c => {
  const r = c.getBoundingClientRect();
  return { top: Math.round(r.top), left: Math.round(r.left), height: Math.round(r.height),
           width: Math.round(r.width), viz: !!c.querySelector('.plan-viz') };
})
"""


@pytest.fixture
def planned(page, base_url):
    """A Plan page with drafts of three types (one a half day) and a vacation budget."""
    today = datetime.date.today()
    monday = today + datetime.timedelta(days=7 - today.weekday())
    day = lambda n: (monday + datetime.timedelta(days=n)).isoformat()  # noqa: E731
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        c.put("/api/config", json={"daily_target_hours": 8, "vacation_budget_days": 20})
        for body in (
            {"dates": [day(0), day(1), day(2)], "day_type": "vacation", "notes": "long weekend"},
            {"dates": [day(7)], "day_type": "flex"},
            {"dates": [day(8)], "day_type": "holiday", "fraction": 0.5},
        ):
            assert c.post("/api/plans", json=body).status_code == 200
    page.goto(f"{base_url}/#plan")
    page.wait_for_selector(".plan-stat .plan-viz", timeout=5000)
    page.wait_for_selector("[data-testid=plan-pips-drafted] .pip", timeout=5000)
    yield page
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")


def test_plan_cards_are_one_row_of_equal_height_at_1280(planned):
    cards = planned.evaluate(CARDS)
    assert len(cards) == 3
    assert max(c["top"] for c in cards) - min(c["top"] for c in cards) <= 1, cards
    assert max(c["height"] for c in cards) - min(c["height"] for c in cards) <= 1, cards
    assert all(c["viz"] for c in cards)
    lefts = [c["left"] for c in cards]
    assert lefts == sorted(lefts) and len(set(lefts)) == 3, lefts


def test_plan_cards_stack_on_a_phone_and_keep_their_drawing(planned):
    planned.set_viewport_size({"width": 375, "height": 800})
    planned.wait_for_timeout(300)
    cards = planned.evaluate(CARDS)
    assert len(cards) == 3 and all(c["viz"] for c in cards)
    tops = [c["top"] for c in cards]
    assert tops == sorted(tops) and len(set(tops)) == 3, tops
    assert len({c["left"] for c in cards}) == 1


def test_plan_drawings_draw_the_figures_on_their_cards(planned):
    got = planned.evaluate(
        """() => {
          const d = Alpine.$data(document.querySelector('main'));
          const p = d.projection;
          const weight = sel => [...document.querySelectorAll(sel)]
            .reduce((s, i) => s + (i.classList.contains('half') ? 0.5 : 1), 0);
          const line = document.querySelector('.ps-line');
          return {
            drafted: p.drafted_days,
            draftedPips: weight('[data-testid=plan-pips-drafted] .pip'),
            vacUsed: p.vacation_used_days, vacDrafted: p.vacation_drafted_days,
            vacBudget: p.vacation_budget_days,
            vacPips: document.querySelectorAll('[data-testid=plan-pips-vacation] .pip').length,
            vacDraftPips: weight('[data-testid=plan-pips-vacation] .pip.draft'),
            path: line.getAttribute('d'),
            stroke: getComputedStyle(line).stroke,
            dots: document.querySelectorAll('.ps-dot').length,
          };
        }"""
    )
    assert got["drafted"] == 4.5 and got["draftedPips"] == got["drafted"], got
    assert got["vacBudget"] == 20 and got["vacPips"] == 20, got  # one pip per budget day
    assert got["vacDraftPips"] == got["vacDrafted"] == 3, got  # lit as drafted, not as used
    assert re.fullmatch(r"M[\d.]+ [\d.]+ L[\d.]+ [\d.]+", got["path"]), got
    assert got["stroke"] == BRASS and got["dots"] == 2, got


def test_drafted_pips_wear_the_colour_of_their_type(planned):
    got = planned.evaluate(
        """() => [...document.querySelectorAll('[data-testid=plan-pips-drafted] .pip')].map(i => {
          const type = ['vacation', 'holiday', 'flex'].find(t => i.classList.contains(t));
          const probe = document.createElement('i');
          probe.style.color = `var(--k-${type})`;
          document.body.append(probe);
          const want = getComputedStyle(probe).color;
          probe.remove();
          return [type, getComputedStyle(i).borderTopColor, want];
        })"""
    )
    assert [t for t, _, _ in got] == ["vacation"] * 3 + ["flex", "holiday"], got
    assert all(border == want for _, border, want in got), got


def test_plan_commit_is_a_brass_outline_and_the_hints_moved_to_titles(planned):
    style = planned.locator(".plan-commit").first.evaluate(
        "el => { const c = getComputedStyle(el); return [c.backgroundColor, c.borderTopColor, c.color]; }"
    )
    assert style == [TRANSPARENT, BRASS, BRASS]
    for sel in (".plan-tools .bulk-hint", ".plan-ledger-note"):
        el = planned.locator(sel)
        assert len(el.get_attribute("title")) > 60, sel
        assert el.evaluate("e => e.getBoundingClientRect().height") < 28, sel  # one short line


def test_plan_has_no_hole_beside_the_calendar(planned):
    cal, ledger = (
        planned.evaluate(
            f"() => {{ const r = document.querySelector('{s}').getBoundingClientRect();"
            " return { top: r.top, bottom: r.bottom, height: r.height }; }"
        )
        for s in (".plan-cal", ".plan-ledger")
    )
    # the calendar is no taller than the column beside it by more than a short list's worth
    assert cal["bottom"] - ledger["bottom"] <= 120, (cal, ledger)
    assert cal["height"] <= 470, cal


# ── 6. Dashboard: the band under the head is the gap every page has ──────────────────────────

BAND = """
(first) => {
  const head = document.querySelector('main .page-head').getBoundingClientRect();
  const el = document.querySelector(first);
  // the top of what is drawn: the chart's first line or the first block, not its blank margin
  const drawn = [...el.querySelectorAll('.traj-month, .hero-label')].map(l => l.getBoundingClientRect().top);
  const top = drawn.length ? Math.min(...drawn) : el.getBoundingClientRect().top;
  return top - head.bottom;
}
"""


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["1280", "375"])
def test_dashboard_band_matches_the_other_pages(make_page, size):
    page = make_page(size, "dashboard")
    page.wait_for_selector(".hero .traj-wrap svg", timeout=5000)
    dash = page.evaluate(BAND, ".hero")
    page.goto(page.url.replace("#dashboard", "#plan"))
    page.wait_for_selector(".plan-strip", timeout=5000)
    other = page.evaluate(BAND, ".plan-strip")
    assert dash <= other + 8, (dash, other)
    assert dash <= 30, dash


# ── 7. Days ──────────────────────────────────────────────────────────────────────────────────

CONTRAST = """
() => {
  // rgb(...) and the color(srgb r g b / a) a colour-mix() computes to
  const parse = c => {
    let m = c.match(/rgba?\\(([^)]+)\\)/);
    if (m) { const p = m[1].split(',').map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; }
    m = c.match(/color\\(srgb ([\\d.]+) ([\\d.]+) ([\\d.]+)(?: \\/ ([\\d.]+))?\\)/);
    if (m) return { r: m[1] * 255, g: m[2] * 255, b: m[3] * 255, a: m[4] === undefined ? 1 : Number(m[4]) };
    return null;
  };
  const over = (f, b) => ({ r: f.r * f.a + b.r * (1 - f.a), g: f.g * f.a + b.g * (1 - f.a),
                            b: f.b * f.a + b.b * (1 - f.a) });
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
                     return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const bgOf = el => { let stack = []; for (let e = el; e; e = e.parentElement) {
      const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > 0) { stack.push(c); if (c.a === 1) break; } }
    let base = { r: 23, g: 20, b: 15 };
    for (const c of stack.reverse()) base = over(c, base);
    return base; };
  const out = [];
  for (const row of document.querySelectorAll('tr.day-row.non-work')) {
    if (row.getBoundingClientRect().width === 0) continue;
    for (const el of row.querySelectorAll('td, td *')) {
      if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
      if (el.offsetParent === null) continue;
      const cs = getComputedStyle(el);
      let op = 1; for (let e = el; e; e = e.parentElement) op *= Number(getComputedStyle(e).opacity);
      if (op === 0) continue;  // a hover-only control (the pencil) is not on screen to be read
      const bg = bgOf(el); const fg = parse(cs.color); fg.a *= op;
      const f = over(fg, bg);
      const L1 = lum(f), L2 = lum(bg);
      const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
      out.push([el.className || el.tagName, cs.color, Math.round(ratio * 100) / 100]);
    }
  }
  return out;
}
"""


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["1280", "375"])
def test_days_off_rows_read_at_4_5_to_1(make_page, size):
    page = make_page(size, "days")
    page.get_by_test_id("wk-expand-all").click()
    page.wait_for_selector("tr.day-row.non-work", timeout=5000)
    page.wait_for_timeout(300)
    rows = page.evaluate(CONTRAST)
    assert len(rows) >= 8, rows  # the demo has weekends, a holiday, vacation and sick days
    low = [r for r in rows if r[2] < 4.5]
    assert low == [], low


def test_days_off_rows_are_still_quieter_than_work_days(make_page):
    page = make_page(DESKTOP, "days")
    page.get_by_test_id("wk-expand-all").click()
    page.wait_for_selector("tr.day-row.non-work", timeout=5000)
    got = page.evaluate(
        """() => {
          const c = sel => getComputedStyle(document.querySelector(sel)).color;
          return [c('tr.day-row:not(.non-work) td:first-child'), c('tr.day-row.non-work td:first-child')];
        }"""
    )
    assert got[0] != got[1], got


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["1280", "375"])
def test_delta_and_sigma_explain_themselves(make_page, size):
    page = make_page(size, "days")
    if size == DESKTOP:
        titles = page.evaluate(
            "() => [...document.querySelectorAll('.days-table th')]"
            ".filter(t => ['Δ', 'Σ'].includes(t.innerText.trim())).map(t => [t.innerText.trim(), t.title])"
        )
        assert titles == [["Δ", "Difference from target"], ["Σ", "Running balance"]]
    got = page.evaluate(
        "() => [...document.querySelectorAll('tr.week-sep td[data-l]')]"
        ".map(t => [t.dataset.l, t.title])"
    )
    assert ["Δ", "Difference from target"] in got and ["Σ", "Running balance"] in got, got


def test_sort_arrows_are_visible_at_rest(make_page):
    page = make_page(DESKTOP, "days")
    got = page.evaluate(
        """() => [...document.querySelectorAll('th.sortable')].map(t => {
          const c = getComputedStyle(t, '::after');
          return [t.innerText.trim(), c.content, Number(c.opacity), t.getAttribute('aria-sort')];
        })"""
    )
    assert len(got) == 2, got
    for _, content, opacity, _ in got:
        assert re.search(r"[↕↑↓]", content) and opacity >= 0.7, got
    # the sorted column says which way, in brass
    sorted_th = next(g for g in got if g[3] in ("ascending", "descending"))
    assert re.search(r"[↑↓]", sorted_th[1]), got


# ── 8. Days: sources on a phone ──────────────────────────────────────────────────────────────


def test_sources_card_gives_the_name_its_room_on_a_phone(make_page):
    page = make_page(PHONE, "days")
    page.locator(".hm-switch button", has_text="Freelance").click()
    page.wait_for_selector(".frow-name", timeout=5000)
    got = page.evaluate(
        """() => [...document.querySelectorAll('.frow-name > span:first-child')].map(s => ({
          text: s.innerText, whole: s.scrollWidth <= s.clientWidth + 1,
          lines: new Set([...(() => { const r = document.createRange(); r.selectNodeContents(s);
                                       return r.getClientRects(); })()].map(x => Math.round(x.top))).size }))"""
    )
    assert any(g["text"] == "Pine & Quill" for g in got), got  # the demo's longest name
    assert all(g["whole"] and g["lines"] == 1 for g in got), got  # none cut, none on two lines
    hidden = page.evaluate("() => getComputedStyle(document.querySelector('.frow > .n')).display")
    assert hidden == "none"  # the blocks column is gone on a phone


def test_blocks_column_stays_on_desktop(make_page):
    page = make_page(DESKTOP, "days")
    page.locator(".hm-switch button", has_text="Freelance").click()
    page.wait_for_selector(".frow-name", timeout=5000)
    assert (
        page.evaluate("() => getComputedStyle(document.querySelector('.frow > .n')).display")
        != "none"
    )


def test_a_freelance_day_row_keeps_its_source_on_one_line_on_a_phone(make_page):
    page = make_page(PHONE, "days")
    page.locator(".hm-switch button", has_text="Freelance").click()
    page.wait_for_selector(".frow-name", timeout=5000)
    page.get_by_test_id("wk-expand-all").click()
    page.wait_for_selector("tr.blk .blk-src", timeout=5000)
    got = page.evaluate(
        """() => [...document.querySelectorAll('tr.blk .blk-src')].filter(s => s.offsetParent).map(s => {
          const r = document.createRange(); r.selectNodeContents(s);
          const tops = new Set([...r.getClientRects()].map(x => Math.round(x.top)));
          return [s.innerText, tops.size, getComputedStyle(s).textOverflow, s.title];
        })"""
    )
    assert got, "no block row on screen"
    assert all(
        n == 1 and overflow == "ellipsis" and title == text for text, n, overflow, title in got
    ), got


# ── 9. Analytics ─────────────────────────────────────────────────────────────────────────────


def test_chart_hint_lives_in_a_title_with_a_question_chip(make_page):
    page = make_page(DESKTOP, "analytics")
    page.wait_for_selector(".an-chart-wrap svg", timeout=5000)
    assert "drag a rectangle" in page.locator(".an-chart-wrap").get_attribute("title").lower()
    assert page.locator(".an-head .an-hint").count() == 0
    chip = page.locator(".q-chip")
    assert chip.inner_text().strip() == "?"
    assert chip.evaluate("c => getComputedStyle(c, '::after').content") == "none"  # shut at rest
    shown = "c => getComputedStyle(c, '::after').content"
    chip.click()
    assert "drag a rectangle to zoom" in chip.evaluate(shown)  # open on a tap
    page.keyboard.press("Escape")
    assert chip.evaluate(shown) == "none"  # Escape shuts it
    chip.click()
    assert chip.evaluate(shown) != "none"
    page.locator(".an-head h2").first.click()  # a tap anywhere else shuts it too
    assert chip.evaluate(shown) == "none"


ROWS = """
() => {
  const ctl = document.querySelector('main .page-head .page-head-controls');
  const kids = [...ctl.children].filter(c => c.offsetParent !== null);
  // rows by the middle of each control: a pill and a year differ in height, not in row
  const mid = k => { const r = k.getBoundingClientRect(); return Math.round(r.top + r.height / 2); };
  const mids = kids.map(mid).sort((a, b) => a - b);
  const of = cls => kids.filter(k => k.classList.contains(cls));
  return { rows: mids.filter((m, i) => i === 0 || m - mids[i - 1] > 10).length,
           buttons: of('head-btn').map(mid), pill: of('hm-switch').map(mid), year: of('year-step').map(mid),
           heights: of('head-btn').map(k => Math.round(k.getBoundingClientRect().height)) };
}
"""


def test_analytics_head_fits_two_rows_on_a_phone(make_page):
    page = make_page(PHONE, "analytics")
    page.wait_for_selector(".head-btn", timeout=5000)
    got = page.evaluate(ROWS)
    assert len(got["buttons"]) == 4, got  # CSV, JSON, Freelance CSV, Payouts CSV
    assert got["rows"] == 2, got
    assert max(got["buttons"]) - min(got["buttons"]) <= 2, got  # the four exports share one row
    assert abs(got["pill"][0] - got["year"][0]) <= 2, got  # the pill and the year share the next
    assert got["pill"][0] > got["buttons"][0] + 10, got
    assert all(24 <= h <= 30 for h in got["heights"]), got  # smaller, still a target


def test_heatmap_opens_on_todays_month_on_a_phone(make_page):
    page = make_page(PHONE, "analytics")
    page.wait_for_function(
        "() => (document.querySelector('.heatmap-scroll')?.scrollLeft || 0) > 0", timeout=5000
    )
    got = page.evaluate(
        """() => {
          const s = document.querySelector('.heatmap-scroll');
          const t = s.querySelector('.hm-today').getBoundingClientRect();
          const b = s.getBoundingClientRect();
          return { left: s.scrollLeft, todayInView: t.left >= b.left && t.right <= b.right };
        }"""
    )
    assert got["left"] > 0 and got["todayInView"], got


def test_heatmap_right_edge_fades_while_there_is_more_to_see(make_page):
    page = make_page(PHONE, "analytics")
    page.wait_for_selector(".heatmap-scroll .hm-today", timeout=5000)
    page.evaluate("() => { document.querySelector('.heatmap-scroll').scrollLeft = 0; }")
    page.wait_for_function(
        "() => document.querySelector('.heatmap-scroll').classList.contains('more-r')", timeout=3000
    )
    mask = page.evaluate(
        "() => getComputedStyle(document.querySelector('.heatmap-scroll')).maskImage"
    )
    assert "linear-gradient" in mask, mask
    page.evaluate(
        "() => { const s = document.querySelector('.heatmap-scroll'); s.scrollLeft = 99999; }"
    )
    page.wait_for_function(
        "() => !document.querySelector('.heatmap-scroll').classList.contains('more-r')",
        timeout=3000,
    )


YEARS = """
() => {
  const rows = [...document.querySelectorAll('.an-years tr')];
  const edge = (el, right) => { const r = document.createRange(); r.selectNodeContents(el);
    const b = r.getBoundingClientRect(); return right ? b.right : b.left; };
  const head = rows[0].children, out = [];
  for (const row of rows.slice(1)) {
    [...row.children].forEach((td, i) => {
      const num = head[i].classList.contains('num');
      out.push([head[i].innerText.trim(), Math.round(Math.abs(edge(head[i], num) - edge(td, num)) * 10) / 10]);
    });
  }
  return out;
}
"""


@pytest.mark.parametrize("size", [DESKTOP, PHONE], ids=["1280", "375"])
def test_years_headers_align_with_their_columns(make_page, size):
    page = make_page(size, "analytics")
    page.wait_for_selector(".an-years td", timeout=5000)
    got = page.evaluate(YEARS)
    assert len(got) >= 7, got
    assert all(d <= 2 for _, d in got), got


# ── 10 and 11. Freelance ─────────────────────────────────────────────────────────────────────


def test_year_strip_inputs_have_visible_small_caps_labels(make_page):
    page = make_page(DESKTOP, "freelance")
    page.wait_for_selector(".fl-plan-inputs .calc-a", timeout=5000)
    got = page.evaluate(
        """() => [...document.querySelectorAll('.fl-plan-inputs .calc-a')].map(l => {
          const lbl = l.querySelector('.fl-lbl'), inp = l.querySelector('input');
          const lb = lbl.getBoundingClientRect(), ib = inp.getBoundingClientRect();
          const cs = getComputedStyle(lbl);
          return { text: lbl.innerText, above: lb.bottom <= ib.top + 1, top: Math.round(lb.top),
                   caps: cs.textTransform, size: parseFloat(cs.fontSize), shown: lb.width > 0 };
        })"""
    )
    assert [g["text"].lower() for g in got] == ["h / week", "days off"], got
    assert all(
        g["above"] and g["shown"] and g["caps"] == "uppercase" and g["size"] >= 10 for g in got
    )
    assert got[0]["top"] == got[1]["top"]  # a tidy pair
    strip = page.get_by_test_id("fl-projection")
    assert "Nothing planned" not in strip.inner_text()


def test_calculator_fields_share_one_grid(make_page):
    page = make_page(DESKTOP, "freelance")
    page.wait_for_selector(".calc-assume", timeout=5000)
    page.locator(".calc-assume .seg-toggle[aria-label=Currency] button", has_text="USD").click()
    page.wait_for_selector(".calc-a--fx", timeout=5000)
    got = page.evaluate(
        """() => {
          const box = s => { const r = document.querySelector(s).getBoundingClientRect();
                             return { l: Math.round(r.left), t: Math.round(r.top), b: Math.round(r.bottom) }; };
          const r2 = [...document.querySelectorAll('.calc-a--r2')].map(e => { const r = e.getBoundingClientRect();
                      return { l: Math.round(r.left), t: Math.round(r.top) }; });
          return { cur: box('.calc-a--cur'), fx: box('.calc-a--fx'), days: box('.calc-a--days'),
                   r2, toggles: box('.calc-toggles') };
        }"""
    )
    lefts = [c["l"] for c in got["r2"]]
    assert len(set(lefts)) == 4 and lefts == sorted(lefts), got
    assert (
        got["cur"]["l"] == lefts[0] and got["fx"]["l"] == lefts[1] and got["days"]["l"] == lefts[2]
    )
    assert len({c["t"] for c in got["r2"]}) == 1, got  # the four amounts share a row
    assert got["toggles"]["t"] > max(c["t"] for c in got["r2"]) + 30, (
        got
    )  # the toggles: their own row
    assert (
        got["cur"]["t"] == got["fx"]["t"] == got["days"]["t"]
        or abs(got["cur"]["t"] - got["fx"]["t"]) <= 2
    )


def test_linked_figures_have_presence_and_the_arrow_turns_once(make_page):
    page = make_page(DESKTOP, "freelance", reduced=False)
    page.wait_for_selector("[data-testid=fl-calc] input[aria-label='Hourly rate']", timeout=5000)
    size = page.evaluate(
        "() => parseFloat(getComputedStyle(document.querySelector('.calc-field input')).fontSize)"
    )
    assert size >= 24, size
    page.locator("input[aria-label='Hourly rate']").fill("100")
    page.wait_for_function(
        "() => document.querySelector('.calc-link').getAnimations().some(a => a.animationName === 'calc-turn')",
        timeout=5000,
    )
    # once: an iteration count of 1, not a loop
    assert page.evaluate(
        "() => getComputedStyle(document.querySelector('.calc-link')).animationIterationCount"
    ) in ("1",)
    page.wait_for_function(
        "() => !document.querySelector('.calc-link').getAnimations().length", timeout=5000
    )


def test_calculator_inputs_show_the_grouping_of_its_results_until_focused(make_page):
    page = make_page(DESKTOP, "freelance")
    calc = page.locator("[data-testid=fl-calc]")
    hourly = calc.locator("input[aria-label='Hourly rate']")
    net = calc.locator("input[aria-label='Net yearly']")
    salary = calc.locator("input[aria-label='Salary']")
    hourly.wait_for(timeout=5000)
    hourly.fill("95")
    page.wait_for_function(
        "() => !Alpine.$data(document.querySelector('main')).calc.busy", timeout=10000
    )
    salary.focus()  # leave the net field alone, and the hourly one
    shown = net.input_value()
    assert re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", shown), shown  # thousands grouped
    result = calc.locator("[data-testid=calc-net]").inner_text()
    # the same number as the result, written the same way (the result keeps its cents)
    as_number = lambda s: float(s.lstrip("€$").replace(".", "").replace(",", "."))  # noqa: E731
    assert abs(as_number(result) - as_number(shown)) < 0.006, (result, shown)
    assert result.lstrip("€$").startswith(shown.split(",")[0]), (result, shown)
    net.focus()
    assert re.fullmatch(r"\d+(,\d+)?", net.input_value()), net.input_value()  # focused: as typed
    salary.fill("55000")
    hourly.focus()
    assert salary.input_value() == "55.000"
    # typing takes a comma, a dot or a grouped number alike
    net.fill("28.960,03")
    page.wait_for_function(
        "() => Alpine.$data(document.querySelector('main')).calc.net === 28960.03", timeout=3000
    )


# ── 12 to 16. Settings ───────────────────────────────────────────────────────────────────────

LUM = """
(el) => {
  const parse = c => c.match(/\\d+(\\.\\d+)?/g).map(Number);
  const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
                               return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const fg = parse(getComputedStyle(el).color), bg = parse(getComputedStyle(document.body).backgroundColor);
  const a = lum(fg), b = lum(bg);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
"""


def test_settings_links_are_readable_and_the_current_one_has_a_brass_tick(make_page):
    page = make_page(DESKTOP, "settings")
    page.wait_for_selector(".settings-group-sections a", timeout=5000)
    page.wait_for_timeout(600)  # the group's own entry animation
    links = page.locator(".settings-group.open .settings-group-sections a")
    n = links.count()
    assert n >= 5
    for i in range(n):
        el = links.nth(i)
        assert el.evaluate(LUM) >= 4.5, (el.inner_text(), el.evaluate(LUM))
        assert el.evaluate("e => getComputedStyle(e).opacity") == "1"
    muted = links.nth(1).evaluate("e => getComputedStyle(e).color")
    assert muted == "rgb(164, 155, 135)", muted  # --k-muted, not Pico's
    tick = page.evaluate(
        """() => {
          const box = document.querySelector('.settings-group.open .settings-group-sections');
          const c = getComputedStyle(box, '::after');
          const a = box.querySelector('a.active');
          return { bg: c.backgroundColor, w: parseFloat(c.width), h: parseFloat(c.height),
                   y: new DOMMatrix(c.transform).m42, top: a.offsetTop, ah: a.offsetHeight };
        }"""
    )
    assert tick["bg"] == BRASS and tick["w"] == 3, tick
    assert abs(tick["h"] - tick["ah"]) <= 1 and abs(tick["y"] - tick["top"]) <= 1, tick


def test_the_settings_tick_slides_to_the_link_you_pick(make_page):
    page = make_page(DESKTOP, "settings", reduced=False)
    page.wait_for_selector(".settings-group-sections a", timeout=5000)
    where = """() => {
      const box = document.querySelector('.settings-group.open .settings-group-sections');
      const a = box.querySelector('a.active');
      return [a.textContent.trim(), a.offsetTop,
              Math.round(new DOMMatrix(getComputedStyle(box, '::after').transform).m42)];
    }"""
    page.wait_for_function(
        "() => { const b = document.querySelector('.settings-group.open .settings-group-sections');"
        " return b && b.style.getPropertyValue('--tick-h') !== ''; }",
        timeout=3000,
    )
    before = page.evaluate(where)
    assert before[0] == "Work" and before[2] == before[1] == 0, before
    page.locator(".settings-group-sections a", has_text="Leave").click()
    page.wait_for_function(
        """() => {
          const box = document.querySelector('.settings-group.open .settings-group-sections');
          const a = box.querySelector('a.active');
          return a.textContent.trim() === 'Leave'
            && Math.abs(new DOMMatrix(getComputedStyle(box, '::after').transform).m42 - a.offsetTop) <= 1;
        }""",
        timeout=5000,
    )
    after = page.evaluate(where)
    assert after[0] == "Leave" and after[1] > 20 and abs(after[2] - after[1]) <= 1, after


def test_general_wears_a_mark_like_its_neighbours(make_page):
    page = make_page(DESKTOP, "settings")
    marks = page.locator(".settings-group-btn span[aria-hidden='true']").all_inner_texts()
    assert len([m for m in marks if m.strip()]) == 3, marks


RIGHT_EDGES = """
() => {
  const out = [];
  for (const card of document.querySelectorAll('.settings-card')) {
    const inner = card.getBoundingClientRect().right - parseFloat(getComputedStyle(card).paddingRight);
    for (const ctl of card.querySelectorAll('.srow-ctl')) {
      const kids = [...ctl.querySelectorAll('input, select, .work-week-picker, .year-step')]
        .filter(e => e.offsetParent !== null && e.type !== 'hidden');
      if (!kids.length) continue;
      const right = Math.max(...kids.map(e => e.getBoundingClientRect().right));
      out.push([card.id, ctl.parentElement.innerText.split('\\n')[0].trim(), Math.round((inner - right) * 10) / 10]);
    }
  }
  return out;
}
"""


@pytest.mark.parametrize("group", ["Employee", "Freelance"])
def test_every_value_control_ends_on_the_cards_right_edge(make_page, group):
    page = make_page(DESKTOP, "settings")
    page.locator(".settings-group-btn", has_text=group).click()
    page.wait_for_selector(".settings-card .srow-ctl", timeout=5000)
    if group == "Freelance":
        page.wait_for_selector("#tax-salary", timeout=5000)
    page.wait_for_timeout(500)
    got = page.evaluate(RIGHT_EDGES)
    assert len(got) >= 5, got
    assert all(abs(gap) <= 2 for _, _, gap in got), got


def test_settings_content_uses_the_width(make_page):
    page = make_page(DESKTOP, "settings")
    page.wait_for_selector(".settings-card", timeout=5000)
    got = page.evaluate(
        """() => { const c = document.querySelector('.settings-card').getBoundingClientRect();
                   const l = document.querySelector('.settings-layout').getBoundingClientRect();
                   return { right: Math.round(l.right - c.right), width: Math.round(c.width) }; }"""
    )
    assert got["right"] <= 2 and got["width"] >= 900, got  # no hole on the right


def test_import_holidays_looks_disabled_only_when_it_is(make_page):
    page = make_page(DESKTOP, "settings")
    button = page.locator("#settings-holidays .settings-card-head button")
    button.wait_for(timeout=5000)
    style = "el => { const c = getComputedStyle(el); return [c.borderTopStyle, c.backgroundColor, c.borderTopColor]; }"
    assert button.is_disabled()  # it needs a country
    assert button.evaluate(style)[0] == "dashed"
    assert button.get_attribute("title") == "Pick a country first"
    _data(page, "d.settingsForm.holiday_country = 'ES'; d.holidayPreview = [];")
    page.wait_for_function(
        "() => !document.querySelector('#settings-holidays .settings-card-head button').disabled",
        timeout=3000,
    )
    assert button.evaluate(style) == ["solid", TRANSPARENT, BRASS]  # a brass outline when ready


def test_the_country_hint_is_one_short_line_with_a_question_chip(make_page):
    page = make_page(DESKTOP, "settings")
    note = page.locator(".holiday-note")
    note.wait_for(timeout=5000)
    assert note.evaluate("e => e.getBoundingClientRect().height") < 40
    chip = note.locator(".q-chip")
    assert len(chip.get_attribute("title")) > 100 and "BOE" in chip.get_attribute("title")
    assert "BOE" not in note.inner_text()
    chip.click()
    assert "BOE" in chip.evaluate("c => getComputedStyle(c, '::after').content")


def test_no_templates_offers_its_one_action(make_page):
    page = make_page(DESKTOP, "settings")
    link = page.locator("#settings-templates .settings-empty a")
    link.wait_for(timeout=5000)
    assert link.inner_text() == "Save one in Log"
    link.click()
    page.wait_for_url("**/#log", timeout=3000)


def test_profile_inputs_and_work_week_on_a_phone(make_page):
    page = make_page(PHONE, "settings")
    page.wait_for_selector("#set-name", timeout=5000)
    got = page.evaluate(
        """() => {
          const card = document.querySelector('#settings-profile').getBoundingClientRect();
          const pad = parseFloat(getComputedStyle(document.querySelector('#settings-profile')).paddingLeft);
          const widths = ['#set-name', '#set-employer', '#set-extra']
            .map(s => Math.round(document.querySelector(s).getBoundingClientRect().width));
          const days = [...document.querySelectorAll('.work-week-picker .work-week-day')].map(b => {
            const r = b.getBoundingClientRect(); return { top: Math.round(r.top), w: r.width, h: r.height }; });
          return { inner: Math.round(card.width - 2 * pad), widths, days };
        }"""
    )
    assert all(abs(w - got["inner"]) <= 2 for w in got["widths"]), got
    assert len(got["days"]) == 7 and len({d["top"] for d in got["days"]}) == 1, got  # one row
    widths = [d["w"] for d in got["days"]]
    assert max(widths) - min(widths) <= 1 and min(d["h"] for d in got["days"]) >= 24, got


@pytest.mark.parametrize(
    "typed,value",
    [
        ("55.000", 55000),
        ("1.234.567", 1234567),
        ("28.960,03", 28960.03),
        ("28960,03", 28960.03),
        ("28960.03", 28960.03),
        ("1,5", 1.5),
        ("1.5", 1.5),
        ("95", 95),
    ],
)
def test_the_calculator_reads_what_a_spanish_hand_types(page, base_url, typed, value):
    page.goto(base_url)
    page.wait_for_selector("main .page-head", timeout=5000)
    got = page.evaluate(
        """(t) => { const a = Alpine.$data(document.querySelector('main'));
          a.calcTyped('salary_annual', t, 'hourly'); return a.calc.salary_annual; }""",
        typed,
    )
    assert got == pytest.approx(value)
