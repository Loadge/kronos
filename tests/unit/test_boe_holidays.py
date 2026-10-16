"""Unit tests for the BOE fiestas-laborales XML parser."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from app.services.boe_holidays import BOE_RESOLUTIONS, parse_fiestas

FIXTURES = Path(__file__).parents[1] / "fixtures" / "boe"
XML_2026 = (FIXTURES / "BOE-A-2025-21667.xml").read_bytes()
XML_2027 = (FIXTURES / "BOE-A-2026-21254.xml").read_bytes()

ES_MD_2027 = [
    date(2027, 1, 1),
    date(2027, 1, 6),
    date(2027, 3, 19),
    date(2027, 3, 25),
    date(2027, 3, 26),
    date(2027, 5, 1),
    date(2027, 8, 16),
    date(2027, 10, 12),
    date(2027, 11, 1),
    date(2027, 12, 6),
    date(2027, 12, 8),
    date(2027, 12, 25),
]

ES_MD_2026 = [
    date(2026, 1, 1),
    date(2026, 1, 6),
    date(2026, 4, 2),
    date(2026, 4, 3),
    date(2026, 5, 1),
    date(2026, 5, 2),
    date(2026, 8, 15),
    date(2026, 10, 12),
    date(2026, 11, 2),
    date(2026, 12, 7),
    date(2026, 12, 8),
    date(2026, 12, 25),
]


def by_date(holidays) -> dict[date, object]:
    return {h.date: h for h in holidays}


# ---------- ES-MD expected lists -------------------------------------------


def test_es_md_2027_exact_dates_in_order():
    holidays = parse_fiestas(XML_2027, 2027)
    assert [h.date for h in holidays["ES-MD"]] == ES_MD_2027


def test_es_md_2027_san_jose_name_and_no_weekend_blind_days():
    holidays = parse_fiestas(XML_2027, 2027)
    md = by_date(holidays["ES-MD"])
    assert md[date(2027, 3, 19)].name == "San José"
    assert date(2027, 8, 15) not in md
    assert date(2027, 5, 2) not in md


def test_es_md_2026_exact_dates_and_regional_flags():
    holidays = parse_fiestas(XML_2026, 2026)
    md = by_date(holidays["ES-MD"])
    assert list(md) == ES_MD_2026
    assert md[date(2026, 5, 2)].regional is True
    assert md[date(2026, 1, 1)].regional is False


def test_mark_with_footnote_text_still_kept():
    baseline = parse_fiestas(XML_2027, 2027)
    assert date(2027, 3, 19) in by_date(baseline["ES-MD"])

    row_start = XML_2027.rfind(b"<tr>", 0, XML_2027.index(b"19 San Jos"))
    row_end = XML_2027.index(b"</tr>", row_start)
    row = XML_2027[row_start:row_end]
    tag = b'<td class="cuerpo_tabla_centro">'
    pos = -1
    for _ in range(12):
        pos = row.index(tag, pos + 1)
    mark_start = row_start + pos + len(tag)
    mark_end = row_start + row.index(b"</td>", pos + len(tag))
    assert XML_2027[mark_start:mark_end] == b"**"

    modified = XML_2027[:mark_start] + b"** (2)" + XML_2027[mark_end:]
    assert modified != XML_2027
    md = by_date(parse_fiestas(modified, 2027)["ES-MD"])
    assert date(2027, 3, 19) in md
    assert md[date(2027, 3, 19)].regional is False

    broad = XML_2027.replace(b'centro">***</td>', b'centro">***(3)</td>').replace(
        b'centro">**</td>', b'centro">** (2)</td>'
    )
    assert broad != XML_2027
    broad_2027 = parse_fiestas(broad, 2027)
    assert [h.date for h in broad_2027["ES-MD"]] == ES_MD_2027
    for code, region_holidays in broad_2027.items():
        expected = 11 if code == "ES-CN" else 12
        assert len(region_holidays) == expected, code
    dia_andalucia = [h for h in broad_2027["ES-AN"] if h.name == "Día de Andalucía"]
    assert len(dia_andalucia) == 1
    assert dia_andalucia[0].date == date(2027, 3, 1)
    assert dia_andalucia[0].regional is True


# ---------- both years: shape and names ------------------------------------


def test_both_years_have_19_regions_with_expected_counts():
    for xml, year in ((XML_2026, 2026), (XML_2027, 2027)):
        holidays = parse_fiestas(xml, year)
        assert len(holidays) == 19
        for code, region_holidays in holidays.items():
            expected = 11 if code == "ES-CN" else 12
            assert len(region_holidays) == expected, f"{code} {year}: {len(region_holidays)}"


def test_names_have_no_trailing_dot():
    for xml, year in ((XML_2026, 2026), (XML_2027, 2027)):
        holidays = parse_fiestas(xml, year)
        for code, region_holidays in holidays.items():
            for h in region_holidays:
                assert not h.name.endswith("."), f"{code} {year}: {h.name!r}"
        new_year = by_date(holidays["ES-MD"])[date(year, 1, 1)]
        assert new_year.name == "Año Nuevo"


# ---------- malformed input --------------------------------------------------


def test_no_table_raises():
    with pytest.raises(ValueError, match="no <table>"):
        parse_fiestas(b"<documento/>", 2027)


def test_header_matching_no_keyword_raises():
    broken = XML_2027.replace(b"Ciudad de Melilla", b"Atlantis")
    assert broken != XML_2027
    with pytest.raises(ValueError, match="Atlantis"):
        parse_fiestas(broken, 2027)


def test_duplicated_header_code_raises():
    broken = XML_2027.replace(b"Ciudad de Ceuta", b"Ciudad de Melilla")
    assert broken != XML_2027
    with pytest.raises(ValueError, match="same code"):
        parse_fiestas(broken, 2027)


def test_dated_row_before_month_raises():
    broken = XML_2027.replace(b">Enero<", b">Foo<")
    assert broken != XML_2027
    with pytest.raises(ValueError, match="before any month row"):
        parse_fiestas(broken, 2027)


# ---------- constants ---------------------------------------------------------


def test_boe_resolutions_mapping():
    assert BOE_RESOLUTIONS[2026] == "BOE-A-2025-21667"
    assert BOE_RESOLUTIONS[2027] == "BOE-A-2026-21254"
