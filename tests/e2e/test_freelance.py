"""E2E: freelance hours next to the working day, and what they add up to.

Nothing freelance is on the page until an income source exists; then the tab, the dashboard
card, the Log panel and the Analytics switches appear. The Log panel adds, edits and removes
a block (with Undo) without touching the employee entry; the Freelance tab shows the year and
its 130s; the calculator reproduces the side-job anchor of tests/unit/test_tax.py to the cent
through the browser; Settings has two levels, as dropdowns on the phone.
"""

from __future__ import annotations

import datetime

import httpx
import pytest

pytestmark = pytest.mark.e2e


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")
        for t in c.get("/api/freelance/tax-years").json():
            c.delete(f"/api/freelance/tax-years/{t['year']}")
        c.put(
            "/api/config",
            json={
                "daily_target_hours": 8,
                "vacation_budget_days": 0,
                "freelance_hours_per_week": 0,
                "freelance_days_off": 0,
            },
        )


@pytest.fixture(autouse=True)
def _clean(base_url):
    _wipe(base_url)
    yield
    _wipe(base_url)


def _source(base_url: str, name="Local", rate=60, currency="EUR") -> int:
    with httpx.Client(base_url=base_url) as c:
        r = c.post(
            "/api/freelance/sources",
            json={"name": name, "hourly_rate": rate, "currency": currency},
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]


def _block(base_url: str, **body) -> dict:
    with httpx.Client(base_url=base_url) as c:
        r = c.post("/api/freelance/blocks", json=body)
        assert r.status_code == 201, r.text
        return r.json()


def _open_log_day(page, base_url: str, iso: str) -> None:
    page.goto(f"{base_url}/#log")
    page.wait_for_selector(".log-cal-day:not(.log-cal-pad)", timeout=5000)
    page.evaluate(f"Alpine.$data(document.querySelector('main')).openDayInLog('{iso}')")
    page.wait_for_selector(f".log-cal-day[aria-label='{iso}'][aria-pressed='true']", timeout=5000)


TODAY = datetime.date.today()
YEAR = TODAY.year
MONDAY = TODAY - datetime.timedelta(days=TODAY.weekday())


# ── nothing until a source exists ─────────────────────────────────────────────


class TestOffUntilASourceExists:
    def test_five_tabs_no_card_no_panel(self, page, base_url):
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector(".hero-num", timeout=5000)
        tabs = page.locator("nav[role='tablist'] a[role='tab']")
        assert tabs.all_inner_texts() == ["Dashboard", "Plan", "Log", "Days", "Analytics"]
        assert page.locator("[data-testid='freelance-card']").count() == 0
        page.goto(f"{base_url}/#log")
        page.wait_for_selector(".log-cal-day:not(.log-cal-pad)", timeout=5000)
        assert page.locator("[data-testid='freelance-panel']").count() == 0
        # the tab's page itself points at Settings
        page.keyboard.press("f")
        page.wait_for_url("**/#freelance", timeout=3000)
        page.wait_for_selector(".fl-empty", timeout=3000)
        page.locator(".fl-empty a").click()
        page.wait_for_selector("#settings-sources", timeout=5000)

    def test_first_source_from_settings_unlocks_the_tab(self, page, base_url):
        page.goto(f"{base_url}/#settings")
        page.wait_for_selector(".settings-group-btn", timeout=5000)
        page.locator(".settings-group-btn", has_text="Freelance").click()
        page.wait_for_selector("#settings-sources", timeout=3000)
        assert "No sources yet" in page.locator("#settings-sources").inner_text()
        page.locator("#settings-sources input[aria-label='Source name']").fill("Northwind")
        page.locator("#settings-sources input[aria-label='Hourly rate']").fill("95")
        page.locator("#settings-sources select[aria-label='Currency']").select_option("USD")
        page.locator("#settings-sources button[type='submit']").click()
        page.wait_for_selector(
            ".save-ribbon.ribbon-show:has-text('First income source')", timeout=5000
        )
        page.wait_for_selector(".src-item", timeout=3000)
        row = page.locator(".src-item").first.inner_text()
        assert "Northwind" in row and "$95.00/h" in row and "default" in row.lower()
        page.wait_for_selector("a.tab-freelance", timeout=3000)
        assert page.locator("nav[role='tablist'] a[role='tab']").count() == 6


# ── the Log panel ─────────────────────────────────────────────────────────────


class TestLogPanel:
    def test_add_edit_remove_and_undo_a_block_on_a_logged_day(self, page, base_url):
        _source(base_url)  # 60 EUR/h
        iso = MONDAY.isoformat()
        with httpx.Client(base_url=base_url) as c:
            r = c.post(
                "/api/entries",
                json={
                    "date": iso,
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "18:00",
                    "breaks": [{"break_minutes": 60}],
                },
            )
            assert r.status_code == 201
        _open_log_day(page, base_url, iso)
        page.wait_for_function(
            "d => Alpine.$data(document.querySelector('main')).editingDate === d",
            arg=iso,
            timeout=5000,
        )
        panel = page.locator("[data-testid='freelance-panel']")
        assert panel.is_visible()
        assert "add freelance" in page.locator(".fl-jump").inner_text()
        # no blocks yet: the panel head carries no "nothing yet" note (the form says it all)
        assert "nothing yet" not in panel.inner_text()
        assert page.locator(".fl-head .fl-total").count() == 0

        # two quarter hours up from 1h, a note, Add: the row, the total and the chip appear
        page.locator(".fl-step[aria-label='Quarter hour more']").click()
        page.locator(".fl-step[aria-label='Quarter hour more']").click()
        assert "€90.00" in page.locator(".fl-preview").inner_text()  # 1.5 x 60
        page.locator(".fl-editor input[aria-label='Block note']").fill("evening fix")
        page.locator(".fl-submit").click()
        page.wait_for_selector(".save-ribbon.ribbon-show:has-text('Block added')", timeout=5000)
        page.wait_for_selector(".fl-block", timeout=3000)
        row = page.locator(".fl-block").first.inner_text()
        assert "Local" in row and "1.5h" in row and "€90.00" in row and "evening fix" in row
        assert "1.5h · €90.00" in page.locator(".fl-total").inner_text()
        assert "1.5h · €90.00" in page.locator(".fl-jump").inner_text()
        assert "has-fl" in (
            page.locator(f".log-cal-day[aria-label='{iso}']").get_attribute("class") or ""
        )
        # the employee's day did not move
        assert page.locator(".impact-card").inner_text().count("8h") >= 1
        with httpx.Client(base_url=base_url) as c:
            e = c.get(f"/api/entries/{iso}").json()
            assert (e["net_hours"], e["surplus_hours"]) == (8.0, 0.0)

        # edit: a quarter hour less, by times instead
        page.locator(".fl-block .fl-icon").first.click()
        page.wait_for_selector(".fl-card--editing", timeout=3000)
        assert page.locator(".fl-editor-row--adv input[aria-label='Rate']").input_value() == "60"
        page.locator(".fl-by", has_text="Start – end").click()
        page.locator("input[aria-label='Block start']").fill("18:00")
        page.locator("input[aria-label='Block end']").fill("19:15")
        page.locator(".fl-submit").click()
        page.wait_for_selector(".save-ribbon.ribbon-show:has-text('Block saved')", timeout=5000)
        page.wait_for_function(
            "() => document.querySelector('.fl-block')?.innerText.includes('18:00–19:15')",
            timeout=3000,
        )
        assert "€75.00" in page.locator(".fl-block").first.inner_text()  # 1.25 x 60

        # remove, then Undo from the ribbon
        page.locator(".fl-block .fl-icon--x").first.click()
        page.wait_for_function(
            "() => document.querySelectorAll('.fl-block').length === 0", timeout=3000
        )
        page.wait_for_selector(".ribbon-action:has-text('Undo')", timeout=3000)
        page.locator(".ribbon-action").click()
        page.wait_for_selector(".fl-block", timeout=3000)
        with httpx.Client(base_url=base_url) as c:
            blocks = c.get("/api/freelance/blocks").json()
        assert len(blocks) == 1
        assert (blocks[0]["start_time"], blocks[0]["hours"], blocks[0]["rate"]) == (
            "18:00",
            1.25,
            60,
        )

    def test_a_block_on_a_day_without_an_entry(self, page, base_url):
        """A Saturday of freelance work needs no employee entry, and creates none."""
        _source(base_url)
        saturday = (MONDAY + datetime.timedelta(days=5)).isoformat()
        _open_log_day(page, base_url, saturday)
        page.wait_for_selector(".btn-action:has-text('Create entry')", timeout=5000)
        page.locator(".fl-submit").click()
        page.wait_for_selector(".fl-block", timeout=5000)
        with httpx.Client(base_url=base_url) as c:
            assert c.get(f"/api/entries/{saturday}").status_code == 404
            assert len(c.get("/api/freelance/blocks").json()) == 1


# ── dashboard ─────────────────────────────────────────────────────────────────


class TestDashboardCard:
    def test_card_week_month_set_aside_and_strip_marker(self, page, base_url):
        src = _source(base_url)
        with httpx.Client(base_url=base_url) as c:
            c.put(f"/api/freelance/tax-years/{YEAR}", json={"year": YEAR, "set_aside_share": 0.3})
        _block(base_url, date=MONDAY.isoformat(), source_id=src, hours=2)  # 120 EUR this week
        page.goto(f"{base_url}/#dashboard")
        card = page.locator("[data-testid='freelance-card']")
        card.wait_for(timeout=5000)
        page.wait_for_function(
            "() => document.querySelector('[data-testid=freelance-card]').innerText"
            ".includes('30%')",
            timeout=5000,
        )
        text = card.inner_text()
        assert "€120.00" in text and "2h" in text
        assert "€36.00" in text  # 30% of the month's 120
        assert (
            page.locator(f".wd[aria-label*='{MONDAY.isoformat()}'] .wd-fl").inner_text() == "⚡2h"
        )
        # the employee hero is untouched: nothing logged, so ±0
        assert page.locator(".hero-num").inner_text().startswith("±0.00")
        card.click()
        page.wait_for_url("**/#freelance", timeout=3000)


# ── the Freelance tab ─────────────────────────────────────────────────────────


class TestFreelanceTab:
    def test_year_quarters_projection_and_the_calculator_anchor(self, page, base_url):
        src = _source(base_url, "Northwind", 100, "USD")
        with httpx.Client(base_url=base_url) as c:
            c.put(
                f"/api/freelance/tax-years/{YEAR}",
                json={"year": YEAR, "salary_annual": 55000, "gestoria_annual": 600},
            )
        # 2h at $100 with a hand rate of $1.25: 160 EUR, in the running quarter
        _block(base_url, date=TODAY.isoformat(), source_id=src, hours=2, fx_rate=1.25)
        page.goto(f"{base_url}/#freelance")
        page.wait_for_selector("[data-testid='fl-gross']", timeout=5000)
        page.wait_for_function(
            "() => document.querySelector('[data-testid=fl-gross]').innerText === '€160.00'",
            timeout=5000,
        )
        cap = page.locator(".fl-hero .hero-cap").inner_text()
        assert "2h" in cap and "€80.00/h" in cap
        quarters = page.locator("[data-testid='fl-quarters'] .fl-q")
        assert quarters.count() == 4
        assert page.locator(".fl-q--current").count() == 1
        assert "running" in page.locator(".fl-q--current").inner_text().lower()
        assert "Jan 30" in quarters.nth(3).inner_text()  # the fourth 130 falls in January
        proj = page.locator("[data-testid='fl-projection']")
        assert "Nothing planned" in proj.inner_text()
        # planning hours a week from the ledger saves the setting and moves the projection
        proj.locator("input[aria-label='Planned hours a week']").fill("5")
        proj.locator("input[aria-label='Planned hours a week']").dispatch_event("change")
        page.wait_for_function(
            "() => document.querySelector('[data-testid=fl-projection]').title"
            ".includes('still to bill')",
            timeout=5000,
        )
        with httpx.Client(base_url=base_url) as c:
            assert c.get("/api/config").json()["freelance_hours_per_week"] == 5

        # the calculator: the side-job anchor — $100/h, 2 h a day, 220 days, 55,000 salary,
        # 600 gestoría at 1.1172 -> 19,938.23 net (tests/unit/test_tax.py, by hand). The calculator
        # writes Spanish decimals (€19.938,23), the rest of the app €19,938.23.
        calc = page.locator("[data-testid='fl-calc']")
        calc.locator(".seg-toggle[aria-label='Currency'] button", has_text="USD").click()
        calc.locator("input[aria-label='Exchange rate']").fill("1.1172")
        calc.locator(".seg-toggle[aria-label='Billable days'] button", has_text="220").click()
        calc.locator("input[aria-label='Hours per day']").fill("2")
        calc.locator("input[aria-label='Salary']").fill("55000")
        calc.locator("input[aria-label='Gestoría']").fill("600")
        calc.locator("input[aria-label='Other expenses']").fill("0")
        calc.locator("input[aria-label='Hourly rate']").fill("100")
        page.wait_for_function(
            "() => document.querySelector('[data-testid=calc-net]')?.innerText === '€19.938,23'",
            timeout=5000,
        )
        assert calc.locator("input[aria-label='Daily rate']").input_value() == "200"
        out = calc.locator(".calc-out").inner_text()
        assert "€13.410,64" in out  # the IRPF
        assert "4 × €1.584,07" in out  # the 130, four times (6336.29 / 4)
        assert "€7.074,36" in out  # the Renta
        assert "€1.562,23" in out  # the pluriactividad refund
        assert "€19.938,23" in out and "€19,938.23" not in out  # one style inside the calculator
        assert "check with an adviser" in out
        assert calc.locator(".calc-seg--net").count() == 1
        # net drives the rate back: the full-time anchor (8 h, no salary) from its net
        calc.locator("input[aria-label='Hours per day']").fill("8")
        calc.locator("input[aria-label='Salary']").fill("0")
        page.wait_for_function(
            "() => !Alpine.$data(document.querySelector('main')).calc.busy", timeout=10000
        )
        calc.locator("input[aria-label='Net yearly']").fill("93423.21")
        page.wait_for_function(
            "() => document.querySelector('[data-testid=fl-calc] input[aria-label=\"Daily rate\"]')"
            ".value === '800'",
            timeout=10000,
        )
        assert calc.locator("input[aria-label='Hourly rate']").input_value() == "100"


# ── analytics ─────────────────────────────────────────────────────────────────


class TestAnalytics:
    def test_heatmap_switch_stacked_bars_income_mode_and_ledger(self, page, base_url):
        src = _source(base_url)
        d = datetime.date(YEAR, 3, 3)
        with httpx.Client(base_url=base_url) as c:
            r = c.post(
                "/api/entries",
                json={
                    "date": d.isoformat(),
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "17:00",
                },
            )
            assert r.status_code == 201
        _block(base_url, date=d.isoformat(), source_id=src, hours=3)  # 180 EUR
        _block(base_url, date=datetime.date(YEAR, 3, 7).isoformat(), source_id=src, hours=1)
        page.goto(f"{base_url}/#analytics")
        page.wait_for_selector(".an-chart", timeout=5000)
        page.locator(".an-presets button", has_text="This year").click()
        ledger = page.locator("[data-testid='an-freelance']")
        ledger.wait_for(timeout=5000)
        text = ledger.inner_text()
        assert "€240.00" in text and "4h" in text and "€60.00" in text
        # the heatmap switch
        page.locator(".page-head .hm-switch button", has_text="Freelance").click()
        sel = f".hm-cell[data-date='{d.isoformat()}']"
        cell = page.locator(sel)
        page.wait_for_function(
            f"() => document.querySelector({sel!r}).classList.contains('hm-fl-3')",
            timeout=3000,
        )
        assert "hm-fl" in (cell.get_attribute("class") or "")
        cell.hover()
        page.wait_for_selector(".hm-tip .hm-tip-fl", timeout=3000)
        assert "Local · 3h · €180.00" in page.locator(".hm-tip").inner_text()
        page.locator(".page-head .hm-switch button", has_text="Employee").click()
        page.wait_for_function(
            f"() => document.querySelector({sel!r}).classList.contains('hm-neutral')",
            timeout=3000,
        )
        # per day: the freelance hours stacked on the employee's bar, and alone on the Saturday
        page.locator(".an-chart-head .seg-toggle button", has_text="Per day").click()
        page.wait_for_selector(".an-bar-fl", timeout=3000)
        assert page.locator(".an-bar-fl").count() == 2
        # income per month
        page.locator(".an-chart-head .seg-toggle button", has_text="Income").click()
        page.wait_for_function(
            "() => document.querySelectorAll('.an-bar-fl').length === 1", timeout=3000
        )
        assert "€240" in page.locator(".an-bar-lbl").text_content()
        # the freelance export is a pill in the head, not a block at the bottom
        head = page.locator(".page-head .page-head-controls")
        assert head.get_by_role("button", name="Freelance CSV", exact=True).count() == 1

    def test_heatmap_tooltip_escapes_the_source_name(self, page, base_url):
        d = datetime.date(YEAR, 3, 6)
        src = _source(base_url, name="<img src=x onerror=window.__xss=1>")
        _block(base_url, date=d.isoformat(), source_id=src, hours=2)
        page.goto(f"{base_url}/#analytics")
        page.wait_for_selector(".an-chart", timeout=5000)
        page.locator(".an-presets button", has_text="This year").click()
        page.locator(".page-head .hm-switch button", has_text="Freelance").click()
        page.locator(f".hm-cell[data-date='{d.isoformat()}']").hover()
        page.wait_for_selector(".hm-tip .hm-tip-fl", timeout=3000)
        assert "<img src=x" in page.locator(".hm-tip").inner_text()
        assert page.locator(".hm-tip img").count() == 0
        assert page.evaluate("() => window.__xss") is None


# ── settings on the phone ─────────────────────────────────────────────────────


class TestSettingsPhone:
    def test_two_dropdowns_drive_the_two_levels(self, browser, base_url):
        ctx = browser.new_context(viewport={"width": 390, "height": 844})
        page = ctx.new_page()
        try:
            page.goto(f"{base_url}/#settings")
            page.wait_for_selector(".settings-dropdowns select", timeout=5000)
            assert not page.locator(".settings-index").is_visible()
            selects = page.locator(".settings-dropdowns select")
            selects.nth(0).select_option("freelance")
            page.wait_for_selector("#settings-taxes", timeout=3000)
            assert page.locator("#settings-work").count() == 0
            assert [o.inner_text() for o in selects.nth(1).locator("option").all()] == [
                "Sources",
                "Taxes",
                "Projection",
                "Currency",
            ]
            selects.nth(1).select_option("currency")
            page.wait_for_function(
                "() => document.querySelector('.settings-dropdowns select:nth-child(2)').value"
                " === 'currency'",
                timeout=3000,
            )
            assert page.locator(".fx-pill").count() == 1  # the ECB rate is asked for on this view
        finally:
            ctx.close()


# ── the UX round: the Log strip, Days · ⚡ Freelance, the Analytics pin ─────────


class TestLogStrip:
    def test_year_strip_picks_the_month_and_back_keeps_it(self, page, base_url):
        sep15 = datetime.date(YEAR, 9, 15).isoformat()
        with httpx.Client(base_url=base_url) as c:
            r = c.post(
                "/api/entries",
                json={
                    "date": sep15,
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "17:00",
                },
            )
            assert r.status_code == 201
        page.goto(f"{base_url}/#log")
        page.wait_for_selector(".log-strip .plan-mini", timeout=5000)
        # no month arrows, no month title: the strip is the navigation
        assert page.locator(".log-cal .log-cal-nav").count() == 0
        assert page.locator(".log-cal .log-cal-title").count() == 0
        assert page.locator(".log-strip .plan-mini").count() == 12
        page.locator(f".log-strip .plan-mini[aria-label='Sep {YEAR}']").click()
        page.wait_for_selector(f".log-cal-day[aria-label='{sep15}']", timeout=3000)
        assert "active" in (
            page.locator(".log-strip .plan-mini").nth(8).get_attribute("class") or ""
        )
        # the Employee card is titled; the freelance panel needs a source
        assert "Employee" in page.locator(".log-form-card .card-title").inner_text()
        # editing a day, then a click on it: the calendar stays in September
        page.locator(f".log-cal-day[aria-label='{sep15}']").click()
        page.wait_for_function(
            "d => Alpine.$data(document.querySelector('main')).editingDate === d",
            arg=sep15,
            timeout=5000,
        )
        page.locator(f".log-cal-day[aria-label='{sep15}']").click()
        page.wait_for_selector(".btn-action:has-text('Create entry')", timeout=3000)
        assert "active" in (
            page.locator(".log-strip .plan-mini").nth(8).get_attribute("class") or ""
        )
        assert page.locator(f".log-cal-day[aria-label='{sep15}']").count() == 1
        # the year switch in the header
        page.locator(".log-header-controls button[aria-label='Previous year']").click()
        page.wait_for_function(
            "() => document.querySelector('.log-header-controls .year-step-v').innerText"
            f" === '{YEAR - 1}'",
            timeout=3000,
        )
        assert page.locator(f".log-cal-day[aria-label='{YEAR - 1}-09-15']").count() == 1


class TestDaysFreelance:
    def test_the_year_stays_at_the_right_edge_on_a_phone(self, page, base_url):
        _source(base_url, "Local", 60, "EUR")
        page.set_viewport_size({"width": 375, "height": 800})
        for tab in ("days", "analytics"):
            page.goto(f"{base_url}/#{tab}")
            page.wait_for_selector(".page-head .hm-switch", timeout=5000)
            yr = page.locator(".page-head .year-step").bounding_box()
            head = page.locator(".page-head").bounding_box()
            # the year selector ends at the head's right edge, even when the head wraps and the
            # year lands on a row of its own
            assert (head["x"] + head["width"]) - (yr["x"] + yr["width"]) < 2, (tab, yr, head)

    def test_subtabs_source_filter_totals_and_the_pdf_picker(self, page, base_url):
        usd = _source(base_url, "Northwind", 95, "USD")
        eur = _source(base_url, "Local", 60, "EUR")
        d1, d2 = datetime.date(YEAR, 3, 3), datetime.date(YEAR, 3, 7)
        _block(
            base_url, date=d1.isoformat(), source_id=usd, hours=2, fx_rate=1.25, notes="api"
        )  # 152 EUR
        _block(base_url, date=d2.isoformat(), source_id=eur, hours=1.5)  # 90 EUR
        with httpx.Client(base_url=base_url) as c:
            c.post(
                "/api/entries",
                json={
                    "date": d1.isoformat(),
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "17:00",
                },
            )
        page.goto(f"{base_url}/#days")
        page.wait_for_selector(".page-head .hm-switch", timeout=5000)
        tabs = page.locator(".page-head .hm-switch button")
        # named, not counted (the counts were noise); 👔 and ⚡ mark the two lives
        assert tabs.nth(0).inner_text().strip() == "👔 Employee"
        assert tabs.nth(1).inner_text().strip() == "⚡ Freelance"
        # the switch is the Analytics pill, in the head, just left of the year selector, and the
        # old strip under the title is gone
        assert page.locator(".subtabs").count() == 0
        sw = page.locator(".page-head .hm-switch").bounding_box()
        yr = page.locator(".page-head .year-all").bounding_box()
        assert sw["x"] + sw["width"] <= yr["x"] and abs(sw["y"] - yr["y"]) < 20
        page.goto(f"{base_url}/#analytics")
        page.wait_for_selector(".page-head .hm-switch", timeout=5000)
        sw2 = page.locator(".page-head .hm-switch").bounding_box()
        yr2 = page.locator(".page-head .year-step").bounding_box()
        assert sw2["x"] + sw2["width"] <= yr2["x"]
        # same height in the head on both pages: the switch does not move when you change page
        assert abs(sw2["y"] - sw["y"]) < 2, (sw, sw2)
        page.goto(f"{base_url}/#days")
        page.wait_for_selector(".page-head .hm-switch", timeout=5000)
        # the employee table: its week lines are always there, the day shows once the weeks are open
        assert page.locator(".days-table .day-row").count() == 0
        page.get_by_test_id("wk-expand-all").click()
        assert page.locator(".days-table .day-row").count() == 1
        # the open state is shared with the Freelance weeks: close them again
        page.get_by_test_id("wk-collapse-all").click()
        assert page.locator(".days-table .day-row").count() == 0
        tabs.nth(1).click()
        page.wait_for_selector("[data-testid='days-freelance']", timeout=3000)
        # the week lines are always there; the blocks show once the weeks are open
        assert page.locator(".days-table--fl .day-row").count() == 0
        page.get_by_test_id("wk-expand-all").click()
        assert page.locator(".days-table--fl .day-row").count() == 2
        total = page.locator("[data-testid='days-fl-total']")
        assert "€242.00" in total.inner_text() and "2 blocks" in total.inner_text()
        # untick a source: the rows, the total and the PDF follow
        page.locator(".frow", has_text="Northwind").locator("input").uncheck()
        page.wait_for_function(
            "() => document.querySelectorAll('.days-table--fl .day-row').length === 1", timeout=3000
        )
        assert "€90.00" in total.inner_text()
        page.locator(".frow-head a", has_text="none").click()
        page.wait_for_function(
            "() => document.querySelectorAll('.days-table--fl .day-row').length === 0", timeout=3000
        )
        assert "No source selected" in page.locator("[data-testid='days-freelance']").inner_text()
        page.locator(".frow-head a", has_text="all").click()
        page.wait_for_function(
            "() => document.querySelectorAll('.days-table--fl .day-row').length === 2", timeout=3000
        )
        # the note search applies to blocks too
        page.locator(".notes-search").fill("api")
        page.wait_for_function(
            "() => document.querySelectorAll('.days-table--fl .day-row').length === 1", timeout=3000
        )
        page.locator(".notes-search").fill("")
        # ⚡ PDF: the picker with the sources ticked, opening the freelance sheet in a new tab
        assert page.locator(".pdf-btn").inner_text() == "⚡ PDF"
        page.locator(".pdf-btn").click()
        page.wait_for_selector(".pdf-modal", timeout=3000)
        assert "Freelance timesheet" in page.locator(".pdf-modal h3").inner_text()
        assert page.locator(".pdf-sources input:checked").count() == 2
        page.locator(".pdf-sources .pdf-src", has_text="Local").locator("input").uncheck()
        page.locator(".pdf-preset", has_text="This year").click()
        with page.context.expect_page() as popup:
            page.locator(".pdf-modal button[type='submit']").click()
        sheet = popup.value
        sheet.wait_for_load_state()
        assert sheet.url.startswith(f"{base_url}/timesheet/freelance?")
        assert f"sources={usd}" in sheet.url and "detail=" not in sheet.url
        body = sheet.locator("main").inner_text()
        assert "Freelance timesheet" in body and "Northwind" in body and "Local" not in body
        assert "$190.00" in body and "€152.00" in body
        sheet.close()
        # a block's row opens its day in Log with the block in the editor
        page.locator(".days-table--fl .day-row").first.click()
        page.wait_for_url("**/#log", timeout=3000)
        page.wait_for_selector(".fl-card--editing", timeout=5000)
        assert page.locator(".fl-editor-row--adv input[aria-label='Rate']").input_value() in (
            "60",
            "95",
        )


class TestAnalyticsPin:
    def test_the_year_stays_at_hand_without_bouncing(self, page, base_url):
        """Scrolled slowly, a notch at a time: the page only ever goes down (the old sticky
        block shrank under the scroll and bounced back to the top), the full year scrolls away
        and a compact copy appears fixed at the top with the switch and the year."""
        d = datetime.date(YEAR, 3, 3).isoformat()
        with httpx.Client(base_url=base_url) as c:
            for i in range(3):
                c.post(
                    "/api/entries",
                    json={
                        "date": datetime.date(YEAR, 3, 3 + i).isoformat(),
                        "day_type": "work",
                        "start_time": "09:00",
                        "end_time": "18:00",
                    },
                )
        page.goto(f"{base_url}/#analytics")
        page.wait_for_selector(".an-glance .hm-cell", timeout=5000)
        bar = page.locator("[data-testid='an-pin']")
        assert not bar.is_visible()
        ys = []
        for _ in range(30):
            page.mouse.wheel(0, 40)
            page.wait_for_timeout(60)
            ys.append(page.evaluate("window.scrollY"))
        assert all(b >= a for a, b in zip(ys, ys[1:], strict=False)), ys
        assert ys[-1] > 400
        page.wait_for_function(
            "() => getComputedStyle(document.querySelector('[data-testid=an-pin]')).display"
            " !== 'none'",
            timeout=3000,
        )
        box = bar.bounding_box()
        assert box["y"] == 0 and box["height"] < 90
        # the pinned copy: 4px days, the switch and the year; the full year is still 13px
        assert page.locator(".heatmap--mini .hm-cell").first.bounding_box()["width"] == 4
        assert page.locator(".an-minibar .year-step").is_visible()
        assert page.locator(f".an-glance .hm-cell[data-date='{d}']").bounding_box()["width"] == 13
        # the year can change from the pinned copy
        page.locator(".an-minibar button[aria-label='Previous year']").click()
        page.wait_for_function(
            f"() => document.querySelector('.an-minibar .year-step-v').innerText === '{YEAR - 1}'",
            timeout=3000,
        )
        assert page.locator(".page-head .year-step-v").inner_text() == str(YEAR - 1)
        # a click on it goes back up to the full year, and it hides again
        page.locator(".an-minibar-title").click()
        page.wait_for_function("() => window.scrollY === 0", timeout=3000)
        page.wait_for_function(
            "() => getComputedStyle(document.querySelector('[data-testid=an-pin]')).display"
            " === 'none'",
            timeout=3000,
        )
        assert page.url.endswith("#analytics")


class TestHeadsAndShortcuts:
    def test_every_tab_has_the_same_head(self, page, base_url):
        _source(base_url)
        expected = {
            "dashboard": ("Dashboard", False),
            "plan": ("Plan", True),
            "log": ("Log", True),
            "days": ("Days", True),
            "analytics": ("Analytics", True),
            "freelance": ("Freelance", True),
            "settings": ("Settings", False),
        }
        for tab, (title, has_year) in expected.items():
            page.goto(f"{base_url}/#{tab}")
            head = page.locator("section .page-head").first
            head.wait_for(timeout=5000)
            assert title in head.locator("h2").inner_text(), tab
            steps = head.locator(".year-step")
            assert steps.count() == (1 if has_year else 0), tab
            if has_year:
                # the year sits in the middle of its pill
                pill = steps.bounding_box()
                value = steps.locator(".year-step-v").bounding_box()
                left = value["x"] - pill["x"]
                right = pill["x"] + pill["width"] - value["x"] - value["width"]
                assert abs(left - right) <= 1, tab
        # Days: no "N entries" count in the head any more
        page.goto(f"{base_url}/#days")
        page.wait_for_selector(".page-head", timeout=5000)
        assert page.locator(".days-count").count() == 0
        assert "entries" not in page.locator(".page-head").inner_text()

    def test_calculator_and_options_lead_to_each_other(self, page, base_url):
        _source(base_url)
        page.goto(f"{base_url}/#freelance")
        page.wait_for_selector("[data-testid='fl-calc']", timeout=5000)
        page.locator(".page-head .head-btn", has_text="Freelance options").click()
        page.wait_for_url("**/#settings", timeout=3000)
        page.wait_for_selector("#settings-taxes", timeout=3000)
        assert "Freelance" in page.locator(".settings-head h2").inner_text()
        page.locator("#tax-salary").fill("55000")
        page.locator(".settings-head .head-btn", has_text="calculator").click()
        page.wait_for_url("**/#freelance", timeout=3000)
        # the calculator starts from what was just changed, and is on screen
        page.wait_for_function(
            "() => document.querySelector('[data-testid=fl-calc] input[aria-label=Salary]')"
            "?.value === '55000'",
            timeout=5000,
        )
        page.wait_for_function(
            "() => Math.abs(document.getElementById('fl-calc').getBoundingClientRect().top) < 80",
            timeout=3000,
        )
        with httpx.Client(base_url=base_url) as c:
            assert c.get(f"/api/freelance/tax-years/{YEAR}").json()["salary_annual"] == 55000


# ── the shared page rules on Freelance and Plan ─────────────────────


class TestUiConsistency:
    def test_exports_live_in_the_head_and_the_calculator_head_is_lean(self, page, base_url):
        _source(base_url)
        page.goto(f"{base_url}/#freelance")
        page.wait_for_selector("[data-testid='fl-calc']", timeout=5000)
        head = page.locator("section .page-head").first
        # the pills are flex boxes, so their innerText puts the mark and the name on two lines
        pills = [" ".join(t.split()) for t in head.locator(".head-btn").all_inner_texts()]
        assert "⚡ Freelance CSV" in pills and "⚡ Payouts CSV" in pills
        for pill in head.locator("a.head-btn").all():
            assert pill.get_attribute("download") is not None
            assert pill.get_attribute("role") == "button"
        # no Export block at the bottom of the page
        assert page.get_by_role("heading", name="Export").count() == 0
        assert page.locator(".an-export").count() == 0
        # the Calculator head: only "Start from this year", and the options live in the head
        calc_head = page.locator(".calc-head")
        assert [t.strip() for t in calc_head.locator("button").all_inner_texts()] == [
            "Start from this year"
        ]
        assert "Freelance options" not in calc_head.inner_text()
        assert page.get_by_text("Freelance options").count() == 1

    def test_the_three_hints_are_gone_and_the_projection_keeps_its_figures(self, page, base_url):
        src = _source(base_url, "Local", 60)
        _block(base_url, date=TODAY.isoformat(), source_id=src, hours=2)
        with httpx.Client(base_url=base_url) as c:
            r = c.put("/api/config", json={"freelance_hours_per_week": 5})
            assert r.status_code == 200, r.text
        page.goto(f"{base_url}/#freelance")
        page.wait_for_selector("[data-testid='fl-calc']", timeout=5000)
        strip = page.locator("[data-testid='fl-projection']")
        page.wait_for_function(
            "() => !!document.querySelector('[data-testid=fl-projection]').title",
            timeout=5000,
        )
        # the hero no longer repeats the year
        assert "Billed" not in page.locator(".fl-hero .hero-label").inner_text()
        # the sentence is not visible, its figures are in the title
        assert "still to bill" not in strip.inner_text()
        title = strip.get_attribute("title")
        assert "still to bill over" in title and "weeks" in title and "/h" in title
        # the Calculator hint
        assert "hourly ⇄" not in page.locator("section").first.inner_text()
        assert page.locator(".calc-head .an-hint").count() == 0

    def test_page_level_titles_are_the_calculator_title(self, page, base_url):
        _source(base_url)
        page.goto(f"{base_url}/#freelance")
        page.wait_for_selector("[data-testid='fl-quarters']", timeout=5000)
        modelo = page.locator(".fl-quarters .an-head > h2")
        assert "Modelo 130" in modelo.inner_text()
        assert page.locator(".fl-quarters h3").count() == 0

        def size(loc):
            return loc.evaluate("e => getComputedStyle(e).fontSize")

        modelo_size = size(modelo)
        assert modelo_size == size(page.locator(".calc-head > h2"))
        # Plan: "Upcoming time off" follows the same rule
        page.goto(f"{base_url}/#plan")
        page.wait_for_selector(".plan-ledger", timeout=5000)
        ledger = page.locator(".plan-ledger .an-head > h2")
        assert "Upcoming time off" in ledger.inner_text()
        assert page.locator(".plan-ledger h3").count() == 0
        assert size(ledger) == modelo_size
        # and its empty state is one short line
        assert page.locator(".plan-ledger > p.muted").first.inner_text().strip() == (
            "No time off yet."
        )
