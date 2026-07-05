"""Public-holiday auto-population via the Nager.Date API (free, no key).

Fetches happen server-side (stdlib urllib — no extra dependency) so the browser
never talks to the external API directly. Nager provides national holidays
(``global: true``) and first-level regional holidays (via ``counties``, e.g.
``ES-MD``). It does NOT cover municipal/local fiestas — those must be logged
manually.
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

router = APIRouter(prefix="/api/holidays", tags=["holidays"])

NAGER_BASE = "https://date.nager.at/api/v3"


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


def _unreachable(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, f"could not reach the holiday service: {exc}")


def _matching_holidays(data: list[dict], region: str | None) -> Iterator[tuple[date, str, bool]]:
    """Yield (date, name, regional) for holidays passing the national+region filter.

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


_CountryQ = Query(..., min_length=2, max_length=2, pattern="^[A-Za-z]{2}$")
_YearQ = Query(..., ge=2000, le=2100)


@router.get("/countries", response_model=list[CountryOut])
def list_countries() -> list[CountryOut]:
    try:
        data = _fetch_countries()
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise _unreachable(exc) from exc
    return [
        CountryOut(code=c["countryCode"], name=c["name"])
        for c in sorted(data, key=lambda c: c["name"])
    ]


@router.get("/subdivisions", response_model=list[str])
def list_subdivisions(country: str = _CountryQ, year: int = _YearQ) -> list[str]:
    """Distinct ISO-3166-2 subdivision codes that have a holiday this year.

    Nager has no dedicated subdivisions endpoint, so we derive the list from the
    ``counties`` fields of the year's holidays — this only surfaces regions that
    actually have a regional holiday.
    """
    try:
        data = _fetch_holidays(country.upper(), year)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
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

    Imports national holidays (``global``) plus, when ``region`` is given, that
    region's holidays. Existing dates (and in-response duplicates) are skipped —
    a work day you already logged on a holiday is preserved.
    """
    try:
        data = _fetch_holidays(country.upper(), year)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise _unreachable(exc) from exc

    imported: list[date] = []
    skipped: list[date] = []
    seen: set[date] = set()

    for d, name, _regional in _matching_holidays(data, region):
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
    try:
        data = _fetch_holidays(country.upper(), year)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise _unreachable(exc) from exc

    out: list[HolidayPreviewOut] = []
    seen: set[date] = set()
    for d, name, regional in _matching_holidays(data, region):
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
