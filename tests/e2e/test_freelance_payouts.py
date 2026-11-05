"""E2E: weekly payouts in the browser.

A source pays a lump sum per ISO week; Days > Freelance has one compact line per week that
opens to a payout field per source. Whatever is typed there is what the week is worth in every
sum on screen (the Days "selected" total, the dashboard card), the Log card shows it read-only,
and a week without a payout looks as it always did.
"""

from __future__ import annotations

import datetime
import time

import httpx
import pytest

pytestmark = pytest.mark.e2e

TODAY = datetime.date.today()
MONDAY = TODAY - datetime.timedelta(days=TODAY.weekday())
LAST_MONDAY = MONDAY - datetime.timedelta(days=7)
LAST_WEDNESDAY = LAST_MONDAY + datetime.timedelta(days=2)


def _wk(monday: datetime.date) -> str:
    return f"W{monday.isocalendar()[1]:02d}"


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


@pytest.fixture(autouse=True)
def _clean(base_url):
    _wipe(base_url)
    yield
    _wipe(base_url)


def _source(base_url: str, name="Local", rate=60, currency="EUR") -> int:
    with httpx.Client(base_url=base_url) as c:
        r = c.post(
            "/api/freelance/sources", json={"name": name, "hourly_rate": rate, "currency": currency}
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]


def _block(base_url: str, **body) -> dict:
    with httpx.Client(base_url=base_url) as c:
        r = c.post("/api/freelance/blocks", json=body)
        assert r.status_code == 201, r.text
        return r.json()


def _payout(base_url: str, **body) -> dict:
    with httpx.Client(base_url=base_url) as c:
        r = c.post("/api/freelance/payouts", json=body)
        assert r.status_code == 201, r.text
        return r.json()


def _payouts(base_url: str) -> list[dict]:
    with httpx.Client(base_url=base_url) as c:
        return c.get("/api/freelance/payouts").json()


def _wait_payouts(base_url: str, n: int, timeout=5.0) -> list[dict]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = _payouts(base_url)
        if len(got) == n:
            return got
        time.sleep(0.1)
    raise AssertionError(f"expected {n} payouts, API has {_payouts(base_url)}")


def _open_days_freelance(page, base_url: str) -> None:
    page.goto(f"{base_url}/#days")
    page.wait_for_selector(".page-head .hm-switch", timeout=5000)
    page.evaluate("Alpine.$data(document.querySelector('main')).daysYear = 'all'")
    page.locator(".page-head .hm-switch button").nth(1).click()
    page.wait_for_selector("[data-testid='days-freelance']", timeout=3000)


def _week_row(page, monday: datetime.date):
    return page.locator(f"tr.wk-row#wk-{monday.isoformat()}")


class TestPayoutsInDays:
    def test_typing_a_payout_saves_it_and_every_sum_follows(self, page, base_url):
        src = _source(base_url, "Local", 60)
        _block(base_url, date=MONDAY.isoformat(), source_id=src, hours=2)  # estimate EUR 120
        _open_days_freelance(page, base_url)
        row = _week_row(page, MONDAY)
        assert "estimated" in row.inner_text().lower()
        total = page.locator("[data-testid='days-fl-total']")
        assert "€120.00" in total.inner_text()

        # the current week starts open: its payout field is there
        field = page.locator("input[aria-label='Payout Local " + _wk(MONDAY) + "']")
        field.fill("150")
        got = _wait_payouts(base_url, 1)
        assert got[0]["amount"] == 150 and got[0]["week_start"] == MONDAY.isoformat()

        page.wait_for_function(
            "(id) => document.querySelector('#wk-' + id).textContent.includes('paid out')",
            arg=MONDAY.isoformat(),
            timeout=3000,
        )
        assert "estimated" not in row.inner_text().lower()
        page.wait_for_function(
            "() => document.querySelector(\"[data-testid='days-fl-total']\").innerText"
            ".includes('€150.00')",
            timeout=3000,
        )
        gap = page.locator(".wk-line", has_text="Local").locator(".wk-gap")
        assert gap.inner_text().strip() == "+€30"
        # the block row keeps its estimate, muted: it is not what counts any more
        cell = page.locator(".days-table--fl .day-row td.fl-est")
        assert cell.count() == 1 and "€120.00" in cell.inner_text()

        # the dashboard card counts the payout, not the block's estimate
        page.evaluate("Alpine.$data(document.querySelector('main')).go('dashboard')")
        page.wait_for_function(
            "() => document.querySelector(\"[data-testid='freelance-card']\")"
            "?.innerText.includes('€150.00')",
            timeout=5000,
        )

    def test_clearing_a_payout_deletes_it_and_undo_brings_it_back(self, page, base_url):
        src = _source(base_url, "Local", 60)
        _block(base_url, date=MONDAY.isoformat(), source_id=src, hours=2)
        _payout(base_url, source_id=src, week_start=MONDAY.isoformat(), amount=150)
        _open_days_freelance(page, base_url)
        field = page.locator("input[aria-label='Payout Local " + _wk(MONDAY) + "']")
        assert field.input_value() == "150"

        field.fill("")
        _wait_payouts(base_url, 0)
        page.wait_for_selector(".save-ribbon.ribbon-show:has-text('Payout deleted')", timeout=3000)
        assert "estimated" in _week_row(page, MONDAY).inner_text().lower()
        page.wait_for_function(
            "() => document.querySelector(\"[data-testid='days-fl-total']\").innerText"
            ".includes('€120.00')",
            timeout=3000,
        )

        page.locator(".ribbon-action").click()
        got = _wait_payouts(base_url, 1)
        assert got[0]["amount"] == 150
        page.wait_for_function(
            "() => document.querySelector(\"[data-testid='days-fl-total']\").innerText"
            ".includes('€150.00')",
            timeout=3000,
        )

    def test_unpaid_weeks_are_estimated_and_old_ones_await_a_payout(self, page, base_url):
        src = _source(base_url, "Local", 60)
        _block(base_url, date=MONDAY.isoformat(), source_id=src, hours=1)
        _block(base_url, date=LAST_WEDNESDAY.isoformat(), source_id=src, hours=1)
        _open_days_freelance(page, base_url)
        now, old = _week_row(page, MONDAY), _week_row(page, LAST_MONDAY)
        assert "estimated" in now.inner_text().lower() and "awaiting payout" not in now.inner_text()
        assert "estimated" in old.inner_text().lower() and "awaiting payout" in old.inner_text()

        # a closed week still lists its blocks
        assert page.locator(".days-table--fl .day-row").count() == 2
        assert old.locator(".wk-head").get_attribute("aria-expanded") == "false"
        assert page.locator("tr.wk-lines").count() == 1  # only the current week is open
        old.locator(".wk-head").click()
        assert old.locator(".wk-head").get_attribute("aria-expanded") == "true"
        assert page.locator("tr.wk-lines").count() == 2
        page.locator("[data-testid='wk-collapse-all']").click()
        assert page.locator("tr.wk-lines").count() == 0
        assert page.locator(".days-table--fl .day-row").count() == 2
        page.locator("[data-testid='wk-expand-all']").click()
        assert page.locator("tr.wk-lines").count() == 2

    def test_a_payout_for_a_week_without_hours_counts_on_its_own(self, page, base_url):
        src = _source(base_url, "Local", 60)
        _payout(base_url, source_id=src, week_start=LAST_MONDAY.isoformat(), amount=400)
        _open_days_freelance(page, base_url)
        row = _week_row(page, LAST_MONDAY)
        assert "paid out" in row.inner_text().lower()
        page.locator("[data-testid='wk-expand-all']").click()
        assert "payout with no hours" in page.locator("tr.wk-lines").inner_text()
        total = page.locator("[data-testid='days-fl-total']")
        assert "€400.00" in total.inner_text()
        # the source filter applies to the week too
        page.locator(".frow", has_text="Local").locator("input").uncheck()
        page.wait_for_function("() => !document.querySelector('tr.wk-row')", timeout=3000)

    def test_a_usd_payout_shows_its_rate_and_the_pencil_saves_a_new_one(self, page, base_url):
        src = _source(base_url, "Northwind", 60, "USD")
        _block(base_url, date=MONDAY.isoformat(), source_id=src, hours=1, fx_rate=1.2)  # $60
        _payout(base_url, source_id=src, week_start=MONDAY.isoformat(), amount=100, fx_rate=1.25)
        _open_days_freelance(page, base_url)
        line = page.locator(".wk-line", has_text="Northwind")
        assert "@ 1.2500" in line.inner_text() and "= €80" in line.inner_text()
        assert line.locator(".wk-gap").inner_text().strip() == "+$40"
        assert "€80.00" in page.locator("[data-testid='days-fl-total']").inner_text()

        line.locator(".pen").click()
        box = line.locator(".fxin")
        box.fill("1.6")
        box.press("Enter")
        end = time.monotonic() + 5
        while time.monotonic() < end and _payouts(base_url)[0]["fx_rate"] != 1.6:
            time.sleep(0.1)
        assert _payouts(base_url)[0]["fx_rate"] == 1.6
        page.wait_for_function(
            "() => document.querySelector('.wk-line').innerText.includes('@ 1.6000')", timeout=3000
        )
        assert "€62.50" in page.locator("[data-testid='days-fl-total']").inner_text()


class TestMonthsCountByDate:
    """A week across two months stays under its Monday's month; the money follows the dates."""

    def test_a_separator_sums_what_is_dated_in_its_month_like_the_freelance_tab(
        self, page, base_url
    ):
        src = _source(base_url, "Local", 60)
        # W40 of 2025 runs Mon Sep 29 - Sun Oct 5: one block in each month, paid 400 for the week
        _block(base_url, date="2025-09-30", source_id=src, hours=2)
        _block(base_url, date="2025-10-01", source_id=src, hours=2)
        _payout(base_url, source_id=src, week_start="2025-09-29", amount=400)
        _block(base_url, date="2025-10-08", source_id=src, hours=1)  # W41, listed under October
        with httpx.Client(base_url=base_url) as c:
            oct_gross = c.get("/api/freelance/summary?year=2025").json()["by_month"][9]["gross_eur"]
        assert oct_gross != 180  # the payout moved money: it is not the blocks' estimates

        _open_days_freelance(page, base_url)
        sep = page.locator("tr.month-sep", has_text="October 2025")
        assert f"€{oct_gross:,.2f}" in sep.inner_text()
        assert f"of it from {_wk(datetime.date(2025, 9, 29))}" in sep.inner_text()
        # W40 sits under September, which holds the payout's September share
        sep_sep = page.locator("tr.month-sep", has_text="September 2025")
        assert "€200.00" in sep_sep.inner_text()
        # and its week row says it splits, since its blocks fall in both months
        assert "splits Sep/Oct" in _week_row(page, datetime.date(2025, 9, 29)).inner_text()

    def test_a_week_inside_one_month_does_not_say_it_splits(self, page, base_url):
        src = _source(base_url, "Local", 60)
        # Mon Oct 27 - Sun Nov 2 2025 crosses a month, but both blocks are in October
        _block(base_url, date="2025-10-28", source_id=src, hours=1)
        _block(base_url, date="2025-10-30", source_id=src, hours=1)
        _open_days_freelance(page, base_url)
        assert "splits" not in _week_row(page, datetime.date(2025, 10, 27)).inner_text()


class TestPayoutOnTheLogCard:
    def test_the_card_shows_the_weeks_payout_and_links_to_it(self, page, base_url):
        src = _source(base_url, "Northwind", 60, "USD")
        _block(base_url, date=MONDAY.isoformat(), source_id=src, hours=1, fx_rate=1.2)
        _payout(base_url, source_id=src, week_start=MONDAY.isoformat(), amount=100, fx_rate=1.25)
        iso = MONDAY.isoformat()
        page.goto(f"{base_url}/#log")
        page.wait_for_selector(".log-cal-day:not(.log-cal-pad)", timeout=5000)
        page.evaluate(f"Alpine.$data(document.querySelector('main')).openDayInLog('{iso}')")
        page.wait_for_selector("[data-testid='fl-payout-line']", timeout=5000)
        line = page.locator("[data-testid='fl-payout-line']")
        assert f"{_wk(MONDAY)} payout $100" in line.inner_text()
        assert line.locator("input").count() == 0  # read-only here
        # the block row's amount is an estimate in a paid week: muted, and says so
        amt = page.locator(".fl-block .fl-amt")
        assert "fl-est" in (amt.get_attribute("class") or "")
        assert amt.get_attribute("title") == "estimate; the week's payout counts"

        # a day of another week has no such line
        other = (MONDAY - datetime.timedelta(days=1)).isoformat()
        page.evaluate(f"Alpine.$data(document.querySelector('main')).openDayInLog('{other}')")
        page.wait_for_function(
            "() => !document.querySelector(\"[data-testid='fl-payout-line']\")", timeout=3000
        )
        page.evaluate(f"Alpine.$data(document.querySelector('main')).openDayInLog('{iso}')")
        page.wait_for_selector("[data-testid='fl-payout-line']", timeout=5000)

        pill = page.locator("[data-testid='fl-payout-pill']")
        assert pill.evaluate("e => e.tagName") == "BUTTON"
        assert pill.inner_text().strip() == f"{_wk(MONDAY)} in Days"
        pill.focus()
        assert pill.evaluate("e => e === document.activeElement")
        page.keyboard.press("Enter")
        page.wait_for_selector("[data-testid='days-freelance']", timeout=5000)
        row = _week_row(page, MONDAY)
        row.wait_for(timeout=3000)
        assert row.locator(".wk-head").get_attribute("aria-expanded") == "true"
        assert page.locator("tr.wk-lines").count() >= 1


def _split_fixture(base_url: str) -> None:
    """This week: Local pays 150 for 2h (estimate 120), Side stays an estimate of 50 for 1h."""
    local = _source(base_url, "Local", 60)
    side = _source(base_url, "Side", 50)
    _block(base_url, date=TODAY.isoformat(), source_id=local, hours=2)
    _block(base_url, date=TODAY.isoformat(), source_id=side, hours=1)
    _payout(base_url, source_id=local, week_start=MONDAY.isoformat(), amount=150)


def _open_freelance_tab(page, base_url: str) -> None:
    page.goto(f"{base_url}/#freelance")
    page.wait_for_selector("[data-testid='fl-gross']", timeout=5000)


class TestPayoutSplitOnScreens:
    """Wherever a freelance total is shown it says how much is paid out and how much estimated."""

    def test_the_hero_splits_the_year_and_matches_the_summary(self, page, base_url):
        _split_fixture(base_url)
        with httpx.Client(base_url=base_url) as c:
            total = c.get(f"/api/freelance/summary?year={TODAY.year}").json()["total"]
        assert total["paid_out_eur"] == 150 and total["estimated_eur"] == 50
        _open_freelance_tab(page, base_url)
        split = page.locator("[data-testid='fl-split']")
        split.wait_for(timeout=5000)
        text = split.inner_text()
        # money reads with cents everywhere outside the charts: €150.00, not €150
        assert f"€{total['paid_out_eur']:,.2f} paid out" in text
        assert f"€{total['estimated_eur']:,.2f} estimated" in text
        # the big number stays the gross
        page.wait_for_function(
            "() => document.querySelector(\"[data-testid='fl-gross']\").innerText === '€200.00'",
            timeout=3000,
        )
        # the thin bar is 150 of 200
        width = page.locator(".fl-splitbar .p").evaluate("e => e.style.width")
        assert width == "75%"

    def test_a_month_bar_with_a_payout_has_both_parts_in_proportion(self, page, base_url):
        _split_fixture(base_url)
        _open_freelance_tab(page, base_url)
        page.wait_for_selector(".flm-est", timeout=5000)
        paid = page.locator(".flm-bar").first.evaluate("e => e.getBBox().height")
        est = page.locator(".flm-est").first.evaluate("e => e.getBBox().height")
        assert est > 0 and abs(paid / est - 3) < 0.05  # 150 against 50
        legend = page.locator(".fl-legend").inner_text()
        assert "paid out" in legend and "estimated" in legend

    def test_weeks_still_awaiting_a_payout_link_to_days(self, page, base_url):
        src = _source(base_url, "Local", 60)
        _block(base_url, date=LAST_WEDNESDAY.isoformat(), source_id=src, hours=1)
        other = _source(base_url, "Other", 60)
        _block(base_url, date=MONDAY.isoformat(), source_id=other, hours=1)
        _payout(base_url, source_id=other, week_start=MONDAY.isoformat(), amount=70)
        with httpx.Client(base_url=base_url) as c:
            n = c.get(f"/api/freelance/summary?year={TODAY.year}").json()["awaiting_payout"]
        assert n >= 1
        _open_freelance_tab(page, base_url)
        link = page.locator("[data-testid='fl-awaiting']")
        link.wait_for(timeout=5000)
        assert link.inner_text() == f"{n} week{'s' if n != 1 else ''} awaiting a payout"
        link.click()
        page.wait_for_selector("[data-testid='days-freelance']", timeout=5000)

    def test_the_dashboard_card_puts_estimated_and_paid_out_side_by_side(self, page, base_url):
        _split_fixture(base_url)
        page.goto(f"{base_url}/#dashboard")
        page.locator("[data-testid='freelance-card']").wait_for(timeout=5000)
        page.wait_for_selector("[data-testid='fl-dash-paid-week']", timeout=5000)
        # estimated: the blocks' own estimates (120 + 50); paid out: the payout (150)
        assert page.locator("[data-testid='fl-dash-est-week']").inner_text() == "€170.00"
        assert page.locator("[data-testid='fl-dash-paid-week']").inner_text() == "€150.00"
        # the gap is against the estimate of the paid part only (Local's 120), not Side's 50
        assert page.locator("[data-testid='fl-dash-gap-week']").inner_text() == "+€30 vs est."
        # two figures of equal weight
        est = page.locator("[data-testid='fl-dash-est-week']")
        paid = page.locator("[data-testid='fl-dash-paid-week']")
        assert est.evaluate("e => getComputedStyle(e).fontSize") == paid.evaluate(
            "e => getComputedStyle(e).fontSize"
        )
        assert est.evaluate("e => getComputedStyle(e).fontWeight") == paid.evaluate(
            "e => getComputedStyle(e).fontWeight"
        )
        assert page.locator("[data-testid='fl-dash-paid-month']").inner_text() == "€150.00"
        assert "paid out" in page.locator("[data-testid='freelance-card']").inner_text().lower()

    def test_a_week_without_a_payout_shows_a_dash_for_paid_out(self, page, base_url):
        src = _source(base_url, "Local", 60)
        _block(base_url, date=TODAY.isoformat(), source_id=src, hours=2)
        _block(base_url, date=LAST_WEDNESDAY.isoformat(), source_id=src, hours=1)
        _payout(base_url, source_id=src, week_start=LAST_MONDAY.isoformat(), amount=70)
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector("[data-testid='fl-dash-paid-week']", timeout=5000)
        assert page.locator("[data-testid='fl-dash-paid-week']").inner_text() == "—"
        assert page.locator("[data-testid='fl-dash-gap-week']").inner_text() == ""
        assert page.locator("[data-testid='fl-dash-est-week']").inner_text() == "€120.00"

    def test_paid_out_has_its_own_colour_apart_from_estimates(self, page, base_url):
        _split_fixture(base_url)

        def colour(sel):
            return page.locator(sel).first.evaluate("e => getComputedStyle(e).color")

        def token():
            return page.evaluate(
                "() => { const d = document.createElement('i'); d.style.color = 'var(--paid)';"
                " document.body.appendChild(d); const c = getComputedStyle(d).color;"
                " d.remove(); return c; }"
            )

        # dashboard
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector("[data-testid='fl-dash-paid-week']", timeout=5000)
        paid_token = token()
        assert paid_token not in ("", "rgba(0, 0, 0, 0)")
        assert colour("[data-testid='fl-dash-paid-week']") == paid_token
        assert colour("[data-testid='fl-dash-est-week']") != paid_token
        # the Freelance hero
        _open_freelance_tab(page, base_url)
        page.wait_for_selector("[data-testid='fl-split']", timeout=5000)
        assert colour(".fl-splitline .fl-sw.paid + b") == paid_token
        assert colour(".fl-splitline .fl-sw.est + b") != paid_token
        assert (
            page.locator(".flm-bar.paid").first.evaluate("e => getComputedStyle(e).fill")
            == paid_token
        )
        # Days: the tag of a fully paid week, against an estimated one
        _open_days_freelance(page, base_url)
        page.wait_for_selector(".wk-tag", timeout=3000)
        tags = page.locator(".wk-tag")
        assert tags.count() == 1  # one week, part paid out (Side is still an estimate)
        assert tags.first.evaluate("e => getComputedStyle(e).color") == paid_token
        assert colour(".wk-pay .payin:not(:placeholder-shown)") == paid_token

    def test_the_estimated_tag_keeps_its_muted_colour(self, page, base_url):
        src = _source(base_url, "Local", 60)
        _block(base_url, date=TODAY.isoformat(), source_id=src, hours=2)
        _open_days_freelance(page, base_url)
        tag = page.locator(".wk-tag.est").first
        tag.wait_for(timeout=3000)
        paid = page.evaluate(
            "() => { const d = document.createElement('i'); d.style.color = 'var(--paid)';"
            " document.body.appendChild(d); const c = getComputedStyle(d).color;"
            " d.remove(); return c; }"
        )
        assert tag.evaluate("e => getComputedStyle(e).color") != paid

    def test_the_blocks_of_a_week_hang_under_its_line(self, page, base_url):
        src = _source(base_url, "Local", 60)
        _block(base_url, date=MONDAY.isoformat(), source_id=src, hours=1)
        _block(base_url, date=MONDAY.isoformat(), source_id=src, hours=2)
        _open_days_freelance(page, base_url)
        page.wait_for_selector(".days-table--fl tr.blk", timeout=3000)
        chev_left = page.locator(f"tr.wk-row#wk-{MONDAY.isoformat()} .chev").bounding_box()["x"]
        date_lefts = page.locator(".days-table--fl tr.blk td:first-child").evaluate_all(
            "els => els.map(e => { const r = document.createRange(); r.selectNodeContents(e);"
            " return r.getBoundingClientRect().left; })"
        )
        assert len(date_lefts) == 2
        # the blocks' text starts well to the right of the week line's own start (>= 1rem)
        assert all(x - chev_left >= 16 for x in date_lefts)
        # the rail: drawn on the blocks, and the last one is marked so it stops there
        assert page.locator(".days-table--fl tr.blk-last").count() == 1
        rail = page.locator(".days-table--fl tr.blk td:first-child").first.evaluate(
            "e => getComputedStyle(e, '::before').borderLeftWidth"
        )
        assert rail == "1px"

    def test_the_analytics_ledger_lists_paid_out_and_estimated_for_a_range(self, page, base_url):
        _split_fixture(base_url)
        page.goto(f"{base_url}/#analytics")
        page.wait_for_selector(".an-chart", timeout=5000)
        page.locator(".an-presets button", has_text="This year").click()
        ledger = page.locator("[data-testid='an-freelance']")
        ledger.wait_for(timeout=5000)
        assert "€200.00" in ledger.inner_text()
        assert "€150.00" in page.locator("[data-testid='an-fl-paid']").inner_text()
        assert "€50.00" in page.locator("[data-testid='an-fl-est']").inner_text()

    def test_the_payouts_csv_downloads(self, page, base_url):
        _split_fixture(base_url)
        _open_freelance_tab(page, base_url)
        with page.expect_download() as dl:
            page.locator("[data-testid='payouts-csv']").click()
        path = dl.value.path()
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        assert dl.value.suggested_filename == "kronos_freelance_payouts.csv"
        assert len(lines) == 2 and lines[0].startswith("week_start") and "Local" in lines[1]

    def test_without_payouts_none_of_it_shows(self, page, base_url):
        src = _source(base_url, "Local", 60)
        _block(base_url, date=TODAY.isoformat(), source_id=src, hours=2)
        _open_freelance_tab(page, base_url)
        page.wait_for_selector(".flm-bar", timeout=5000)
        assert page.locator("[data-testid='fl-split']").count() == 0
        assert page.locator(".fl-awaiting").count() == 0
        assert page.locator(".flm-est").count() == 0
        assert page.locator(".fl-legend").count() == 0

        page.evaluate("Alpine.$data(document.querySelector('main')).go('dashboard')")
        page.locator("[data-testid='freelance-card']").wait_for(timeout=5000)
        # the card is exactly as it was: one figure per period, no estimated / paid out pair
        assert page.locator("[data-testid='fl-dash-pair-week']").count() == 0
        assert page.locator("[data-testid='fl-dash-paid-week']").count() == 0
        assert "paid out" not in page.locator("[data-testid='freelance-card']").inner_text().lower()

        page.goto(f"{base_url}/#analytics")
        page.wait_for_selector(".an-chart", timeout=5000)
        page.locator(".an-presets button", has_text="This year").click()
        page.locator("[data-testid='an-freelance']").wait_for(timeout=5000)
        assert page.locator("[data-testid='an-fl-paid']").count() == 0
        assert page.locator("[data-testid='an-fl-est']").count() == 0
