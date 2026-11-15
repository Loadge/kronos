# ruff: noqa: E501
"""Migration 0014 closes the chain of accounts.

Every payout without legs is given them by the rule 0013 used, every payout's account becomes the
account of its last leg, and the columns the chain replaced are dropped. The database it runs on
is ``tests/fixtures/no_legs_0013.sql`` (see ``tests/fixtures/build_no_legs_0013.py``): a database at
0013 with the payouts a version of the old request shape left behind, no leg among them. Each case
is a payout of the rule: a dollar payout with no account, a sent side in a bare currency, the same
account on both sides, both accounts, and a source with usual accounts and no chain.

Every expected leg below is written by hand from the rule. "The same as 0013" is proved by putting
the same rows into a database at 0012 and letting 0013 give them their legs.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

import pytest
from sqlalchemy import text

from alembic import command
from tests.api.era_expectations import ERAS, REPO
from tests.api.test_chain_migration import _columns, _config, _engine, _legs, _rows, _upgrade

FIXTURES = REPO / "tests" / "fixtures"
SQL = FIXTURES / "no_legs_0013.sql"

# payout id -> its legs after 0014: (account, amount, fixed), first leg first. By hand.
LEGS = {
    1: [("USD account", 1900.0, True)],  # dollars, no account: the made dollar account
    2: [("USD account", 999.0, True), ("Main bank", 894.76, True)],  # a bare currency sent
    3: [("EUR account", 900.0, True), ("Wise", 900.0, True)],  # sent from where it arrived
    4: [("Stripe", 999.0, True), ("Main bank", 894.76, True)],  # both accounts
    5: [("EUR account", 450.0, True)],  # euros, no account: the made euro account, reused
    6: [("Wise", 300.0, True)],  # an account, nothing sent
    7: [("USD account", 1000.0, True)],  # dollars into a euro account: the currency wins
    8: [("USD account", 990.0, True), ("Main bank", 880.0, True)],  # sent in the source's currency
}
# the account each payout ends in: its last leg's
LAST = {pid: chain[-1][0] for pid, chain in LEGS.items()}
# What 0013 gives these sources from their defaults (paid from, then paid into; the same account
# twice is one; an archived one left out). The fixture is a database at 0013 whose chains were
# left empty: 0014 does not read the defaults (0013 did; an empty chain at 0014 is one a person
# emptied), so after it they are all still empty.
CHAINS_0013 = {
    "Northwind": ["Stripe", "Main bank"],
    "Local": ["Wise"],
    "Same": ["Wise"],
    "Shelved": [],
    "Plain": [],
}
CHAINS = {name: [] for name in CHAINS_0013}
KEPT = "id, source_id, week_start, amount, currency, fx_rate, note, rate_source, rate_date"  # what 0014 must not touch in a payout


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_no_legs", FIXTURES / "build_no_legs_0013.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _no_legs_db(upto: str | None = None):
    engine = _engine(script=SQL.read_text("utf-8"))
    if upto:
        _upgrade(engine, upto)
    return engine


def _names(engine) -> dict[int, str]:
    with engine.connect() as conn:
        return {i: n for i, n in conn.execute(text("SELECT id, name FROM accounts"))}


def _chains(engine) -> dict[str, list[str]]:
    with engine.connect() as conn:
        out = {n: [] for (n,) in conn.execute(text("SELECT name FROM income_sources"))}
        for source, account in conn.execute(
            text(
                "SELECT s.name, a.name FROM income_source_accounts c"
                " JOIN income_sources s ON s.id = c.source_id"
                " JOIN accounts a ON a.id = c.account_id ORDER BY c.source_id, c.position"
            )
        ):
            out[source].append(account)
    return out


def _by_name(engine, legs: dict[int, list[tuple]]) -> dict[int, list[tuple]]:
    """The legs with each account's currency beside its name."""
    with engine.connect() as conn:
        currency = dict(conn.execute(text("SELECT name, currency FROM accounts")).all())
    return {i: [(n, currency[n], a, f) for n, a, f in chain] for i, chain in legs.items()}


@pytest.fixture
def before():
    engine = _no_legs_db()
    yield engine
    engine.dispose()


@pytest.fixture
def after():
    engine = _no_legs_db("head")
    yield engine
    engine.dispose()


class TestTheFixture:
    def test_it_is_what_the_builder_makes(self):
        done = subprocess.run(
            [sys.executable, str(FIXTURES / "build_no_legs_0013.py"), "--check"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={
                **{
                    k: v
                    for k, v in os.environ.items()
                    if not k.startswith(("KRONOS_", "DATABASE_"))
                },
                "PYTHONUTF8": "1",
            },
            cwd=str(REPO),
        )
        assert done.returncode == 0, done.stderr[-1500:]
        made = done.stdout.split("CHECK-BEGIN\n", 1)[1]
        # the same statements; the order of the indexes in a dump is not fixed
        assert sorted(made.splitlines()) == sorted(SQL.read_text("utf-8").splitlines())

    def test_it_has_payouts_without_legs_and_the_columns_0014_drops(self, before):
        """The control for everything below: the proof means nothing on a database that already
        had legs or lacked the columns."""
        assert _rows(before, "freelance_payout_legs") == []
        assert _rows(before, "income_source_accounts") == []
        assert len(_rows(before, "freelance_payouts")) == len(LEGS)
        assert {"sent_amount", "sent_currency", "from_account_id"} <= set(
            _columns(before, "freelance_payouts")
        )
        assert {"default_account_id", "default_from_account_id"} <= set(
            _columns(before, "income_sources")
        )
        assert "role" in _columns(before, "accounts")
        with before.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0013"


class TestEveryPayoutGetsItsChain:
    def test_the_legs_are_the_ones_the_rule_gives(self, after):
        assert _legs(after) == LEGS

    def test_the_same_legs_as_0013_gives_the_same_rows(self, after):
        """The rows the fixture holds, put into a database at 0012: 0013 gives them their legs."""
        engine = _engine(upto="0012")
        with engine.begin() as conn:
            for sql in _builder().ROWS:
                conn.execute(text(sql))
        _upgrade(engine, "0013")
        by_0013 = _legs(engine)
        assert by_0013 == LEGS  # the control: 0013's own answer is the hand-written one
        assert _by_name(after, _legs(after)) == _by_name(engine, by_0013)
        # the chains differ on purpose: 0013 builds them from the defaults, 0014 does not read
        # the defaults (see CHAINS), so the sources the fixture left empty stay empty
        assert _chains(engine) == CHAINS_0013
        assert _chains(after) == CHAINS

        # and the accounts it made are the same, in the same order
        def made(e):
            with e.connect() as conn:
                return [
                    tuple(r)
                    for r in conn.execute(
                        text(
                            "SELECT name, currency, kind, is_default, archived, position"
                            " FROM accounts WHERE id > 4 ORDER BY id"
                        )
                    )
                ]

        assert (
            made(after)
            == made(engine)
            == [
                ("USD account", "USD", "other", 0, 0, 4),
                ("EUR account", "EUR", "other", 0, 0, 5),
            ]
        )
        engine.dispose()

    def test_every_payout_has_a_leg_and_the_last_is_what_it_is_worth(self, after):
        with after.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT p.id, p.amount, p.currency, l.amount, a.currency"
                    " FROM freelance_payouts p"
                    " JOIN freelance_payout_legs l ON l.payout_id = p.id"
                    " JOIN accounts a ON a.id = l.account_id"
                    " WHERE l.position = (SELECT MAX(position) FROM freelance_payout_legs"
                    "                     WHERE payout_id = p.id) ORDER BY p.id"
                )
            ).all()
        assert [r[0] for r in rows] == list(LEGS)
        assert all(tuple(r[1:3]) == tuple(r[3:5]) for r in rows)

    def test_an_existing_made_account_is_used_before_a_new_one_is_made(self):
        """The rule of 0014 (the one 0013 did not have to meet): a "<CUR> account" of kind
        "other" that is live and that the chain does not hold yet is taken. An archived one, a
        bank or one of another currency is not."""
        engine = _no_legs_db()
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM freelance_payouts WHERE id NOT IN (5, 2)"))
            for i, name, cur, kind, arch in (
                (10, "EUR account 3", "EUR", "bank", 0),  # a bank: not a made one
                (11, "EUR account 2", "EUR", "other", 1),  # archived
                (12, "USD account 5", "EUR", "other", 0),  # named for another currency
                (13, "eur ACCOUNT 7", "EUR", "other", 0),  # any case, any number: the one
                (14, "EUR account 8", "EUR", "other", 0),
                (15, "USD account 9", "USD", "other", 0),
            ):
                conn.execute(
                    text(
                        "INSERT INTO accounts (id, name, currency, kind, is_default, archived,"
                        " role, created_at, position) VALUES"
                        f" ({i}, '{name}', '{cur}', '{kind}', 0, {arch}, 'both',"
                        f" '2026-11-01 10:00:00', {i})"
                    )
                )
        _upgrade(engine)
        names = _names(engine)
        assert _legs(engine) == {
            2: [("USD account 9", 999.0, True), ("Main bank", 894.76, True)],
            5: [("eur ACCOUNT 7", 450.0, True)],
        }
        assert sorted(names.values()) == sorted(
            [
                "Stripe",
                "Main bank",
                "Wise",
                "Old pot",
                "EUR account 3",
                "EUR account 2",
                "USD account 5",
                "eur ACCOUNT 7",
                "EUR account 8",
                "USD account 9",
            ]
        ), "an account was made though one was free"
        engine.dispose()

    def test_two_sides_of_one_currency_take_two_made_accounts(self):
        engine = _no_legs_db()
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM freelance_payouts WHERE id != 3"))
        _upgrade(engine)
        assert _legs(engine) == {3: [("EUR account", 900.0, True), ("Wise", 900.0, True)]}
        engine.dispose()
        # none free to start with: the arrival takes the first, the send side the next, new
        engine = _no_legs_db()
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM freelance_payouts WHERE id != 3"))
            conn.execute(
                text("UPDATE freelance_payouts SET account_id = NULL, from_account_id = NULL")
            )
        _upgrade(engine)
        assert _legs(engine) == {3: [("EUR account 2", 900.0, True), ("EUR account", 900.0, True)]}
        engine.dispose()

    def test_a_payout_that_has_its_legs_is_left_alone(self):
        engine = _no_legs_db()
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO freelance_payout_legs (payout_id, position, account_id, amount, fixed)"
                    " VALUES (1, 0, 3, 5.0, 0)"
                )
            )
        _upgrade(engine)
        legs = _legs(engine)
        assert legs[1] == [("Wise", 5.0, False)]  # not given a second chain, nor rewritten
        assert {k: v for k, v in legs.items() if k != 1} == {
            k: v for k, v in LEGS.items() if k != 1
        }
        engine.dispose()


class TestTheSourcesGetTheirChain:
    def test_an_empty_chain_beside_defaults_stays_empty_and_the_defaults_are_gone(self, after):
        """Sources with defaults and no chain (one a person emptied): 0014 drops the defaults
        without reading them."""
        assert _chains(after) == CHAINS
        assert not {"default_account_id", "default_from_account_id"} & set(
            _columns(after, "income_sources")
        )

    def test_a_source_that_has_a_chain_keeps_it(self):
        engine = _no_legs_db()
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO income_source_accounts (source_id, position, account_id) VALUES (1, 0, 4)"
                )
            )
        _upgrade(engine)
        assert _chains(engine)["Northwind"] == ["Old pot"]
        engine.dispose()


class TestAndAccountIsTheLastLegs:
    def test_each_payouts_account_is_its_last_legs(self, after):
        names = _names(after)
        with after.connect() as conn:
            got = {
                i: names[a]
                for i, a in conn.execute(text("SELECT id, account_id FROM freelance_payouts"))
            }
        assert got == LAST

    def test_nothing_else_of_a_payout_changes(self, before):
        was = _rows(before, "freelance_payouts", KEPT.split(", "))
        assert len(was) == len(LEGS)
        _upgrade(before)
        assert _rows(before, "freelance_payouts", KEPT.split(", ")) == was

    def test_an_amount_that_a_leg_could_round_is_not_rounded_into_the_payout(self):
        """A payout's amount is read by every total: it is never rewritten from a leg."""
        engine = _no_legs_db()
        with engine.begin() as conn:
            conn.execute(text("UPDATE freelance_payouts SET amount = 894.7649 WHERE id = 4"))
        _upgrade(engine)
        assert _rows(engine, "freelance_payouts", ["amount"])[3] == (894.7649,)
        assert _legs(engine)[4][-1][1] == 894.7649
        engine.dispose()


class TestTheColumnsGo:
    def test_they_are_gone(self, after):
        assert not {"sent_amount", "sent_currency", "from_account_id"} & set(
            _columns(after, "freelance_payouts")
        )
        assert not {"default_account_id", "default_from_account_id"} & set(
            _columns(after, "income_sources")
        )
        assert "role" not in _columns(after, "accounts")

    def test_so_are_their_foreign_keys_and_indexes_and_nothing_points_nowhere(self, after):
        with after.connect() as conn:
            payout_fks = {
                r[3] for r in conn.execute(text("PRAGMA foreign_key_list(freelance_payouts)"))
            }
            assert payout_fks == {"source_id", "account_id"}
            assert list(conn.execute(text("PRAGMA foreign_key_list(income_sources)"))) == []
            indexes = {r[1] for r in conn.execute(text("PRAGMA index_list(freelance_payouts)"))}
            assert "ix_freelance_payouts_from_account_id" not in indexes
            assert "ix_freelance_payouts_account_id" in indexes  # the control: others stay
            assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
            # the legs table still points at its payouts (the table was rebuilt under it)
            legs_fks = {
                r[2] for r in conn.execute(text("PRAGMA foreign_key_list(freelance_payout_legs)"))
            }
            assert legs_fks == {"freelance_payouts", "accounts"}
            assert conn.execute(text("SELECT COUNT(*) FROM freelance_payout_legs")).scalar() == 12

    def test_the_orm_and_the_tables_agree(self, after):
        # the app's own models read and write what is left
        from app.models import Account, FreelancePayout, IncomeSource
        from sqlalchemy import select
        from sqlalchemy.orm import sessionmaker

        with sessionmaker(bind=after)() as s:
            assert len(s.scalars(select(FreelancePayout)).all()) == len(LEGS)
            assert len(s.scalars(select(IncomeSource)).all()) == 5
            assert len(s.scalars(select(Account)).all()) == 6
            payout = s.get(FreelancePayout, 4)
            assert payout.account.name == "Main bank" and len(payout.legs) == 2


class TestGoingDown:
    def test_the_columns_come_back_with_what_a_chain_can_tell_and_the_legs_stay(self, after):
        legs = _legs(after)
        with after.begin() as conn:  # two sources a person gave a chain after the migration
            conn.execute(
                text(
                    "INSERT INTO income_source_accounts (source_id, position, account_id)"
                    " VALUES (1, 0, 1), (1, 1, 2), (2, 0, 3)"
                )
            )
        cfg = _config()
        with after.connect() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "0013")
            conn.commit()
        assert {"sent_amount", "sent_currency", "from_account_id"} <= set(
            _columns(after, "freelance_payouts")
        )
        assert {"default_account_id", "default_from_account_id"} <= set(
            _columns(after, "income_sources")
        )
        assert "role" in _columns(after, "accounts")
        assert _legs(after) == legs  # the legs stay
        names = _names(after)
        with after.connect() as conn:
            sent = {
                i: (a, c, names.get(f))
                for i, a, c, f in conn.execute(
                    text(
                        "SELECT id, sent_amount, sent_currency, from_account_id FROM freelance_payouts"
                    )
                )
            }
            roles = {r[0] for r in conn.execute(text("SELECT role FROM accounts"))}
            defaults = {
                n: (names.get(into), names.get(frm))
                for n, into, frm in conn.execute(
                    text(
                        "SELECT name, default_account_id, default_from_account_id FROM income_sources"
                    )
                )
            }
        # two or more legs: the first is the sent side; one leg is "as billed"
        assert sent == {
            1: (None, None, None),
            2: (999.0, "USD", "USD account"),
            3: (900.0, "EUR", "EUR account"),
            4: (999.0, "USD", "Stripe"),
            5: (None, None, None),
            6: (None, None, None),
            7: (None, None, None),
            8: (999.0 - 9.0, "USD", "USD account"),
        }
        assert roles == {"both"}
        # two or more accounts: first as paid from, last as paid into; one: as paid into
        assert defaults == {
            "Northwind": ("Main bank", "Stripe"),
            "Local": ("Wise", None),
            "Same": (None, None),
            "Shelved": (None, None),
            "Plain": (None, None),
        }

    def test_up_again_gives_the_same_database(self, after):
        legs, chains = _legs(after), _chains(after)
        before_rows = _rows(after, "freelance_payouts")
        cfg = _config()
        with after.connect() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "0013")
            conn.commit()
        _upgrade(after)
        assert (_legs(after), _chains(after)) == (legs, chains)
        assert _rows(after, "freelance_payouts") == before_rows
        with after.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_key_check")).all() == []

    def test_an_empty_database_goes_down_and_up(self):
        engine = _engine(upto="head")
        cfg = _config()
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "0013")
            command.upgrade(cfg, "head")
            conn.commit()
        assert _rows(engine, "accounts") == []
        engine.dispose()


class TestARunCutShort:
    def test_the_next_one_finishes_the_job(self):
        """The columns are gone but the revision still says 0013 (a run cut short after the last
        step): the next run finds nothing to give, nothing to drop, and ends at 0014."""
        engine = _no_legs_db("head")
        legs = _legs(engine)
        with engine.begin() as conn:
            conn.execute(text("UPDATE alembic_version SET version_num = '0013'"))
        _upgrade(engine)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0014"
        assert _legs(engine) == legs
        engine.dispose()


class TestEveryEraAtHead:
    @pytest.mark.parametrize("era", ["v56", "v57"])
    def test_each_payout_keeps_its_figures_and_its_account_is_its_last_legs(self, era):
        engine = _engine(script=(ERAS / f"{era}.sql").read_text("utf-8"))
        kept = _rows(
            engine,
            "freelance_payouts",
            ["id", "amount", "currency", "fx_rate", "rate_source", "rate_date"],
        )
        _upgrade(engine)
        assert (
            _rows(
                engine,
                "freelance_payouts",
                ["id", "amount", "currency", "fx_rate", "rate_source", "rate_date"],
            )
            == kept
        )
        names = _names(engine)
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT p.id, p.amount, p.account_id, l.account_id, l.amount FROM freelance_payouts p"
                    " JOIN freelance_payout_legs l ON l.payout_id = p.id"
                    " WHERE l.position = (SELECT MAX(position) FROM freelance_payout_legs"
                    " WHERE payout_id = p.id)"
                )
            ).all()
        assert len(rows) == len(kept)
        for pid, amount, account, last_account, last_amount in rows:
            assert account == last_account and last_amount == amount, pid
        assert names[rows[0][2]]  # an account with a name
        engine.dispose()

    def test_the_payouts_before_accounts_of_a_version_51_database(self):
        """v51 wrote payouts with no account, in the source's currency: five of them are in the
        v56 fixture (ids 1 to 5). Put into a database at 0010, as that version had it, they come
        out of every migration with their figures and a chain."""
        import sqlite3

        source = sqlite3.connect(":memory:")
        source.executescript((ERAS / "v56.sql").read_text("utf-8"))
        engine = _engine(upto="0010")
        cols = {
            "income_sources": "id, name, hourly_rate, currency, is_default, archived",
            "freelance_blocks": "id, date, source_id, minutes, start_time, end_time, notes, rate, currency, fx_rate",
            "freelance_payouts": "id, source_id, week_start, amount, currency, fx_rate, note",
        }
        with engine.begin() as conn:
            for table, columns in cols.items():
                where = " WHERE id <= 5" if table == "freelance_payouts" else ""
                for row in source.execute(f"SELECT {columns} FROM {table}{where}"):
                    marks = ", ".join(f":{i}" for i in range(len(row)))
                    conn.execute(
                        text(f"INSERT INTO {table} ({columns}) VALUES ({marks})"),
                        {str(i): v for i, v in enumerate(row)},
                    )
        kept = _rows(engine, "freelance_payouts")
        assert len(kept) == 5
        _upgrade(engine)
        assert (
            _rows(
                engine,
                "freelance_payouts",
                ["id", "source_id", "week_start", "amount", "currency", "fx_rate", "note"],
            )
            == kept
        )
        assert _legs(engine) == {
            1: [("USD account", 750.0, True)],
            2: [("USD account", 1800.0, True)],
            3: [("EUR account", 480.0, True)],
            4: [("USD account", 2000.0, True)],
            5: [("USD account", 700.0, True)],
        }
        engine.dispose()
        source.close()
