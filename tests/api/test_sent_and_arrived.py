# ruff: noqa: E501
"""A payout has two sides: what was sent and what arrived, each with a currency and an amount.

The ECB and CoinGecko are stubbed in every test: no request leaves the process, and nothing here
depends on the day the suite runs.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path

import app.services.crypto as crypto
import app.services.fx as fx
import pytest
from alembic.config import Config
from app.database import get_session
from app.main import app as fastapi_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from alembic import command

REPO = Path(__file__).resolve().parents[2]
RATE = 1.1165  # USD per EUR on every day the ECB document below covers
W45 = "2026-11-02"  # its Sunday, Nov 8, is a weekend: the ECB's last word is Friday's
W44 = "2026-10-26"

_DAYS = ("2026-11-06", "2026-11-05", "2026-11-04", "2026-11-03", "2026-11-02", "2026-10-30")
_CUBES = "".join(f'<Cube time="{d}"><Cube currency="USD" rate="{RATE}"/></Cube>' for d in _DAYS)
ECB = f"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>{_CUBES}</Cube>
</gesmes:Envelope>
"""


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    fx._reset()
    crypto._reset()
    monkeypatch.setattr(fx, "_fetch", lambda url, timeout=3: ECB.encode())
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


def _account(client, name, currency, role="both", **kw):
    r = client.post(
        "/api/freelance/accounts", json={"name": name, "currency": currency, "role": role, **kw}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _source(client, name="Northwind", rate=90, currency="USD", **kw) -> int:
    r = client.post(
        "/api/freelance/sources",
        json={"name": name, "hourly_rate": rate, "currency": currency, **kw},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _block(client, source_id, day="2026-11-03", hours=22.55):
    r = client.post(
        "/api/freelance/blocks",
        json={"date": day, "source_id": source_id, "hours": hours, "fx_rate": RATE},
    )
    assert r.status_code == 201, r.text


def _payout(client, expect=201, **body):
    r = client.post("/api/freelance/payouts", json=body)
    assert r.status_code == expect, r.text
    return r.json()


@pytest.fixture
def w45(client):
    """Miguel's week: $2,029.50 billed (22.55 h at $90), a USD account that sends, a euro one that
    receives, a dollar one that receives and one that does either."""
    src = _source(client)
    _block(client, src)
    return {
        "src": src,
        "stripe": _account(client, "Stripe", "USD", "origin"),
        "bank": _account(client, "Deutsche Bank", "EUR", "destination"),
        "mercury": _account(client, "Mercury", "USD", "destination"),
        "wise": _account(client, "Wise", "EUR", "both"),
    }


# ── Miguel's W45 ──────────────────────────────────────────────────────────────


class TestMiguelsWeek:
    def test_999_sent_through_a_dollar_account_arrives_as_894_76(self, client, w45):
        out = _payout(
            client,
            source_id=w45["src"],
            week_start=W45,
            amount=894.76,
            account_id=w45["bank"]["id"],
            sent_amount=999,
            from_account_id=w45["stripe"]["id"],
        )
        # what arrived keeps meaning what it meant
        assert (out["amount"], out["currency"], out["amount_eur"]) == (894.76, "EUR", 894.76)
        assert out["account_name"] == "Deutsche Bank"
        # what was sent, as stored; the account gives the currency
        assert (out["sent_amount"], out["sent_currency"]) == (999.0, "USD")
        assert (out["from_account_id"], out["from_account_name"]) == (
            w45["stripe"]["id"],
            "Stripe",
        )
        # the week billed $2,029.50: the gap is sent minus billed, the chip's figure is billed
        # at the day's rate against what arrived
        assert out["billed_amount"] == 2029.5 and out["billed_eur"] == 1817.73
        assert out["sent_gap"] == -1030.5
        assert out["fx_cost_eur"] == 922.97
        assert round(922.97 / 1817.73 * 100, 1) == 50.8  # "DIFF -50.8%"

    def test_the_rate_endpoint_answers_units_of_b_per_one_a(self, client):
        r = client.get(
            "/api/freelance/rate", params={"from": "USD", "to": "EUR", "on": "2026-11-08"}
        )
        assert r.status_code == 200
        rate = r.json()["rate"]
        assert rate == pytest.approx(1 / RATE, rel=1e-7)
        assert round(999 * rate, 2) == 894.76  # the suggestion the cell shows
        r = client.get(
            "/api/freelance/rate", params={"from": "EUR", "to": "USD", "on": "2026-11-08"}
        )
        assert r.json() == {"rate": RATE}
        r = client.get(
            "/api/freelance/rate", params={"from": "USD", "to": "USD", "on": "2026-11-08"}
        )
        assert r.json() == {"rate": 1.0}

    def test_no_rate_is_null_and_an_unknown_currency_is_refused(self, client, monkeypatch):
        fx._reset()
        monkeypatch.setenv("KRONOS_FX_URL", "")
        monkeypatch.setenv("KRONOS_FX_HIST90_URL", "")
        monkeypatch.setenv("KRONOS_FX_HIST_URL", "")
        r = client.get(
            "/api/freelance/rate", params={"from": "USD", "to": "EUR", "on": "2026-11-08"}
        )
        assert r.status_code == 200 and r.json() == {"rate": None}
        r = client.get(
            "/api/freelance/rate", params={"from": "XXX", "to": "EUR", "on": "2026-11-08"}
        )
        assert r.status_code == 422

    def test_a_coin_with_no_price_gives_null_without_asking_anyone_else(self, client):
        def refuse(url: str) -> bytes:
            raise OSError("offline")

        crypto._fetch = refuse
        r = client.get(
            "/api/freelance/rate", params={"from": "USD", "to": "BTC", "on": "2025-09-29"}
        )
        assert r.json() == {"rate": None}

    def test_the_same_currency_on_both_sides_has_no_difference_chip_but_a_gap(self, client, w45):
        out = _payout(
            client,
            source_id=w45["src"],
            week_start=W45,
            amount=999,
            account_id=w45["mercury"]["id"],
            sent_amount=999,
            from_account_id=w45["stripe"]["id"],
        )
        assert out["currency"] == "USD" and out["fx_cost_eur"] is None
        assert out["amount_eur"] == 894.76 and out["sent_gap"] == -1030.5

    def test_a_bare_currency_on_line_1_has_no_account_and_its_gap_is_converted(self, client, w45):
        out = _payout(
            client,
            source_id=w45["src"],
            week_start=W45,
            amount=900,
            account_id=w45["wise"]["id"],
            sent_amount=900,
            sent_currency="EUR",
        )
        assert (out["sent_amount"], out["sent_currency"]) == (900.0, "EUR")
        assert out["from_account_id"] is None and out["from_account_name"] is None
        # EUR 900 is $1,004.85 at the day's rate: against $2,029.50 billed
        assert out["sent_gap"] == -1024.65

    def test_an_amount_alone_is_in_the_sources_currency(self, client, w45):
        out = _payout(
            client,
            source_id=w45["src"],
            week_start=W45,
            amount=1500,
            account_id=w45["mercury"]["id"],
            sent_amount=1500,
        )
        assert (out["sent_currency"], out["from_account_id"]) == ("USD", None)
        assert out["sent_gap"] == -529.5

    def test_no_rate_for_the_day_means_no_gap_and_not_a_guess(self, client, w45, monkeypatch):
        fx._reset()
        monkeypatch.setenv("KRONOS_FX_URL", "")
        monkeypatch.setenv("KRONOS_FX_HIST90_URL", "")
        monkeypatch.setenv("KRONOS_FX_HIST_URL", "")
        out = _payout(
            client,
            source_id=w45["src"],
            week_start=W45,
            amount=900,
            account_id=w45["wise"]["id"],
            sent_amount=900,
            sent_currency="EUR",
        )
        assert out["sent_gap"] is None

    def test_changing_the_sent_side_keeps_what_arrived_and_clearing_it_goes_back(self, client, w45):
        base = {
            "source_id": w45["src"],
            "week_start": W45,
            "amount": 900,
            "account_id": w45["bank"]["id"],
        }
        first = _payout(client, **base, sent_amount=999, from_account_id=w45["stripe"]["id"])
        r = client.put(
            f"/api/freelance/payouts/{first['id']}",
            json={**base, "sent_amount": 1000, "from_account_id": w45["stripe"]["id"]},
        )
        assert r.status_code == 200
        assert (r.json()["amount"], r.json()["sent_amount"]) == (900.0, 1000.0)
        r = client.put(f"/api/freelance/payouts/{first['id']}", json=base)
        assert r.json()["sent_amount"] is None and r.json()["from_account_id"] is None
        assert r.json()["sent_currency"] is None and r.json()["sent_gap"] is None


# ── the rules of the two sides ────────────────────────────────────────────────


class TestTheRules:
    def _body(self, w45, **kw):
        return {"source_id": w45["src"], "week_start": W45, "amount": 900, **kw}

    def test_an_account_that_only_receives_cannot_send(self, client, w45):
        r = client.post(
            "/api/freelance/payouts",
            json=self._body(w45, sent_amount=999, from_account_id=w45["bank"]["id"]),
        )
        assert r.status_code == 422
        # the same payout from an account that sends is fine
        _payout(client, **self._body(w45, sent_amount=999, from_account_id=w45["stripe"]["id"]))

    def test_an_account_that_only_sends_cannot_receive(self, client, w45):
        r = client.post(
            "/api/freelance/payouts",
            json=self._body(w45, account_id=w45["stripe"]["id"]),
        )
        assert r.status_code == 422

    def test_an_account_that_does_either_can_be_either_side(self, client, w45):
        out = _payout(
            client,
            **self._body(
                w45,
                account_id=w45["wise"]["id"],
                sent_amount=900,
                from_account_id=w45["wise"]["id"],
            ),
        )
        assert out["account_id"] == out["from_account_id"] == w45["wise"]["id"]

    def test_a_currency_that_disagrees_with_the_sending_account_is_refused(self, client, w45):
        r = client.post(
            "/api/freelance/payouts",
            json=self._body(
                w45, sent_amount=999, sent_currency="EUR", from_account_id=w45["stripe"]["id"]
            ),
        )
        assert r.status_code == 422
        out = _payout(
            client,
            **self._body(
                w45, sent_amount=999, sent_currency="USD", from_account_id=w45["stripe"]["id"]
            ),
        )
        assert out["sent_currency"] == "USD"

    def test_a_sent_side_needs_its_amount(self, client, w45):
        for extra in ({"sent_currency": "EUR"}, {"from_account_id": w45["stripe"]["id"]}):
            r = client.post("/api/freelance/payouts", json=self._body(w45, **extra))
            assert r.status_code == 422, extra
        r = client.post("/api/freelance/payouts", json=self._body(w45, sent_amount=0))
        assert r.status_code == 422

    def test_an_unknown_sending_account_is_refused(self, client, w45):
        r = client.post(
            "/api/freelance/payouts", json=self._body(w45, sent_amount=1, from_account_id=999)
        )
        assert r.status_code == 422

    def test_an_old_row_stays_editable_when_its_account_changes_role(self, client, w45):
        wise = w45["wise"]["id"]
        out = _payout(
            client,
            **self._body(w45, account_id=wise, sent_amount=900, from_account_id=wise),
        )
        client.put(f"/api/freelance/accounts/{wise}", json={"role": "origin"})
        r = client.put(
            f"/api/freelance/payouts/{out['id']}",
            json=self._body(w45, account_id=wise, sent_amount=950, from_account_id=wise),
        )
        assert r.status_code == 200 and r.json()["sent_amount"] == 950
        # a new payout into it is refused
        r = client.post(
            "/api/freelance/payouts",
            json={**self._body(w45, account_id=wise), "week_start": W44},
        )
        assert r.status_code == 422

    def test_an_account_has_a_role_that_defaults_to_both_and_is_validated(self, client):
        a = _account(client, "Plain", "EUR")
        assert a["role"] == "both"
        r = client.put(f"/api/freelance/accounts/{a['id']}", json={"role": "destination"})
        assert r.json()["role"] == "destination"
        r = client.put(f"/api/freelance/accounts/{a['id']}", json={"role": "sideways"})
        assert r.status_code == 422
        assert (
            client.post(
                "/api/freelance/accounts", json={"name": "X", "currency": "EUR", "role": "no"}
            ).status_code
            == 422
        )

    def test_the_sources_two_defaults_follow_the_same_roles(self, client, w45):
        stripe, bank = w45["stripe"]["id"], w45["bank"]["id"]
        src = _source(client, "Other", default_account_id=bank, default_from_account_id=stripe)
        row = {s["id"]: s for s in client.get("/api/freelance/sources").json()}[src]
        assert (row["default_account_id"], row["default_from_account_id"]) == (bank, stripe)
        assert (
            client.put(
                f"/api/freelance/sources/{src}", json={"default_from_account_id": bank}
            ).status_code
            == 422
        )
        assert (
            client.put(
                f"/api/freelance/sources/{src}", json={"default_account_id": stripe}
            ).status_code
            == 422
        )
        r = client.put(f"/api/freelance/sources/{src}", json={"name": "Renamed"})
        assert r.json()["default_from_account_id"] == stripe  # left out: kept
        r = client.put(f"/api/freelance/sources/{src}", json={"default_from_account_id": None})
        assert r.json()["default_from_account_id"] is None

    def test_an_account_in_use_on_either_side_or_as_either_default_is_not_deleted(
        self, client, w45
    ):
        stripe, bank, wise = w45["stripe"]["id"], w45["bank"]["id"], w45["wise"]["id"]
        # a sending account used by a payout
        _payout(
            client,
            **self._body(w45, account_id=bank, sent_amount=999, from_account_id=stripe),
        )
        assert client.delete(f"/api/freelance/accounts/{stripe}").status_code == 409
        assert client.delete(f"/api/freelance/accounts/{bank}").status_code == 409
        assert (
            client.put(f"/api/freelance/accounts/{stripe}", json={"currency": "EUR"}).status_code
            == 409
        )
        # an account that only a source names, once as "Paid from", once as "Paid into"
        _source(client, "A", default_from_account_id=wise)
        assert client.delete(f"/api/freelance/accounts/{wise}").status_code == 409
        assert (
            client.put(f"/api/freelance/accounts/{wise}", json={"currency": "USD"}).status_code
            == 409
        )
        mercury = w45["mercury"]["id"]
        s = _source(client, "B", default_account_id=mercury)
        assert client.delete(f"/api/freelance/accounts/{mercury}").status_code == 409
        # the lock lifts when nothing uses it any more
        client.put(f"/api/freelance/sources/{s}", json={"default_account_id": None})
        assert client.delete(f"/api/freelance/accounts/{mercury}").status_code == 204

    def test_the_account_list_counts_a_payout_on_either_side(self, client, w45):
        _payout(
            client,
            **self._body(
                w45,
                account_id=w45["bank"]["id"],
                sent_amount=999,
                from_account_id=w45["stripe"]["id"],
            ),
        )
        counts = {a["name"]: a["payouts"] for a in client.get("/api/freelance/accounts").json()}
        assert counts["Stripe"] == 1 and counts["Deutsche Bank"] == 1 and counts["Wise"] == 0


# ── a payout from before this changed is the same, to the cent ────────────────


class TestOldRowsDoNotMove:
    def _two_old_rows(self, client, w45):
        """One with no account (in dollars, as before accounts) and one with an account."""
        no_account = _payout(
            client, source_id=w45["src"], week_start=W45, amount=1900, fx_rate=RATE
        )
        _block(client, w45["src"], day="2026-10-27", hours=10)  # $900
        with_account = _payout(
            client,
            source_id=w45["src"],
            week_start=W44,
            amount=800,
            account_id=w45["bank"]["id"],
            paid_on="2026-11-01",
        )
        return no_account, with_account

    def test_a_row_with_no_sent_side_reads_exactly_as_it_did(self, client, w45):
        no_account, with_account = self._two_old_rows(client, w45)
        # no account: dollars, its euro value from the rate it was saved with, no exchange to cost
        assert (no_account["amount"], no_account["currency"]) == (1900.0, "USD")
        assert (no_account["amount_eur"], no_account["fx_cost_eur"]) == (1701.75, None)
        assert no_account["billed_amount"] == 2029.5 and no_account["effective_rate"] is None
        # with an account: euros, and what the exchange cost against the week's estimate
        assert (with_account["amount"], with_account["amount_eur"]) == (800.0, 800.0)
        assert (with_account["billed_eur"], with_account["fx_cost_eur"]) == (806.09, 6.09)
        for row in (no_account, with_account):
            assert row["sent_amount"] is None and row["sent_currency"] is None
            assert row["from_account_id"] is None and row["from_account_name"] is None
            assert row["sent_gap"] is None  # their gap is today's, computed from what arrived

    def test_the_year_figures_do_not_move_either(self, client, w45):
        self._two_old_rows(client, w45)
        year = client.get("/api/freelance/summary", params={"year": 2026}).json()
        assert year["fx_cost_eur"] == 6.09


class TestTheMigration:
    """Rows written by the schema before this one come out of the new one unchanged."""

    def test_old_rows_keep_every_figure_and_the_new_columns_are_empty(self):
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        cfg = Config(str(REPO / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO / "alembic"))
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "0011")
            conn.execute(
                text(
                    "INSERT INTO accounts (id, name, currency, kind, is_default, archived, created_at)"
                    " VALUES (1, 'Deutsche Bank', 'EUR', 'bank', 1, 0, '2026-11-01 10:00:00')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO income_sources (id, name, hourly_rate, currency, is_default, archived,"
                    " default_account_id) VALUES (1, 'Northwind', 90, 'USD', 1, 0, 1)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO freelance_blocks (id, date, source_id, minutes, rate, currency, fx_rate)"
                    " VALUES (1, '2026-11-03', 1, 1353, 90, 'USD', 1.1165),"
                    " (2, '2026-10-27', 1, 600, 90, 'USD', 1.1165)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO freelance_payouts (id, source_id, week_start, amount, currency, fx_rate)"
                    " VALUES (1, 1, '2026-11-02', 1900, 'USD', 1.1165)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO freelance_payouts (id, source_id, week_start, amount, currency,"
                    " account_id, rate_date) VALUES (2, 1, '2026-10-26', 800, 'EUR', 1, '2026-11-01')"
                )
            )
            conn.commit()
            before = [
                tuple(r)
                for r in conn.execute(
                    text(
                        "SELECT id, source_id, week_start, amount, currency, fx_rate, note, account_id,"
                        " rate_source, rate_date FROM freelance_payouts ORDER BY id"
                    )
                )
            ]
            command.upgrade(cfg, "head")
            conn.commit()
            after = [
                tuple(r)
                for r in conn.execute(
                    text(
                        "SELECT id, source_id, week_start, amount, currency, fx_rate, note, account_id,"
                        " rate_source, rate_date FROM freelance_payouts ORDER BY id"
                    )
                )
            ]
            assert after == before
            new = conn.execute(
                text("SELECT sent_amount, sent_currency, from_account_id FROM freelance_payouts")
            ).all()
            assert [tuple(r) for r in new] == [(None, None, None)] * 2
            assert conn.execute(text("SELECT role FROM accounts")).scalar() == "both"
            assert (
                conn.execute(text("SELECT default_from_account_id FROM income_sources")).scalar()
                is None
            )
        # and the app reads them as it always did
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

        def session():
            s = factory()
            try:
                yield s
            finally:
                s.close()

        fastapi_app.dependency_overrides[get_session] = session
        try:
            with TestClient(fastapi_app) as c:
                rows = {p["week_start"]: p for p in c.get("/api/freelance/payouts").json()}
        finally:
            fastapi_app.dependency_overrides.clear()
        a, b = rows[W45], rows[W44]
        assert (a["amount"], a["amount_eur"], a["fx_cost_eur"], a["sent_gap"]) == (
            1900.0,
            1701.75,
            None,
            None,
        )
        assert (b["amount"], b["amount_eur"], b["fx_cost_eur"], b["sent_gap"]) == (
            800.0,
            800.0,
            6.09,
            None,
        )
        engine.dispose()

    def test_the_migration_goes_down_again(self):
        engine = create_engine("sqlite://", poolclass=StaticPool)
        cfg = Config(str(REPO / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO / "alembic"))
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "0011")
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(freelance_payouts)"))}
        engine.dispose()
        assert "sent_amount" not in cols and "from_account_id" not in cols


# ── backup, restore and the CSV ───────────────────────────────────────────────


def _full(client, w45):
    """The W45 payout with its sent side, plus the sources' two defaults."""
    client.put(
        f"/api/freelance/sources/{w45['src']}",
        json={
            "default_account_id": w45["bank"]["id"],
            "default_from_account_id": w45["stripe"]["id"],
        },
    )
    return _payout(
        client,
        source_id=w45["src"],
        week_start=W45,
        amount=894.76,
        account_id=w45["bank"]["id"],
        sent_amount=999,
        from_account_id=w45["stripe"]["id"],
    )


def _stable(backup: dict) -> dict:
    out = json.loads(json.dumps(backup))
    out.pop("exported_at", None)
    for a in out["accounts"]:
        a.pop("created_at", None)
    return out


class TestBackup:
    def test_the_round_trip_carries_roles_defaults_and_the_sent_side(self, client, w45):
        _full(client, w45)
        first = client.get("/api/backup").json()
        assert first["version"] == 4
        assert {a["name"]: a["role"] for a in first["accounts"]} == {
            "Stripe": "origin",
            "Deutsche Bank": "destination",
            "Mercury": "destination",
            "Wise": "both",
        }
        assert first["income_sources"][0]["default_from_account_id"] == w45["stripe"]["id"]
        (p,) = first["freelance_payouts"]
        assert (p["sent_amount"], p["sent_currency"], p["from_account_id"]) == (
            999.0,
            "USD",
            w45["stripe"]["id"],
        )
        assert client.post("/api/restore", json=first).status_code == 200
        second = client.get("/api/backup").json()
        assert _stable(second) == _stable(first)
        (out,) = client.get("/api/freelance/payouts").json()
        assert (out["sent_amount"], out["from_account_name"], out["sent_gap"]) == (
            999.0,
            "Stripe",
            -1030.5,
        )

    def test_a_file_from_before_this_restores_as_before(self, client, w45):
        _full(client, w45)
        old = client.get("/api/backup").json()
        for a in old["accounts"]:
            del a["role"]
        for s in old["income_sources"]:
            del s["default_from_account_id"]
        for p in old["freelance_payouts"]:
            for k in ("sent_amount", "sent_currency", "from_account_id"):
                del p[k]
        assert client.post("/api/restore", json=old).status_code == 200
        assert {a["role"] for a in client.get("/api/freelance/accounts").json()} == {"both"}
        (out,) = client.get("/api/freelance/payouts").json()
        assert out["amount"] == 894.76 and out["amount_eur"] == 894.76
        assert out["sent_amount"] is None and out["sent_gap"] is None
        assert out["fx_cost_eur"] == 922.97  # the chip's figure is the same as always

    def test_a_file_that_sends_from_an_unknown_account_is_refused(self, client, w45):
        _full(client, w45)
        bad = client.get("/api/backup").json()
        bad["freelance_payouts"][0]["from_account_id"] = 4242
        assert client.post("/api/restore", json=bad).status_code == 422
        bad = client.get("/api/backup").json()
        bad["income_sources"][0]["default_from_account_id"] = 4242
        assert client.post("/api/restore", json=bad).status_code == 422


class TestPayoutsCsv:
    def test_the_sent_side_is_at_the_end_and_an_old_row_leaves_it_empty(self, client, w45):
        _full(client, w45)
        old_week = _payout(client, source_id=w45["src"], week_start=W44, amount=100, fx_rate=RATE)
        assert old_week["sent_amount"] is None
        rows = list(csv.reader(io.StringIO(client.get("/api/freelance/payouts.csv").text)))
        assert rows[0][-3:] == ["sent_amount", "sent_currency", "from_account"]
        by_week = {r[0]: r for r in rows[1:]}
        assert by_week[W45][-3:] == ["999.00", "USD", "Stripe"]
        assert by_week[W44][-3:] == ["", "", ""]
        # what was there before is where it was
        assert rows[0][:5] == ["week_start", "week_end", "source", "currency", "amount"]
        assert by_week[W45][4] == "894.76"


def test_the_week_of_a_date_is_a_monday():
    assert date.fromisoformat(W45).weekday() == 0 and date.fromisoformat(W44).weekday() == 0
