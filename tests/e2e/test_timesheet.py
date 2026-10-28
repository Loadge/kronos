"""E2E: the printable timesheet — Days → PDF picker, the page itself, Settings → Profile."""

from __future__ import annotations

import datetime

import httpx
import pytest

pytestmark = pytest.mark.e2e


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        c.put(
            "/api/config",
            json={
                "daily_target_hours": 8,
                "profile_name": "",
                "profile_employer": "",
                "profile_extra": "",
            },
        )


@pytest.fixture(autouse=True)
def _clean(base_url):
    _wipe(base_url)
    yield
    _wipe(base_url)


def _open_picker(page, base_url):
    page.goto(f"{base_url}/#days")
    page.wait_for_load_state("networkidle")
    page.evaluate("localStorage.removeItem('k-pdf-options')")
    page.wait_for_selector(".pdf-btn", timeout=5000)
    page.locator(".pdf-btn").click()
    page.wait_for_selector(".pdf-modal", timeout=5000)


class TestPicker:
    def test_opens_the_timesheet_in_a_new_tab_with_the_chosen_options(
        self, page, base_url, context
    ):
        _open_picker(page, base_url)
        page.locator(".pdf-preset", has_text="Last month").click()
        page.locator(".pdf-modal .seg-toggle button", has_text="7:30").click()
        page.locator(".pdf-modal .seg-toggle button", has_text="Dark").click()
        page.locator(".pdf-check", has_text="Signature").click()
        with context.expect_page() as popup:
            page.locator("button", has_text="Open timesheet").click()
        sheet = popup.value
        sheet.wait_for_load_state()
        today = datetime.date.today()
        last = today.replace(day=1) - datetime.timedelta(days=1)
        assert f"from={last.replace(day=1).isoformat()}" in sheet.url
        assert f"to={last.isoformat()}" in sheet.url
        assert "hours=hm" in sheet.url and "theme=dark" in sheet.url and "sign=1" in sheet.url
        assert "notes=1" not in sheet.url
        assert sheet.locator("html").get_attribute("data-theme") == "dark"
        assert sheet.locator(".sign").count() == 1
        assert sheet.locator("table.sheet tbody tr[data-date]").count() == last.day
        assert page.locator(".pdf-modal").count() == 0  # picker closed

    def test_this_month_preset_stops_at_today(self, page, base_url, context):
        _open_picker(page, base_url)
        with context.expect_page() as popup:
            page.locator("button", has_text="Open timesheet").click()
        sheet = popup.value
        sheet.wait_for_load_state()
        today = datetime.date.today().isoformat()
        assert f"to={today}" in sheet.url
        rows = sheet.locator("table.sheet tbody tr[data-date]")
        assert rows.last.get_attribute("data-date") == today

    def test_options_are_remembered(self, page, base_url):
        _open_picker(page, base_url)
        page.locator(".pdf-modal .seg-toggle button", has_text="Compact").click()
        page.locator(".pdf-preset", has_text="This year").click()
        page.locator("button", has_text="Open timesheet").click()
        page.wait_for_timeout(300)
        page.locator(".pdf-btn").click()
        page.wait_for_selector(".pdf-modal", timeout=5000)
        assert "on" in page.locator(
            ".pdf-modal .seg-toggle button", has_text="Compact"
        ).get_attribute("class")
        assert page.locator(".pdf-preset input[value='this_year']").is_checked()

    def test_theme_always_starts_light(self, page, base_url):
        _open_picker(page, base_url)
        page.locator(".pdf-modal .seg-toggle button", has_text="Dark").click()
        page.locator("button", has_text="Open timesheet").click()
        page.wait_for_timeout(300)
        page.locator(".pdf-btn").click()
        page.wait_for_selector(".pdf-modal", timeout=5000)
        assert "on" in page.locator(
            ".pdf-modal .seg-toggle button", has_text="Light"
        ).get_attribute("class")

    def test_custom_range_inputs_bound_each_other(self, page, base_url):
        _open_picker(page, base_url)
        page.locator(".pdf-preset", has_text="Custom").click()
        page.locator(".pdf-custom input").nth(0).fill("2026-09-10")
        assert page.locator(".pdf-custom input").nth(1).get_attribute("min") == "2026-09-10"
        page.locator(".pdf-custom input").nth(1).fill("2026-09-20")
        assert page.locator(".pdf-custom input").nth(0).get_attribute("max") == "2026-09-20"

    def test_custom_range_validates(self, page, base_url, context):
        _open_picker(page, base_url)
        page.locator(".pdf-preset", has_text="Custom").click()
        page.locator(".pdf-custom input").nth(0).fill("2026-09-10")
        page.locator(".pdf-custom input").nth(1).fill("2026-09-01")  # before 'from'
        # The browser's own validation (min/max) blocks the submit: no tab opens, the
        # picker stays, the 'to' input is flagged invalid.
        pages_before = len(context.pages)
        page.locator("button", has_text="Open timesheet").click()
        page.wait_for_timeout(400)
        assert len(context.pages) == pages_before
        assert page.locator(".pdf-modal").count() == 1
        to_input = page.locator(".pdf-custom input").nth(1)
        assert to_input.evaluate("el => el.checkValidity()") is False

    def test_palette_command(self, page, base_url):
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_load_state("networkidle")
        page.keyboard.press(".")
        page.wait_for_selector("#k-palette-input", timeout=3000)
        page.keyboard.type("pdf")
        page.keyboard.press("Enter")
        page.wait_for_selector(".pdf-modal", timeout=5000)
        page.wait_for_url("**/#days", timeout=5000)


class TestPage:
    def test_switches_on_the_page_reload_with_new_params(self, page, base_url):
        with httpx.Client(base_url=base_url) as c:
            c.post(
                "/api/entries",
                json={
                    "date": "2026-09-01",
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "18:30",
                    "breaks": [{"break_minutes": 30}],
                },
            )
        page.goto(f"{base_url}/timesheet?from=2026-09-01&to=2026-09-30")
        page.wait_for_selector("table.sheet")
        assert page.locator("tr[data-date='2026-09-01'] td.n").nth(3).inner_text() == "9.00"
        page.locator(".toolbar .seg label", has_text="7:30").click()
        page.wait_for_url("**hours=hm**", timeout=5000)
        page.wait_for_selector("table.sheet")
        assert page.locator("tr[data-date='2026-09-01'] td.n").nth(3).inner_text() == "9:00"
        page.locator(".toolbar .seg label", has_text="Compact").click()
        page.wait_for_url("**detail=compact**", timeout=5000)
        assert page.locator("th", has_text="Σ").count() == 0

    def test_toggling_keeps_the_scroll_position(self, page, base_url):
        page.set_viewport_size({"width": 900, "height": 700})
        page.goto(f"{base_url}/timesheet?from=2026-08-01&to=2026-09-30")
        page.wait_for_selector("table.sheet")
        page.evaluate("window.scrollTo(0, 1200)")
        page.locator(".toolbar .tb-check", has_text="signatures").click()
        page.wait_for_url("**sign=1**", timeout=5000)
        page.wait_for_selector(".sign")
        page.wait_for_function("() => window.scrollY > 1000", timeout=3000)

    def test_date_inputs_bound_each_other(self, page, base_url):
        page.goto(f"{base_url}/timesheet?from=2026-08-01&to=2026-09-30")
        page.wait_for_selector("table.sheet")
        assert page.locator("#ts-from").get_attribute("max") == "2026-09-30"
        assert page.locator("#ts-to").get_attribute("min") == "2026-08-01"
        # A 'to' before 'from' fails the browser's constraint validation: no request is made.
        page.locator("#ts-to").evaluate(
            "el => { el.value = '2026-07-15';"
            " el.dispatchEvent(new Event('change', { bubbles: true })); }"
        )
        page.wait_for_timeout(400)
        assert "to=2026-09-30" in page.url
        assert page.locator("#ts-to").evaluate("el => el.checkValidity()") is False

    def test_profile_from_settings_prints_in_the_header(self, page, base_url):
        page.goto(f"{base_url}/#settings")
        page.wait_for_selector("#set-name", timeout=5000)
        page.locator("#set-name").fill("Juan Pérez")
        page.locator("#set-employer").fill("ACME")
        page.locator("button", has_text="Save profile").click()
        page.wait_for_selector(".save-ribbon.ribbon-show:has-text('Settings saved')", timeout=5000)
        with httpx.Client(base_url=base_url) as c:
            assert c.get("/api/config").json()["profile_name"] == "Juan Pérez"
        page.goto(f"{base_url}/timesheet")
        page.wait_for_selector(".who")
        assert "Juan Pérez" in page.locator(".who").inner_text()
        assert "ACME" in page.locator(".who").inner_text()

    def test_saves_as_pdf(self, page, base_url):
        """Chromium's own PDF printer is what "Save as PDF" uses; the page must not choke on it."""
        page.goto(f"{base_url}/timesheet?from=2026-08-01&to=2026-09-30&notes=1&sign=1")
        page.wait_for_selector("table.sheet")
        pdf = page.pdf(format="A4", print_background=True)
        assert pdf[:5] == b"%PDF-"
        assert len(pdf) > 10_000
