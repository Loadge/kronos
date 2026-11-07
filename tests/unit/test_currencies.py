"""The currency catalogue and `rate_for`, the one place a currency becomes euros."""

from __future__ import annotations

import json
from datetime import date, timedelta

import app.services.crypto as crypto
import app.services.fx as fx
import pytest
from app.services import currencies
from app.services.clock import local_today

DOC = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-10-30">
      <Cube currency="USD" rate="1.1172"/>
      <Cube currency="JPY" rate="172.35"/>
      <Cube currency="GBP" rate="0.8650"/>
    </Cube>
    <Cube time="2026-10-29">
      <Cube currency="USD" rate="1.1160"/>
      <Cube currency="JPY" rate="171.00"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    fx._reset()
    crypto._reset()
    daily = DOC.replace(
        """    <Cube time="2026-10-29">
      <Cube currency="USD" rate="1.1160"/>
      <Cube currency="JPY" rate="171.00"/>
    </Cube>
""",
        "",
    )
    monkeypatch.setattr(
        fx, "_fetch", lambda url, timeout=3: (daily if "daily" in url else DOC).encode()
    )
    monkeypatch.setenv("KRONOS_FX_URL", "https://fx.example.invalid/daily.xml")
    monkeypatch.setenv("KRONOS_FX_HIST90_URL", "https://fx.example.invalid/90d.xml")
    monkeypatch.setenv("KRONOS_FX_HIST_URL", "https://fx.example.invalid/all.xml")
    monkeypatch.setenv("KRONOS_CRYPTO_URL", "https://crypto.example.invalid")
    yield
    fx._reset()
    crypto._reset()


def test_the_catalogue_has_eur_the_ecb_and_five_coins():
    assert currencies.CODES[0] == "EUR"
    fiat = [c for c in currencies.CATALOGUE if c.kind == "fiat"]
    assert len(fiat) == 30  # EUR + the 29 the ECB publishes
    assert {"USD", "JPY", "GBP", "ZAR"} <= set(currencies.CODES)
    coins = {c.code: c.coingecko_id for c in currencies.CATALOGUE if c.kind == "crypto"}
    assert coins == {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "USDC": "usd-coin",
        "USDT": "tether",
        "SOL": "solana",
    }
    assert [c.rate_source for c in currencies.CATALOGUE if c.code in ("EUR", "USD", "BTC")] == [
        "none",
        "ecb",
        "coingecko",
    ]
    assert currencies.decimals("USD") == 2 and currencies.decimals("BTC") == 8
    assert len(set(currencies.CODES)) == len(currencies.CODES)


def test_a_coin_amount_keeps_eight_decimals_and_a_fiat_amount_two():
    assert currencies.quantize(0.123456789, "BTC") == 0.12345679
    assert currencies.quantize(0.123456789, "USD") == 0.12
    assert currencies.units(0.01234567, "BTC") == 1234567
    assert currencies.units(877.94, "EUR") == 87794


def test_eur_is_one_with_no_source():
    r = currencies.rate_for("EUR", date(2026, 10, 30))
    assert (r["available"], r["per_eur"], r["source"], r["date"]) == (True, 1.0, None, "2026-10-30")


def test_usd_is_the_ecbs():
    r = currencies.rate_for("USD", date(2026, 10, 30))
    assert (r["available"], r["per_eur"], r["source"], r["date"]) == (
        True,
        1.1172,
        "ECB",
        "2026-10-30",
    )


def test_any_ecb_currency_is_the_ecbs_and_a_weekend_takes_the_last_day():
    r = currencies.rate_for("JPY", date(2026, 10, 31))
    assert (r["per_eur"], r["source"], r["date"]) == (172.35, "ECB", "2026-10-30")
    assert currencies.rate_for("JPY", date(2026, 10, 29))["per_eur"] == 171.0


def test_a_currency_the_ecb_did_not_publish_that_day_is_unavailable():
    r = currencies.rate_for("GBP", date(2026, 10, 29))
    assert r["available"] is False and r["per_eur"] is None and r["error"]


def test_a_coin_is_coingecko_and_a_far_past_date_is_not_asked(monkeypatch):
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return json.dumps({"market_data": {"current_price": {"eur": 68195}}}).encode()

    monkeypatch.setattr(crypto, "_fetch", fetch)
    on = local_today() - timedelta(days=30)
    r = currencies.rate_for("BTC", on)
    assert (r["available"], r["per_eur"], r["source"]) == (True, 1 / 68195, "CoinGecko")
    far = currencies.rate_for("BTC", local_today() - timedelta(days=400))
    assert far["available"] is False and len(calls) == 1


def test_an_unknown_currency_is_unavailable_not_an_error():
    r = currencies.rate_for("XXX", date(2026, 10, 30))
    assert r["available"] is False and "XXX" in r["error"]
