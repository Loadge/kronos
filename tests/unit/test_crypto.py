"""Crypto prices: lazy, cached, never an exception, and never a request CoinGecko would refuse.

Every test replaces `crypto._fetch`, so none reaches the network.
"""

from __future__ import annotations

import json
import urllib.error
from datetime import timedelta

import app.services.crypto as crypto
import pytest
from app.services.clock import local_today

BASE = "https://crypto.example.invalid"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    crypto._reset()
    monkeypatch.setenv("KRONOS_CRYPTO_URL", BASE)
    yield
    crypto._reset()


def _fake(monkeypatch, eur=68195.0, fail=False):
    """Replace the fetch; returns the list of URLs asked."""
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        if fail:
            raise urllib.error.URLError("name resolution failed")
        if "/simple/price" in url:
            return json.dumps({"bitcoin": {"eur": eur}}).encode()
        return json.dumps({"market_data": {"current_price": {"eur": eur}}}).encode()

    monkeypatch.setattr(crypto, "_fetch", fetch)
    return calls


def test_today_asks_the_simple_price_endpoint(monkeypatch):
    calls = _fake(monkeypatch)
    d = crypto.price("BTC", local_today(), now=1000.0)
    assert calls == [f"{BASE}/api/v3/simple/price?ids=bitcoin&vs_currencies=eur"]
    assert d == {
        "available": True,
        "per_eur": 1 / 68195.0,
        "date": local_today().isoformat(),
        "source": "CoinGecko",
        "stale": False,
        "error": None,
    }


def test_today_is_asked_once_an_hour(monkeypatch):
    calls = _fake(monkeypatch)
    crypto.price("BTC", local_today(), now=1000.0)
    crypto.price("BTC", local_today(), now=1500.0)
    assert len(calls) == 1
    crypto.price("BTC", local_today(), now=4601.0)
    assert len(calls) == 2


def test_a_failed_refresh_serves_the_old_price_as_stale(monkeypatch):
    _fake(monkeypatch)
    crypto.price("BTC", local_today(), now=1000.0)
    _fake(monkeypatch, fail=True)
    d = crypto.price("BTC", local_today(), now=4700.0)
    assert d["available"] is True and d["stale"] is True and d["error"] == "URLError"


def test_a_past_day_asks_the_history_endpoint_and_is_kept_for_good(monkeypatch):
    calls = _fake(monkeypatch)
    on = local_today() - timedelta(days=30)
    d = crypto.price("BTC", on, now=1000.0)
    expected = f"{BASE}/api/v3/coins/bitcoin/history?date={on:%d-%m-%Y}&localization=false"
    assert calls == [expected]
    assert d["per_eur"] == 1 / 68195.0 and d["date"] == on.isoformat()
    # a dated price never changes: not asked again, however much later
    crypto.price("BTC", on, now=1000.0 + 10 * 3600)
    assert calls == [expected]


def test_365_days_back_is_still_asked_and_366_is_not(monkeypatch):
    calls = _fake(monkeypatch)
    assert crypto.price("BTC", local_today() - timedelta(days=365))["available"] is True
    assert len(calls) == 1
    d = crypto.price("BTC", local_today() - timedelta(days=366))
    assert d["available"] is False and d["error"] == "CoinGecko's free API only goes back 365 days"
    assert len(calls) == 1


def test_400_days_back_makes_no_request(monkeypatch):
    calls = _fake(monkeypatch)
    d = crypto.price("BTC", local_today() - timedelta(days=400))
    assert d["available"] is False
    assert d["error"] == "CoinGecko's free API only goes back 365 days"
    assert d["per_eur"] is None and d["source"] == "CoinGecko"
    assert calls == []


def test_a_failed_day_is_retried_at_most_once_an_hour(monkeypatch):
    calls = _fake(monkeypatch, fail=True)
    on = local_today() - timedelta(days=10)
    first = crypto.price("BTC", on, now=1000.0)
    assert first["available"] is False and first["error"] == "URLError"
    assert crypto.price("BTC", on, now=2000.0) == first
    assert len(calls) == 1
    _fake_ok = _fake(monkeypatch)
    assert crypto.price("BTC", on, now=4601.0)["available"] is True
    assert len(_fake_ok) == 1


def test_a_price_that_is_not_a_positive_number_is_a_failed_attempt(monkeypatch):
    for bad in (0, -5, "x", None):
        crypto._reset()
        _fake(monkeypatch, eur=bad)
        d = crypto.price("BTC", local_today() - timedelta(days=3), now=1000.0)
        assert d["available"] is False and d["error"], bad


def test_the_request_carries_a_user_agent_and_a_five_second_timeout(monkeypatch):
    seen = {}

    class Resp:
        def read(self):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        seen["ua"] = req.get_header("User-agent")
        seen["timeout"] = timeout
        return Resp()

    monkeypatch.setattr(crypto.urllib.request, "urlopen", urlopen)
    crypto._fetch(f"{BASE}/x")
    assert seen == {"ua": "Kronos", "timeout": 5}


def test_an_empty_url_disables_fetching(monkeypatch):
    calls = _fake(monkeypatch)
    monkeypatch.setenv("KRONOS_CRYPTO_URL", "")
    d = crypto.price("BTC", local_today())
    assert d["available"] is False and "disabled" in d["error"]
    assert calls == []


def test_an_unknown_coin_is_unavailable(monkeypatch):
    calls = _fake(monkeypatch)
    assert crypto.price("DOGE", local_today())["available"] is False
    assert calls == []
