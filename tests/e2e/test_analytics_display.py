"""E2E: two Analytics display rules the user asked for on 2026-10-02.

WHY these tests exist:

* Weekday pattern — the per-weekday average under each swatch was unreadable:
  it carried the heatmap's ``hm-surplus`` class, which paints a *background*,
  plus ``muted``, which wins over the text colour. The number has to be text
  in the surplus/deficit colour on no background, or nobody can read it.
* Records — "Worst year" and "Most deficit month" only mean something when
  they are negative. With every month in surplus (or a single year of data)
  they showed a positive number in red, i.e. a "worst" that is not bad. The
  rule chosen: show each card only when its value is strictly negative; a
  zero or positive value hides the card. The API still returns both records.
"""

from __future__ import annotations

import datetime

import httpx
import pytest

pytestmark = pytest.mark.e2e

GATED_CARDS = ["Worst year", "Most deficit month"]


def _last_weekday(weekday: int) -> datetime.date:
    """Most recent past date (today excluded) falling on `weekday` (Mon=0)."""
    d = datetime.date.today() - datetime.timedelta(days=1)
    while d.weekday() != weekday:
        d -= datetime.timedelta(days=1)
    return d


def _entry(day: datetime.date, end: str) -> dict:
    # 09:00 to `end` with a 60-minute break against the default 8 h target:
    # "18:00" is exactly on target, "19:00" is +1 h, "17:00" is -1 h.
    return {
        "date": day.isoformat(),
        "day_type": "work",
        "start_time": "09:00",
        "end_time": end,
        "breaks": [{"break_minutes": 60}],
    }


def _seed(base_url: str, entries: list[dict]) -> None:
    with httpx.Client(base_url=base_url) as c:
        for body in entries:
            r = c.post("/api/entries", json=body)
            assert r.status_code == 201, f"seed failed: {r.text}"


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")


def _open_analytics(page, base_url: str) -> None:
    page.goto(f"{base_url}/#analytics")
    page.wait_for_selector(".hm-cell", timeout=10000)
    page.wait_for_selector(".weekday-cell", timeout=10000)


def _record_titles(page) -> list[str]:
    return page.locator("section[aria-label=Analytics] .summary-card h3").all_inner_texts()


class TestAnalyticsDisplay:
    @pytest.fixture(autouse=True)
    def _clean(self, base_url):
        _wipe(base_url)
        yield
        _wipe(base_url)

    def test_weekday_average_is_coloured_text_on_no_background(self, page, base_url):
        monday = _last_weekday(0)
        _seed(base_url, [_entry(monday, "19:00")])  # Monday average: +1h
        _open_analytics(page, base_url)

        avg = page.locator(".weekday-cell", has_text="Mon").locator(".weekday-avg")
        assert avg.inner_text() == "+1h"
        style = avg.evaluate(
            """el => {
                const probe = document.createElement('span');
                probe.className = 'surplus';
                el.parentElement.appendChild(probe);
                const want = getComputedStyle(probe).color;
                probe.remove();
                const cs = getComputedStyle(el);
                return { color: cs.color, background: cs.backgroundColor, want };
            }"""
        )
        assert style["background"] in ("rgba(0, 0, 0, 0)", "transparent"), style
        assert style["color"] == style["want"], style

    @pytest.mark.parametrize("end", ["19:00", "18:00"], ids=["surplus", "on-target"])
    def test_worst_cards_hidden_unless_negative(self, page, base_url, end):
        _seed(base_url, [_entry(_last_weekday(0), end), _entry(_last_weekday(1), end)])
        _open_analytics(page, base_url)

        titles = _record_titles(page)
        assert "Longest day" in titles, titles  # Records did render
        for card in GATED_CARDS:
            assert card not in titles, titles

    def test_worst_cards_shown_when_negative(self, page, base_url):
        _seed(base_url, [_entry(_last_weekday(0), "17:00")])  # -1h
        _open_analytics(page, base_url)

        titles = _record_titles(page)
        for card in GATED_CARDS:
            assert card in titles, titles
            metric = page.locator(".summary-card", has_text=card).locator(".metric")
            assert metric.inner_text().startswith("−"), metric.inner_text()
