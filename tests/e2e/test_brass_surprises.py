"""E2E: the brass surprises.

Small reactions for the moments of Kronos that deserve one: the odometer on the big numbers, the
stamp on a saved day, the seal on a finished week, the coins of a payout, the bead of the day on the
header's hairline and the logo's turn for the "kronos" egg. Every one is off under
`prefers-reduced-motion: reduce`, with the end state shown at once.

Most of what they draw lives for a second or less, and a slow runner can miss it between two calls:
a test that needs it installs an observer (or runs the action) in the same `page.evaluate`, and
anything that has to settle is waited for, never slept on.
"""

from __future__ import annotations

import datetime
import json

import httpx
import pytest

pytestmark = pytest.mark.e2e

TODAY = datetime.date.today()
MONDAY = TODAY - datetime.timedelta(days=TODAY.weekday())
LAST_MONDAY = MONDAY - datetime.timedelta(days=7)
OLD_MONDAY = MONDAY - datetime.timedelta(days=21)
MINUS = "−"

MAIN = "Alpine.$data(document.querySelector('main'))"

# What an odometer shows, read from the drawing: a reel's digit is how far its strip is turned.
READ_ODO = """(sel) => {
  const o = document.querySelector(sel);
  const parts = [...o.children].slice(1);
  const digits = parts.map((p) => {
    if (!p.classList.contains('odo-reel')) return p.dataset.ch;
    const y = p.firstElementChild.getBoundingClientRect().top - p.getBoundingClientRect().top;
    return String(Math.round(-y / p.offsetHeight) - 1);
  }).join('');
  return {
    shown: digits,
    text: o.firstElementChild.textContent,
    busy: o.getAnimations({ subtree: true }).length,
    width: o.offsetWidth,
    hidden: parts.every((p) => p.getAttribute('aria-hidden') === 'true'),
  };
}"""


# ── helpers ───────────────────────────────────────────────────────────────────


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")
        # another module of the same worker may have left these moved
        r = c.put(
            "/api/config",
            json={
                "daily_target_hours": 8,
                "work_week_days": [0, 1, 2, 3, 4],
                "cumulative_start_date": "2026-01-01",
                "reset_annually": False,
            },
        )
        assert r.status_code == 200, r.text


@pytest.fixture(autouse=True)
def _clean(base_url):
    _wipe(base_url)
    yield
    _wipe(base_url)


def _entry(base_url: str, date: str, start="08:00", end="17:00", breaks=()) -> None:
    body = {
        "date": date,
        "day_type": "work",
        "start_time": start,
        "end_time": end,
        "breaks": [{"break_minutes": m} for m in breaks],
    }
    with httpx.Client(base_url=base_url) as c:
        r = c.post("/api/entries", json=body)
        assert r.status_code == 201, r.text


def _week(monday: datetime.date, n: int) -> list[str]:
    return [(monday + datetime.timedelta(days=i)).isoformat() for i in range(n)]


def _wk(monday: datetime.date) -> str:
    return f"W{monday.isocalendar()[1]:02d}"


def _open_dashboard(page, base_url: str) -> None:
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector(".hero-num .odo-reel", timeout=5000)


def _settled(page, sel: str, shown: str) -> dict:
    """Wait until the reels stand on `shown` and nothing is moving; return what they read."""
    check = "([sel, shown]) => { const r = (__READ__)(sel); return r.shown === shown && !r.busy; }"
    page.wait_for_function(
        check.replace("__READ__", READ_ODO),
        arg=[sel, shown],
        timeout=8000,
    )
    return page.evaluate(READ_ODO, sel)


def _watch_ribbon(page) -> None:
    """Record every (message, seal) the save ribbon shows: it is gone again in a few seconds."""
    page.evaluate(
        """() => {
          window.__ribbon = [];
          const host = document.querySelector('.save-ribbon-host');
          const note = () => {
            const msg = host.querySelector('.ribbon-msg').textContent;
            const seal = host.querySelector('.ribbon-seal');
            const row = { msg, seal: seal ? seal.textContent : null };
            const last = window.__ribbon[window.__ribbon.length - 1];
            if (!last || last.msg !== row.msg || last.seal !== row.seal) window.__ribbon.push(row);
          };
          new MutationObserver(note).observe(host, {
            subtree: true, childList: true, characterData: true,
          });
        }"""
    )


def _ribbon(page, startswith: str) -> list[dict]:
    page.wait_for_function(
        "(p) => window.__ribbon.some((r) => r.msg.startsWith(p))", arg=startswith, timeout=8000
    )
    return page.evaluate("window.__ribbon")


def _open_log(page, base_url: str) -> None:
    page.goto(f"{base_url}/#log")
    page.wait_for_selector("button.log-cal-day:not(.log-cal-pad)", timeout=5000)


def _pick(page, iso: str) -> None:
    """Show the month of `iso` in the Log calendar and click its cell."""
    d = datetime.date.fromisoformat(iso)
    page.evaluate(
        f"([y, m]) => {{ const a = {MAIN}; a.calYear = y; a.calMonth = m; }}", [d.year, d.month - 1]
    )
    page.locator(f"button.log-cal-day[aria-label='{iso}']").click()
    page.wait_for_function(f"d => {MAIN}.form.date === d", arg=iso)
    # an existing day opens for editing; a free one stays a new entry
    page.wait_for_timeout(150)


def _save_new_day(page, iso: str, start="08:00", end="17:00") -> None:
    _pick(page, iso)
    times = page.locator("input[type='time']")
    times.nth(0).fill(start)
    times.nth(1).fill(end)
    page.locator("button.btn-action--block").click()


def _watch_stamps(page) -> None:
    """Count how often each calendar cell takes the stamp class."""
    page.evaluate(
        """() => {
          window.__stamps = {};
          const grid = document.querySelector('main');
          const seen = new WeakSet();
          const look = () => document.querySelectorAll('button.log-cal-day').forEach((b) => {
            const on = b.classList.contains('cal-stamp');
            if (on && !seen.has(b)) {
              seen.add(b);
              const k = b.getAttribute('aria-label');
              window.__stamps[k] = (window.__stamps[k] || 0) + 1;
            }
            if (!on) seen.delete(b);
          });
          new MutationObserver(look).observe(grid, {
            subtree: true, attributes: true, attributeFilter: ['class'], childList: true,
          });
        }"""
    )


# ── 1. the counter ────────────────────────────────────────────────────────────


class TestOdometer:
    def test_the_balance_settles_on_its_text_and_keeps_its_name(self, page, base_url):
        _entry(base_url, "2026-07-20")  # 9h against 8h: +1.00h
        _entry(base_url, "2026-07-21")  # and another: +2.00h
        _open_dashboard(page, base_url)
        read = _settled(page, ".hero-num .odo", "+2.00h")

        assert read["shown"] == "+2.00h"
        assert read["text"] == "+2.00h"
        assert read["hidden"] is True  # the reels are for the eye; the name is the text
        assert page.locator(".hero-num").inner_text() == "+2.00h"
        assert page.locator(".hero-num").aria_snapshot().strip() == "- text: +2.00h"
        # "+2.00h" is three reels (2, 0, 0) and three characters that stand still (+ . h)
        assert page.locator(".hero-num .odo-reel").count() == 3
        assert page.locator(".hero-num .odo-ch").count() == 3

    def test_a_negative_balance_keeps_its_sign_still(self, page, base_url):
        _entry(base_url, "2026-07-20", start="09:00", end="15:00")  # 6h: -2.00h
        _open_dashboard(page, base_url)
        read = _settled(page, ".hero-num .odo", f"{MINUS}2.00h")
        assert read["text"] == f"{MINUS}2.00h"
        assert page.locator(".hero-num").inner_text() == f"{MINUS}2.00h"

    def test_it_rolls_from_zero_on_first_view_and_when_the_value_changes(self, page, base_url):
        _entry(base_url, "2026-07-20")  # +1.00h
        # the first view: a reel is on 0 when it appears and is moving the next moment
        page.add_init_script(
            """
            window.__first = null;
            new MutationObserver(() => {
              const o = document.querySelector('.hero-num .odo-reel');
              if (o && !window.__first) {
                const i = o.firstElementChild;
                window.__first = { d: o.style.getPropertyValue('--d') };
                requestAnimationFrame(() => {
                  window.__first.moving = i.getAnimations().length;
                });
              }
            }).observe(document, { subtree: true, childList: true });
            """
        )
        _open_dashboard(page, base_url)
        _settled(page, ".hero-num .odo", "+1.00h")
        first = page.evaluate("window.__first")
        assert first["d"] in ("0", "1"), first  # born on 0 (or already turning to the 1)
        assert first["moving"] >= 1, first

        # a change: the reels turn to the new value, and the box does not move meanwhile
        _entry(base_url, "2026-07-21")
        out = page.evaluate(
            """async () => {
              const f = __READ__;
              const a = __MAIN__;
              const before = f('.hero-num .odo');
              await a.loadDashboard();
              let moved = 0, widths = new Set();
              for (let i = 0; i < 120; i++) {
                await new Promise(requestAnimationFrame);
                const r = f('.hero-num .odo');
                widths.add(r.width);
                if (r.busy > 0) moved++;
                if (r.shown === '+2.00h' && r.busy === 0) break;
              }
              const end = f('.hero-num .odo');
              return { before: before.shown, moved, widths: [...widths], end: end.shown };
            }""".replace("__READ__", READ_ODO).replace("__MAIN__", MAIN),
        )
        assert out["before"] == "+1.00h"
        assert out["end"] == "+2.00h"
        assert out["moved"] >= 2, out  # it rolled, it did not jump
        assert len(out["widths"]) == 1, out  # a reel never changes the box

    def test_reels_land_on_the_width_plain_text_has(self, page, base_url):
        _entry(base_url, "2026-07-20")
        _open_dashboard(page, base_url)
        read = _settled(page, ".hero-num .odo", "+1.00h")
        plain = page.evaluate(
            """() => {
              const h = document.querySelector('.hero-num');
              const s = document.createElement('span');
              s.style.cssText = 'display:inline-block;white-space:pre;'
                + 'position:absolute;visibility:hidden';
              s.textContent = '+1.00h';
              h.appendChild(s);
              const w = s.getBoundingClientRect().width;
              s.remove();
              return w;
            }"""
        )
        assert abs(read["width"] - plain) <= 1.5, (read["width"], plain)

    def test_the_freelance_hero_rolls_too(self, page, base_url):
        with httpx.Client(base_url=base_url) as c:
            src = c.post(
                "/api/freelance/sources",
                json={"name": "Local", "hourly_rate": 80, "currency": "EUR"},
            ).json()["id"]
            r = c.post(
                "/api/freelance/blocks",
                json={"date": TODAY.isoformat(), "source_id": src, "hours": 2},
            )
            assert r.status_code == 201, r.text
        page.goto(f"{base_url}/#freelance")
        page.wait_for_selector("[data-testid='fl-gross'] .odo-reel", timeout=5000)
        read = _settled(page, "[data-testid='fl-gross'] .odo", "€160.00")
        assert read["text"] == "€160.00"
        assert page.locator("[data-testid='fl-gross']").inner_text() == "€160.00"
        assert page.locator("[data-testid='fl-gross'] .odo-reel").count() == 5

    def test_the_small_chips_keep_their_count_up(self, page, base_url):
        _entry(base_url, "2026-07-20")
        _open_dashboard(page, base_url)
        assert page.locator(".chip .odo").count() == 0
        assert page.locator(".chip-value").first.is_visible()


# ── 2. the stamp ──────────────────────────────────────────────────────────────


class TestStamp:
    def test_the_saved_day_takes_the_stamp_once_and_no_other_cell(self, page, base_url):
        day = TODAY.replace(day=3) if TODAY.day != 3 else TODAY.replace(day=4)
        _open_log(page, base_url)
        _watch_stamps(page)
        _save_new_day(page, day.isoformat())
        page.wait_for_function("() => Object.keys(window.__stamps).length > 0", timeout=8000)
        # the class goes by itself, so a stamp does not stay on the cell
        page.wait_for_function("() => !document.querySelector('.cal-stamp')", timeout=8000)
        assert page.evaluate("window.__stamps") == {day.isoformat(): 1}

    def test_editing_a_day_stamps_it_again(self, page, base_url):
        day = TODAY.replace(day=3) if TODAY.day != 3 else TODAY.replace(day=4)
        _entry(base_url, day.isoformat())
        _open_log(page, base_url)
        _watch_stamps(page)
        _pick(page, day.isoformat())
        page.locator("input[type='time']").nth(1).fill("18:00")
        page.locator("button.btn-action--block").click()
        page.wait_for_function("() => Object.keys(window.__stamps).length > 0", timeout=8000)
        assert page.evaluate("window.__stamps") == {day.isoformat(): 1}


# ── 3. the seal ───────────────────────────────────────────────────────────────


class TestSeal:
    def test_the_last_work_day_of_a_week_seals_it(self, page, base_url):
        days = _week(LAST_MONDAY, 5)
        for d in days[:4]:
            _entry(base_url, d)  # four days of +1.00h
        _open_log(page, base_url)
        _watch_ribbon(page)
        _save_new_day(page, days[4])
        shown = _ribbon(page, f"{_wk(LAST_MONDAY)} sealed")
        assert shown[-1]["msg"] == f"{_wk(LAST_MONDAY)} sealed +5.00h"
        assert any(r["seal"] == _wk(LAST_MONDAY) for r in shown), shown
        # it is remembered for this browser
        done = json.loads(page.evaluate("localStorage.getItem('k-week-sealed')"))
        assert done == [LAST_MONDAY.isoformat()]

    def test_the_fourth_day_does_not(self, page, base_url):
        days = _week(LAST_MONDAY, 5)
        for d in days[:3]:
            _entry(base_url, d)
        _open_log(page, base_url)
        _watch_ribbon(page)
        _save_new_day(page, days[3])
        shown = _ribbon(page, "Saved")
        assert all(r["seal"] is None for r in shown), shown
        assert not any("sealed" in r["msg"] for r in shown), shown
        assert page.evaluate("localStorage.getItem('k-week-sealed')") is None

    def test_a_week_is_not_sealed_twice(self, page, base_url):
        days = _week(LAST_MONDAY, 5)
        for d in days[:4]:
            _entry(base_url, d)
        _open_log(page, base_url)
        _watch_ribbon(page)
        _save_new_day(page, days[4])
        _ribbon(page, f"{_wk(LAST_MONDAY)} sealed")

        # take the last day away and log it again: the week was sealed already
        with httpx.Client(base_url=base_url) as c:
            assert c.delete(f"/api/entries/{days[4]}").status_code in (200, 204)
        _open_log(page, base_url)
        page.reload()
        page.wait_for_selector("button.log-cal-day:not(.log-cal-pad)", timeout=5000)
        _watch_ribbon(page)
        _save_new_day(page, days[4])
        shown = _ribbon(page, "Saved")
        assert all(r["seal"] is None for r in shown), shown

    def test_an_old_week_is_not_sealed(self, page, base_url):
        days = _week(OLD_MONDAY, 5)
        for d in days[:4]:
            _entry(base_url, d)
        _open_log(page, base_url)
        _watch_ribbon(page)
        _save_new_day(page, days[4])
        shown = _ribbon(page, "Saved")
        assert all(r["seal"] is None for r in shown), shown
        assert page.evaluate("localStorage.getItem('k-week-sealed')") is None

    def test_editing_a_finished_week_does_not_seal_it_again(self, page, base_url):
        days = _week(LAST_MONDAY, 5)
        for d in days:
            _entry(base_url, d)
        _open_log(page, base_url)
        _watch_ribbon(page)
        _pick(page, days[4])
        page.locator("input[type='time']").nth(1).fill("18:00")
        page.locator("button.btn-action--block").click()
        shown = _ribbon(page, "Saved")
        assert all(r["seal"] is None for r in shown), shown

    def test_a_week_that_works_a_different_set_of_days(self, page, base_url):
        with httpx.Client(base_url=base_url) as c:
            r = c.put("/api/config", json={"work_week_days": [0, 1, 2]})
            assert r.status_code == 200, r.text
        days = _week(LAST_MONDAY, 3)
        for d in days[:2]:
            _entry(base_url, d)
        _open_log(page, base_url)
        _watch_ribbon(page)
        _save_new_day(page, days[2])  # the third and last work day
        shown = _ribbon(page, f"{_wk(LAST_MONDAY)} sealed")
        assert shown[-1]["msg"] == f"{_wk(LAST_MONDAY)} sealed +3.00h"


# ── 4. the coins ──────────────────────────────────────────────────────────────


def _payout_setup(base_url: str) -> int:
    """One source at 60/h and two hours on last Wednesday: an estimate of 120."""
    with httpx.Client(base_url=base_url) as c:
        src = c.post(
            "/api/freelance/sources", json={"name": "Local", "hourly_rate": 60, "currency": "EUR"}
        ).json()["id"]
        wed = (LAST_MONDAY + datetime.timedelta(days=2)).isoformat()
        r = c.post("/api/freelance/blocks", json={"date": wed, "source_id": src, "hours": 2})
        assert r.status_code == 201, r.text
    return src


def _open_days_freelance(page, base_url: str) -> None:
    page.goto(f"{base_url}/#days")
    page.wait_for_selector(".page-head .hm-switch", timeout=5000)
    page.evaluate(f"{MAIN}.daysYear = 'all'")
    page.locator(".page-head .hm-switch button").nth(1).click()
    page.wait_for_selector("[data-testid='days-freelance']", timeout=3000)


WATCH_COINS = """() => {
  const w = window.__coins = { added: 0, bumps: 0, out: 0, wide: 0, left: 0, boxes: 0 };
  const vw = document.documentElement.clientWidth, vh = window.innerHeight;
  new MutationObserver((ms) => ms.forEach((m) => {
    m.addedNodes.forEach((n) => {
      if (n.classList && n.classList.contains('coin-fly')) w.added++;
    });
  })).observe(document.body, { childList: true });
  document.addEventListener('animationstart', (e) => {
    if (e.animationName === 'bz-bump' && e.target.closest('[data-testid=days-fl-total]')) w.bumps++;
  });
  const look = () => {
    document.querySelectorAll('.coin-fly i').forEach((i) => {
      const r = i.getBoundingClientRect();
      w.boxes++;
      if (r.left < 0 || r.top < 0 || r.right > vw || r.bottom > vh) w.out++;
    });
    if (document.documentElement.scrollWidth > document.documentElement.clientWidth) w.wide++;
    requestAnimationFrame(look);
  };
  look();
}"""


class TestCoins:
    @pytest.mark.parametrize(
        "typed, coins",
        [("150", 5), ("100", 1), ("120", 1)],
        ids=["above the estimate", "below it", "at it"],
    )
    def test_coins_follow_the_payout_and_leave_nothing_behind(self, page, base_url, typed, coins):
        _payout_setup(base_url)
        _open_days_freelance(page, base_url)
        page.evaluate(WATCH_COINS)
        field = page.locator(f"input[aria-label='Payout Local {_wk(LAST_MONDAY)}']")
        field.scroll_into_view_if_needed()
        field.fill(typed)
        page.wait_for_function(
            "(n) => window.__coins.added >= n && !document.querySelector('.coin-fly')",
            arg=coins,
            timeout=10000,
        )
        page.wait_for_function("() => window.__coins.bumps >= 1", timeout=5000)
        got = page.evaluate("window.__coins")
        assert got["added"] == coins, got
        assert got["bumps"] == 1, got
        assert got["boxes"] > 0, got  # they were seen flying
        assert got["out"] == 0, got  # inside the viewport all the way
        assert got["wide"] == 0, got  # and the page never scrolled sideways
        assert page.locator(".coin-fly").count() == 0

    def test_the_selected_card_shows_the_payout_after_the_coins(self, page, base_url):
        _payout_setup(base_url)
        _open_days_freelance(page, base_url)
        page.locator(f"input[aria-label='Payout Local {_wk(LAST_MONDAY)}']").fill("150")
        page.wait_for_function(
            "() => document.querySelector(\"[data-testid='days-fl-total']\")"
            ".innerText.includes('€150.00')",
            timeout=8000,
        )


# ── 5. the day bead ───────────────────────────────────────────────────────────

BEAD_FRAC = """() => {
  const b = document.querySelector('.day-bead').getBoundingClientRect();
  const h = document.querySelector('.app-header').getBoundingClientRect();
  return {
    frac: (b.left - h.left) / (h.width - b.width),
    busy: document.querySelector('.day-bead').getAnimations().length,
    title: document.querySelector('.day-bead').title,
  };
}"""


def _at(page, base_url: str, clock: str) -> None:
    page.clock.set_fixed_time(clock)
    page.goto(f"{base_url}/#dashboard")
    page.wait_for_selector(".day-bead", state="attached", timeout=5000)


class TestDayBead:
    def test_noon_is_a_third_of_the_way(self, page, base_url):
        _at(page, base_url, "2026-11-04T12:00:00")
        page.wait_for_function("() => document.querySelector('.day-bead').title === 'Now 12:00'")
        got = page.evaluate(BEAD_FRAC)
        assert got["title"] == "Now 12:00"
        assert got["frac"] == pytest.approx(1 / 3, abs=0.01), got

    def test_six_in_the_morning_and_midnight_are_the_two_edges(self, page, base_url):
        _at(page, base_url, "2026-11-04T06:00:00")
        assert page.evaluate(BEAD_FRAC)["frac"] == pytest.approx(0, abs=0.01)
        page.clock.set_fixed_time("2026-11-04T23:59:00")
        page.reload()
        page.wait_for_selector(".day-bead", state="attached", timeout=5000)
        page.wait_for_function("() => document.querySelector('.day-bead').title === 'Now 23:59'")
        page.wait_for_function(
            "() => { const r = (__READ__)(); return r.frac > 0.99 && r.busy === 0; }".replace(
                "__READ__", BEAD_FRAC
            ),
            timeout=8000,
        )

    def test_before_six_it_rests_at_the_left(self, page, base_url):
        _at(page, base_url, "2026-11-04T03:30:00")
        page.wait_for_function("() => document.querySelector('.day-bead').title === 'Now 03:30'")
        assert page.evaluate(BEAD_FRAC)["frac"] == pytest.approx(0, abs=0.01)

    def test_it_follows_the_clock_of_the_page(self, page, base_url):
        _at(page, base_url, "2026-11-04T12:00:00")
        page.evaluate(f"{MAIN}.nowDisplay = '18:00'")
        page.wait_for_function(
            (
                "() => { const r = (__READ__)(); "
                "return r.title === 'Now 18:00' && !r.busy && Math.abs(r.frac - 2 / 3) < 0.01; }"
            ).replace("__READ__", BEAD_FRAC),
            timeout=8000,
        )

    def test_it_is_decoration_that_takes_no_pointer(self, page, base_url):
        _at(page, base_url, "2026-11-04T12:00:00")
        got = page.evaluate(
            """() => {
              const b = document.querySelector('.day-bead');
              return { hidden: b.getAttribute('aria-hidden'),
                       events: getComputedStyle(b).pointerEvents };
            }"""
        )
        assert got == {"hidden": "true", "events": "none"}

    def test_a_phone_has_no_hairline_so_no_bead(self, page, base_url):
        page.set_viewport_size({"width": 375, "height": 800})
        _at(page, base_url, "2026-11-04T12:00:00")
        assert (
            page.evaluate("getComputedStyle(document.querySelector('.day-bead')).display") == "none"
        )


# ── 6. the egg ────────────────────────────────────────────────────────────────


class TestEgg:
    def test_kronos_winds_the_logo_and_keeps_the_ride(self, page, base_url):
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector(".brand-logo", timeout=5000)
        got = page.evaluate(
            """() => {
              for (const ch of 'kronos') {
                document.body.dispatchEvent(
                  new KeyboardEvent('keydown', { key: ch, bubbles: true }));
              }
              const logo = document.querySelector('.brand-logo');
              return {
                wind: logo.classList.contains('logo-wind'),
                names: logo.getAnimations().map((a) => a.animationName),
              };
            }"""
        )
        assert got["wind"] is True, got
        assert got["names"] == ["logo-wind"], got
        page.wait_for_selector(".egg-emoji.egg-go", state="attached", timeout=3000)
        # one full turn, and it is gone again afterwards
        page.wait_for_function(
            "() => !document.querySelector('.brand-logo').classList.contains('logo-wind')",
            timeout=5000,
        )

    def test_other_words_leave_the_logo_alone(self, page, base_url):
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector(".brand-logo", timeout=5000)
        got = page.evaluate(
            """() => {
              for (const ch of 'kronoz') {
                document.body.dispatchEvent(
                  new KeyboardEvent('keydown', { key: ch, bubbles: true }));
              }
              return document.querySelector('.brand-logo').classList.contains('logo-wind');
            }"""
        )
        assert got is False


# ── 7. reduced motion ─────────────────────────────────────────────────────────


@pytest.fixture
def calm(page):
    page.emulate_media(reduced_motion="reduce")
    return page


class TestReducedMotion:
    def test_the_number_is_simply_there(self, calm, base_url):
        page = calm
        _entry(base_url, "2026-07-20")
        _entry(base_url, "2026-07-21")
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector(".hero-num .odo-reel", timeout=5000)
        # no waiting for a roll: the first read already has the end state, and nothing moves
        read = page.evaluate(READ_ODO, ".hero-num .odo")
        assert read["shown"] == "+2.00h", read
        assert read["busy"] == 0, read
        assert page.locator(".hero-num").inner_text() == "+2.00h"
        assert (
            page.evaluate(
                "getComputedStyle(document.querySelector('.odo-reel i')).transitionDuration"
            )
            == "0s"
        )

    def test_the_seal_and_the_toast_still_say_it_and_nothing_stamps(self, calm, base_url):
        page = calm
        days = _week(LAST_MONDAY, 5)
        for d in days[:4]:
            _entry(base_url, d)
        _open_log(page, base_url)
        _watch_ribbon(page)
        _watch_stamps(page)
        _save_new_day(page, days[4])
        shown = _ribbon(page, f"{_wk(LAST_MONDAY)} sealed")
        assert shown[-1]["msg"] == f"{_wk(LAST_MONDAY)} sealed +5.00h"
        assert any(r["seal"] == _wk(LAST_MONDAY) for r in shown), shown
        page.wait_for_selector(".save-ribbon.ribbon-show .ribbon-seal", timeout=5000)
        assert page.evaluate("document.querySelector('.ribbon-seal').getAnimations().length") == 0
        assert page.evaluate("window.__stamps") == {}

    def test_no_coins_fly(self, calm, base_url):
        page = calm
        _payout_setup(base_url)
        _open_days_freelance(page, base_url)
        page.evaluate(WATCH_COINS)
        page.locator(f"input[aria-label='Payout Local {_wk(LAST_MONDAY)}']").fill("150")
        page.wait_for_function(
            "() => document.querySelector(\"[data-testid='days-fl-total']\")"
            ".innerText.includes('€150.00')",
            timeout=8000,
        )
        page.wait_for_timeout(400)
        got = page.evaluate("window.__coins")
        assert got["added"] == 0 and got["bumps"] == 0, got

    def test_the_bead_jumps_and_the_logo_stays(self, calm, base_url):
        page = calm
        _at(page, base_url, "2026-11-04T12:00:00")
        assert (
            page.evaluate(
                "getComputedStyle(document.querySelector('.day-bead')).transitionDuration"
            )
            == "0s"
        )
        got = page.evaluate(
            """() => {
              for (const ch of 'kronos') {
                document.body.dispatchEvent(
                  new KeyboardEvent('keydown', { key: ch, bubbles: true }));
              }
              const logo = document.querySelector('.brand-logo');
              return { names: logo.getAnimations().map((a) => a.animationName) };
            }"""
        )
        assert got["names"] == [], got
