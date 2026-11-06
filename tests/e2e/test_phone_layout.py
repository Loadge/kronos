"""E2E: what a phone must show (UI_GUIDE.md, "Look at it").

On a 375px screen the Days tables are two lines per row, so nothing scrolls sideways and nothing is
dropped; on Analytics the Range card follows the chart. A desktop screen keeps the wide table.
Rows are seeded here, because an empty table never shows a row that is too wide.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import httpx
import pytest

pytestmark = pytest.mark.e2e

PHONE = {"width": 375, "height": 800}
DESKTOP = {"width": 1280, "height": 900}
NOTE = "Dentist at eleven, then the long review with the whole team"


def _past_weekdays(n: int) -> list[str]:
    """The last `n` weekdays of this year, oldest first."""
    found, day = [], date.today()
    while len(found) < n:
        day -= timedelta(days=1)
        if day.weekday() < 5 and day.year == date.today().year:
            found.append(day.isoformat())
    return found[::-1]


@pytest.fixture
def days(base_url):
    """A worked day with breaks and a note (Net 7.5h, 0.5h short of the 8h target) and, after it,
    a vacation day. Yields (worked, vacation)."""
    worked, vacation = _past_weekdays(2)
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        r = c.post(
            "/api/entries",
            json={
                "date": worked,
                "day_type": "work",
                "start_time": "09:30",
                "end_time": "18:00",
                "breaks": [{"break_minutes": 60}],
                "notes": NOTE,
            },
        )
        assert r.status_code == 201, r.text
        entry = r.json()
        assert (entry["net_hours"], entry["surplus_hours"]) == (7.5, -0.5), entry
        r = c.post("/api/entries", json={"date": vacation, "day_type": "vacation"})
        assert r.status_code == 201, r.text
    yield worked, vacation
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        # the sources outlive /api/data, and a leftover one adds the Freelance tab everywhere
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


def _open_days(page, base_url: str, size: dict) -> None:
    page.set_viewport_size(size)
    page.goto(f"{base_url}/#days")
    page.wait_for_selector("tr.day-row", timeout=5000)
    page.wait_for_timeout(300)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _inside_the_screen(page, locator, width: int) -> None:
    box = locator.bounding_box()
    assert box is not None, "not drawn"
    assert box["x"] >= 0 and box["x"] + box["width"] <= width + 0.5, box


def test_a_worked_day_shows_its_numbers_and_its_note_on_a_phone(page, base_url, days):
    worked, _ = days
    _open_days(page, base_url, PHONE)
    row = page.locator(f"#day-row-{worked} tr.day-row")
    cells = row.locator("td")
    # line 1: date, weekday, type, Net, delta
    assert _squash(cells.nth(0).inner_text()) == worked
    assert _squash(cells.nth(6).inner_text()) == "7.5h"
    assert _squash(cells.nth(8).inner_text()) == "−0.50h"
    # line 2: times, breaks, the running total and the note
    sub = row.locator("td.day-sub")
    assert _squash(sub.inner_text()) == f"09:30-18:00 · 60m · Σ −0.50h · {NOTE}"
    # all of it is on the screen as it opens, with no scrolling in any direction
    for visible in (cells.nth(0), cells.nth(6), cells.nth(8), sub):
        assert visible.is_visible()
        _inside_the_screen(page, visible, PHONE["width"])
    assert page.evaluate("document.documentElement.scrollWidth") <= PHONE["width"]
    assert page.evaluate("document.querySelector('.days-wrap').scrollWidth") <= PHONE["width"]
    # the cells that line 2 replaced are not drawn
    assert not row.locator("td.notes-col").is_visible()
    assert not row.locator("td.act-col").is_visible()


def test_a_vacation_day_has_no_dashes_on_line_2(page, base_url, days):
    _, vacation = days
    _open_days(page, base_url, PHONE)
    sub = page.locator(f"#day-row-{vacation} td.day-sub")
    text = _squash(sub.inner_text())
    assert text == "Σ −0.50h", text
    assert "—" not in text and " - " not in text


def test_the_note_search_still_highlights_on_a_phone(page, base_url, days):
    worked, _ = days
    _open_days(page, base_url, PHONE)
    page.fill("input.notes-search", "dentist")
    page.wait_for_timeout(200)
    marked = page.locator(f"#day-row-{worked} td.day-sub mark")
    assert marked.count() == 1
    assert marked.inner_text().lower() == "dentist"


def test_a_freelance_block_is_two_lines_on_a_phone(page, base_url, days):
    worked, _ = days
    with httpx.Client(base_url=base_url) as c:
        r = c.post(
            "/api/freelance/sources",
            json={"name": "Northwind", "hourly_rate": 70, "currency": "USD"},
        )
        assert r.status_code == 201, r.text
        r = c.post(
            "/api/freelance/blocks",
            json={
                "date": worked,
                "source_id": r.json()["id"],
                "start_time": "19:00",
                "end_time": "20:30",
                "fx_rate": 1.1,
                "notes": "Evening call",
            },
        )
        assert r.status_code == 201, r.text
    page.set_viewport_size(PHONE)
    page.goto(f"{base_url}/#days")
    page.get_by_role("radio", name="Freelance").click()
    # the week of the block may be the only one, and open already: `+` is then aria-disabled
    page.get_by_test_id("wk-expand-all").click(force=True)
    row = page.locator("tr.blk").first
    row.wait_for(timeout=5000)
    line1 = _squash(" ".join(row.locator("td:visible:not(.day-sub)").all_inner_texts()))
    assert worked in line1 and "Northwind" in line1 and "1.5h" in line1 and "€95.45" in line1, line1
    sub = _squash(row.locator("td.day-sub").inner_text())
    assert sub == "19:00-20:30 · $70.00/h · $105.00 · Evening call", sub
    assert page.evaluate("document.querySelector('.days-wrap').scrollWidth") <= PHONE["width"]


def test_the_desktop_table_keeps_its_columns(page, base_url, days):
    worked, _ = days
    _open_days(page, base_url, DESKTOP)
    row = page.locator(f"#day-row-{worked} tr.day-row")
    assert not row.locator("td.day-sub").is_visible()
    notes = row.locator("td.notes-col")
    assert notes.is_visible()
    assert NOTE in notes.inner_text()
    assert page.locator("table.days-table thead").is_visible()


def test_the_range_card_follows_the_chart_on_a_phone(page, base_url, days):
    page.set_viewport_size(PHONE)
    page.goto(f"{base_url}/#analytics")
    page.wait_for_selector(".an-ledger", timeout=5000)
    page.wait_for_timeout(300)
    brush = page.locator(".an-brush").bounding_box()
    ledger = page.locator(".an-ledger").bounding_box()
    weekday = page.locator("#an-weekday-h").bounding_box()
    assert brush["y"] + brush["height"] <= ledger["y"] + 1, (brush, ledger)
    assert ledger["y"] + ledger["height"] <= weekday["y"] + 1, (ledger, weekday)


def test_the_years_table_fits_a_phone(page, base_url, days):
    page.set_viewport_size(PHONE)
    page.goto(f"{base_url}/#analytics")
    page.wait_for_selector(".an-years", timeout=5000)
    wrap = page.locator(".an-years").locator("xpath=..")
    assert wrap.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
