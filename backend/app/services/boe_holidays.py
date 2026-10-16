"""Pure parser for the BOE yearly "relación de fiestas laborales" resolution.

No DB, no HTTP, no file I/O: ``parse_fiestas`` takes the raw XML bytes of the
Dirección General de Trabajo resolution (one ``<table>`` with 19 region
columns) and returns each region's holidays for the given year, keyed by
ISO-3166-2 code. Fetching the document lives elsewhere.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date
from typing import NamedTuple

#: Holiday year -> BOE document id of its "relación de fiestas laborales" resolution.
BOE_RESOLUTIONS: dict[int, str] = {2026: "BOE-A-2025-21667", 2027: "BOE-A-2026-21254"}

_REGION_COLUMNS = 19

#: (lowercased keyword, ISO-3166-2 code). Matched in order, first hit wins;
#: header texts drift between years ("Com. Madrid" vs "Com. de Madrid"), so
#: keyword matching instead of exact text.
_HEADER_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("andaluc", "ES-AN"),
    ("arag", "ES-AR"),
    ("asturias", "ES-AS"),
    ("balear", "ES-IB"),
    ("canarias", "ES-CN"),
    ("cantabria", "ES-CB"),
    ("mancha", "ES-CM"),
    ("castilla y le", "ES-CL"),
    ("catalu", "ES-CT"),
    ("extremadura", "ES-EX"),
    ("galicia", "ES-GA"),
    ("madrid", "ES-MD"),
    ("murcia", "ES-MC"),
    ("navarra", "ES-NC"),
    ("vasco", "ES-PV"),
    ("rioja", "ES-RI"),
    ("valencia", "ES-VC"),
    ("ceuta", "ES-CE"),
    ("melilla", "ES-ML"),
)

_MONTHS: dict[str, int] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_DATED_ROW = re.compile(r"^(\d{1,2})\s+(.+)$")


class BoeHoliday(NamedTuple):
    """One working holiday of one region."""

    date: date
    name: str
    regional: bool


def _collapse(text: str) -> str:
    """Join all whitespace runs (incl. NBSP) into a single space and strip the ends."""
    return " ".join(text.split())


def _element_text(element: ET.Element) -> str:
    return _collapse("".join(element.itertext()))


def _header_code(header: str) -> str:
    """Map a header's full text to its ISO-3166-2 code, or raise ValueError."""
    low = header.lower()
    for keyword, code in _HEADER_KEYWORDS:
        if keyword in low:
            return code
    raise ValueError(f"no region keyword matches header {header!r}")


def _region_columns(table: ET.Element) -> list[str]:
    """Read the 19 region codes from the second <tr> of the header row."""
    thead = table.find("thead")
    if thead is None:
        raise ValueError("table has no <thead>")
    header_rows = thead.findall("tr")
    if len(header_rows) < 2:
        raise ValueError(f"expected 2 header rows, got {len(header_rows)}")
    headers = header_rows[1].findall("th")
    if len(headers) != _REGION_COLUMNS:
        raise ValueError(f"expected {_REGION_COLUMNS} region columns, got {len(headers)}")
    codes: list[str] = []
    seen: set[str] = set()
    for th in headers:
        code = _header_code(_element_text(th))
        if code in seen:
            raise ValueError(f"two headers map to the same code {code}")
        seen.add(code)
        codes.append(code)
    return codes


def parse_fiestas(xml: bytes, year: int) -> dict[str, list[BoeHoliday]]:
    """Parse the BOE fiestas-laborales resolution XML into per-region holiday lists.

    Returns a dict with one key per ISO-3166-2 region code, each mapped to that
    region's holidays sorted by date. Raises ValueError on malformed input
    (missing table, wrong column count, unmatched or duplicated header, dated
    row before any month row) — never partial data.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"not well-formed XML: {exc}") from exc

    table = root.find(".//table")
    if table is None:
        raise ValueError("no <table> found in document")

    codes = _region_columns(table)
    holidays: dict[str, list[BoeHoliday]] = {code: [] for code in codes}

    tbody = table.find("tbody")
    if tbody is None:
        raise ValueError("table has no <tbody>")

    month: int | None = None
    for tr in tbody.findall("tr"):
        tds = tr.findall("td")
        if not tds:
            continue
        label = _element_text(tds[0])
        low = label.lower()
        if low in _MONTHS:
            month = _MONTHS[low]
            continue
        match = _DATED_ROW.match(label)
        if match is None:
            continue  # rows with any other label are ignored
        if month is None:
            raise ValueError(f"dated row {label!r} appears before any month row")
        holiday_date = date(year, month, int(match.group(1)))
        name = _collapse(match.group(2))
        if name.endswith("."):
            name = name[:-1]
        for code, td in zip(codes, tds[1:], strict=True):
            mark = _element_text(td)
            if mark.startswith("***"):
                holidays[code].append(BoeHoliday(holiday_date, name, regional=True))
            elif mark.startswith("*"):
                holidays[code].append(BoeHoliday(holiday_date, name, regional=False))

    for region_holidays in holidays.values():
        region_holidays.sort(key=lambda h: h.date)
    return holidays
