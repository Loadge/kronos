"""E2E: the shared UI rules that can be seen in a browser (UI_GUIDE.md).

Exports are pills in the page head, hints that said what the page already shows are gone, every
primary button wears the same look (`.btn-action`), and the Dashboard marks the employee side with
👔 the way the Freelance strip is marked with ⚡.
"""

from __future__ import annotations

import datetime
import re

import httpx
import pytest

pytestmark = pytest.mark.e2e

TODAY = datetime.date.today()


@pytest.fixture(autouse=True)
def _freelance_source(base_url):
    """The freelance pills and the Add block button only exist once an income source does."""
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        r = c.post(
            "/api/freelance/sources",
            json={"name": "Local", "hourly_rate": 60, "currency": "EUR"},
        )
        assert r.status_code == 201, r.text
        source_id = r.json()["id"]
        b = c.post(
            "/api/freelance/blocks",
            json={"date": TODAY.isoformat(), "source_id": source_id, "hours": 2},
        )
        assert b.status_code == 201, b.text
    yield
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        # the sources outlive /api/data, and a leftover one adds the Freelance tab everywhere
        for s in c.get("/api/freelance/sources").json():
            c.delete(f"/api/freelance/sources/{s['id']}")


def _rgb(css: str) -> tuple[float, float, float]:
    nums = re.findall(r"[\d.]+", css)[:3]
    return tuple(float(n) for n in nums)  # type: ignore[return-value]


def _hue(rgb: tuple[float, float, float]) -> float:
    import colorsys

    h, _, _ = colorsys.rgb_to_hsv(*(v / 255 for v in rgb))
    return h * 360


def _style(locator, prop: str) -> str:
    return locator.evaluate(f"e => getComputedStyle(e).{prop}")


def _open_analytics(page, base_url):
    page.goto(f"{base_url}/#analytics")
    page.wait_for_selector("main .page-head .hm-switch", timeout=10000)


class TestAnalyticsExports:
    def test_head_holds_the_export_pills_before_the_switch(self, page, base_url):
        _open_analytics(page, base_url)
        head = page.locator("main .page-head .page-head-controls")
        for name in ("CSV", "JSON", "Freelance CSV", "Payouts CSV"):
            pill = head.get_by_role("button", name=name, exact=True)
            assert pill.count() == 1, f"missing head pill {name!r}"
            assert "head-btn" in pill.get_attribute("class")
        order = head.evaluate(
            "el => [...el.children].filter(c => c.offsetParent !== null).map(c =>"
            " c.classList.contains('hm-switch') ? 'pill'"
            " : c.classList.contains('head-btn') ? c.textContent.trim()"
            " : c.classList.contains('year-step') ? 'year' : 'other')"
        )
        assert order == ["CSV", "JSON", "⚡ Freelance CSV", "⚡ Payouts CSV", "pill", "year"], order

    def test_the_downloads_still_point_at_their_endpoints(self, page, base_url):
        _open_analytics(page, base_url)
        head = page.locator("main .page-head .page-head-controls")
        hrefs = {
            "CSV": "/api/export.csv",
            "JSON": "/api/export.json",
            "Freelance CSV": "/api/freelance/export.csv",
            "Payouts CSV": "/api/freelance/payouts.csv",
        }
        for name, href in hrefs.items():
            assert head.get_by_role("button", name=name, exact=True).get_attribute("href") == href

    def test_the_freelance_pills_wait_for_a_source(self, page, base_url):
        with httpx.Client(base_url=base_url) as c:
            c.delete("/api/data")
            for s in c.get("/api/freelance/sources").json():
                c.delete(f"/api/freelance/sources/{s['id']}")
        page.goto(f"{base_url}/#analytics")
        page.wait_for_selector("main .page-head .year-step", timeout=10000)
        head = page.locator("main .page-head .page-head-controls")
        assert head.get_by_role("button", name="CSV", exact=True).count() == 1
        assert head.get_by_role("button", name="JSON", exact=True).count() == 1
        assert head.get_by_role("button", name="Freelance CSV", exact=True).count() == 0
        assert head.get_by_role("button", name="Payouts CSV", exact=True).count() == 0

    def test_no_export_block_at_the_bottom(self, page, base_url):
        _open_analytics(page, base_url)
        section = page.locator("section[aria-label=Analytics]")
        headings = [h.strip() for h in section.locator("h2").all_inner_texts()]
        assert "Export" not in headings, headings
        assert section.locator(".an-export").count() == 0

    def test_its_page_level_titles_are_all_section_heads(self, page, base_url):
        _open_analytics(page, base_url)
        for title in ("Year at a glance", "Years", "Records"):
            h2 = page.locator("section[aria-label=Analytics] h2", has_text=title).first
            assert h2.evaluate("e => e.parentElement.classList.contains('an-head')"), title
            root = float(page.evaluate("getComputedStyle(document.documentElement).fontSize")[:-2])
            assert _style(h2, "fontSize") == f"{root * 1.25:g}px", (title, _style(h2, "fontSize"))


class TestHintsAreGone:
    def test_analytics_hints_are_absent(self, page, base_url):
        _open_analytics(page, base_url)
        text = page.locator("section[aria-label=Analytics]").inner_text().lower()
        assert "hover a day" not in text
        assert "for the range shown" not in text

    def test_the_information_lives_in_a_title(self, page, base_url):
        _open_analytics(page, base_url)
        glance = page.locator("[data-testid=an-glance] .an-head")
        assert "hover a day" in glance.get_attribute("title").lower()


class TestOnePrimaryButton:
    def test_log_pdf_and_add_block_share_the_look(self, page, base_url):
        # Log: the main submit and the Add block button
        page.goto(f"{base_url}/#log")
        page.wait_for_selector(".log-cal-day:not(.log-cal-pad)", timeout=5000)
        page.evaluate(
            f"Alpine.$data(document.querySelector('main')).openDayInLog('{TODAY.isoformat()}')"
        )
        submit = page.locator("button.btn-action.btn-action--block")
        assert submit.count() == 1
        add_block = page.locator("button.btn-action.fl-submit")
        add_block.wait_for(timeout=5000)
        for prop in ("borderRadius", "fontWeight"):
            assert _style(submit, prop) == _style(add_block, prop), prop
        assert _style(submit, "borderRadius") == "6px"
        assert _style(submit, "fontWeight") == "700"
        assert _style(submit, "width") != _style(add_block, "width")  # block vs. auto
        log_bg = _style(submit, "backgroundColor")
        # Add block keeps the coin gold, the same warm family as the brass
        assert abs(_hue(_rgb(log_bg)) - _hue(_rgb(_style(add_block, "backgroundColor")))) < 15

        # Days: the PDF modal's submit is the same brass
        page.goto(f"{base_url}/#days")
        page.wait_for_selector("main .page-head .pdf-btn", timeout=5000)
        page.locator("main .page-head .pdf-btn").click()
        modal_submit = page.locator(".pdf-modal button[type=submit]")
        modal_submit.wait_for(timeout=3000)
        assert "btn-action--block" in modal_submit.get_attribute("class")
        assert _style(modal_submit, "backgroundColor") == log_bg
        assert _style(modal_submit, "width") == _style(modal_submit.locator("xpath=.."), "width")


class TestDashboardMark:
    def test_the_employee_side_wears_the_tie(self, page, base_url):
        page.goto(f"{base_url}/#dashboard")
        page.wait_for_selector(".hero-num", timeout=5000)
        hero = page.locator(".hero-label")
        assert "👔" in hero.inner_text()
        assert hero.locator("span[aria-hidden=true]").first.inner_text() == "👔"
        # the Freelance strip keeps its ⚡
        assert "⚡" in page.locator("[data-testid=freelance-card]").inner_text()


ARROWS = """s => ['::before', '::after'].filter(p => {
    const c = getComputedStyle(s, p);
    return c.display !== 'none' && c.content !== 'none' && c.content !== 'normal';
}).length"""


class TestDisclosures:
    def test_a_collapsible_wears_one_arrow(self, page, base_url):
        """Pico draws a chevron after every summary; ours draws its own arrow before the text."""
        page.goto(f"{base_url}/#log")
        page.wait_for_selector(".log-cal-day:not(.log-cal-pad)", timeout=5000)
        page.evaluate(
            f"Alpine.$data(document.querySelector('main')).openDayInLog('{TODAY.isoformat()}')"
        )
        summary = page.locator(".save-template-section summary")
        summary.wait_for(timeout=5000)
        assert summary.evaluate(ARROWS) == 1
        summary.click()  # the open state draws its arrow from another rule
        assert summary.evaluate(ARROWS) == 1

        page.goto(f"{base_url}/#settings")
        summary = page.locator(".target-schedule > summary")
        summary.wait_for(timeout=5000)
        assert summary.evaluate(ARROWS) == 1
