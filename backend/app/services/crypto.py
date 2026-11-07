"""Coin prices from CoinGecko, as coins per 1 EUR — fetched lazily, like `fx.py`.

`price()` is the only trigger: no timer, nothing at startup, so a Kronos nobody queries never
touches the network. The answer is always a dict, never an exception: `available` says whether
a price is on hand and `stale` that the value is from an earlier fetch because the latest
attempt failed.

* Today (or a later date): `/simple/price`, kept for an hour per coin.
* A past day within the last 365 days: `/coins/<id>/history`. A dated price never changes, so it
  is kept for the life of the process; a failed attempt for a (coin, day) is retried at most once
  an hour.
* Older than 365 days: unavailable, and no request is made (the keyless API refuses them).

`per_eur` is how many coins one euro buys: 1 / the coin's price in euros.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import date

from app.services.clock import local_today

DEFAULT_BASE_URL = "https://api.coingecko.com"
SOURCE = "CoinGecko"
TTL_SECONDS = 3600.0
FETCH_TIMEOUT = 5
HISTORY_DAYS = 365
TOO_OLD = "CoinGecko's free API only goes back 365 days"

COIN_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "USDC": "usd-coin",
    "USDT": "tether",
    "SOL": "solana",
}

_lock = threading.Lock()
_latest: dict[str, dict] = {}  # code -> {"per_eur", "date", "attempt", "error"}
_dated: dict[tuple[str, str], float] = {}  # (code, iso day) -> per_eur, for good
_failed: dict[tuple[str, str], tuple[float, str]] = {}  # (code, iso day) -> (attempt, error)


def _fetch(url: str, timeout: float = FETCH_TIMEOUT) -> bytes:
    """CoinGecko's JSON. The one function the tests replace, so they never reach it."""
    req = urllib.request.Request(url, headers={"User-Agent": "Kronos"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def _base() -> str | None:
    """`KRONOS_CRYPTO_URL` is the API's base URL; "" switches every fetch off."""
    url = os.environ.get("KRONOS_CRYPTO_URL", DEFAULT_BASE_URL)
    return url.rstrip("/") if url else None


def _reason(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    return type(exc).__name__


def _per_eur(eur_price) -> float:
    """Coins per euro out of the coin's price in euros; anything but a number > 0 is an error."""
    if isinstance(eur_price, bool) or not isinstance(eur_price, int | float):
        raise ValueError("the price is not a number")
    if not math.isfinite(eur_price) or eur_price <= 0:
        raise ValueError("the price is not a finite number > 0")
    return 1.0 / eur_price


def _shape(per_eur: float | None, day: str | None, *, stale: bool, error: str | None) -> dict:
    return {
        "available": per_eur is not None,
        "per_eur": per_eur,
        "date": day,
        "source": SOURCE,
        "stale": stale,
        "error": error,
    }


def _unavailable(error: str) -> dict:
    return _shape(None, None, stale=False, error=error)


def _latest_locked(code: str, coin: str, base: str, now: float, today: date) -> dict:
    slot = _latest.setdefault(code, {"per_eur": None, "date": None, "attempt": None, "error": None})
    if slot["attempt"] is None or now - slot["attempt"] >= TTL_SECONDS:
        try:
            body = json.loads(_fetch(f"{base}/api/v3/simple/price?ids={coin}&vs_currencies=eur"))
            slot["per_eur"] = _per_eur(body[coin]["eur"])
            slot["date"] = today.isoformat()
            slot["error"] = None
        except Exception as exc:
            slot["error"] = _reason(exc)
        slot["attempt"] = now
    if slot["per_eur"] is None:
        return _unavailable(slot["error"])
    return _shape(
        slot["per_eur"], slot["date"], stale=slot["error"] is not None, error=slot["error"]
    )


def _dated_locked(code: str, coin: str, base: str, on: date, now: float) -> dict:
    key = (code, on.isoformat())
    if key in _dated:
        return _shape(_dated[key], key[1], stale=False, error=None)
    failed = _failed.get(key)
    if failed is not None and now - failed[0] < TTL_SECONDS:
        return _unavailable(failed[1])
    url = (
        f"{base}/api/v3/coins/{coin}/history?date={on.day:02d}-{on.month:02d}-{on.year}"
        "&localization=false"
    )
    try:
        body = json.loads(_fetch(url))
        _dated[key] = _per_eur(body["market_data"]["current_price"]["eur"])
    except Exception as exc:
        _failed[key] = (now, _reason(exc))
        return _unavailable(_failed[key][1])
    _failed.pop(key, None)
    return _shape(_dated[key], key[1], stale=False, error=None)


def price(code: str, on: date, now: float | None = None) -> dict:
    """Coins per 1 EUR on `on`: {"available", "per_eur", "date", "source", "stale", "error"}.

    Today and later dates take the current price; a past day within the last 365 days takes that
    day's price; an older one is unavailable without any request. `now` is a monotonic time, for
    tests; None means now.
    """
    coin = COIN_IDS.get(code)
    if coin is None:
        return _unavailable(f"unknown coin {code}")
    today = local_today()
    if (today - on).days > HISTORY_DAYS:
        return _unavailable(TOO_OLD)
    base = _base()
    if base is None:
        return _unavailable("fetching is disabled (KRONOS_CRYPTO_URL is empty)")
    if now is None:
        now = time.monotonic()
    with _lock:
        if on >= today:
            return _latest_locked(code, coin, base, now, today)
        return _dated_locked(code, coin, base, on, now)


def _reset() -> None:
    """Forget every price so the next call fetches again (tests)."""
    with _lock:
        _latest.clear()
        _dated.clear()
        _failed.clear()
