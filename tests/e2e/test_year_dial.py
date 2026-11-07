"""E2E: the year dial, the brass chronograph the logo opens.

The browser clock is fixed to Wednesday 2026-11-04. A handful of real days sit around it, so every
figure below is a hand sum of those days:

    2025-12-31  Wed  09:00-19:00, 60 min break              9h    +1.00h
    2026-09-15  Tue  vacation, the whole day
    2026-10-22  Thu  25% sick, 08:30-16:00, 30 min break    7h (against 6h)   +1.00h
    2026-10-27  Tue  a freelance block of 1h, in a week with a payout
    2026-10-30  Fri  09:00-19:00, 60 min break              9h    +1.00h
    2026-11-02  Mon  09:00-18:00, 60 min break              8h     0.00h
    2026-11-03  Tue  09:00-17:00, 60 min break              7h    -1.00h   (a long note)
    2026-11-04  Wed  09:00-18:30, 60 min break              8.5h  +0.50h   (a freelance block, 2.5h)
    2026-11-25  Wed  a drafted vacation day

So the running balance is +1.00 on 2025-12-31, +2.00 on 2026-10-22, +3.00 on 2026-10-30 (its
highest), +2.00 on 2026-11-03 and +2.50 today. The 8h day target is the one the fixture sets.
The two tests that need the clock to move (the second hand, the winding) run on the real one and
read today from it.
"""

from __future__ import annotations

import datetime
import math

import httpx
import pytest

pytestmark = pytest.mark.e2e

FIXED_NOW = "2026-11-04T10:00:00"
TODAY = "2026-11-04"
LONG_NOTE = "Release night, " + "the migration ran long and the rollback plan was needed " * 4
STAGE = "[data-yd=stage]"
RING = "[data-yd=ring]"
TICKS = ".yd-ticks:not(.yd-flring) path"
DAYS_2026 = 365


# ── data ───────────────────────────────────────────────────────────────────────


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


@pytest.fixture(autouse=True)
def _clean(base_url):
    _wipe(base_url)
    with httpx.Client(base_url=base_url) as c:
        # the balance follows these two: another module of this worker may have left them moved
        c.put(
            "/api/config",
            json={
                "daily_target_hours": 8,
                "vacation_budget_days": 0,
                "cumulative_start_date": "2025-01-01",
                "reset_annually": False,
            },
        )
    yield
    _wipe(base_url)


def _work(c, date: str, end: str = "18:00", notes: str | None = None) -> None:
    body = {"date": date, "day_type": "work", "start_time": "09:00", "end_time": end}
    body["breaks"] = [{"break_minutes": 60}]
    if notes:
        body["notes"] = notes
    r = c.post("/api/entries", json=body)
    assert r.status_code == 201, r.text


def _seed(base_url: str, *, far: bool = False, note: str = LONG_NOTE) -> None:
    """The days of the module docstring. `far` adds a day in 2028, a leap year."""
    with httpx.Client(base_url=base_url) as c:
        _work(c, "2025-12-31", "19:00")
        r = c.post("/api/entries", json={"date": "2026-09-15", "day_type": "vacation"})
        assert r.status_code == 201, r.text
        partial = {"date": "2026-10-22", "day_type": "sick", "fraction": 0.25}
        partial |= {"start_time": "08:30", "end_time": "16:00", "breaks": [{"break_minutes": 30}]}
        r = c.post("/api/entries", json=partial)
        assert r.status_code == 201, r.text
        _work(c, "2026-10-30", "19:00")
        _work(c, "2026-11-02")
        _work(c, "2026-11-03", "17:00", notes=note)
        _work(c, "2026-11-04", "18:30")
        if far:
            _work(c, "2028-03-01")
        r = c.post("/api/plans", json={"dates": ["2026-11-25"], "day_type": "vacation"})
        assert r.status_code == 200, r.text
        source = {"name": "Local", "hourly_rate": 100, "currency": "EUR"}
        r = c.post("/api/freelance/sources", json=source)
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
        for date, hours in (("2026-11-04", 2.5), ("2026-10-27", 1)):
            r = c.post(
                "/api/freelance/blocks", json={"date": date, "source_id": sid, "hours": hours}
            )
            assert r.status_code == 201, r.text
        payout = {"source_id": sid, "week_start": "2026-10-26", "amount": 100}
        r = c.post("/api/freelance/payouts", json=payout)
        assert r.status_code == 201, r.text


# ── the page ───────────────────────────────────────────────────────────────────

# Counts what dial.js asks of the browser: frames, and the timers it starts and clears.
WATCH = """
(() => {
  window.__dialRaf = 0;
  window.__dialTimers = new Set();
  const raf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = cb => {
    if (new Error().stack.includes('dial.js')) window.__dialRaf++;
    return raf(cb);
  };
  const si = window.setInterval.bind(window), ci = window.clearInterval.bind(window);
  window.setInterval = (fn, ms, ...a) => {
    const id = si(fn, ms, ...a);
    if (new Error().stack.includes('dial.js')) window.__dialTimers.add(id);
    return id;
  };
  window.clearInterval = id => { window.__dialTimers.delete(id); return ci(id); };
})();
"""

# Counts the audio contexts the page makes.
AUDIO = """
(() => {
  window.__audio = 0;
  const Base = window.AudioContext;
  window.AudioContext = class extends Base {
    constructor(...a) { super(...a); window.__audio++; }
  };
})();
"""

LOADED = """
(wantEntries) => {
  const d = Alpine.$data(document.querySelector('main'));
  const home = location.hash === '#dashboard' ? d.dashboard : true;
  return home && !d.loading.days && (!wantEntries || d.entries.length > 0);
}
"""


def _open_app(
    page,
    base_url,
    size=(1280, 900),
    *,
    calm: bool = True,
    tab: str = "dashboard",
    entries: bool = True,
    fixed: bool = True,
):
    """The app on `tab`, its data loaded. Reduced motion by default: a key lands on its day."""
    # the milestone toast belongs to a first visit
    page.add_init_script("localStorage.setItem('k-milestone-seen', '100000')")
    page.set_viewport_size({"width": size[0], "height": size[1]})
    if calm:
        page.emulate_media(reduced_motion="reduce")
    if fixed:
        page.clock.set_fixed_time(FIXED_NOW)
    page.goto(f"{base_url}/#{tab}")
    page.wait_for_function(LOADED, arg=entries, timeout=8000)


def _open_dial(page, how: str = "key") -> None:
    if how == "logo":
        page.get_by_role("button", name="Open the year dial").click()
    elif how == "palette":
        page.keyboard.press(".")
        page.wait_for_selector("#k-palette-input:focus")
        page.keyboard.type("year")
        page.keyboard.press("Enter")
    else:
        page.keyboard.press("y")
    page.wait_for_selector("#yd [data-yd=stage][data-day]:not([data-day=''])", timeout=8000)


def _wait_day(page, iso: str) -> None:
    page.wait_for_function(
        "(iso) => document.querySelector('[data-yd=stage]')?.dataset.day === iso",
        arg=iso,
        timeout=8000,
    )


def _day(page) -> str:
    return page.locator(STAGE).get_attribute("data-day")


def _face(page) -> dict:
    """The whole readout in one read: it changes with the day, and a slow runner must not see two
    different ones."""
    return page.evaluate(
        """() => {
          const t = n => document.querySelector(`[data-yd=${n}]`).textContent;
          const day = document.querySelector('[data-yd=stage]').dataset.day;
          return { day, date: t('date'), wk: t('wk'), big: t('big'), sub: t('sub'),
                   note: t('note'), fl: t('fl'), balv: t('balv'), weekv: t('weekv') };
        }"""
    )


def _goto(page, iso: str) -> None:
    """Turn the ring to a day of the year shown, by keys (with reduced motion each press lands)."""
    page.locator(RING).focus()
    n = (datetime.date.fromisoformat(iso) - datetime.date.fromisoformat(_day(page))).days
    keys = ("PageUp", "ArrowUp", "ArrowRight") if n > 0 else ("PageDown", "ArrowDown", "ArrowLeft")
    n = abs(n)
    for key, size in zip(keys, (30, 7, 1), strict=True):
        for _ in range(n // size):
            page.keyboard.press(key)
        n %= size
    _wait_day(page, iso)


def _rotation(page) -> float:
    t = page.locator("[data-yd=rotor]").get_attribute("transform")
    return float(t.removeprefix("rotate(").removesuffix(")"))


def _steps(page) -> float:
    """How many days the ring has turned from its start: a whole number when it rests on a day."""
    return -_rotation(page) / (360 / _days(page))


def _settle(page) -> None:
    """Wait until the ring stops turning."""
    last = None
    for _ in range(60):
        now = page.locator("[data-yd=rotor]").get_attribute("transform")
        if now == last:
            return
        last = now
        page.wait_for_timeout(150)
    raise AssertionError("the ring never stopped")


def _days(page) -> int:
    return int(page.locator(RING).get_attribute("aria-valuemax"))


def _index_of(iso: str) -> int:
    d = datetime.date.fromisoformat(iso)
    return (d - datetime.date(d.year, 1, 1)).days


def _back(page, today: str = TODAY) -> int:
    """How many days before `today` the day under the index is (going round the year)."""
    return (_index_of(today) - _index_of(_day(page))) % _days(page)


def _geometry(page) -> dict:
    return page.evaluate(
        """() => { const b = document.querySelector('[data-yd=stage]').getBoundingClientRect();
          return { x: b.left + b.width / 2, y: b.top + b.height / 2, w: b.width }; }"""
    )


def _at(g: dict, deg: float, units: float = 400) -> tuple[float, float]:
    """The screen point `deg` clockwise from twelve o'clock, `units` (of the 1040 box) out."""
    r = units * g["w"] / 1040
    return g["x"] + r * math.sin(math.radians(deg)), g["y"] - r * math.cos(math.radians(deg))


def _drag(page, a0: float, a1: float, *, steps: int = 30, gap: int = 8, hold: int = 160) -> None:
    """A hand on the tick band from `a0` to `a1` degrees. `hold` is the pause before letting go:
    0 is a flick."""
    g = _geometry(page)
    page.mouse.move(*_at(g, a0))
    page.mouse.down()
    for k in range(1, steps + 1):
        page.mouse.move(*_at(g, a0 + (a1 - a0) * k / steps))
        page.wait_for_timeout(gap)
    if hold:
        page.wait_for_timeout(hold)
    page.mouse.up()


def _flick(page, a0: float, a1: float, *, steps: int = 20) -> None:
    """The same hand, let go while moving. It runs inside the page: on a slow runner the time
    between two calls from here is longer than the pause that tells a flick from a held drag."""
    g = _geometry(page)
    points = [_at(g, a0 + (a1 - a0) * k / steps) for k in range(steps + 1)]
    page.evaluate(
        """async (points) => {
          const stage = document.querySelector('[data-yd=stage]');
          const fire = (type, [clientX, clientY]) => stage.dispatchEvent(new PointerEvent(type, {
            bubbles: true, pointerId: 7, pointerType: 'mouse', button: 0, clientX, clientY }));
          fire('pointerdown', points[0]);
          for (const at of points.slice(1)) {
            await new Promise(done => setTimeout(done, 8));
            fire('pointermove', at);
          }
          fire('pointerup', points[points.length - 1]);
        }""",
        points,
    )


def _segments(page, selector: str) -> list[tuple[int, int]]:
    """Each tick under `selector` as the two radii it runs between."""
    paths = page.evaluate(
        "(s) => [...document.querySelectorAll(s)].map(p => p.getAttribute('d'))", selector
    )
    out = []
    for d in paths:
        for part in d.split("M")[1:]:
            a, b = part.split("L")
            r1 = math.hypot(*map(float, a.split()))
            r2 = math.hypot(*map(float, b.split()))
            out.append((round(min(r1, r2)), round(max(r1, r2))))
    return out


def _crown(page) -> None:
    page.get_by_role("button", name="Back to today").click()


# ── opening and closing ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("how", ["logo", "key", "palette"])
def test_it_opens_by_the_logo_by_y_and_by_the_palette(page, base_url, how):
    _seed(base_url)
    _open_app(page, base_url)
    assert page.locator("#yd").count() == 0
    _open_dial(page, how)
    dialog = page.get_by_role("dialog", name="Year dial")
    assert dialog.get_attribute("aria-modal") == "true"
    assert _day(page) == TODAY
    # focus went into the dial: the ring has it
    assert page.evaluate("document.activeElement.dataset.yd") == "ring"


def test_y_typed_in_a_field_does_not_open_it(page, base_url):
    _seed(base_url)
    _open_app(page, base_url, tab="days")
    field = page.get_by_role("searchbox", name="Filter entries by notes")
    field.click()
    field.press("y")
    assert field.input_value() == "y"
    page.wait_for_timeout(300)
    assert page.locator("#yd").count() == 0
    # the control: out of the field, the same key opens it
    field.press("Escape")
    page.keyboard.press("y")
    page.wait_for_selector("#yd")


def test_esc_closes_it_and_focus_goes_back_to_the_logo(page, base_url):
    _seed(base_url)
    _open_app(page, base_url, tab="days")
    page.get_by_role("button", name="Open the year dial").focus()
    _open_dial(page, "logo")
    page.keyboard.press("Escape")
    page.wait_for_selector("#yd", state="detached")
    assert page.evaluate("document.activeElement.className") == "brand-btn"
    # Esc closed the dial and nothing else: the tab behind it is still Days
    assert page.evaluate("Alpine.$data(document.querySelector('main')).tab") == "days"
    # the cross closes it too, and gives the focus back the same way
    _open_dial(page, "logo")
    page.get_by_role("button", name="Close the year dial").click()
    page.wait_for_selector("#yd", state="detached")
    assert page.evaluate("document.activeElement.className") == "brand-btn"


def test_a_key_of_the_app_does_nothing_while_it_is_open(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    for key in ("p", "l", "d", "s", ".", "y", "a", "f"):
        page.keyboard.press(key)
    page.wait_for_timeout(200)
    state = page.evaluate(
        """() => { const d = Alpine.$data(document.querySelector('main'));
          return { tab: d.tab, palette: d.palette.open,
                   dials: document.querySelectorAll('#yd').length }; }"""
    )
    assert state == {"tab": "dashboard", "palette": False, "dials": 1}


def test_tab_stays_inside_and_the_page_behind_does_not_scroll(page, base_url):
    _seed(base_url)
    _open_app(page, base_url, size=(1280, 500))
    _open_dial(page)
    inside = []
    for key in ["Tab"] * 14 + ["Shift+Tab"] * 14:
        page.keyboard.press(key)
        inside.append(page.evaluate("!!document.activeElement.closest('#yd')"))
    assert inside == [True] * 28
    page.locator(RING).focus()
    page.mouse.move(640, 250)
    page.mouse.wheel(0, 600)
    page.keyboard.press("Space")
    page.wait_for_timeout(200)
    assert page.evaluate("window.scrollY") == 0
    assert page.evaluate("getComputedStyle(document.documentElement).overflow") == "hidden"
    page.keyboard.press("Escape")
    page.wait_for_selector("#yd", state="detached")
    assert page.evaluate("getComputedStyle(document.documentElement).overflow") == "visible"


def test_the_logo_is_a_real_button_that_turns_on_hover(page, base_url):
    _open_app(page, base_url, entries=False)
    logo = page.locator(".brand-btn")
    assert logo.evaluate("e => e.tagName") == "BUTTON"
    assert logo.get_attribute("aria-label") == "Open the year dial"
    page.emulate_media(reduced_motion="no-preference")
    before = page.locator(".brand-logo").bounding_box()
    logo.hover()
    page.wait_for_timeout(700)
    assert page.locator(".brand-logo").evaluate("e => getComputedStyle(e).transform") != "none"
    page.mouse.move(5, 500)
    page.wait_for_timeout(700)
    assert page.locator(".brand-logo").bounding_box() == before


# ── what it says ────────────────────────────────────────────────────────────────


def test_it_opens_on_today_and_the_readout_is_that_days(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    assert _face(page) == {
        "day": TODAY,
        "date": "Wed, Nov 4",
        "wk": "W45 · today",
        "big": "8.5h",
        "sub": "+0.50h",
        "note": "",
        "fl": "⚡ 2.5h · €250.00",
        "balv": "+2.50h",
        "weekv": "−0.50h",
    }
    ring = page.locator(RING)
    assert ring.get_attribute("aria-valuenow") == str(_index_of(TODAY) + 1)
    assert ring.get_attribute("aria-valuetext") == "Wed, Nov 4, 8.5h +0.50h"
    assert page.locator("[data-yd=year]").text_content() == "2026"


def test_a_day_with_nothing_a_future_day_a_leave_day_and_a_draft(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    _goto(page, "2026-11-01")
    face = _face(page)
    want = ("Sun, Nov 1", "W44", "–", "no entry")
    assert (face["date"], face["wk"], face["big"], face["sub"]) == want
    _goto(page, "2026-11-05")
    face = _face(page)
    want = ("Thu, Nov 5", "–", "still to come", "")
    assert (face["date"], face["big"], face["sub"], face["fl"]) == want
    _goto(page, "2026-09-15")
    face = _face(page)
    assert (face["date"], face["big"], face["sub"]) == ("Tue, Sep 15", "vacation", "")
    _goto(page, "2026-11-25")
    face = _face(page)
    assert (face["big"], face["sub"]) == ("vacation", "planned")
    _goto(page, "2026-11-03")
    face = _face(page)
    want = ("Tue, Nov 3", "7h", "−1.00h", "−0.50h")
    assert (face["date"], face["big"], face["sub"], face["weekv"]) == want
    assert face["note"] == LONG_NOTE
    _goto(page, "2026-10-22")
    face = _face(page)
    assert (face["wk"], face["big"], face["sub"]) == ("W43 · sick · 2h", "7h", "+1.00h")


def test_the_freelance_line_of_a_paid_week_is_teal(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    fill = "e => getComputedStyle(e).fill"
    estimated = page.locator("[data-yd=fl]").evaluate(fill)
    assert not page.locator("[data-yd=fl]").evaluate("e => e.classList.contains('paid')")
    _goto(page, "2026-10-27")
    assert _face(page)["fl"] == "⚡ 1h · €100.00"
    assert page.locator("[data-yd=fl]").evaluate("e => e.classList.contains('paid')")
    assert page.locator("[data-yd=fl]").evaluate(fill) != estimated


@pytest.mark.parametrize(
    "size,selector", [((1280, 900), "[data-yd=note]"), ((375, 800), "[data-yd=note2]")]
)
def test_a_very_long_note_stays_in_two_lines(page, base_url, size, selector):
    """On the face and on the phone's panel; a single word with no break in it as well."""
    _seed(base_url, note="x" * 300)
    _open_app(page, base_url, size)
    _open_dial(page)
    _goto(page, "2026-11-03")
    lines = page.locator(selector).evaluate(
        """e => { const r = e.getBoundingClientRect();
          const line = parseFloat(getComputedStyle(e).lineHeight);
          return r.height / line / (r.width / e.offsetWidth); }"""
    )
    assert 1.9 < lines <= 2.05, lines
    assert page.evaluate("document.documentElement.scrollWidth") <= size[0]


def test_a_year_with_no_entries_still_opens(page, base_url):
    _open_app(page, base_url, entries=False)
    _open_dial(page)
    face = _face(page)
    want = ("Wed, Nov 4", "–", "no entry", "±0.00h", "±0.00h")
    assert (face["date"], face["big"], face["sub"], face["balv"], face["weekv"]) == want
    assert len(_segments(page, TICKS)) == DAYS_2026
    assert page.locator("[data-yd=prev]").is_disabled()
    assert page.locator("[data-yd=next]").is_disabled()


def test_the_ticks_are_the_days_of_the_year(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)

    def count(cls: str) -> int:
        return len(_segments(page, f"{TICKS}.yd-t-{cls}"))

    assert len(_segments(page, TICKS)) == DAYS_2026
    assert page.locator(".yd-month").count() == 12
    # 10-22 (a partial day takes the bar of its surplus), 10-30 and 11-04; 11-03; 11-02; 09-15
    assert [count(c) for c in ("surplus", "deficit", "neutral", "vacation", "sick")] == [
        3,
        1,
        1,
        1,
        0,
    ]
    assert count("draft-vacation") == 1
    assert count("empty") == DAYS_2026 - 7  # every day without an entry or a draft
    # length goes with the surplus: +1.00h is the longest bar (56), +0.50h half of it, outward;
    # -1.00h as long, inward; a whole leave day a fixed bar across the base line
    surplus = sorted(_segments(page, ".yd-ticks path.yd-t-surplus"))
    assert [b - a for a, b in surplus] == [28, 56, 56]
    assert {a for a, _ in surplus} == {366}
    assert _segments(page, ".yd-ticks path.yd-t-deficit") == [(310, 366)]
    assert _segments(page, ".yd-ticks path.yd-t-vacation") == [(344, 388)]
    # the freelance ring: brass for the estimated day, teal for the paid week
    assert len(_segments(page, ".yd-flring path.yd-t-fl")) == 1
    assert len(_segments(page, ".yd-flring path.yd-t-paid")) == 1
    # days after today are dimmer: Nov 5 to Dec 31 is 57 of them
    assert len(_segments(page, ".yd-future path")) == 57
    # the brass pip is on today whichever day is under the index
    _goto(page, "2026-03-01")
    pip = page.locator("[data-yd=pip]").evaluate(
        "e => [+e.getAttribute('cx'), +e.getAttribute('cy')]"
    )
    angle = math.degrees(math.atan2(pip[0], -pip[1])) % 360
    assert abs(angle - _index_of(TODAY) * 360 / DAYS_2026) < 0.5
    assert abs(math.hypot(*pip) - 422) < 0.5


def test_the_week_dial_lights_the_selected_day(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    lit = """() => [...document.querySelectorAll('[data-yd=week] rect')]
      .map(r => r.classList.contains('on'))"""
    assert page.evaluate(lit) == [False, False, True, False, False, False, False]
    _goto(page, "2026-11-02")
    assert page.evaluate(lit) == [True, False, False, False, False, False, False]


# ── turning ─────────────────────────────────────────────────────────────────────


def test_the_keys_move_the_day_and_the_slider_follows(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    ring = page.locator(RING)
    assert (ring.get_attribute("aria-valuemin"), ring.get_attribute("aria-valuemax")) == (
        "1",
        "365",
    )
    steps = [
        ("ArrowRight", "2026-11-05", "Thu, Nov 5, – still to come"),
        ("ArrowUp", "2026-11-12", None),
        ("ArrowLeft", "2026-11-11", None),
        ("ArrowDown", "2026-11-04", "Wed, Nov 4, 8.5h +0.50h"),
        ("PageDown", "2026-10-05", None),
        ("PageUp", "2026-11-04", None),
        ("ArrowRight", "2026-11-05", None),
        ("Home", "2026-11-04", "Wed, Nov 4, 8.5h +0.50h"),
    ]
    for key, want, text in steps:
        page.keyboard.press(key)
        _wait_day(page, want)
        assert ring.get_attribute("aria-valuenow") == str(_index_of(want) + 1), key
        if text:
            assert ring.get_attribute("aria-valuetext") == text, key


def test_a_wheel_notch_is_one_day(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    g = _geometry(page)
    page.mouse.move(g["x"], g["y"])
    page.mouse.wheel(0, 100)
    _wait_day(page, "2026-11-05")
    page.wait_for_timeout(300)
    page.mouse.wheel(0, -100)
    _wait_day(page, TODAY)
    page.wait_for_timeout(300)
    page.mouse.wheel(0, -100)
    _wait_day(page, "2026-11-03")


def test_the_ring_wraps_from_the_first_of_january_to_the_last_of_december(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    _goto(page, "2026-01-01")
    assert _face(page)["date"] == "Thu, Jan 1"
    page.keyboard.press("ArrowLeft")
    _wait_day(page, "2026-12-31")
    assert page.locator(RING).get_attribute("aria-valuenow") == "365"
    page.keyboard.press("ArrowRight")
    _wait_day(page, "2026-01-01")
    assert page.locator(RING).get_attribute("aria-valuenow") == "1"


def test_a_drag_of_a_quarter_turn_moves_about_91_days_and_lands_on_a_day(page, base_url):
    _seed(base_url)
    _open_app(page, base_url, calm=False)
    _open_dial(page)
    _wait_day(page, TODAY)
    _settle(page)
    _drag(page, 0, 90)  # clockwise: back in time, like turning a dial
    _settle(page)
    assert _back(page) in (91, 92), _day(page)
    steps = _steps(page)
    assert abs(steps - round(steps)) < 0.01, steps  # a whole number of days
    assert round(steps) % _days(page) == _index_of(_day(page))
    _drag(page, 90, 0)  # and back
    _settle(page)
    assert _day(page) == TODAY


def test_a_flick_goes_on_with_friction_and_a_held_drag_does_not(page, base_url):
    _seed(base_url)
    _open_app(page, base_url, calm=False)
    _open_dial(page)
    _wait_day(page, TODAY)
    _settle(page)
    _flick(page, 0, 40)
    _settle(page)
    assert _back(page) > 46, _day(page)  # 40 degrees are 41 days; the rest is the ring coasting
    assert abs(_steps(page) - round(_steps(page))) < 0.01
    _crown(page)
    _wait_day(page, TODAY)
    _settle(page)
    _drag(page, 0, 40, steps=20, gap=8, hold=200)
    _settle(page)
    assert _back(page) == 41, _day(page)


def test_a_press_on_the_band_turns_the_ring_to_the_day_pressed(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    g = _geometry(page)
    today = _index_of(TODAY)
    for deg in (-90, 90, 45, 170, -150):
        page.keyboard.press("Home")
        _wait_day(page, TODAY)
        page.mouse.click(*_at(g, deg))
        want = (today + deg / (360 / DAYS_2026)) % DAYS_2026
        page.wait_for_function(
            """(want) => {
              const n = +document.querySelector('[data-yd=ring]').getAttribute('aria-valuenow') - 1;
              const d = Math.abs(n - want);
              return Math.min(d, 365 - d) <= 1;
            }""",
            arg=want,
            timeout=5000,
        )
    # a press on the face is not on the band: nothing turns
    page.keyboard.press("Home")
    _wait_day(page, TODAY)
    page.mouse.click(g["x"], g["y"] - 60)
    page.wait_for_timeout(300)
    assert _day(page) == TODAY


def test_the_crown_takes_the_short_way_round(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    _goto(page, "2026-05-24")  # 164 days before today, 201 the other way round
    before = _steps(page)
    _crown(page)
    _wait_day(page, TODAY)
    assert round(_steps(page) - before) == 164


# ── the bar and the sub-dials ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "config",
    [{"cumulative_start_date": "2026-10-23"}, {"reset_annually": True}],
    ids=["since", "reset"],
)
def test_the_balance_counts_as_the_dashboard_does(page, base_url, config):
    """Both settings move the balance, on the dial as on the Dashboard."""
    _seed(base_url)
    with httpx.Client(base_url=base_url) as c:
        c.put("/api/config", json=config)
        expected = c.get("/api/dashboard").json()["cumulative"]["surplus_hours"]
    try:
        _open_app(page, base_url)
        _open_dial(page)
        _wait_day(page, TODAY)
        shown = page.locator("[data-yd=balv]").text_content()
        assert float(shown.rstrip("h").replace("−", "-").replace("±", "")) == pytest.approx(
            expected
        )
    finally:
        with httpx.Client(base_url=base_url) as c:
            c.put(
                "/api/config", json={"cumulative_start_date": "2025-01-01", "reset_annually": False}
            )


def test_after_a_click_on_the_bar_the_arrows_still_turn_the_ring(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    _wait_day(page, TODAY)
    page.locator("[data-yd=sound]").click()
    page.keyboard.press("ArrowRight")
    _wait_day(page, "2026-11-05")


def test_on_a_phone_the_figures_of_the_small_dials_are_in_the_panel(page, base_url):
    _seed(base_url)
    _open_app(page, base_url, (375, 800))
    _open_dial(page)
    _wait_day(page, TODAY)
    assert not page.locator("[data-yd=balv]").is_visible()
    panel = page.locator(".yd-nums")
    assert "Balance" in panel.inner_text() and "Week" in panel.inner_text()
    assert (
        page.locator("[data-yd=balv2]").inner_text()
        == page.locator("[data-yd=balv]").text_content()
    )
    size = panel.evaluate("e => parseFloat(getComputedStyle(e).fontSize)")
    assert size >= 12


def test_balance_on_today_is_the_dashboards_and_earlier_it_is_the_sum_by_hand(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    dash = page.evaluate(
        "Alpine.$data(document.querySelector('main')).dashboard.cumulative.surplus_hours"
    )
    assert dash == pytest.approx(2.5)
    assert _face(page)["balv"] == "+2.50h"
    for iso, want in (
        ("2026-11-03", "+2.00h"),
        ("2026-10-30", "+3.00h"),
        ("2026-10-21", "+1.00h"),
        ("2026-03-01", "+1.00h"),  # the Dec 31 of the year before counts too
        ("2026-01-01", "+1.00h"),
    ):
        _goto(page, iso)
        assert _face(page)["balv"] == want, iso
    # the needle: plus or minus the highest the balance reaches (3.00h) is 135 degrees each way
    _goto(page, TODAY)
    needle = page.locator("[data-yd=bal]").get_attribute("transform")
    assert float(needle.removeprefix("rotate(").removesuffix(")")) == pytest.approx(112.5, abs=0.1)


def test_the_year_buttons_step_through_the_years_with_entries(page, base_url):
    _seed(base_url, far=True)
    _open_app(page, base_url)
    _open_dial(page)
    assert page.locator("[data-yd=year]").text_content() == "2026"
    page.get_by_role("button", name="Next year").click()
    _wait_day(page, "2028-11-04")  # 2027 has no entries: it is skipped
    assert page.locator("[data-yd=year]").text_content() == "2028"
    assert _days(page) == 366
    assert len(_segments(page, TICKS)) == 366
    assert page.locator("[data-yd=next]").is_disabled()
    # no pip on a year that does not hold today
    assert page.locator("[data-yd=pip]").get_attribute("visibility") == "hidden"
    # the leap day, and a year back: it keeps the month and day as far as the year has them
    _goto(page, "2028-02-29")
    assert _face(page)["date"] == "Tue, Feb 29"
    page.get_by_role("button", name="Previous year").click()
    _wait_day(page, "2026-02-28")
    assert _days(page) == 365
    _goto(page, TODAY)
    page.get_by_role("button", name="Next year").click()
    _wait_day(page, "2028-11-04")
    page.get_by_role("button", name="Previous year").click()
    _wait_day(page, TODAY)
    # in 2025 the last day is a real one: an entry on Dec 31
    page.get_by_role("button", name="Previous year").click()
    _wait_day(page, "2025-11-04")
    _goto(page, "2025-12-31")
    face = _face(page)
    want = ("Wed, Dec 31", "9h", "+1.00h", "+1.00h")
    assert (face["date"], face["big"], face["sub"], face["balv"]) == want
    assert len(_segments(page, ".yd-ticks path.yd-t-surplus")) == 1
    page.keyboard.press("ArrowRight")
    _wait_day(page, "2025-01-01")


def test_enter_opens_the_day_in_log_and_the_dial_closes(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    _goto(page, "2026-11-03")
    page.keyboard.press("Enter")
    page.wait_for_selector("#yd", state="detached")
    page.wait_for_function(
        """() => { const d = Alpine.$data(document.querySelector('main'));
          return d.tab === 'log' && d.editingDate === '2026-11-03'; }""",
        timeout=5000,
    )
    # the brass button does the same
    page.keyboard.press("y")
    page.wait_for_selector("#yd")
    _wait_day(page, TODAY)
    page.get_by_role("button", name="Open in Log").click()
    page.wait_for_selector("#yd", state="detached")
    page.wait_for_function(
        "Alpine.$data(document.querySelector('main')).editingDate === '2026-11-04'", timeout=5000
    )


# ── sound ───────────────────────────────────────────────────────────────────────


def test_sound_is_off_by_default_makes_a_context_only_when_on_and_is_remembered(page, base_url):
    _seed(base_url)
    page.add_init_script(AUDIO)
    _open_app(page, base_url)
    _open_dial(page)
    button = page.locator("[data-yd=sound]")
    assert button.text_content() == "Sound off"
    for _ in range(3):
        page.keyboard.press("ArrowRight")
    _wait_day(page, "2026-11-07")
    assert page.evaluate("window.__audio") == 0
    button.click()
    assert button.text_content() == "Sound on"
    page.locator(RING).focus()
    for _ in range(2):
        page.keyboard.press("ArrowRight")
    _wait_day(page, "2026-11-09")
    assert page.evaluate("window.__audio") == 1
    assert page.evaluate("localStorage.getItem('k-dial-sound')") == "1"
    page.reload()
    page.wait_for_function(LOADED, arg=True, timeout=8000)
    _open_dial(page)
    assert page.locator("[data-yd=sound]").text_content() == "Sound on"
    page.locator("[data-yd=sound]").click()
    assert page.evaluate("localStorage.getItem('k-dial-sound')") == "0"
    assert page.locator("[data-yd=sound]").text_content() == "Sound off"


# ── motion ──────────────────────────────────────────────────────────────────────


def test_with_reduced_motion_it_opens_on_today_at_once_and_a_release_does_not_coast(page, base_url):
    _seed(base_url)
    today = datetime.date.today().isoformat()
    _open_app(page, base_url, fixed=False)  # reduced motion, the real clock
    page.get_by_role("button", name="Open the year dial").click()
    page.wait_for_function("document.querySelector('[data-yd=stage]')?.dataset.day")
    # the first thing it ever says is today: nothing winds round
    assert _day(page) == today
    assert _steps(page) == pytest.approx(_index_of(today), abs=0.01)
    _drag(page, 0, 40, steps=20, gap=8, hold=0)
    page.wait_for_timeout(100)
    landed = _day(page)
    page.wait_for_timeout(800)
    assert _day(page) == landed
    assert _back(page, today) == 41
    assert abs(_steps(page) - round(_steps(page))) < 0.01
    # no jiggle, and a second hand that holds still
    assert not page.locator(".yd-index").evaluate("e => e.classList.contains('tick')")
    sec = page.locator("[data-yd=sec]").evaluate("e => e.style.transform")
    page.wait_for_timeout(1300)
    assert page.locator("[data-yd=sec]").evaluate("e => e.style.transform") == sec


def test_with_motion_the_ring_winds_to_today_the_index_jiggles_and_the_second_hand_ticks(
    page, base_url
):
    _seed(base_url)
    today = datetime.date.today().isoformat()
    _open_app(page, base_url, calm=False, fixed=False)
    page.get_by_role("button", name="Open the year dial").click()
    page.wait_for_function("document.querySelector('[data-yd=stage]')?.dataset.day")
    assert _day(page) != today  # it starts 150 days away
    _wait_day(page, today)
    page.keyboard.press("ArrowRight")
    page.wait_for_function("document.querySelector('.yd-index').classList.contains('tick')")
    seconds = "e => parseFloat(e.style.transform.slice(7))"
    one = page.locator("[data-yd=sec]").evaluate(seconds)
    page.wait_for_timeout(1400)
    assert page.locator("[data-yd=sec]").evaluate(seconds) > one


def test_when_closed_no_frame_and_no_timer_of_the_dial_keeps_running(page, base_url):
    _seed(base_url)
    page.add_init_script(WATCH)
    _open_app(page, base_url, calm=False, fixed=False)  # a fixed clock replaces the timers
    _open_dial(page)
    page.wait_for_timeout(500)
    # the control: while it is open it does ask for frames, and keeps a timer for the seconds
    page.evaluate("window.__dialRaf = 0")
    page.wait_for_timeout(300)
    assert page.evaluate("window.__dialRaf") > 5
    assert page.evaluate("window.__dialTimers.size") == 1
    page.keyboard.press("Escape")
    page.wait_for_selector("#yd", state="detached")
    page.wait_for_timeout(100)
    page.evaluate("window.__dialRaf = 0")
    page.wait_for_timeout(500)
    assert page.evaluate("window.__dialRaf") == 0
    assert page.evaluate("window.__dialTimers.size") == 0


# ── every width ─────────────────────────────────────────────────────────────────

SIZES = [(320, 700), (375, 800), (640, 900), (768, 900), (1024, 800), (1280, 900), (800, 400)]
MEASURE = """
() => {
  const box = e => { const b = e.getBoundingClientRect();
    return [b.left, b.top, b.right, b.bottom, b.width, b.height]; };
  const q = s => document.querySelector(s);
  return {
    sw: document.documentElement.scrollWidth,
    dial: [q('#yd').scrollWidth - q('#yd').clientWidth,
           q('#yd').scrollHeight - q('#yd').clientHeight],
    stage: box(q('[data-yd=stage]')), crown: box(q('[data-yd=crown]')), bar: box(q('.yd-bar')),
    buttons: [...document.querySelectorAll('.yd-bar button')].map(box),
    panel: getComputedStyle(q('.yd-panel')).display,
    face: getComputedStyle(q('.yd-face-only')).display,
  };
}
"""


@pytest.mark.parametrize("size", SIZES, ids=[f"{w}x{h}" for w, h in SIZES])
def test_the_whole_dial_fits_at_every_width(page, base_url, size):
    _seed(base_url)
    _open_app(page, base_url, size)
    _open_dial(page)
    m = page.evaluate(MEASURE)
    w, h = size
    assert m["sw"] <= w
    assert m["dial"] == [0, 0]  # nothing of the dial scrolls
    left, top, right, bottom, width, height = m["stage"]
    assert left >= 0 and top >= 0 and right <= w and bottom <= h
    assert abs(width - height) < 1
    assert m["bar"][0] >= 0 and m["bar"][2] <= w and m["bar"][3] <= h
    assert len(m["buttons"]) == 5  # year back and forward, Open in Log, sound, close
    for b in m["buttons"]:
        assert b[4] >= 24 and b[5] >= 24, b
        assert b[0] >= 0 and b[2] <= w and b[3] <= h
    crown = m["crown"]
    assert crown[4] >= 24 and crown[5] >= 24
    assert crown[0] >= 0 and crown[2] <= w
    if w <= 640:
        assert (m["panel"], m["face"]) == ("block", "none")
        assert width >= 0.93 * w  # the dial takes the width
    else:
        assert m["panel"] == "none"
        assert m["face"] != "none"
    if size == (800, 400):
        assert height > 300  # in landscape it takes the height


# ── a finger ────────────────────────────────────────────────────────────────────


def test_a_real_finger_turns_the_ring(page, base_url):
    _seed(base_url)
    _open_app(page, base_url, (375, 800), calm=False)
    _open_dial(page)
    _wait_day(page, TODAY)
    _settle(page)
    cdp = page.context.new_cdp_session(page)
    cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
    g = _geometry(page)

    def finger(kind: str, x: float = 0, y: float = 0) -> None:
        points = [] if kind == "touchEnd" else [{"x": x, "y": y}]
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})

    finger("touchStart", *_at(g, 0))
    for k in range(1, 31):
        finger("touchMove", *_at(g, 90 * k / 30))
        page.wait_for_timeout(12)
    page.wait_for_timeout(160)
    finger("touchEnd")
    _settle(page)
    assert _back(page) in (91, 92), _day(page)
    assert page.evaluate("window.scrollY") == 0
    assert abs(_steps(page) - round(_steps(page))) < 0.01


# ── the crown can be found: a label while the ring is away from today ──────────────

LABEL = "[data-yd=crownlabel]"


def test_the_crown_label_is_hidden_on_today_shown_when_away_and_gone_after_pressing_it(
    page, base_url
):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    _wait_day(page, TODAY)
    label = page.locator(LABEL)
    assert label.count() == 1  # kept in the page
    assert label.is_hidden()
    assert label.get_attribute("aria-hidden") == "true"
    page.locator(RING).focus()
    for _ in range(10):
        page.keyboard.press("ArrowLeft")
    _wait_day(page, "2026-10-25")  # 10 days turned
    assert label.is_visible()
    assert label.inner_text() == "Today"
    label.click()
    _wait_day(page, TODAY)
    page.wait_for_selector(LABEL, state="hidden")
    assert _day(page) == TODAY  # the ring is back on today
    assert label.get_attribute("hidden") is not None


def test_the_crown_does_the_same_and_keeps_its_name_and_its_tooltip(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    crown = page.get_by_role("button", name="Back to today")
    assert crown.get_attribute("title") == "Back to today"
    _goto(page, "2026-10-25")
    assert page.locator(LABEL).is_visible()
    crown.click()
    _wait_day(page, TODAY)
    page.wait_for_selector(LABEL, state="hidden")


def test_the_label_follows_the_year_too(page, base_url):
    """Another year never has today under the index, so the label stays until the ring is back."""
    _seed(base_url)
    _open_app(page, base_url)
    _open_dial(page)
    page.locator("[data-yd=prev]").click()
    page.wait_for_function("() => document.querySelector('[data-yd=stage]').dataset.day < '2026'")
    assert page.locator(LABEL).is_visible()
    page.locator(LABEL).click()
    _wait_day(page, TODAY)
    page.wait_for_selector(LABEL, state="hidden")


def test_the_crown_glows_once_each_time_the_ring_leaves_today_and_not_while_it_winds_in(
    page, base_url
):
    _seed(base_url)
    _open_app(page, base_url, calm=False)
    page.evaluate(
        """() => {
          window.__label = { shown: 0 };
          new MutationObserver(() => {
            const l = document.querySelector('[data-yd=crownlabel]');
            if (l && !l.hidden) window.__label.shown++;
          }).observe(document.body, {
            subtree: true, attributes: true, attributeFilter: ['hidden'],
          });
        }"""
    )
    _open_dial(page)
    _wait_day(page, TODAY)
    _settle(page)  # the opening wind has ended
    assert page.evaluate("window.__label.shown") == 0  # the wind round to today is not leaving it
    crown = "[data-yd=crown]"
    names = f"document.querySelector('{crown}').getAnimations().map(a => a.animationName)"
    assert page.evaluate(names) == []
    page.locator(RING).focus()
    page.keyboard.press("ArrowLeft")
    page.wait_for_function(f"() => {names}.includes('yd-crown-glow')")
    once = page.evaluate(
        f"""() => document.querySelector('{crown}').getAnimations()[0].effect.getComputedTiming()
              .iterations"""
    )
    assert once == 1
    page.wait_for_function(f"() => {names}.length === 0", timeout=4000)  # one pulse, not a loop
    page.keyboard.press("ArrowLeft")  # still away: no second pulse
    page.wait_for_timeout(300)
    assert page.evaluate(names) == []
    assert page.locator(LABEL).is_visible()
    page.locator(LABEL).click()
    _settle(page)
    _wait_day(page, TODAY)
    page.wait_for_selector(LABEL, state="hidden")
    page.keyboard.press("ArrowRight")  # leaving again glows again
    page.wait_for_function(f"() => {names}.includes('yd-crown-glow')")


def test_with_reduced_motion_the_label_still_shows_and_the_crown_does_not_glow(page, base_url):
    _seed(base_url)
    _open_app(page, base_url)  # reduced motion
    _open_dial(page)
    page.locator(RING).focus()
    page.keyboard.press("ArrowLeft")
    page.wait_for_selector(LABEL, state="visible")
    assert page.evaluate("document.querySelector('[data-yd=crown]').getAnimations().length") == 0
    assert page.evaluate(f"document.querySelector('{LABEL}').getAnimations().length") == 0


CROWN_LABEL = """
() => {
  const q = s => document.querySelector(s);
  const st = q('[data-yd=stage]').getBoundingClientRect();
  const l = q('[data-yd=crownlabel]').getBoundingClientRect();
  const c = q('[data-yd=crown]').getBoundingClientRect();
  const art = q('.yd-crown-art rect').getBoundingClientRect();
  const cx = st.left + st.width / 2, cy = st.top + st.height / 2;
  const corners = [[l.left, l.top], [l.right, l.top], [l.left, l.bottom], [l.right, l.bottom]];
  return {
    label: [l.left, l.top, l.right, l.bottom], crown: [c.left, c.top, c.right, c.bottom],
    ring: st.width * 500 / 1040,                       // the circle of the dial, in px
    nearest: Math.min(...corners.map(([x, y]) => Math.hypot(x - cx, y - cy))),
    art: art.height * 1040 / st.width,                  // the brass, in the 1040 box
    sw: document.documentElement.scrollWidth, w: innerWidth, h: innerHeight,
  };
}
"""


@pytest.mark.parametrize("size", SIZES, ids=[f"{w}x{h}" for w, h in SIZES])
def test_the_crown_label_fits_outside_the_ring_at_every_width(page, base_url, size):
    _seed(base_url)
    _open_app(page, base_url, size)
    _open_dial(page)
    page.locator(RING).focus()
    page.keyboard.press("ArrowLeft")
    page.wait_for_selector(LABEL, state="visible")
    m = page.evaluate(CROWN_LABEL)
    left, top, right, bottom = m["label"]
    assert left >= 0 and right <= m["w"] and top >= 0 and bottom <= m["h"], m  # never clipped
    assert m["sw"] <= m["w"], m  # and no sideways scroll
    assert m["nearest"] >= m["ring"] - 1, m  # outside the circle: never over a tick
    cl, ct, cr, cb = m["crown"]
    assert right <= cl + 1 or left >= cr - 1 or bottom <= ct + 1 or top >= cb - 1, (
        m
    )  # not on the crown
    assert 105 <= m["art"] <= 112, m  # the brass grew from 68 to about 109 units
