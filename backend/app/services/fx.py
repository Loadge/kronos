"""The ECB's EUR/USD reference rate — the latest, or the one of a date — fetched lazily on demand.

`latest()` and `for_date()` are the only triggers: there is no timer, no background task and
nothing at startup, so a Kronos nobody queries never touches the network. Each of the three ECB
documents (today's, the last 90 days, the whole history) is asked for at most once an hour (the
monotonic time of the last attempt, good or failed, is the clock), so a dead network is asked at
most once an hour per document, and the answer is always a dict, not an exception: `available`
says whether a rate is on hand and `stale` that the value is from an earlier fetch because the
latest attempt failed.

The rate of a date is the last one the ECB published on or before it (a weekend or a holiday
takes Friday's). The 90-day document covers most lookups; a date older than that opens the full
history (a few MB, hence asked for only when needed and kept for the hour).
"""

from __future__ import annotations

import math
import os
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

DEFAULT_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
DEFAULT_HIST90_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
DEFAULT_HIST_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.xml"
SOURCE = "ECB"
TTL_SECONDS = 3600.0
FETCH_TIMEOUT = 3
HIST_FETCH_TIMEOUT = 20  # the full history is a few MB

_lock = threading.Lock()
_good: tuple[float, str] | None = None  # (usd_per_eur, date) of the last good fetch
_last_attempt: float | None = None  # monotonic time of the last attempt, good or failed
_last_error: str | None = None  # short reason of the last attempt, when it failed

# The dated documents: {iso_date: usd_per_eur} of the last good fetch, the time of the last
# attempt and its error, for the 90-day file and for the whole history.
_hist: dict[str, dict] = {
    "90d": {"rates": None, "attempt": None, "error": None},
    "all": {"rates": None, "attempt": None, "error": None},
}


def _local_name(tag: str) -> str:
    """The tag without its namespace, so the gesmes/eurofxref prefixes do not matter."""
    return tag.rpartition("}")[2]


def _fetch(url: str, timeout: float = FETCH_TIMEOUT) -> bytes:
    """The ECB's XML document. The one function the tests replace, so they never reach it."""
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def _usd_of(cube) -> float | None:
    """The USD rate of one dated cube, or None when the cube has none."""
    child = next(
        (
            el
            for el in cube
            if _local_name(el.tag) == "Cube" and (el.get("currency") or "").upper() == "USD"
        ),
        None,
    )
    if child is None:
        return None
    rate = float(child.get("rate"))
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("the USD rate is not a finite number > 0")
    return rate


def _parse_history(data: bytes) -> dict[str, float]:
    """{date: usd_per_eur} out of an ECB history document (90 days or the whole series)."""
    root = ET.fromstring(data)
    out: dict[str, float] = {}
    for el in root.iter():
        if _local_name(el.tag) == "Cube" and el.get("time"):
            rate = _usd_of(el)
            if rate is not None:
                out[el.get("time")] = rate
    if not out:
        raise ValueError("no dated USD rate in the ECB history")
    return out


def _parse(data: bytes) -> tuple[float, str]:
    """(usd_per_eur, date) out of the ECB XML; anything else is a failed attempt."""
    root = ET.fromstring(data)
    cubes = [el for el in root.iter() if _local_name(el.tag) == "Cube" and el.get("time")]
    if not cubes:
        raise ValueError("no dated cube in the ECB response")
    cube = cubes[-1]
    rate = _usd_of(cube)
    if rate is None:
        raise ValueError("no USD rate in the ECB response")
    return rate, cube.get("time")


def _reason(exc: Exception) -> str:
    """A short reason for the answer: the HTTP status, else the exception's class name."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    return type(exc).__name__


def _unavailable(error: str) -> dict:
    """The answer when there is no rate: the unavailable shape, with the reason."""
    return {
        "available": False,
        "usd_per_eur": None,
        "date": None,
        "source": SOURCE,
        "stale": False,
        "error": error,
    }


def _answer() -> dict:
    """The answer from the cache: the last good value, or the unavailable shape."""
    if _good is None:
        return _unavailable(_last_error)
    rate, date = _good
    return {
        "available": True,
        "usd_per_eur": rate,
        "date": date,
        "source": SOURCE,
        "stale": _last_error is not None,
        "error": _last_error,
    }


def _disabled() -> bool:
    """`KRONOS_FX_URL` set to "" switches every fetch off (tests, an air-gapped Kronos)."""
    return os.environ.get("KRONOS_FX_URL") == ""


def _latest_locked(now: float) -> dict:
    global _good, _last_attempt, _last_error
    if _last_attempt is None or now - _last_attempt >= TTL_SECONDS:
        if _disabled():
            return _unavailable("fetching is disabled (KRONOS_FX_URL is empty)")
        try:
            _good = _parse(_fetch(os.environ.get("KRONOS_FX_URL", DEFAULT_URL)))
            _last_error = None
        except Exception as exc:
            _last_error = _reason(exc)
        _last_attempt = now
    return _answer()


def latest(now: float | None = None) -> dict:
    """The latest EUR/USD reference rate, fetching the ECB at most once an hour.

    The only trigger is this call. `now` is a monotonic time, for tests; None means now. When the
    last attempt is less than an hour old the cache answers without fetching, even after a failed
    attempt. `KRONOS_FX_URL` set to "" disables fetching entirely.
    """
    if now is None:
        now = time.monotonic()
    with _lock:
        return _latest_locked(now)


def _history(which: str, now: float) -> dict[str, float] | None:
    """The rates of one history document from the cache, fetching at most once an hour.
    The caller holds the lock. None when nothing is on hand."""
    slot = _hist[which]
    if slot["attempt"] is None or now - slot["attempt"] >= TTL_SECONDS:
        if _disabled():
            slot["error"] = "fetching is disabled (KRONOS_FX_URL is empty)"
        else:
            env, default = (
                ("KRONOS_FX_HIST90_URL", DEFAULT_HIST90_URL)
                if which == "90d"
                else ("KRONOS_FX_HIST_URL", DEFAULT_HIST_URL)
            )
            try:
                slot["rates"] = _parse_history(
                    _fetch(os.environ.get(env, default), HIST_FETCH_TIMEOUT)
                )
                slot["error"] = None
            except Exception as exc:
                slot["error"] = _reason(exc)
        slot["attempt"] = now
    return slot["rates"]


def _pick(rates: dict[str, float] | None, on: str) -> tuple[float, str] | None:
    """The rate of the last published day on or before `on` (ISO dates sort as strings)."""
    if not rates:
        return None
    days = [d for d in rates if d <= on]
    if not days:
        return None
    day = max(days)
    return rates[day], day


def for_date(on: date, now: float | None = None) -> dict:
    """The EUR/USD reference rate in force on `on`: the ECB's last publication on or before it.

    A recent date is answered from today's document when that already covers it (a block
    logged today, the common case); otherwise the 90-day document, and the whole history only
    for a date older than that. Each is fetched at most once an hour, only by this call. The
    answer has the `latest()` shape plus `requested` (the date asked for); `date` is the
    publication day actually used.
    """
    if now is None:
        now = time.monotonic()
    wanted = on.isoformat()
    with _lock:
        error: str | None = None
        hit: tuple[float, str] | None = None
        if (date.today() - on).days <= 7:
            d = _latest_locked(now)
            if d["available"] and d["date"] <= wanted:
                hit = (d["usd_per_eur"], d["date"])
            error = d["error"]
        if hit is None:
            rates = _history("90d", now)
            hit = _pick(rates, wanted)
            error = _hist["90d"]["error"]
            if hit is None and (rates is None or wanted < min(rates)):
                rates = _history("all", now)
                hit = _pick(rates, wanted)
                error = _hist["all"]["error"]
        if hit is None:
            return {
                **_unavailable(error or "no rate published on or before that date"),
                "requested": wanted,
            }
        rate, day = hit
        return {
            "available": True,
            "usd_per_eur": rate,
            "date": day,
            "source": SOURCE,
            "stale": error is not None,
            "error": error,
            "requested": wanted,
        }


def _reset() -> None:
    """Clear the cache so the next call fetches again (tests)."""
    global _good, _last_attempt, _last_error
    with _lock:
        _good = None
        _last_attempt = None
        _last_error = None
        for slot in _hist.values():
            slot.update(rates=None, attempt=None, error=None)
