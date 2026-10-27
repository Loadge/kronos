"""Public-holiday auto-population.

Spain comes from the official source: the yearly resolution of the Dirección General de
Trabajo published in the BOE (``relación de fiestas laborales``), one column per region.
Nager.Date is wrong for Spain — it keeps national holidays that fall on a Sunday on the
Sunday instead of the Monday the regions move them to, and it misses each region's own
choices (San José, Easter Monday, substitutions). Every other country still comes from
Nager.Date (free, no key). A Spanish year whose resolution Kronos doesn't know yet is an
error, never a silent fallback to Nager: add its BOE id to ``BOE_RESOLUTIONS`` each October.

Fetches happen server-side (stdlib urllib — no extra dependency) so the browser never
talks to an external API directly. Neither source covers municipal/local fiestas — those
must be logged manually.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import DayType, WorkEntry
from app.schemas import CountryOut, HolidayImportOut, HolidayPreviewOut
from app.services.boe_holidays import BOE_RESOLUTIONS, BoeHoliday, parse_fiestas

router = APIRouter(prefix="/api/holidays", tags=["holidays"])

NAGER_BASE = "https://date.nager.at/api/v3"
BOE_XML_URL = "https://www.boe.es/diario_boe/xml.php?id={}"

_NETWORK_ERRORS = (urllib.error.URLError, TimeoutError, ValueError, OSError)


def _fetch_json(url: str):
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "Kronos"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (fixed host)
        return json.loads(resp.read().decode("utf-8"))


def _fetch_countries() -> list[dict]:
    return _fetch_json(f"{NAGER_BASE}/AvailableCountries")


def _fetch_holidays(country: str, year: int) -> list[dict]:
    return _fetch_json(f"{NAGER_BASE}/PublicHolidays/{year}/{country}")


def _fetch_boe(boe_id: str) -> bytes:
    req = urllib.request.Request(
        BOE_XML_URL.format(boe_id), headers={"Accept": "application/xml", "User-Agent": "Kronos"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 (fixed host)
        return resp.read()


def _unreachable(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, f"could not reach the holiday service: {exc}")


def _matching_holidays(data: list[dict], region: str | None) -> Iterator[tuple[date, str, bool]]:
    """Yield (date, name, regional) for Nager holidays passing the national+region filter.

    National (``global``) holidays always pass; a regional holiday passes only when
    ``region`` matches one of its ``counties``. Order follows the source; callers
    dedupe same-date entries. ``regional`` is True for non-global holidays.
    """
    for h in data:
        counties = h.get("counties") or []
        is_global = h.get("global", False)
        if not is_global and (not region or region not in counties):
            continue
        try:
            d = date.fromisoformat(h["date"])
        except (KeyError, ValueError):
            continue
        yield d, (h.get("localName") or h.get("name") or ""), (not is_global)


def _boe_by_region(year: int) -> dict[str, list[BoeHoliday]]:
    """The BOE resolution for ``year``, parsed into each region's holidays."""
    boe_id = BOE_RESOLUTIONS.get(year)
    if boe_id is None:
        known = ", ".join(str(y) for y in sorted(BOE_RESOLUTIONS))
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"no official (BOE) holiday list for Spain {year} yet — Kronos knows {known}; "
            "the list is published each October",
        )
    try:
        xml = _fetch_boe(boe_id)
    except _NETWORK_ERRORS as exc:
        raise _unreachable(exc) from exc
    try:
        return parse_fiestas(xml, year)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"could not read the BOE holiday list {boe_id}: {exc}"
        ) from exc


def _spanish_holidays(year: int, region: str | None) -> list[tuple[date, str, bool]]:
    """(date, name, regional) for Spain from the BOE.

    With a region, that region's column (its national holidays, moved or substituted as
    it chose, plus its own). Without one, only the holidays every region has.
    """
    by_region = _boe_by_region(year)
    if region:
        if region not in by_region:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown Spanish region {region!r}"
            )
        return [(h.date, h.name, h.regional) for h in by_region[region]]
    columns = list(by_region.values())
    shared = set.intersection(*({h.date for h in col} for col in columns))
    return [(h.date, h.name, False) for h in columns[0] if h.date in shared]


def _holidays_for(country: str, year: int, region: str | None) -> list[tuple[date, str, bool]]:
    """(date, name, regional) for a country/year/region: BOE for Spain, Nager elsewhere."""
    if country == "ES":
        return _spanish_holidays(year, region)
    try:
        data = _fetch_holidays(country, year)
    except _NETWORK_ERRORS as exc:
        raise _unreachable(exc) from exc
    return list(_matching_holidays(data, region))


_CountryQ = Query(..., min_length=2, max_length=2, pattern="^[A-Za-z]{2}$")
_YearQ = Query(..., ge=2000, le=2100)


@router.get("/countries", response_model=list[CountryOut])
def list_countries() -> list[CountryOut]:
    try:
        data = _fetch_countries()
    except _NETWORK_ERRORS as exc:
        raise _unreachable(exc) from exc
    return [
        CountryOut(code=c["countryCode"], name=c["name"])
        for c in sorted(data, key=lambda c: c["name"])
    ]


@router.get("/subdivisions", response_model=list[str])
def list_subdivisions(country: str = _CountryQ, year: int = _YearQ) -> list[str]:
    """ISO-3166-2 subdivision codes to pick a region from.

    Spain: the 19 columns of the BOE table. Elsewhere, Nager has no dedicated
    subdivisions endpoint, so the list is derived from the ``counties`` fields of the
    year's holidays — this only surfaces regions that actually have a regional holiday.
    """
    if country.upper() == "ES":
        return sorted(_boe_by_region(year))
    try:
        data = _fetch_holidays(country.upper(), year)
    except _NETWORK_ERRORS as exc:
        raise _unreachable(exc) from exc
    codes: set[str] = set()
    for h in data:
        for c in h.get("counties") or []:
            codes.add(c)
    return sorted(codes)


@router.post("/import", response_model=HolidayImportOut)
def import_holidays(
    country: str = _CountryQ,
    year: int = _YearQ,
    region: str | None = Query(None, description="ISO-3166-2 code, e.g. ES-MD"),
    session: Session = Depends(get_session),
) -> HolidayImportOut:
    """Create ``holiday`` entries for the given country/year.

    Imports national holidays plus, when ``region`` is given, that region's holidays
    (for Spain, that region's column of the BOE list). Existing dates (and in-response
    duplicates) are skipped — a work day you already logged on a holiday is preserved.
    """
    imported: list[date] = []
    skipped: list[date] = []
    seen: set[date] = set()

    for d, name, _regional in _holidays_for(country.upper(), year, region):
        if d in seen or session.get(WorkEntry, d):
            skipped.append(d)
            continue
        seen.add(d)
        session.add(WorkEntry(date=d, day_type=DayType.HOLIDAY.value, notes=name or None))
        imported.append(d)

    if imported:
        session.commit()
    return HolidayImportOut(imported=imported, skipped=skipped)


@router.get("/preview", response_model=list[HolidayPreviewOut])
def preview_holidays(
    country: str = _CountryQ,
    year: int = _YearQ,
    region: str | None = Query(None, description="ISO-3166-2 code, e.g. ES-MD"),
    session: Session = Depends(get_session),
) -> list[HolidayPreviewOut]:
    """List the holidays a matching import would create, sorted by date.

    Read-only: flags each with ``regional`` (national vs the chosen region) and
    ``exists`` (a date already logged, which import would skip).
    """
    out: list[HolidayPreviewOut] = []
    seen: set[date] = set()
    for d, name, regional in _holidays_for(country.upper(), year, region):
        if d in seen:
            continue
        seen.add(d)
        out.append(
            HolidayPreviewOut(
                date=d,
                name=name,
                regional=regional,
                exists=session.get(WorkEntry, d) is not None,
            )
        )
    out.sort(key=lambda item: item.date)
    return out
