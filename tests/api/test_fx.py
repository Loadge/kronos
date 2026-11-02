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


# ---------- the rate of a date -------------------------------------------------------

HIST_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-10-30">
      <Cube currency="USD" rate="1.1172"/><Cube currency="JPY" rate="172.35"/>
    </Cube>
    <Cube time="2026-10-29"><Cube currency="USD" rate="1.1160"/></Cube>
    <Cube time="2026-10-28"><Cube currency="USD" rate="1.1150"/></Cube>
    <Cube time="2026-10-27"><Cube currency="USD" rate="1.1140"/></Cube>
    <Cube time="2026-10-26"><Cube currency="USD" rate="1.1130"/></Cube>
    <Cube time="2026-10-23"><Cube currency="USD" rate="1.1100"/></Cube>
  </Cube>
</gesmes:Envelope>
"""

FULL_XML = HIST_XML.replace(
    '<Cube time="2026-10-23">',
    '<Cube time="2024-01-02"><Cube currency="USD" rate="1.0956"/></Cube>\n'
    '    <Cube time="2026-10-23">',
)


def _fake_docs(monkeypatch, *, fail_hist=False):
    """Three fake documents behind the three URLs; returns the list of URLs asked."""
    calls: list[str] = []
    urls = {
        "daily": "https://fx.example.invalid/daily.xml",
        "90d": "https://fx.example.invalid/90d.xml",
        "all": "https://fx.example.invalid/all.xml",
    }

    def fetch(url: str, timeout: float = 3) -> bytes:
        calls.append(url)
        if url == urls["daily"]:
            return ECB_XML.encode()
        if fail_hist:
            raise urllib.error.URLError("name resolution failed")
        if url == urls["90d"]:
            return HIST_XML.encode()
        return FULL_XML.encode()

    monkeypatch.setattr(fx, "_fetch", fetch)
    monkeypatch.setenv("KRONOS_FX_URL", urls["daily"])
    monkeypatch.setenv("KRONOS_FX_HIST90_URL", urls["90d"])
    monkeypatch.setenv("KRONOS_FX_HIST_URL", urls["all"])
    return calls, urls


def test_history_parses_every_dated_usd_rate():
    rates = fx._parse_history(HIST_XML.encode())
    assert rates["2026-10-30"] == 1.1172 and rates["2026-10-23"] == 1.11
    assert len(rates) == 6


def test_for_date_takes_the_last_published_day_on_or_before(monkeypatch):
    calls, urls = _fake_docs(monkeypatch)
    import datetime as dt

    # A Saturday: Friday's rate, and the answer says which day it used
    d = fx.for_date(dt.date(2026, 10, 24), now=1000.0)
    assert d["available"] is True
    assert (d["usd_per_eur"], d["date"], d["requested"]) == (1.11, "2026-10-23", "2026-10-24")
    assert d["stale"] is False
    # a published day is itself
    assert fx.for_date(dt.date(2026, 10, 28), now=1001.0)["usd_per_eur"] == 1.115
    # the 90-day document was fetched once for both
    assert calls.count(urls["90d"]) == 1
    assert urls["all"] not in calls


def test_for_date_older_than_the_90_days_opens_the_whole_history_once(monkeypatch):
    calls, urls = _fake_docs(monkeypatch)
    import datetime as dt

    d = fx.for_date(dt.date(2024, 6, 15), now=1000.0)
    assert (d["usd_per_eur"], d["date"]) == (1.0956, "2024-01-02")
    fx.for_date(dt.date(2025, 2, 1), now=1500.0)
    assert calls.count(urls["all"]) == 1  # once an hour, whatever the number of lookups
    # nothing before the first published day
    none = fx.for_date(dt.date(2020, 1, 1), now=1600.0)
    assert none["available"] is False and none["usd_per_eur"] is None
    assert none["requested"] == "2020-01-01"


def test_for_date_within_the_week_is_answered_from_todays_document(monkeypatch):
    import datetime as dt

    calls, urls = _fake_docs(monkeypatch)
    today = dt.date.today()
    monkeypatch.setattr(fx, "_parse", lambda data: (1.2, today.isoformat()))
    d = fx.for_date(today, now=1000.0)
    assert d["usd_per_eur"] == 1.2 and d["date"] == today.isoformat()
    assert calls == [urls["daily"]]  # no history document needed


def test_for_date_with_a_dead_network_is_unavailable_with_a_reason(monkeypatch):
    import datetime as dt

    calls, urls = _fake_docs(monkeypatch, fail_hist=True)
    d = fx.for_date(dt.date(2026, 10, 1), now=1000.0)
    assert d["available"] is False
    assert isinstance(d["error"], str) and d["error"]
    # not retried within the hour
    fx.for_date(dt.date(2026, 10, 2), now=1500.0)
    assert calls.count(urls["90d"]) == 1 and calls.count(urls["all"]) == 1


def test_for_date_disabled_never_fetches(monkeypatch):
    import datetime as dt

    calls, _ = _fake_docs(monkeypatch)
    monkeypatch.setenv("KRONOS_FX_URL", "")
    d = fx.for_date(dt.date(2026, 10, 1), now=1000.0)
    assert d["available"] is False and "disabled" in d["error"]
    assert calls == []


def test_api_fx_with_a_date(monkeypatch, client):
    _fake_docs(monkeypatch)
    r = client.get("/api/fx?date=2026-10-25")
    assert r.status_code == 200
    d = r.json()
    assert (d["usd_per_eur"], d["date"], d["requested"]) == (1.11, "2026-10-23", "2026-10-25")
    assert client.get("/api/fx?date=not-a-date").status_code == 422
