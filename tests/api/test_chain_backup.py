"""A backup carries the chain of accounts, and a restore brings it back.

Version 5 added each payout's legs, each source's usual chain and the hand-made order of accounts
and sources; version 6 dropped the account role, a source's default accounts and a payout's sent
side, which the chains say. A restore of an older file builds the chains by the rule the
migrations used, so the two agree: ``tests/fixtures/eras/v56.backup.json`` and
``v57.backup.json`` were written by the real old code from the same data as ``v56.sql`` /
``v57.sql``, and what they restore to is what ``era_expectations`` says by hand (the migration
test checks the same figures).

The ECB is stubbed with the document the fixtures were made with and a coin's price fails the
test: nothing here reaches the network or depends on the day it runs.
"""

from __future__ import annotations

import csv
import io
import json

import app.services.crypto as crypto
import app.services.fx as fx
import pytest
from app.database import Base, get_session
from app.main import app as fastapi_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tests.api.era_expectations import ACCOUNT_ORDER, CHAINS, ERAS, LEGS, MONEY
from tests.api.test_chain_migration import _client, _engine, _upgrade

W45 = "2026-11-02"


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    fx._reset()
    crypto._reset()
    history = (ERAS / "ecb.xml").read_bytes()
    daily = (ERAS / "ecb_daily.xml").read_bytes()
    monkeypatch.setattr(
        fx, "_fetch", lambda url, timeout=3: daily if url.endswith("daily.xml") else history
    )
    monkeypatch.setenv("KRONOS_FX_URL", "https://fx.example.invalid/daily.xml")
    monkeypatch.setenv("KRONOS_FX_HIST90_URL", "https://fx.example.invalid/90d.xml")
    monkeypatch.setenv("KRONOS_FX_HIST_URL", "https://fx.example.invalid/all.xml")
    monkeypatch.setenv("KRONOS_CRYPTO_URL", "https://crypto.example.invalid")

    def no_coins(url: str, timeout: float = 5) -> bytes:
        raise AssertionError(f"unexpected CoinGecko request {url}")

    monkeypatch.setattr(crypto, "_fetch", no_coins)
    yield
    fx._reset()
    crypto._reset()


# ---------- helpers ----------------------------------------------------------------


def _restore(engine, payload: dict):
    try:
        with _client(engine) as c:
            return c.post("/api/restore", json=payload)
    finally:
        fastapi_app.dependency_overrides.clear()


def _sql(engine, query: str) -> list[tuple]:
    with engine.connect() as conn:
        return [tuple(r) for r in conn.execute(text(query))]


def _legs_by_week(engine) -> dict[tuple[int, str], list[tuple]]:
    """(source id, week) -> [(account name, amount, fixed), ...] in the chain's order."""
    out: dict[tuple[int, str], list[tuple]] = {}
    rows = _sql(
        engine,
        "SELECT p.source_id, p.week_start, l.position, a.name, l.amount, l.fixed"
        " FROM freelance_payout_legs l JOIN freelance_payouts p ON p.id = l.payout_id"
        " JOIN accounts a ON a.id = l.account_id ORDER BY p.id, l.position",
    )
    for source_id, week, position, name, amount, fixed in rows:
        chain = out.setdefault((source_id, str(week)), [])
        assert position == len(chain)
        chain.append((name, amount, bool(fixed)))
    return out


def _source_chains(engine) -> dict[str, list[str]]:
    chains = {n: [] for (n,) in _sql(engine, "SELECT name FROM income_sources")}
    for name, account in _sql(
        engine,
        "SELECT s.name, a.name FROM income_source_accounts c"
        " JOIN income_sources s ON s.id = c.source_id JOIN accounts a ON a.id = c.account_id"
        " ORDER BY c.source_id, c.position",
    ):
        chains[name].append(account)
    return chains


def _dump(engine) -> dict:
    """Everything the chain touches, with no row id that a restore is free to change."""
    columns = [r[1] for r in _sql(engine, "PRAGMA table_info(freelance_payouts)") if r[1] != "id"]
    legs = _legs_by_week(engine)
    payouts = _sql(
        engine,
        f"SELECT {', '.join(columns)} FROM freelance_payouts ORDER BY source_id, week_start",
    )
    keyed = {
        (r[columns.index("source_id")], str(r[columns.index("week_start")])): r for r in payouts
    }
    return {
        "accounts": _sql(
            engine,
            "SELECT id, name, currency, kind, is_default, archived, created_at, position"
            " FROM accounts ORDER BY id",
        ),
        "sources": _sql(
            engine,
            "SELECT id, name, hourly_rate, currency, is_default, archived, position"
            " FROM income_sources ORDER BY id",
        ),
        "chains": _sql(
            engine,
            "SELECT source_id, position, account_id FROM income_source_accounts"
            " ORDER BY source_id, position",
        ),
        "payouts": [(key, row, legs.get(key)) for key, row in sorted(keyed.items())],
    }


def _orphans(engine) -> dict[str, int]:
    return {
        "legs": _sql(
            engine,
            "SELECT COUNT(*) FROM freelance_payout_legs"
            " WHERE payout_id NOT IN (SELECT id FROM freelance_payouts)",
        )[0][0],
        "legs_account": _sql(
            engine,
            "SELECT COUNT(*) FROM freelance_payout_legs"
            " WHERE account_id NOT IN (SELECT id FROM accounts)",
        )[0][0],
        "chain": _sql(
            engine,
            "SELECT COUNT(*) FROM income_source_accounts"
            " WHERE source_id NOT IN (SELECT id FROM income_sources)",
        )[0][0],
        "chain_account": _sql(
            engine,
            "SELECT COUNT(*) FROM income_source_accounts"
            " WHERE account_id NOT IN (SELECT id FROM accounts)",
        )[0][0],
    }


def _era_file(name: str) -> dict:
    return json.loads((ERAS / f"{name}.backup.json").read_text("utf-8"))


def _era_answers(name: str) -> dict:
    return json.loads((ERAS / f"{name}.json").read_text("utf-8"))


@pytest.fixture(params=["v56", "v57"])
def restored_era(request):
    """An empty, fully migrated database with a past version's backup restored into it."""
    name = request.param
    engine = _engine(upto="head")
    assert _sql(engine, "SELECT COUNT(*) FROM accounts") == [(0,)]
    assert _restore(engine, _era_file(name)).status_code == 200
    yield name, engine
    engine.dispose()


# ---------- a) an old file restores to what the migration gives ---------------------


class TestAnOldFileGivesWhatTheMigrationGives:
    def test_the_file_is_a_version_4_one_without_chains(self, restored_era):
        """A positive control: the proof below means nothing if the file already had chains."""
        name, _ = restored_era
        file = _era_file(name)
        assert file["version"] == 4
        assert all("legs" not in p for p in file["freelance_payouts"])
        assert all("chain" not in s and "position" not in s for s in file["income_sources"])
        assert all("position" not in a for a in file["accounts"])
        assert len(file["freelance_payouts"]) == len(LEGS[name]) == 12 + 6 * (name == "v57")

    def test_every_payout_gets_the_chain_the_migration_gives_it(self, restored_era):
        name, engine = restored_era
        want = {}
        for old in _era_answers(name)["payouts"]:
            want[(old["source_id"], old["week_start"])] = [
                (account, amount, True) for account, amount in LEGS[name][old["id"]]
            ]
        got = _legs_by_week(engine)
        assert got == want
        assert len(got) == len(_sql(engine, "SELECT id FROM freelance_payouts"))

    def test_every_source_gets_paid_from_then_paid_into(self, restored_era):
        name, engine = restored_era
        assert _source_chains(engine) == CHAINS[name]

    def test_the_lists_keep_the_order_they_were_shown_in(self, restored_era):
        name, engine = restored_era
        accounts = _sql(engine, "SELECT name, position FROM accounts ORDER BY position")
        assert [a[0] for a in accounts] == ACCOUNT_ORDER[name]
        assert [a[1] for a in accounts] == list(range(len(accounts)))
        sources = _sql(engine, "SELECT name, position FROM income_sources ORDER BY position")
        assert sources == [("Northwind Labs", 0), ("Local consulting", 1), ("Old client", 2)]

    def test_the_last_leg_of_each_is_what_the_payout_is_worth(self, restored_era):
        _, engine = restored_era
        rows = _sql(
            engine,
            "SELECT p.amount, p.currency, l.amount, a.currency FROM freelance_payouts p"
            " JOIN freelance_payout_legs l ON l.payout_id = p.id"
            " JOIN accounts a ON a.id = l.account_id"
            " WHERE l.position = (SELECT MAX(position) FROM freelance_payout_legs"
            "                     WHERE payout_id = p.id)",
        )
        assert rows and all(r[:2] == r[2:] for r in rows)


def _by_name(engine) -> dict:
    """What a database says about accounts, chains and payouts, with every account by its name:
    the ids a restore gives are its own business, the figures are not."""
    accounts = {i: n for i, n in _sql(engine, "SELECT id, name FROM accounts")}
    payouts = _sql(
        engine,
        "SELECT source_id, week_start, amount, currency, fx_rate, rate_source, rate_date, note,"
        " account_id FROM freelance_payouts ORDER BY source_id, week_start",
    )
    return {
        "accounts": _sql(
            engine,
            "SELECT name, currency, kind, is_default, archived, position FROM accounts"
            " ORDER BY position",
        ),
        "sources": _sql(
            engine,
            "SELECT name, hourly_rate, currency, is_default, archived, position"
            " FROM income_sources ORDER BY position",
        ),
        "chains": _source_chains(engine),
        "payouts": [(*p[:8], accounts[p[8]]) for p in payouts],
        "legs": _legs_by_week(engine),
    }


class TestARestoreIsWhatTheMigrationGives:
    """The same data, once as a database that 0013 and 0014 migrate and once as the backup the
    same version wrote and a restore reads: the two answer alike, account by account and cent
    by cent (the era files are the real old code's)."""

    @pytest.mark.parametrize("era", ["v56", "v57"])
    def test_accounts_chains_and_payouts_are_the_same(self, era):
        migrated = _engine(script=(ERAS / f"{era}.sql").read_text("utf-8"))
        _upgrade(migrated)
        restored = _engine(upto="head")
        assert _restore(restored, _era_file(era)).status_code == 200
        want, got = _by_name(migrated), _by_name(restored)
        # the controls: there is something to compare, and it has the made accounts and a chain
        assert len(want["payouts"]) == len(LEGS[era]) and want["chains"]["Northwind Labs"]
        assert any(n.startswith("USD account") for n, *_ in want["accounts"])
        assert want["legs"] and all(p[8] for p in want["payouts"])  # every payout has an account
        assert got == want
        migrated.dispose()
        restored.dispose()

    @pytest.mark.parametrize("era", ["v56", "v57"])
    def test_the_payouts_account_is_the_last_legs(self, era):
        restored = _engine(upto="head")
        assert _restore(restored, _era_file(era)).status_code == 200
        rows = _sql(
            restored,
            "SELECT p.id, p.account_id, (SELECT l.account_id FROM freelance_payout_legs l"
            " WHERE l.payout_id = p.id ORDER BY l.position DESC LIMIT 1) FROM freelance_payouts p",
        )
        assert len(rows) == len(LEGS[era]) and all(a is not None and a == b for _, a, b in rows)
        restored.dispose()

    def test_the_old_fields_of_an_older_file_are_read_and_not_kept(self):
        """A v57 file says role, default accounts and a sent side: they become chains and legs,
        and nothing of them is left to write again."""
        restored = _engine(upto="head")
        file = _era_file("v57")
        assert any("role" in a for a in file["accounts"])
        assert any(s.get("default_from_account_id") for s in file["income_sources"])
        assert any(p.get("sent_amount") for p in file["freelance_payouts"])
        assert _restore(restored, file).status_code == 200
        try:
            with _client(restored) as c:
                again = c.get("/api/backup").json()
        finally:
            fastapi_app.dependency_overrides.clear()
        assert again["version"] == 6
        assert not any("role" in a for a in again["accounts"])
        assert not any(
            {"default_account_id", "default_from_account_id"} & s.keys()
            for s in again["income_sources"]
        )
        assert not any(
            {"sent_amount", "sent_currency", "from_account_id"} & p.keys()
            for p in again["freelance_payouts"]
        )
        restored.dispose()


class TestNoFigureMovesOnRestore:
    def test_the_app_answers_what_the_old_version_answered(self, restored_era):
        name, engine = restored_era
        try:
            with _client(engine) as c:
                now = c.get("/api/freelance/payouts").json()
        finally:
            fastapi_app.dependency_overrides.clear()
        by_key = {(p["source_id"], p["week_start"]): p for p in now}
        old = _era_answers(name)["payouts"]
        assert len(now) == len(old) == len(by_key)
        for was in old:
            got = by_key[(was["source_id"], was["week_start"])]
            assert {k: got[k] for k in MONEY} == {k: was[k] for k in MONEY}, f"payout {was['id']}"


# ---------- c) the round trip ------------------------------------------------------


class TestTheRoundTrip:
    def test_a_version_6_backup_restores_to_an_identical_database(self):
        a = _engine(script=(ERAS / "v57.sql").read_text("utf-8"))
        _upgrade(a)
        try:
            with _client(a) as c:
                ids = {x["name"]: x["id"] for x in c.get("/api/freelance/accounts").json()}
                made = c.post(
                    "/api/freelance/payouts",
                    json={
                        "source_id": 1,
                        "week_start": "2026-11-09",
                        "legs": [
                            {"account_id": ids["Stripe"], "amount": 1000},
                            {"account_id": ids["Dollar account"]},  # worked out: not fixed
                            {"account_id": ids["Main bank"], "amount": 890.1},
                        ],
                    },
                )
                assert made.status_code == 201, made.text
                assert [leg["fixed"] for leg in made.json()["legs"]] == [True, False, True]
        finally:
            fastapi_app.dependency_overrides.clear()
        # a hand-made order, not the one they started with
        started_as = dict(_sql(a, "SELECT name, position FROM accounts"))
        assert sorted(started_as.values()) == list(range(len(started_as)))
        with a.begin() as conn:
            conn.execute(text("UPDATE accounts SET position = position * 3 + 7"))
            conn.execute(text("UPDATE income_sources SET position = (3 - position) * 5"))
        try:
            with _client(a) as c:
                raw = c.get("/api/backup")
                assert raw.status_code == 200
                backup = raw.json()
        finally:
            fastapi_app.dependency_overrides.clear()
        assert backup["version"] == 6
        assert {x["name"]: x["position"] for x in backup["accounts"]} == {
            name: position * 3 + 7 for name, position in started_as.items()
        }
        assert {x["name"]: x["position"] for x in backup["income_sources"]} == {
            "Northwind Labs": 15,
            "Local consulting": 10,
            "Old client": 5,
        }
        (three,) = [p for p in backup["freelance_payouts"] if len(p["legs"]) == 3]
        assert [leg["fixed"] for leg in three["legs"]] == [True, False, True]
        assert all(p["legs"] for p in backup["freelance_payouts"])

        b = _engine(upto="head")
        assert _restore(b, backup).status_code == 200

        dump_a, dump_b = _dump(a), _dump(b)
        assert dump_a == dump_b
        # positive controls: the comparison is not between two empty things
        assert len(dump_a["payouts"]) == 19 and all(p[2] for p in dump_a["payouts"])
        assert [p[2] for p in dump_a["payouts"] if len(p[2]) == 3] == [
            [
                ("Stripe", 1000.0, True),
                ("Dollar account", 1000.0, False),
                ("Main bank", 890.1, True),
            ]
        ]
        assert dump_a["chains"]
        assert {n: p for n, p in _sql(b, "SELECT name, position FROM accounts")} == {
            name: position * 3 + 7 for name, position in started_as.items()
        }
        assert _sql(b, "SELECT name FROM income_sources ORDER BY position") == [
            ("Old client",),
            ("Local consulting",),
            ("Northwind Labs",),
        ]
        a.dispose()
        b.dispose()


# ---------- d) the refusals and the fall-backs ------------------------------------------


def _account(client, name, currency):
    r = client.post("/api/freelance/accounts", json={"name": name, "currency": currency})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _world(client):
    """Northwind Labs (dollars), a payout through Stripe into Main bank, two more accounts."""
    ids = {
        "stripe": _account(client, "Stripe", "USD"),
        "bank": _account(client, "Main bank", "EUR"),
        "mercury": _account(client, "Mercury", "USD"),
        "wise": _account(client, "Wise", "EUR"),
    }
    r = client.post(
        "/api/freelance/sources",
        json={
            "name": "Northwind Labs",
            "hourly_rate": 90,
            "currency": "USD",
            "chain": [ids["stripe"], ids["bank"]],
        },
    )
    assert r.status_code == 201, r.text
    ids["src"] = r.json()["id"]
    r = client.post(
        "/api/freelance/payouts",
        json={
            "source_id": ids["src"],
            "week_start": W45,
            "legs": [
                {"account_id": ids["stripe"], "amount": 999},
                {"account_id": ids["bank"], "amount": 894.76},
            ],
        },
    )
    assert r.status_code == 201, r.text
    return ids


@pytest.fixture
def world(client):
    return _world(client)


def as_version_4(file: dict, ids: dict) -> dict:
    """The file a version 4 Kronos wrote for the same data: no positions, no chains, no legs;
    the sent side and the arrival in the payout's columns, the usual accounts in the source's."""
    file["version"] = 4
    for a in file["accounts"]:
        del a["position"]
        a["role"] = "both"
    for src in file["income_sources"]:
        del src["chain"], src["position"]
        src["default_account_id"] = ids["bank"]
        src["default_from_account_id"] = ids["stripe"]
    for p in file["freelance_payouts"]:
        first = p["legs"][0]
        p["sent_amount"], p["sent_currency"] = first["amount"], "USD"
        p["from_account_id"] = first["account_id"]
        del p["legs"]
    return file


def _stable(backup: dict) -> dict:
    out = json.loads(json.dumps(backup))
    out.pop("exported_at", None)
    return out


class TestTheRefusals:
    def _refused(self, client, mutate, *needles):
        before = client.get("/api/backup").json()
        file = json.loads(json.dumps(before))
        mutate(file)
        r = client.post("/api/restore", json=file)
        assert r.status_code == 422, r.text
        for needle in needles:
            assert needle in r.json()["detail"], r.json()["detail"]
        # and nothing was wiped on the way
        assert _stable(client.get("/api/backup").json()) == _stable(before)

    def test_a_leg_on_an_unknown_account(self, client, world):
        def mutate(f):
            f["freelance_payouts"][0]["legs"][0]["account_id"] = 4242

        self._refused(client, mutate, W45, "unknown account 4242")

    def test_more_than_four_legs(self, client, world):
        def mutate(f):
            leg = f["freelance_payouts"][0]["legs"][1]
            f["freelance_payouts"][0]["legs"] = [leg] * 5

        self._refused(client, mutate, W45, "more than 4 legs")

    def test_the_same_account_twice_in_one_chain(self, client, world):
        def mutate(f):
            bank = world["bank"]
            f["freelance_payouts"][0]["legs"] = [
                {"account_id": bank, "amount": 900.0, "fixed": True},
                {"account_id": bank, "amount": 894.76, "fixed": True},
            ]

        self._refused(client, mutate, W45, "same account twice")

    def test_a_last_leg_that_is_not_the_payouts_amount(self, client, world):
        def mutate(f):
            f["freelance_payouts"][0]["legs"][-1]["amount"] = 894.77

        self._refused(client, mutate, W45, "last leg", "894.77", "894.76")

    def test_a_last_leg_in_another_currency_than_the_payouts(self, client, world):
        def mutate(f):
            f["freelance_payouts"][0]["legs"][-1]["account_id"] = world["mercury"]

        self._refused(client, mutate, W45, "last leg", "USD", "EUR")

    def test_a_leg_on_an_account_the_database_lacks_when_the_file_has_none(self, client, world):
        def mutate(f):
            del f["accounts"]
            f["freelance_payouts"][0]["legs"][0]["account_id"] = 4242

        self._refused(client, mutate, W45, "unknown account 4242")

    def test_a_source_chain_on_an_unknown_account(self, client, world):
        def mutate(f):
            f["income_sources"][0]["chain"] = [world["stripe"], 4242]

        self._refused(client, mutate, "Northwind Labs", "unknown account 4242")

    def test_a_source_chain_of_five(self, client, world):
        def mutate(f):
            f["income_sources"][0]["chain"] = [world["stripe"]] * 5

        self._refused(client, mutate, "Northwind Labs", "more than 4")

    def test_a_source_chain_with_the_same_account_twice(self, client, world):
        def mutate(f):
            f["income_sources"][0]["chain"] = [world["stripe"], world["stripe"]]

        self._refused(client, mutate, "Northwind Labs", "same account twice")

    def test_the_good_file_is_not_refused(self, client, world):
        """The control for every refusal above: the unchanged file restores."""
        before = client.get("/api/backup").json()
        assert client.post("/api/restore", json=before).status_code == 200
        assert _stable(client.get("/api/backup").json()) == _stable(before)


class TestAPayoutWithoutLegsGetsThemFromItsColumns:
    def _old_columns(self, client, world):
        """A version 5 file: the payout says what arrived and what was sent in its columns, and
        still carries its legs (the test takes them out)."""
        file = client.get("/api/backup").json()
        file["version"] = 5
        (p,) = file["freelance_payouts"]
        assert (p["amount"], p["account_id"]) == (894.76, world["bank"])
        p["sent_amount"], p["sent_currency"] = 999, "USD"
        p["from_account_id"] = world["stripe"]
        return file

    @pytest.mark.parametrize("how", ["key left out", "empty list"])
    def test_a_version_5_payout_without_legs(self, client, world, how):
        file = self._old_columns(client, world)
        (p,) = file["freelance_payouts"]
        assert len(p["legs"]) == 2  # the control: the API wrote its legs
        if how == "key left out":
            del p["legs"]
        else:
            p["legs"] = []
        assert client.post("/api/restore", json=file).status_code == 200
        (out,) = client.get("/api/freelance/payouts").json()
        assert [(leg["account_name"], leg["amount"], leg["fixed"]) for leg in out["legs"]] == [
            ("Stripe", 999.0, True),
            ("Main bank", 894.76, True),
        ]
        assert (out["amount"], out["currency"]) == (894.76, "EUR")
        assert out["account_id"] == world["bank"]  # the payout's account is its last leg's

    def test_a_payout_saved_with_no_account_at_all_gets_a_made_one(self, client, world):
        file = client.get("/api/backup").json()
        file["version"] = 4
        file["freelance_payouts"] = [
            {
                "source_id": world["src"],
                "week_start": W45,
                "amount": 1900,
                "currency": "USD",
                "fx_rate": 1.1165,
            }
        ]
        assert "USD account" not in {a["name"] for a in file["accounts"]}
        assert client.post("/api/restore", json=file).status_code == 200
        (after,) = client.get("/api/freelance/payouts").json()
        assert [
            (leg["account_name"], leg["currency"], leg["amount"], leg["fixed"])
            for leg in after["legs"]
        ] == [("USD account", "USD", 1900.0, True)]
        assert after["account_name"] == "USD account"
        assert (after["amount"], after["currency"], after["fx_rate"]) == (1900.0, "USD", 1.1165)
        assert after["amount_eur"] == 1701.75


class TestAFileWithoutAccountsKeepsTheAccountsThereAre:
    def test_the_accounts_stay_and_the_payouts_get_legs(self, client, world):
        file = as_version_4(client.get("/api/backup").json(), world)
        names = [a["name"] for a in client.get("/api/freelance/accounts").json()]
        positions = {a["name"]: a["position"] for a in client.get("/api/backup").json()["accounts"]}
        del file["accounts"]
        assert client.post("/api/restore", json=file).status_code == 200
        assert [a["name"] for a in client.get("/api/freelance/accounts").json()] == names
        after = client.get("/api/backup").json()
        assert {a["name"]: a["position"] for a in after["accounts"]} == positions
        (out,) = client.get("/api/freelance/payouts").json()
        assert [(leg["account_name"], leg["amount"]) for leg in out["legs"]] == [
            ("Stripe", 999.0),
            ("Main bank", 894.76),
        ]
        (src,) = after["income_sources"]
        assert src["chain"] == [world["stripe"], world["bank"]]  # paid from, then paid into


class TestARestoredPayoutsAccountIsItsLastLegs:
    @pytest.mark.parametrize("how", ["null (before accounts)", "the first leg's account"])
    def test_a_file_whose_account_id_is_not_the_last_legs_is_restored_with_the_last_legs(
        self, client, world, how
    ):
        file = client.get("/api/backup").json()
        file["version"] = 5
        (p,) = file["freelance_payouts"]
        assert p["account_id"] == world["bank"]  # the control: the export had the last leg's
        p["account_id"] = None if how.startswith("null") else world["stripe"]
        assert client.post("/api/restore", json=file).status_code == 200
        (out,) = client.get("/api/freelance/payouts").json()
        assert (out["account_id"], out["account_name"]) == (world["bank"], "Main bank")
        assert (out["amount"], out["currency"], out["amount_eur"]) == (894.76, "EUR", 894.76)
        assert [leg["account_name"] for leg in out["legs"]] == ["Stripe", "Main bank"]


class TestTheTwoRoadsAgreeOnAnEmptiedChain:
    """A source whose chain a person emptied in Settings still has its old defaults in the
    columns. Migration 0014 and the restore of a version 5 file must both leave its chain empty;
    only a file with no chain at all for it (version 4) builds one from the defaults."""

    def _emptied_at_0013(self):
        engine = _engine(script=(ERAS / "v57.sql").read_text("utf-8"))
        _upgrade(engine, "0013")
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM income_source_accounts WHERE source_id = 1"))
        return engine

    def test_the_migration_and_a_version_5_restore_both_leave_it_empty(self):
        migrated = self._emptied_at_0013()
        # the control: the defaults are there, and 0013 had made the other sources' chains
        assert _sql(migrated, "SELECT default_account_id FROM income_sources WHERE id = 1") != [
            (None,)
        ]
        assert _source_chains(migrated)["Local consulting"] == ["Wise"]
        _upgrade(migrated)
        want = _source_chains(migrated)
        assert want["Northwind Labs"] == [] and want["Local consulting"] == ["Wise"]

        # the version 5 file of that same state: its chains as they were, its defaults still there
        file = _era_file("v57")
        file["version"] = 5
        ids = {a["name"]: a["id"] for a in file["accounts"]}
        for position, source in enumerate(file["income_sources"]):
            source["position"] = position
            source["chain"] = [ids[name] for name in want[source["name"]]]
        assert any(s["default_from_account_id"] for s in file["income_sources"])  # still in it
        restored = _engine(upto="head")
        assert _restore(restored, file).status_code == 200
        assert _source_chains(restored) == want
        migrated.dispose()
        restored.dispose()

    def test_a_source_with_no_chain_key_in_a_version_4_file_still_gets_its_defaults(self):
        file = _era_file("v57")
        assert file["version"] == 4 and all("chain" not in s for s in file["income_sources"])
        restored = _engine(upto="head")
        assert _restore(restored, file).status_code == 200
        assert _source_chains(restored)["Northwind Labs"] == ["Stripe", "Main bank"]
        restored.dispose()


# ---------- e) no orphans ------------------------------------------------------------


@pytest.fixture(params=["foreign keys off", "foreign keys on"])
def fk_client(request):
    """The suite's engine does not enforce foreign keys and production's does."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    if request.param == "foreign keys on":

        @event.listens_for(engine, "connect")
        def _pragma(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def session():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    fastapi_app.dependency_overrides[get_session] = session
    try:
        with TestClient(fastapi_app) as c:
            c.engine = engine
            c.enforced = request.param == "foreign keys on"
            yield c
    finally:
        fastapi_app.dependency_overrides.clear()
        engine.dispose()


class TestNoOrphans:
    def test_two_restores_in_a_row_leave_no_row_without_its_parent(self, fk_client, world_for_fk):
        engine = fk_client.engine
        if fk_client.enforced:  # the control: the engine really enforces them
            assert _sql(engine, "PRAGMA foreign_keys") == [(1,)]
        else:
            assert _sql(engine, "PRAGMA foreign_keys") == [(0,)]
        file = fk_client.get("/api/backup").json()
        for _ in range(2):
            assert fk_client.post("/api/restore", json=file).status_code == 200
            assert _orphans(engine) == {
                "legs": 0,
                "legs_account": 0,
                "chain": 0,
                "chain_account": 0,
            }
        # the control: there were rows to be orphaned
        assert _sql(engine, "SELECT COUNT(*) FROM freelance_payout_legs") == [(2,)]
        assert _sql(engine, "SELECT COUNT(*) FROM income_source_accounts") == [(2,)]
        assert _sql(engine, "SELECT COUNT(*) FROM freelance_payouts") == [(1,)]
        if fk_client.enforced:
            assert _sql(engine, "PRAGMA foreign_key_check") == []

    def test_a_restore_of_an_older_file_over_chains_leaves_none_behind(
        self, fk_client, world_for_fk
    ):
        engine = fk_client.engine
        file = as_version_4(fk_client.get("/api/backup").json(), world_for_fk)
        assert fk_client.post("/api/restore", json=file).status_code == 200
        assert fk_client.post("/api/restore", json=file).status_code == 200
        assert _orphans(engine) == {"legs": 0, "legs_account": 0, "chain": 0, "chain_account": 0}
        assert _sql(engine, "SELECT COUNT(*) FROM freelance_payout_legs") == [(2,)]


@pytest.fixture
def world_for_fk(fk_client):
    return _world(fk_client)


# ---------- g) the CSV ---------------------------------------------------------------

OLD_HEADER = [
    "week_start",
    "week_end",
    "source",
    "currency",
    "amount",
    "fx_rate",
    "amount_eur",
    "estimate_amount",
    "estimate_eur",
    "blocks",
    "hours",
    "note",
    "account",
    "rate_source",
    "rate_date",
    "billed_amount",
    "billed_eur",
    "fx_cost_eur",
    "sent_amount",
    "sent_currency",
    "from_account",
]
DROPPED = {"sent_amount", "sent_currency", "from_account"}  # the columns of a dropped side
NEW_HEADER = [
    "account_1",
    "amount_1",
    "currency_1",
    "account_2",
    "amount_2",
    "currency_2",
    "account_3",
    "amount_3",
    "currency_3",
    "account_4",
    "amount_4",
    "currency_4",
]


class TestThePayoutsCsvShowsTheChain:
    @pytest.fixture
    def rows(self):
        engine = _engine(script=(ERAS / "v57.sql").read_text("utf-8"))
        _upgrade(engine)
        try:
            with _client(engine) as c:
                text_ = c.get("/api/freelance/payouts.csv").text
        finally:
            fastapi_app.dependency_overrides.clear()
            engine.dispose()
        return list(csv.reader(io.StringIO(text_)))

    def test_the_header_is_the_old_one_without_the_sent_side_and_twelve_more(self, rows):
        old = next(csv.reader(io.StringIO(_era_answers("v57")["payouts_csv"])))
        assert old == OLD_HEADER  # the control: the old header is what the old code wrote
        assert rows[0] == [c for c in OLD_HEADER if c not in DROPPED] + NEW_HEADER
        assert len(rows[0]) == 30

    def test_a_two_account_payout_fills_two_legs_and_leaves_six_empty(self, rows):
        (row,) = [r for r in rows[1:] if r[0] == W45 and r[2] == "Northwind Labs"]
        assert row[18:] == ["Stripe", "999.00", "USD", "Main bank", "894.76", "EUR"] + [""] * 6

    def test_a_one_account_payout_fills_only_the_first_three(self, rows):
        (row,) = [r for r in rows[1:] if r[0] == "2026-06-01" and r[2] == "Northwind Labs"]
        assert row[18:] == ["Main bank", "1650.00", "EUR"] + [""] * 9

    def test_a_coin_is_written_with_eight_decimals(self, rows):
        (row,) = [r for r in rows[1:] if r[0] == "2026-06-15" and r[2] == "Northwind Labs"]
        assert row[18:21] == ["Cold wallet", "0.02100000", "BTC"]
        assert row[21:] == [""] * 9

    def test_every_row_is_as_wide_as_the_header(self, rows):
        assert {len(r) for r in rows} == {30}
        assert len(rows) == 1 + 18
