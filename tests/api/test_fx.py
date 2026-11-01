"""FX: the ECB rate is fetched lazily, at most once an hour, and GET /api/fx always answers 200."""

from __future__ import annotations

import urllib.error

import app.services.fx as fx
import pytest

ECB_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <gesmes:Sender>
    <gesmes:name>European Central Bank</gesmes:name>
  </gesmes:Sender>
  <Cube>
    <Cube time="2026-10-30">
      <Cube currency="USD" rate="1.1172"/>
      <Cube currency="JPY" rate="172.35"/>
      <Cube currency="AUD" rate="1.7977"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


@pytest.fixture(autouse=True)
def _fresh_cache():
    fx._reset()
    yield
    fx._reset()


def _fake_fetch(monkeypatch, payload: str = ECB_XML, fail: bool = False):
    """Replace the fetch with `payload` (or a dead network); returns the list of URLs asked."""
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        if fail:
            raise urllib.error.URLError("name resolution failed")
        return payload.encode()

    monkeypatch.setattr(fx, "_fetch", fetch)
    monkeypatch.setenv("KRONOS_FX_URL", "https://fx.example.invalid/eurofxref-daily.xml")
    return calls


def test_ecb_xml_parses_to_rate_and_date(monkeypatch):
    calls = _fake_fetch(monkeypatch)
    assert fx._parse(ECB_XML.encode()) == (1.1172, "2026-10-30")
    d = fx.latest(now=1000.0)
    assert d == {
        "available": True,
        "usd_per_eur": 1.1172,
        "date": "2026-10-30",
        "source": "ECB",
        "stale": False,
        "error": None,
    }
    assert len(calls) == 1


def test_two_calls_ten_seconds_apart_fetch_once(monkeypatch):
    calls = _fake_fetch(monkeypatch)
    first = fx.latest(now=1000.0)
    second = fx.latest(now=1010.0)
    assert len(calls) == 1
    assert second == first
    assert second["available"] is True
    assert second["stale"] is False


def test_call_an_hour_and_one_second_later_fetches_again(monkeypatch):
    calls = _fake_fetch(monkeypatch)
    fx.latest(now=1000.0)
    d = fx.latest(now=4601.0)
    assert len(calls) == 2
    assert d["available"] is True
    assert d["stale"] is False
    assert d["usd_per_eur"] == 1.1172
    assert d["date"] == "2026-10-30"


def test_failed_fetch_after_a_good_one_serves_the_old_value_as_stale(monkeypatch):
    _fake_fetch(monkeypatch)
    fx.latest(now=1000.0)
    calls: list[str] = []

    def dead(url: str) -> bytes:
        calls.append(url)
        raise urllib.error.URLError("network unreachable")

    monkeypatch.setattr(fx, "_fetch", dead)
    d = fx.latest(now=4700.0)
    assert len(calls) == 1
    assert d["available"] is True
    assert d["usd_per_eur"] == 1.1172
    assert d["date"] == "2026-10-30"
    assert d["stale"] is True
    assert isinstance(d["error"], str) and d["error"]


def test_failed_first_fetch_is_unavailable_and_not_retried_within_the_hour(monkeypatch):
    calls = _fake_fetch(monkeypatch, fail=True)
    first = fx.latest(now=1000.0)
    assert first["available"] is False
    assert first["usd_per_eur"] is None
    assert first["date"] is None
    assert first["source"] == "ECB"
    assert first["stale"] is False
    assert isinstance(first["error"], str) and first["error"]
    second = fx.latest(now=1500.0)
    assert len(calls) == 1
    assert second == first


@pytest.mark.parametrize("rate", ["0", "-1.1", "inf", "nan", "x"])
def test_a_rate_that_is_not_a_positive_number_is_a_failed_attempt(monkeypatch, rate):
    # a zero would divide every USD rate by zero in the Calculator
    _fake_fetch(monkeypatch, payload=ECB_XML.replace('rate="1.1172"', f'rate="{rate}"'))
    d = fx.latest(now=1000.0)
    assert (d["available"], d["usd_per_eur"]) == (False, None)
    assert d["error"]


def test_empty_url_disables_fetching_entirely(monkeypatch):
    calls = _fake_fetch(monkeypatch)
    monkeypatch.setenv("KRONOS_FX_URL", "")
    for now in (1000.0, 2000.0, 10_000.0):
        d = fx.latest(now=now)
        assert d["available"] is False
        assert d["usd_per_eur"] is None
        assert d["date"] is None
        assert d["source"] == "ECB"
        assert d["stale"] is False
        assert isinstance(d["error"], str) and d["error"]
    assert calls == []


def test_api_fx_answers_200_with_the_rate(monkeypatch, client):
    _fake_fetch(monkeypatch)
    r = client.get("/api/fx")
    assert r.status_code == 200
    d = r.json()
    assert d["available"] is True
    assert d["usd_per_eur"] == 1.1172
    assert d["date"] == "2026-10-30"
    assert d["source"] == "ECB"
    assert d["stale"] is False
    assert d["error"] is None
