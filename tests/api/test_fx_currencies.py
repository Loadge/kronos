"""fx.py beyond USD: every ECB currency, the USD answers unchanged, GET /api/currencies."""

from __future__ import annotations

from datetime import date

import app.services.fx as fx
import pytest

DAILY = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-10-30">
      <Cube currency="USD" rate="1.1172"/>
      <Cube currency="JPY" rate="172.35"/>
      <Cube currency="AUD" rate="oops"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""

HIST = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-10-30">
      <Cube currency="USD" rate="1.1172"/>
      <Cube currency="JPY" rate="172.35"/>
    </Cube>
    <Cube time="2026-10-29">
      <Cube currency="USD" rate="1.1160"/>
      <Cube currency="JPY" rate="171.0"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


@pytest.fixture(autouse=True)
def _docs(monkeypatch):
    fx._reset()
    calls: list[str] = []

    def fetch(url: str, timeout: float = 3) -> bytes:
        calls.append(url)
        return (DAILY if url.endswith("daily.xml") else HIST).encode()

    monkeypatch.setattr(fx, "_fetch", fetch)
    monkeypatch.setenv("KRONOS_FX_URL", "https://fx.example.invalid/daily.xml")
    monkeypatch.setenv("KRONOS_FX_HIST90_URL", "https://fx.example.invalid/90d.xml")
    monkeypatch.setenv("KRONOS_FX_HIST_URL", "https://fx.example.invalid/all.xml")
    yield calls
    fx._reset()


def test_the_default_currency_is_usd_with_the_original_shape():
    assert fx.latest(now=1.0) == {
        "available": True,
        "usd_per_eur": 1.1172,
        "date": "2026-10-30",
        "source": "ECB",
        "stale": False,
        "error": None,
    }
    d = fx.for_date(date(2026, 10, 29), now=2.0)
    assert (d["usd_per_eur"], d["date"], d["requested"]) == (1.116, "2026-10-29", "2026-10-29")


def test_for_date_without_a_currency_is_usd():
    assert fx.for_date(date(2026, 10, 30), now=1.0)["usd_per_eur"] == 1.1172
    assert fx.for_date(date(2026, 10, 30), now=1.0, currency="USD")["usd_per_eur"] == 1.1172


def test_another_currency_answers_per_eur_from_the_same_documents(_docs):
    d = fx.latest(now=1.0, currency="JPY")
    assert (d["available"], d["currency"], d["per_eur"], d["date"]) == (
        True,
        "JPY",
        172.35,
        "2026-10-30",
    )
    assert "usd_per_eur" not in d
    # the document was parsed once for both currencies
    fx.latest(now=2.0)
    assert len(_docs) == 1
    h = fx.for_date(date(2026, 10, 29), now=3.0, currency="JPY")
    assert (h["per_eur"], h["date"], h["requested"]) == (171.0, "2026-10-29", "2026-10-29")


def test_the_currency_may_come_as_the_second_positional_argument():
    assert fx.latest("JPY")["per_eur"] == 172.35
    assert fx.for_date(date(2026, 10, 29), "JPY")["per_eur"] == 171.0


def test_a_currency_the_ecb_does_not_publish_is_unavailable_with_a_reason():
    d = fx.latest(now=1.0, currency="XYZ")
    assert d["available"] is False and d["per_eur"] is None and "XYZ" in d["error"]
    assert fx.for_date(date(2026, 10, 30), now=2.0, currency="XYZ")["available"] is False


def test_a_bad_rate_of_another_currency_only_leaves_that_currency_out():
    assert fx.latest(now=1.0)["available"] is True  # AUD="oops" does not fail the document
    assert fx.latest(now=2.0, currency="AUD")["available"] is False


def test_api_fx_takes_a_currency(client):
    assert client.get("/api/fx").json()["usd_per_eur"] == 1.1172
    d = client.get("/api/fx?currency=jpy").json()
    assert (d["currency"], d["per_eur"]) == ("JPY", 172.35)
    d = client.get("/api/fx?currency=JPY&date=2026-10-29").json()
    assert (d["per_eur"], d["date"]) == (171.0, "2026-10-29")


def test_api_currencies_lists_the_catalogue(client):
    r = client.get("/api/currencies")
    assert r.status_code == 200
    rows = r.json()
    assert rows[0] == {
        "code": "EUR",
        "name": "Euro",
        "kind": "fiat",
        "rate_source": "none",
        "decimals": 2,
    }
    by = {c["code"]: c for c in rows}
    assert by["USD"]["rate_source"] == "ecb" and by["JPY"]["decimals"] == 2
    assert by["BTC"] == {
        "code": "BTC",
        "name": "Bitcoin",
        "kind": "crypto",
        "rate_source": "coingecko",
        "decimals": 8,
    }
    assert {"ETH", "USDC", "USDT", "SOL"} <= set(by) and len(rows) == 35
