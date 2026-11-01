"""The ECB's latest EUR/USD reference rate, fetched lazily on demand.

`latest()` is the only trigger: there is no timer, no background task and nothing at startup, so
a Kronos nobody queries never touches the network. The ECB is asked at most once an hour (the
monotonic time of the last attempt, good or failed, is the clock), so a dead network is asked at
most once an hour, and the answer is always a dict, not an exception: `available` says whether a
rate is on hand and `stale` that the value is from an earlier fetch because the latest attempt
failed.
"""

from __future__ import annotations

import math
import os
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

DEFAULT_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
SOURCE = "ECB"
TTL_SECONDS = 3600.0
FETCH_TIMEOUT = 3

_lock = threading.Lock()
_good: tuple[float, str] | None = None  # (usd_per_eur, date) of the last good fetch
_last_attempt: float | None = None  # monotonic time of the last attempt, good or failed
_last_error: str | None = None  # short reason of the last attempt, when it failed


def _local_name(tag: str) -> str:
    """The tag without its namespace, so the gesmes/eurofxref prefixes do not matter."""
    return tag.rpartition("}")[2]


def _fetch(url: str) -> bytes:
    """The ECB's XML document. The one function the tests replace, so they never reach it."""
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as response:
        return response.read()


def _parse(data: bytes) -> tuple[float, str]:
    """(usd_per_eur, date) out of the ECB XML; anything else is a failed attempt."""
    root = ET.fromstring(data)
    cubes = [el for el in root.iter() if _local_name(el.tag) == "Cube" and el.get("time")]
    if not cubes:
        raise ValueError("no dated cube in the ECB response")
    cube = cubes[-1]
    child = next(
        (
            el
            for el in cube
            if _local_name(el.tag) == "Cube" and (el.get("currency") or "").upper() == "USD"
        ),
        None,
    )
    if child is None:
        raise ValueError("no USD rate in the ECB response")
    rate = float(child.get("rate"))
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("the USD rate is not a finite number > 0")
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


def latest(now: float | None = None) -> dict:
    """The latest EUR/USD reference rate, fetching the ECB at most once an hour.

    The only trigger is this call. `now` is a monotonic time, for tests; None means now. When the
    last attempt is less than an hour old the cache answers without fetching, even after a failed
    attempt. `KRONOS_FX_URL` set to "" disables fetching entirely.
    """
    global _good, _last_attempt, _last_error
    if now is None:
        now = time.monotonic()
    with _lock:
        if _last_attempt is None or now - _last_attempt >= TTL_SECONDS:
            url = os.environ.get("KRONOS_FX_URL", DEFAULT_URL)
            if not url:
                return _unavailable("fetching is disabled (KRONOS_FX_URL is empty)")
            try:
                _good = _parse(_fetch(url))
                _last_error = None
            except Exception as exc:
                _last_error = _reason(exc)
            _last_attempt = now
        return _answer()


def _reset() -> None:
    """Clear the cache so the next call fetches again (tests)."""
    global _good, _last_attempt, _last_error
    with _lock:
        _good = None
        _last_attempt = None
        _last_error = None
