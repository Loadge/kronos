"""Accounts (where the money lands) and payouts in any currency.

The ECB and CoinGecko are stubbed in every test: no request leaves the process.
"""

from __future__ import annotations

import json
from datetime import timedelta

import app.services.crypto as crypto
import app.services.fx as fx
import pytest
from app.services.clock import local_today

ECB_DAILY = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-11-01">
      <Cube currency="USD" rate="1.1172"/>
      <Cube currency="JPY" rate="170.0"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""

ECB_HIST = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-11-01">
      <Cube currency="USD" rate="1.1172"/>
      <Cube currency="JPY" rate="170.0"/>
    </Cube>
    <Cube time="2026-10-30">
      <Cube currency="USD" rate="1.1172"/>
      <Cube currency="JPY" rate="170.0"/>
    </Cube>
    <Cube time="2026-10-29"><Cube currency="USD" rate="1.1172"/></Cube>
    <Cube time="2026-10-27"><Cube currency="USD" rate="1.1172"/></Cube>
    <Cube time="2026-10-26"><Cube currency="USD" rate="1.1172"/></Cube>
  </Cube>
</gesmes:Envelope>
"""


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    fx._reset()
    crypto._reset()
    monkeypatch.setattr(
        fx,
        "_fetch",
        lambda url, timeout=3: (ECB_DAILY if url.endswith("daily.xml") else ECB_HIST).encode(),
    )
    monkeypatch.setenv("KRONOS_FX_URL", "https://fx.example.invalid/daily.xml")
    monkeypatch.setenv("KRONOS_FX_HIST90_URL", "https://fx.example.invalid/90d.xml")
    monkeypatch.setenv("KRONOS_FX_HIST_URL", "https://fx.example.invalid/all.xml")
    monkeypatch.setenv("KRONOS_CRYPTO_URL", "https://crypto.example.invalid")

    def no_coins(url: str) -> bytes:
        raise AssertionError(f"unexpected CoinGecko request {url}")

    monkeypatch.setattr(crypto, "_fetch", no_coins)
    yield
    fx._reset()
    crypto._reset()


def _account(client, name="Deutsche Bank", currency="EUR", **kw):
    r = client.post("/api/freelance/accounts", json={"name": name, "currency": currency, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _source(client, name="Northwind", rate=95, currency="USD", **kw) -> int:
    r = client.post(
        "/api/freelance/sources",
        json={"name": name, "hourly_rate": rate, "currency": currency, **kw},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _block(client, day, source, hours):
    r = client.post(
        "/api/freelance/blocks", json={"date": day, "source_id": source, "hours": hours}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _payout(client, **body):
    r = client.post("/api/freelance/payouts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _w44(client, usd):
    """ISO week 2026-W44 (Mon Oct 26 to Sun Nov 1): 11.15 h at $95 = $1,059.25."""
    for day, hours in (("2026-10-26", 3), ("2026-10-27", 4.15), ("2026-10-29", 4)):
        _block(client, day, usd, hours)


def _summary(client):
    r = client.get("/api/freelance/summary?year=2026&today=2026-11-07")
    assert r.status_code == 200, r.text
    return r.json()


class TestAccountsApi:
    def test_create_list_update_and_the_shape(self, client):
        a = _account(client, "  Deutsche Bank ", "EUR", is_default=True)
        assert (a["name"], a["currency"], a["kind"], a["is_default"], a["archived"]) == (
            "Deutsche Bank",
            "EUR",
            "bank",
            True,
            False,
        )
        assert a["payouts"] == 0 and a["created_at"]
        w = _account(client, "Cold wallet", "BTC", kind="wallet")
        assert client.get("/api/freelance/accounts").json()[0]["id"] == a["id"]
        r = client.put(
            f"/api/freelance/accounts/{w['id']}",
            json={"name": "Hot wallet", "kind": "other", "is_default": True},
        )
        assert r.status_code == 200
        rows = {x["id"]: x for x in client.get("/api/freelance/accounts").json()}
        assert (rows[w["id"]]["name"], rows[w["id"]]["is_default"]) == ("Hot wallet", True)
        assert rows[a["id"]]["is_default"] is False  # at most one default

    def test_archived_accounts_are_listed_and_flagged(self, client):
        a = _account(client, is_default=True)
        client.put(f"/api/freelance/accounts/{a['id']}", json={"archived": True})
        (row,) = client.get("/api/freelance/accounts").json()
        assert row["archived"] is True and row["is_default"] is False

    def test_validation(self, client):
        post = client.post
        assert (
            post("/api/freelance/accounts", json={"name": "", "currency": "EUR"}).status_code == 422
        )
        long = {"name": "x" * 61, "currency": "EUR"}
        assert post("/api/freelance/accounts", json=long).status_code == 422
        assert (
            post("/api/freelance/accounts", json={"name": "x" * 60, "currency": "EUR"}).status_code
            == 201
        )
        bad_currency = {"name": "A", "currency": "XXX"}
        assert post("/api/freelance/accounts", json=bad_currency).status_code == 422
        assert (
            post(
                "/api/freelance/accounts", json={"name": "B", "currency": "EUR", "kind": "safe"}
            ).status_code
            == 422
        )
        assert client.put("/api/freelance/accounts/999", json={"name": "x"}).status_code == 404

    def test_the_name_is_unique_whatever_the_case(self, client):
        a = _account(client, "Revolut", "USD")
        r = client.post("/api/freelance/accounts", json={"name": "REVOLUT", "currency": "EUR"})
        assert r.status_code == 409
        other = _account(client, "Other", "EUR")
        r = client.put(f"/api/freelance/accounts/{other['id']}", json={"name": "revolut"})
        assert r.status_code == 409
        # renaming to its own name in another case is fine
        assert (
            client.put(f"/api/freelance/accounts/{a['id']}", json={"name": "REVOLUT"}).status_code
            == 200
        )

    def test_an_account_with_payouts_is_not_deleted_nor_changes_currency(self, client):
        usd = _source(client)
        a = _account(client)
        _payout(client, source_id=usd, week_start="2026-10-26", amount=100, account_id=a["id"])
        r = client.delete(f"/api/freelance/accounts/{a['id']}")
        assert r.status_code == 409
        r = client.put(f"/api/freelance/accounts/{a['id']}", json={"currency": "USD"})
        assert r.status_code == 409
        # the same currency, or a rename, is not a change
        assert (
            client.put(f"/api/freelance/accounts/{a['id']}", json={"currency": "EUR"}).status_code
            == 200
        )
        assert [x["payouts"] for x in client.get("/api/freelance/accounts").json()] == [1]
        assert len(client.get("/api/freelance/accounts").json()) == 1  # still there

    def test_an_unused_account_is_deleted_and_leaves_no_default_behind(self, client):
        a = _account(client)
        usd = _source(client, default_account_id=a["id"])
        assert client.get("/api/freelance/sources").json()[0]["default_account_id"] == a["id"]
        assert client.delete(f"/api/freelance/accounts/{a['id']}").status_code == 204
        assert client.get("/api/freelance/accounts").json() == []
        (src,) = client.get("/api/freelance/sources").json()
        assert src["id"] == usd and src["default_account_id"] is None

    def test_a_source_default_account_must_exist_and_can_be_cleared(self, client):
        r = client.post(
            "/api/freelance/sources",
            json={"name": "A", "hourly_rate": 1, "default_account_id": 77},
        )
        assert r.status_code == 422
        a = _account(client)
        s = _source(client)
        r = client.put(f"/api/freelance/sources/{s}", json={"default_account_id": a["id"]})
        assert r.json()["default_account_id"] == a["id"]
        r = client.put(f"/api/freelance/sources/{s}", json={"name": "Renamed"})
        assert r.json()["default_account_id"] == a["id"]  # left out: kept
        r = client.put(f"/api/freelance/sources/{s}", json={"default_account_id": None})
        assert r.json()["default_account_id"] is None


class TestTheCase:
    """USD $95/h, 11.15 h in 2026-W44 = $1,059.25; 877.94 arrived in euros."""

    def test_a_euro_account_reads_what_arrived_not_the_dollar_conversion(self, client):
        usd = _source(client)
        a = _account(client)
        _w44(client, usd)
        out = _payout(
            client,
            source_id=usd,
            week_start="2026-10-26",
            amount=877.94,
            account_id=a["id"],
        )
        assert (out["currency"], out["amount"], out["amount_eur"]) == ("EUR", 877.94, 877.94)
        assert (out["account_id"], out["account_name"]) == (a["id"], "Deutsche Bank")
        assert out["fx_rate"] is None and out["rate_source"] is None
        assert out["rate_date"] == "2026-11-01"  # the week's Sunday, as no paid_on was given
        assert (out["billed_amount"], out["billed_currency"]) == (1059.25, "USD")
        assert out["billed_eur"] == 948.13
        assert out["fx_cost_eur"] == 70.19
        assert out["effective_rate"] == 1.2065
        s = _summary(client)
        assert s["total"]["gross_eur"] == 877.94 and s["total"]["paid_out_eur"] == 877.94
        assert s["by_month"][9]["gross_eur"] == 877.94  # October, where the blocks are
        q4 = s["quarters"][3]
        assert (q4["gross_eur"], q4["gross_ytd"]) == (877.94, 877.94)  # the 130's base
        assert s["fx_cost_eur"] == 70.19
        assert s["accounts"] == [
            {
                "id": a["id"],
                "name": "Deutsche Bank",
                "currency": "EUR",
                "amount": 877.94,
                "amount_eur": 877.94,
                "payouts": 1,
            }
        ]
        # a dollar source still totals in dollars: the euros turned back at the ECB's rate
        (by_source,) = s["by_source"]
        assert (by_source["currency"], by_source["amount"]) == ("USD", 980.83)  # 877.94 x 1.1172

    def test_the_same_payout_with_no_account_still_reads_as_dollars(self, client):
        usd = _source(client)
        _w44(client, usd)
        out = _payout(client, source_id=usd, week_start="2026-10-26", amount=877.94)
        assert (out["currency"], out["account_id"], out["amount_eur"]) == ("USD", None, 785.84)
        assert out["fx_cost_eur"] is None and out["effective_rate"] is None
        assert (out["billed_amount"], out["billed_currency"]) == (1059.25, "USD")
        s = _summary(client)
        assert s["total"]["gross_eur"] == 785.84
        assert s["fx_cost_eur"] == 0.0 and s["accounts"] == []
        assert s["by_source"][0]["amount"] == 877.94

    def test_a_dollar_account_for_a_dollar_source_has_no_exchange_cost(self, client):
        usd = _source(client)
        a = _account(client, "Wise USD", "USD")
        _w44(client, usd)
        out = _payout(
            client, source_id=usd, week_start="2026-10-26", amount=1000, account_id=a["id"]
        )
        assert (out["currency"], out["fx_rate"], out["rate_source"]) == ("USD", 1.1172, "ECB")
        assert out["amount_eur"] == 895.09
        assert out["fx_cost_eur"] is None and out["effective_rate"] is None

    def test_a_hand_typed_euro_value_beats_any_rate(self, client):
        usd = _source(client)
        a = _account(client, "Wise USD", "USD")
        _w44(client, usd)
        out = _payout(
            client,
            source_id=usd,
            week_start="2026-10-26",
            amount=1000,
            account_id=a["id"],
            eur_amount=900,
        )
        assert (out["amount_eur"], out["rate_source"], out["fx_rate"]) == (
            900.0,
            "manual",
            1000 / 900,
        )

    def test_paid_on_picks_the_day_of_the_rate(self, client):
        usd = _source(client)
        a = _account(client, "Wise USD", "USD")
        out = _payout(
            client,
            source_id=usd,
            week_start="2026-10-26",
            amount=1000,
            account_id=a["id"],
            paid_on="2026-10-29",
        )
        assert out["rate_date"] == "2026-10-29"

    def test_an_account_in_another_ecb_currency(self, client):
        usd = _source(client)
        a = _account(client, "Yen", "JPY")
        out = _payout(
            client,
            source_id=usd,
            week_start="2026-10-26",
            amount=170000,
            account_id=a["id"],
            paid_on="2026-10-30",
        )
        assert (out["currency"], out["fx_rate"], out["rate_source"]) == ("JPY", 170.0, "ECB")
        assert out["amount_eur"] == 1000.0

    def test_no_rate_and_no_eur_amount_saves_it_as_missing(self, client, monkeypatch):
        monkeypatch.setenv("KRONOS_FX_URL", "")
        monkeypatch.setenv("KRONOS_FX_HIST90_URL", "")
        monkeypatch.setenv("KRONOS_FX_HIST_URL", "")
        fx._reset()
        usd = _source(client)
        a = _account(client, "Wise USD", "USD")
        out = _payout(
            client, source_id=usd, week_start="2026-10-26", amount=1000, account_id=a["id"]
        )
        assert out["fx_rate"] is None and out["amount_eur"] is None
        assert out["rate_source"] is None and out["rate_date"] == "2026-11-01"

    def test_updating_the_amount_keeps_the_stored_rate(self, client):
        usd = _source(client)
        a = _account(client, "Wise USD", "USD")
        out = _payout(
            client,
            source_id=usd,
            week_start="2026-10-26",
            amount=1000,
            account_id=a["id"],
            eur_amount=900,
        )
        r = client.put(
            f"/api/freelance/payouts/{out['id']}",
            json={
                "source_id": usd,
                "week_start": "2026-10-26",
                "amount": 1100,
                "account_id": a["id"],
                "fx_rate": 1000 / 900,
            },
        )
        assert r.status_code == 200
        assert r.json()["amount_eur"] == 990.0

    def test_the_account_is_checked(self, client):
        usd = _source(client)
        r = client.post(
            "/api/freelance/payouts",
            json={"source_id": usd, "week_start": "2026-10-26", "amount": 5, "account_id": 99},
        )
        assert r.status_code == 422


class TestCrypto:
    def test_a_btc_wallet_payout_30_days_ago(self, client, monkeypatch):
        calls: list[str] = []

        def fetch(url: str) -> bytes:
            calls.append(url)
            return json.dumps({"market_data": {"current_price": {"eur": 68195}}}).encode()

        monkeypatch.setattr(crypto, "_fetch", fetch)
        usd = _source(client)
        wallet = _account(client, "Cold wallet", "BTC", kind="wallet")
        on = local_today() - timedelta(days=30)
        monday = on - timedelta(days=on.weekday())
        out = _payout(
            client,
            source_id=usd,
            week_start=monday.isoformat(),
            amount=0.01,
            account_id=wallet["id"],
            paid_on=on.isoformat(),
        )
        assert out["currency"] == "BTC" and out["amount"] == 0.01
        assert out["amount_eur"] == 681.95
        assert (out["rate_source"], out["rate_date"]) == ("CoinGecko", on.isoformat())
        assert len(calls) == 1 and "/coins/bitcoin/history?date=" in calls[0]

    def test_400_days_ago_makes_no_request_and_the_rate_is_missing(self, client, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(crypto, "_fetch", lambda url: calls.append(url) or b"{}")
        usd = _source(client)
        wallet = _account(client, "Cold wallet", "BTC", kind="wallet")
        on = local_today() - timedelta(days=400)
        monday = on - timedelta(days=on.weekday())
        out = _payout(
            client,
            source_id=usd,
            week_start=monday.isoformat(),
            amount=0.01,
            account_id=wallet["id"],
            paid_on=on.isoformat(),
        )
        assert calls == []
        assert out["fx_rate"] is None and out["amount_eur"] is None
        # typed by hand, it counts
        out = client.put(
            f"/api/freelance/payouts/{out['id']}",
            json={
                "source_id": usd,
                "week_start": monday.isoformat(),
                "amount": 0.01,
                "account_id": wallet["id"],
                "paid_on": on.isoformat(),
                "eur_amount": 250.5,
            },
        ).json()
        assert (out["amount_eur"], out["rate_source"]) == (250.5, "manual")
        assert calls == []

    def test_a_coin_amount_keeps_its_eight_decimals(self, client):
        usd = _source(client)
        wallet = _account(client, "Cold wallet", "BTC", kind="wallet")
        out = _payout(
            client,
            source_id=usd,
            week_start="2026-10-26",
            amount=0.12345678,
            account_id=wallet["id"],
            eur_amount=8000,
        )
        assert out["amount"] == 0.12345678
        csv_rows = client.get("/api/freelance/payouts.csv").text.splitlines()
        assert csv_rows[1].split(",")[4] == "0.12345678"


class TestBlocksInAnyCurrency:
    def test_a_yen_source_snapshots_the_ecb_rate_of_its_day(self, client):
        jpy = _source(client, "Tokyo", 15000, "JPY")
        b = _block(client, "2026-10-30", jpy, 2)
        assert (b["currency"], b["fx_rate"], b["amount"], b["amount_eur"]) == (
            "JPY",
            170.0,
            30000.0,
            176.47,
        )

    def test_the_calculator_asks_for_a_rate_in_any_currency_but_euros(self, client):
        base = {"year": 2026, "mode": "hourly", "value": 100, "billable_days": 200}
        assert (
            client.post("/api/freelance/calc", json={**base, "currency": "JPY"}).status_code == 422
        )
        r = client.post("/api/freelance/calc", json={**base, "currency": "JPY", "fx_rate": 170.0})
        assert r.status_code == 200 and r.json()["fx_rate"] == 170.0
        assert (
            client.post("/api/freelance/calc", json={**base, "currency": "EUR"}).json()["fx_rate"]
            is None
        )
