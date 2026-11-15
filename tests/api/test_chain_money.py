# ruff: noqa: E501
"""The money of a payout that went through accounts, in Miguel's week and in rows from before.

This file holds what ``test_sent_and_arrived.py`` proved with a payout's "sent" and "arrived"
fields, proved again with ``legs`` and the same figures (the old file is gone with the shape it
tested), and the rows written by older schemas that must still read to the cent.

The ECB and CoinGecko are stubbed in every test: no request leaves the process, and nothing here
depends on the day the suite runs.
"""

from __future__ import annotations

import csv
import io
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


def _account(client, name, currency, **kw):
    r = client.post("/api/freelance/accounts", json={"name": name, "currency": currency, **kw})
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


def _legs(*items) -> list[dict]:
    """Legs from (account, amount) pairs; an amount of None is left to be worked out."""
    return [
        {"account_id": acc["id"], **({} if amount is None else {"amount": amount})}
        for acc, amount in items
    ]


def _payout(client, w45, *items, week=W45, expect=201, **kw):
    body = {"source_id": w45["src"], "week_start": week, "legs": _legs(*items), **kw}
    r = client.post("/api/freelance/payouts", json=body)
    assert r.status_code == expect, r.text
    return r.json()


@pytest.fixture
def w45(client):
    """Miguel's week: $2,029.50 billed (22.55 h at $90), a USD account, a euro one, a dollar one
    and one more euro one."""
    src = _source(client)
    _block(client, src)
    return {
        "src": src,
        "stripe": _account(client, "Stripe", "USD"),
        "bank": _account(client, "Deutsche Bank", "EUR"),
        "mercury": _account(client, "Mercury", "USD"),
        "wise": _account(client, "Wise", "EUR"),
    }


# ── Miguel's W45 ──────────────────────────────────────────────────────────────


class TestMiguelsWeek:
    def test_999_sent_through_a_dollar_account_arrives_as_894_76(self, client, w45):
        out = _payout(client, w45, (w45["stripe"], 999), (w45["bank"], 894.76))
        # what arrived keeps meaning what it meant
        assert (out["amount"], out["currency"], out["amount_eur"]) == (894.76, "EUR", 894.76)
        assert out["account_name"] == "Deutsche Bank"
        # what was sent is the first leg, in its account's currency
        first = out["legs"][0]
        assert (first["amount"], first["currency"], first["account_name"]) == (
            999.0,
            "USD",
            "Stripe",
        )
        # the week billed $2,029.50: the gap is the first leg minus billed, the chip's figure is
        # billed at the day's rate against what arrived
        assert out["billed_amount"] == 2029.5 and out["billed_eur"] == 1817.73
        assert out["gap"] == -1030.5
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
        out = _payout(client, w45, (w45["stripe"], 999), (w45["mercury"], 999))
        assert out["currency"] == "USD" and out["fx_cost_eur"] is None
        assert out["amount_eur"] == 894.76 and out["gap"] == -1030.5

    def test_a_first_leg_in_euros_has_its_gap_converted(self, client, w45):
        out = _payout(client, w45, (w45["wise"], 900))
        # EUR 900 is $1,004.85 at the day's rate: against $2,029.50 billed
        assert out["gap"] == -1024.65 and out["gap_currency"] == "USD"

    def test_a_first_leg_in_the_sources_currency_has_its_gap_as_it_is(self, client, w45):
        out = _payout(client, w45, (w45["mercury"], 1500))
        assert out["gap"] == -529.5

    def test_no_rate_for_the_day_means_no_gap_and_not_a_guess(self, client, w45, monkeypatch):
        fx._reset()
        monkeypatch.setenv("KRONOS_FX_URL", "")
        monkeypatch.setenv("KRONOS_FX_HIST90_URL", "")
        monkeypatch.setenv("KRONOS_FX_HIST_URL", "")
        out = _payout(client, w45, (w45["wise"], 900))
        assert out["gap"] is None

    def test_changing_the_first_leg_keeps_what_arrived_and_dropping_it_goes_back(self, client, w45):
        first = _payout(client, w45, (w45["stripe"], 999), (w45["bank"], 900))
        body = {"source_id": w45["src"], "week_start": W45}
        r = client.put(
            f"/api/freelance/payouts/{first['id']}",
            json={**body, "legs": _legs((w45["stripe"], 1000), (w45["bank"], 900))},
        )
        assert r.status_code == 200
        assert (r.json()["amount"], r.json()["legs"][0]["amount"]) == (900.0, 1000.0)
        r = client.put(
            f"/api/freelance/payouts/{first['id']}",
            json={**body, "legs": _legs((w45["bank"], 900))},
        )
        assert [leg["account_name"] for leg in r.json()["legs"]] == ["Deutsche Bank"]
        assert r.json()["amount"] == 900.0


# ── a payout from before this changed is the same, to the cent ────────────────


class TestRowsAreTheSameToTheCent:
    def test_a_dollar_row_and_a_euro_row_read_exactly_as_they_did(self, client, w45):
        """Replaces the two "old rows" of the older shape: 1,900 dollars (the payout that had no
        account is now in a dollar account) and 800 euros into a euro account."""
        dollars = _payout(client, w45, (w45["mercury"], 1900))
        _block(client, w45["src"], day="2026-10-27", hours=10)  # $900
        euros = _payout(client, w45, (w45["bank"], 800), week=W44, paid_on="2026-11-01")
        # dollars: its euro value from the rate of the day, no exchange to cost
        assert (dollars["amount"], dollars["currency"]) == (1900.0, "USD")
        assert (dollars["amount_eur"], dollars["fx_cost_eur"]) == (1701.75, None)
        assert dollars["billed_amount"] == 2029.5 and dollars["effective_rate"] is None
        # euros: and what the exchange cost against the week's estimate
        assert (euros["amount"], euros["amount_eur"]) == (800.0, 800.0)
        assert (euros["billed_eur"], euros["fx_cost_eur"]) == (806.09, 6.09)

    def test_the_year_figures_do_not_move_either(self, client, w45):
        _payout(client, w45, (w45["mercury"], 1900))
        _block(client, w45["src"], day="2026-10-27", hours=10)
        _payout(client, w45, (w45["bank"], 800), week=W44, paid_on="2026-11-01")
        year = client.get("/api/freelance/summary", params={"year": 2026}).json()
        assert year["fx_cost_eur"] == 6.09


class TestRowsOfSchema0011:
    """Rows written by the schema of the accounts era come out of every later one with their
    figures. (``account_id`` is the one column that may change: a payout with none is given the
    account of its currency.)"""

    def _migrated(self):
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )
        cfg = Config(str(REPO / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO / "alembic"))
        columns = (
            "id, source_id, week_start, amount, currency, fx_rate, note, rate_source, rate_date"
        )
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
                for r in conn.execute(text(f"SELECT {columns} FROM freelance_payouts ORDER BY id"))
            ]
            command.upgrade(cfg, "head")
            conn.commit()
            after = [
                tuple(r)
                for r in conn.execute(text(f"SELECT {columns} FROM freelance_payouts ORDER BY id"))
            ]
            accounts = [
                tuple(r)
                for r in conn.execute(
                    text("SELECT id, account_id FROM freelance_payouts ORDER BY id")
                )
            ]
        return engine, before, after, accounts

    def test_old_rows_keep_every_figure_and_the_dropped_columns_are_gone(self):
        engine, before, after, accounts = self._migrated()
        assert after == before and len(before) == 2
        with engine.connect() as conn:
            payouts = {r[1] for r in conn.execute(text("PRAGMA table_info(freelance_payouts)"))}
            assert not {"sent_amount", "sent_currency", "from_account_id"} & payouts
            assert "role" not in {r[1] for r in conn.execute(text("PRAGMA table_info(accounts)"))}
            sources = {r[1] for r in conn.execute(text("PRAGMA table_info(income_sources)"))}
            assert not {"default_account_id", "default_from_account_id"} & sources
        # the row that had an account keeps it; the one that had none has its currency's
        assert accounts[1] == (2, 1)
        assert accounts[0][1] is not None and accounts[0][1] != 1
        engine.dispose()

    def test_and_the_app_reads_them_as_it_always_did(self):
        engine, *_ = self._migrated()
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
        assert (a["amount"], a["amount_eur"], a["fx_cost_eur"]) == (1900.0, 1701.75, None)
        assert (b["amount"], b["amount_eur"], b["fx_cost_eur"]) == (800.0, 800.0, 6.09)
        assert [leg["amount"] for leg in a["legs"]] == [1900.0]
        assert [leg["amount"] for leg in b["legs"]] == [800.0]
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


# ── restore and the CSV ───────────────────────────────────────────────────────


def _stable(backup: dict) -> dict:
    out = {k: v for k, v in backup.items() if k != "exported_at"}
    out["accounts"] = [{k: v for k, v in a.items() if k != "created_at"} for a in out["accounts"]]
    return out


class TestBackup:
    def test_a_file_that_sends_from_an_unknown_account_is_refused(self, client, w45):
        _payout(client, w45, (w45["stripe"], 999), (w45["bank"], 894.76))
        bad = client.get("/api/backup").json()
        bad["version"] = 5
        (p,) = bad["freelance_payouts"]
        p["sent_amount"], p["sent_currency"], p["from_account_id"] = 999, "USD", 4242
        assert client.post("/api/restore", json=bad).status_code == 422
        bad = client.get("/api/backup").json()
        bad["income_sources"][0]["default_from_account_id"] = 4242
        assert client.post("/api/restore", json=bad).status_code == 422

    def test_the_round_trip_is_identical_and_says_version_6(self, client, w45):
        _payout(client, w45, (w45["stripe"], 999), (w45["bank"], 894.76))
        first = client.get("/api/backup").json()
        assert first["version"] == 6
        assert client.post("/api/restore", json=first).status_code == 200
        second = client.get("/api/backup").json()
        assert _stable(second) == _stable(first)
        (out,) = client.get("/api/freelance/payouts").json()
        assert (out["amount"], out["gap"], out["fx_cost_eur"]) == (894.76, -1030.5, 922.97)


class TestPayoutsCsv:
    def test_the_columns_that_were_there_stay_where_they_were(self, client, w45):
        _payout(client, w45, (w45["stripe"], 999), (w45["bank"], 894.76))
        _payout(client, w45, (w45["mercury"], 100), week=W44)
        rows = list(csv.reader(io.StringIO(client.get("/api/freelance/payouts.csv").text)))
        assert rows[0][:5] == ["week_start", "week_end", "source", "currency", "amount"]
        by_week = {r[0]: r for r in rows[1:]}
        assert by_week[W45][4] == "894.76"
        assert by_week[W45][12] == "Deutsche Bank"  # the "account" column
        # the chain follows the columns that were there: nothing of the sent side in between
        assert rows[0][17:19] == ["fx_cost_eur", "account_1"]
        assert by_week[W45][18:24] == ["Stripe", "999.00", "USD", "Deutsche Bank", "894.76", "EUR"]
        assert by_week[W44][18:21] == ["Mercury", "100.00", "USD"]


def test_the_week_of_a_date_is_a_monday():
    assert date.fromisoformat(W45).weekday() == 0 and date.fromisoformat(W44).weekday() == 0
