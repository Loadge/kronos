"""The rules of UI_GUIDE.md that can be checked by reading the source.

A rule that only lives in a document drifts: these fail the build when a template brings back a
pattern the guide retired, so the next page cannot quietly go its own way.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = sorted((ROOT / "backend" / "app" / "templates").glob("_tab_*.html"))
INDEX = ROOT / "backend" / "app" / "templates" / "index.html"
STYLES = ROOT / "backend" / "static" / "styles.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _pages() -> dict[str, str]:
    return {p.name: _read(p) for p in [*TEMPLATES, INDEX]}


def test_the_pages_were_found():
    # a guard for the guards: an empty glob would make every check below pass for nothing
    assert len(TEMPLATES) >= 7


def test_no_export_block_at_the_bottom_of_a_page():
    for name, src in _pages().items():
        assert 'class="an-export"' not in src, f"{name}: exports live in the page head"
        assert not re.search(r"<h2[^>]*>\s*Export\s*</h2>", src), f"{name}: no Export heading"


def test_export_buttons_use_the_short_names():
    for name, src in _pages().items():
        for old in (
            "Download CSV",
            "Download JSON",
            "Download freelance CSV",
            "Download payouts CSV",
        ):
            assert old not in src, (
                f"{name}: '{old}' is now 'CSV', 'JSON', '⚡ Freelance CSV', '⚡ Payouts CSV'"
            )


def test_one_primary_button_look():
    for name, src in _pages().items():
        assert "log-submit-btn" not in src, f"{name}: primary buttons are btn-action"
        assert "btn-action-ghost" not in src, f"{name}: secondary openers are 'secondary outline'"
    css = _read(STYLES)
    assert ".log-submit-btn" not in css and "btn-action-ghost" not in css


def test_money_in_templates_has_cents():
    # fmtMoney0 (no cents) is for the labels inside charts, which live in app.js
    for name, src in _pages().items():
        assert "fmtMoney0(" not in src, f"{name}: use fmtMoney (cents) outside a chart"


def test_numbers_are_not_formatted_by_hand_in_templates():
    for name, src in _pages().items():
        assert ".toFixed(" not in src, f"{name}: use fmtHours, formatSurplus, fmtMoney or pct"
        assert "toLocaleString(" not in src, f"{name}: use the shared formatters"


def test_the_removed_hints_stay_removed():
    gone = [
        "hover a day · click to open it in Log",
        "for the range shown",
        "Billed · ",
        "hourly ⇄ daily ⇄ net yearly",
        "nothing yet",
    ]
    for name, src in _pages().items():
        # the text may survive inside an HTML comment or a title="" tooltip, not as visible text
        visible = re.sub(r"<!--.*?-->", "", src, flags=re.S)
        visible = re.sub(r'title="[^"]*"', "", visible)
        for text in gone:
            assert text not in visible, f"{name}: hint '{text}' was removed on purpose"


def test_page_level_titles_are_h2():
    # a title outside a card is an h2 (UI_GUIDE.md, "Titles, hints and empty states")
    for name in ("_tab_freelance.html", "_tab_plan.html"):
        src = _read(next(p for p in TEMPLATES if p.name == name))
        assert not re.search(r"<h3[^>]*>\s*Modelo 130", src), name
        assert not re.search(r"<h3[^>]*>\s*Upcoming time off", src), name
