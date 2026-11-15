"""The migration to a chain of accounts moves no figure of a payout that exists.

The databases it runs on were written by the real code of past versions (see
``tests/fixtures/eras/build_eras.py``): ``v56`` holds payouts from before accounts and from the
accounts era, ``v57`` adds the ones that say what was sent. Next to each is what that version's
API answered about it, and the app must still answer the same after the migration.

The ECB is stubbed with the document the fixtures were made with; a request for a coin's price
fails the test.

Two levels. The proofs about migration 0013 (the legs it gives, the accounts it makes, the rows it
leaves alone) run on the database as 0013 leaves it. The app's answers are read after 0014, which
drops the columns the old answers had and gives every payout an account; the comparison is then
narrowed to exactly what 0014 changes on purpose, each narrowing with its reason beside it
(``TestTheAppAfterTheCloseOfTheChain``). 0014's own rules are in ``test_chain_close.py``.
"""

from __future__ import annotations

import csv
import io
import json

import app.services.crypto as crypto
import app.services.fx as fx
import pytest
from alembic.config import Config
from app.database import get_session
from app.main import app as fastapi_app
from app.models import FreelancePayout, IncomeSource
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from alembic import command
from tests.api.era_expectations import (
    ACCOUNT_ORDER,
    ARRIVED,
    CHAINS,
    ERAS,
    LEGS,
    LEGS_V57,
    MADE,
    MONEY,
    REPO,
    TODAY,
)


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    fx._reset()
    crypto._reset()
    history = (ERAS / "ecb.xml").read_bytes()
    daily = (ERAS / "ecb_daily.xml").read_bytes()  # one day, as the ECB's daily document is
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


def _config() -> Config:
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "alembic"))
    return cfg


def _engine(script: str | None = None, upto: str | None = None):
    """An in-memory database: loaded from a fixture's SQL, or migrated up to a revision."""
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    if script is not None:
        raw = engine.raw_connection()
        raw.executescript(script)
        raw.commit()
    if upto is not None:
        _upgrade(engine, upto)
    return engine


def _upgrade(engine, revision: str = "head") -> None:
    cfg = _config()
    with engine.connect() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, revision)
        conn.commit()


def _columns(engine, table: str) -> list[str]:
    with engine.connect() as conn:
        return [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))]


def _rows(engine, table: str, columns: list[str] | None = None) -> list[tuple]:
    """Every row of a table, whole, or only the columns named (the ones an older schema had)."""
    what = ", ".join(columns) if columns else "*"
    with engine.connect() as conn:
        found = conn.execute(text(f"SELECT {what} FROM {table} ORDER BY rowid"))
        return [tuple(r) for r in found]


def _snapshot(engine) -> dict[str, tuple[list[str], list[tuple]]]:
    """Every table of the database, whole: its columns and its rows."""
    with engine.connect() as conn:
        tables = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
                " AND name NOT IN ('alembic_version', 'sqlite_sequence')"
            )
        ).scalars()
        tables = list(tables)
    return {t: (_columns(engine, t), _rows(engine, t)) for t in tables}


def _assert_nothing_moved(engine, snapshot, made_accounts: int) -> None:
    """Every row that was there still says the same in every column it had. ``accounts`` is the
    one table allowed more rows, after the old ones: the accounts the migration makes."""
    assert {"freelance_payouts", "freelance_blocks", "income_sources", "accounts"} <= set(snapshot)
    for table, (columns, rows) in snapshot.items():
        now = _rows(engine, table, columns)
        extra = made_accounts if table == "accounts" else 0
        assert len(now) == len(rows) + extra, table
        assert now[: len(rows)] == rows, table


def _legs(engine) -> dict[int, list[tuple]]:
    """payout id -> [(account name, amount, typed by hand), ...] in the chain's order."""
    out: dict[int, list[tuple]] = {}
    with engine.connect() as conn:
        for payout_id, position, name, amount, fixed in conn.execute(
            text(
                "SELECT l.payout_id, l.position, a.name, l.amount, l.fixed"
                " FROM freelance_payout_legs l JOIN accounts a ON a.id = l.account_id"
                " ORDER BY l.payout_id, l.position"
            )
        ):
            chain = out.setdefault(payout_id, [])
            assert position == len(chain), f"payout {payout_id}: a gap in its chain"
            chain.append((name, amount, bool(fixed)))
    return out


@pytest.fixture(params=["v56", "v57"])
def era(request):
    """A past version's database, as it was and after migration 0013, with its version's answers."""
    name = request.param
    engine = _engine(script=(ERAS / f"{name}.sql").read_text("utf-8"))
    snapshot = _snapshot(engine)
    _upgrade(engine, "0013")
    answers = json.loads((ERAS / f"{name}.json").read_text("utf-8"))
    yield {
        "name": name,
        "engine": engine,
        "snapshot": snapshot,
        "payouts": snapshot["freelance_payouts"][1],
        "answers": answers,
    }
    engine.dispose()


@pytest.fixture(params=["v56", "v57"])
def era_at_head(request):
    """The same database after every migration, with the answers that version gave."""
    name = request.param
    engine = _engine(script=(ERAS / f"{name}.sql").read_text("utf-8"))
    _upgrade(engine)
    answers = json.loads((ERAS / f"{name}.json").read_text("utf-8"))
    yield {"name": name, "engine": engine, "answers": answers}
    engine.dispose()


def _client(engine):
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def session():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    fastapi_app.dependency_overrides[get_session] = session
    return TestClient(fastapi_app)


class TestNoFigureMoves:
    def test_the_fixtures_hold_every_era(self, era):
        """A positive control: the proof below is empty if the fixture is."""
        kinds = {
            (account is not None, sent is not None, rate is not None, currency)
            for (_, _, _, _, currency, rate, _, account, *rest) in era["payouts"]
            for sent in [rest[2] if len(rest) > 2 else None]
        }
        assert (False, False, True, "USD") in kinds  # before accounts
        assert (False, False, False, "USD") in kinds  # before accounts, no rate
        assert (True, False, False, "EUR") in kinds  # into an account
        assert (True, False, True, "BTC") in kinds  # a coin
        if era["name"] == "v57":
            assert (True, True, False, "EUR") in kinds  # sent and arrived
            assert (False, True, False, "EUR") in kinds  # sent, no account at all
        assert len(era["payouts"]) == len(LEGS[era["name"]])
        for table in ("freelance_blocks", "income_sources", "accounts", "templates"):
            assert era["snapshot"][table][1], f"the fixture has no {table}"

    def test_no_row_that_existed_changes(self, era):
        """Every table, every row, every column the old schema had, to the last digit: payouts
        and blocks, and also the sources, accounts and templates the migration does write to."""
        _assert_nothing_moved(era["engine"], era["snapshot"], made_accounts=len(MADE[era["name"]]))
        if era["name"] == "v56":  # the columns it did not have yet stay empty
            sent = _rows(
                era["engine"],
                "freelance_payouts",
                ["sent_amount", "sent_currency", "from_account_id"],
            )
            assert sent == [(None, None, None)] * len(era["payouts"])

    def test_nothing_points_at_a_row_that_is_not_there(self, era):
        """The app runs with foreign keys on; the migration runs with them off."""
        with era["engine"].connect() as conn:
            assert conn.execute(text("PRAGMA foreign_key_check")).all() == []

    def test_every_payout_gets_its_chain(self, era):
        want = {
            pid: [(name, amount, True) for name, amount in chain]
            for pid, chain in LEGS[era["name"]].items()
        }
        assert _legs(era["engine"]) == want

    def test_the_last_account_holds_what_the_payout_is_worth(self, era):
        with era["engine"].connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT p.id, p.amount, p.currency, l.amount, a.currency"
                    " FROM freelance_payouts p"
                    " JOIN freelance_payout_legs l ON l.payout_id = p.id"
                    " JOIN accounts a ON a.id = l.account_id"
                    " WHERE l.position = (SELECT MAX(position) FROM freelance_payout_legs"
                    "                     WHERE payout_id = p.id)"
                    " ORDER BY p.id"
                )
            ).all()
        assert len(rows) == len(LEGS[era["name"]])
        totals: dict[str, float] = {}
        for pid, amount, currency, leg_amount, leg_currency in rows:
            assert (leg_amount, leg_currency) == (amount, currency), f"payout {pid}"
            totals[currency] = totals.get(currency, 0.0) + leg_amount
        assert {c: round(v, 8) for c, v in totals.items()} == ARRIVED[era["name"]]


def _only_keys_of(old, new):
    """``new`` cut down to the keys ``old`` has, at every depth: a later version may say more
    than an earlier one did, never something else."""
    if isinstance(old, dict) and isinstance(new, dict):
        return {k: _only_keys_of(old[k], new[k]) if k in new else "<gone>" for k in old}
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        return [_only_keys_of(o, n) for o, n in zip(old, new, strict=True)]
    return new


class TestTheChainsAndTheOrder:
    def test_a_source_gets_paid_from_then_paid_into(self, era):
        with sessionmaker(bind=era["engine"])() as s:
            chains = {
                src.name: [link.account.name for link in src.chain]
                for src in s.scalars(select(IncomeSource))
            }
        assert chains == CHAINS[era["name"]]

    def test_the_lists_keep_the_order_they_had_and_the_made_accounts_go_last(self, era):
        with era["engine"].connect() as conn:
            accounts = conn.execute(
                text("SELECT name, position FROM accounts ORDER BY position")
            ).all()
            sources = conn.execute(
                text("SELECT name FROM income_sources ORDER BY position")
            ).scalars()
            assert [a[0] for a in accounts] == ACCOUNT_ORDER[era["name"]]
            assert [a[1] for a in accounts] == list(range(len(accounts)))
            assert list(sources) == ["Northwind Labs", "Local consulting", "Old client"]

    def test_a_made_account_is_plain_and_in_use(self, era):
        old = len(era["snapshot"]["accounts"][1])
        with era["engine"].connect() as conn:
            made = conn.execute(
                text(
                    "SELECT a.name, a.currency, a.kind, a.is_default, a.archived, a.role,"
                    " (SELECT COUNT(*) FROM freelance_payout_legs l WHERE l.account_id = a.id)"
                    " FROM accounts a ORDER BY a.id"
                )
            ).all()[old:]
        assert [tuple(m[:6]) for m in made] == [
            (name, currency, "other", 0, 0, "both") for name, currency in MADE[era["name"]]
        ]
        assert all(m[6] > 0 for m in made), "an account was made that no payout uses"

    def test_the_models_read_a_chain_in_its_order(self, era):
        if era["name"] != "v57":
            pytest.skip("the two-account payouts are the v57 ones")
        with sessionmaker(bind=era["engine"])() as s:
            payout = s.get(FreelancePayout, 13)
            assert [(leg.account.name, leg.amount, leg.fixed) for leg in payout.legs] == [
                ("Stripe", 999.0, True),
                ("Main bank", 894.76, True),
            ]
            assert payout.legs[-1].amount == payout.amount


def _seeded(statements: list[str]):
    """The schema of the last version, with rows put in by hand: the cases its API refuses."""
    engine = _engine(upto="0012")
    with engine.connect() as conn:
        for sql in statements:
            conn.execute(text(sql))
        conn.commit()
    return engine


_ACCOUNT = (
    "INSERT INTO accounts (id, name, currency, kind, is_default, archived, role, created_at)"
    " VALUES ({id}, '{name}', '{currency}', 'bank', {default}, 0, 'both', '2026-11-01 10:00:00')"
)
_SOURCE = (
    "INSERT INTO income_sources (id, name, hourly_rate, currency, is_default, archived)"
    " VALUES ({id}, '{name}', 90, '{currency}', {default}, 0)"
)


# What 0014 changes on purpose in an answer, each with its reason. Anything else in an answer
# that an old version gave must come out the same.
GONE_FROM_A_PAYOUT = {
    "sent_amount",
    "sent_currency",
    "from_account_id",
    "from_account_name",
    "sent_gap",
}
GONE_FROM_A_SOURCE = {"default_account_id", "default_from_account_id"}  # the chain says it
GONE_FROM_AN_ACCOUNT = {"role"}  # what an account may do is no longer asked of it
GONE_FROM_THE_CSV = {"sent_amount", "sent_currency", "from_account"}  # columns of dropped fields


class TestTheAppAfterTheCloseOfTheChain:
    @staticmethod
    def _answers(engine):
        try:
            with _client(engine) as c:
                return {
                    "payouts": {p["id"]: p for p in c.get("/api/freelance/payouts").json()},
                    "summary": c.get(f"/api/freelance/summary?year=2026&today={TODAY}").json(),
                    "sheet": c.get("/api/freelance/payouts.csv").text,
                    "sources": c.get("/api/freelance/sources").json(),
                    "accounts": c.get("/api/freelance/accounts").json(),
                    "export": c.get("/api/freelance/export.csv").text,
                }
        finally:
            fastapi_app.dependency_overrides.clear()

    def test_every_figure_of_every_payout_is_what_it_was(self, era_at_head):
        now = self._answers(era_at_head["engine"])
        old = era_at_head["answers"]
        assert len(now["payouts"]) == len(old["payouts"]) == len(LEGS[era_at_head["name"]])
        for was in old["payouts"]:
            got = now["payouts"][was["id"]]
            assert {k: got[k] for k in MONEY} == {k: was[k] for k in MONEY}, f"payout {was['id']}"
            # the first leg against what was billed: the gap an old row had is the one it has
            assert got["gap"] == (was["gap"] if "gap" in was else got["gap"])
            assert not GONE_FROM_A_PAYOUT & got.keys()

    def test_the_account_of_a_payout_is_its_last_legs_and_an_old_one_is_kept(self, era_at_head):
        """The one field of a payout that changes on purpose: a payout that had no account now
        has the made account of its currency (its last leg). One that had one keeps it."""
        name = era_at_head["name"]
        now = self._answers(era_at_head["engine"])
        kept = created = 0
        for was in era_at_head["answers"]["payouts"]:
            got = now["payouts"][was["id"]]
            last = LEGS[name][was["id"]][-1][0]
            assert got["account_name"] == last, f"payout {was['id']}"
            assert got["account_id"] == got["legs"][-1]["account_id"]
            if was["account_id"] is None:
                created += 1
            else:
                kept += 1
                assert (got["account_id"], got["account_name"]) == (
                    was["account_id"],
                    was["account_name"],
                )
        assert kept and created  # the controls: both kinds are in the fixture

    def test_the_summary_is_the_same_but_for_the_accounts_that_gained_payouts(self, era_at_head):
        """`accounts` groups money by the payout's account: a payout that had none now counts under
        the made account of its currency. Everything else in the summary is what it was; the
        accounts that had payouts have them still; the new rows are the made accounts, with the
        sums worked out by hand from the payouts that had no account."""
        name = era_at_head["name"]
        now = self._answers(era_at_head["engine"])["summary"]
        old = era_at_head["answers"]["summary"]
        assert {k: v for k, v in _only_keys_of(old, now).items() if k != "accounts"} == {
            k: v for k, v in old.items() if k != "accounts"
        }
        by_name = {a["name"]: a for a in now["accounts"]}
        for was in old["accounts"]:
            assert by_name[was["name"]] == was
        extra = {n: a for n, a in by_name.items() if n not in {w["name"] for w in old["accounts"]}}
        # hand-added from the fixtures: the payouts of 2026 that had no account, per currency
        want = {
            "v56": {"USD account": (5250.0, 4139.01, 4), "EUR account": (1080.0, 1080.0, 2)},
            "v57": {"USD account": (5250.0, 4139.01, 4), "EUR account": (1875.0, 1875.0, 4)},
        }[name]
        assert {n: (a["amount"], a["amount_eur"], a["payouts"]) for n, a in extra.items()} == want

    def test_the_sheet_loses_only_the_columns_of_the_dropped_fields(self, era_at_head):
        now = self._answers(era_at_head["engine"])["sheet"]
        was_rows = list(csv.DictReader(io.StringIO(era_at_head["answers"]["payouts_csv"])))
        now_rows = list(csv.DictReader(io.StringIO(now)))
        assert len(now_rows) == len(was_rows)
        if era_at_head["name"] == "v57":  # v56 had no sent side yet
            assert was_rows[0].keys() >= GONE_FROM_THE_CSV
        assert now_rows[0].keys().isdisjoint(GONE_FROM_THE_CSV)
        kept = [k for k in was_rows[0] if k not in GONE_FROM_THE_CSV]
        for was, got in zip(was_rows, now_rows, strict=True):
            for k in kept:
                if k == "account" and not was[k]:
                    assert got[k], "a payout that had no account has one now"
                else:
                    assert got[k] == was[k], (k, was["week_start"], was["source"])

    def test_sources_and_accounts_lose_only_the_dropped_fields(self, era_at_head):
        now = self._answers(era_at_head["engine"])
        old = era_at_head["answers"]
        for src in now["sources"]:
            assert not GONE_FROM_A_SOURCE & src.keys()
        for acc in now["accounts"]:
            assert not GONE_FROM_AN_ACCOUNT & acc.keys()
        was_sources = [
            {k: v for k, v in x.items() if k not in GONE_FROM_A_SOURCE} for x in old["sources"]
        ]
        assert _only_keys_of(was_sources, now["sources"]) == was_sources
        known = {a["id"] for a in old["accounts"]}
        was_accounts = [
            {k: v for k, v in x.items() if k not in GONE_FROM_AN_ACCOUNT} for x in old["accounts"]
        ]
        kept = [a for a in now["accounts"] if a["id"] in known]
        assert _only_keys_of(was_accounts, kept) == was_accounts

    def test_the_block_export_keeps_its_columns_and_figures(self, era_at_head):
        """Not part of the old answers; pinned against the same database read before 0014's
        account change: its only account column is the source's usual one."""
        now = self._answers(era_at_head["engine"])["export"]
        rows = list(csv.DictReader(io.StringIO(now)))
        assert rows and list(rows[0]) == [
            "date",
            "source",
            "hours",
            "start_time",
            "end_time",
            "rate",
            "currency",
            "fx_rate",
            "amount",
            "amount_eur",
            "notes",
            "account",
        ]
        # the source of the first block (Northwind Labs) is usually paid into its chain's last
        northwind = [r for r in rows if r["source"] == "Northwind Labs"]
        want = CHAINS[era_at_head["name"]]["Northwind Labs"][-1]
        assert {r["account"] for r in northwind} == {want}


class TestTheEdges:
    def test_an_empty_kronos_gets_no_account(self):
        engine = _engine(upto="head")
        assert _rows(engine, "accounts") == []
        assert _legs(engine) == {}
        engine.dispose()

    def test_a_name_already_taken_is_not_taken_twice(self):
        engine = _seeded(
            [
                _ACCOUNT.format(id=1, name="USD account", currency="EUR", default=0),
                _SOURCE.format(id=1, name="Northwind Labs", currency="USD", default=1),
                "INSERT INTO freelance_payouts (id, source_id, week_start, amount, currency,"
                " fx_rate) VALUES (1, 1, '2026-11-02', 1900, 'USD', 1.1165)",
            ]
        )
        _upgrade(engine, "0013")
        assert _legs(engine) == {1: [("USD account 2", 1900.0, True)]}
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT currency FROM accounts WHERE name = 'USD account 2'")
                ).scalar()
                == "USD"
            )
        engine.dispose()

    def test_an_account_in_another_currency_never_changes_what_a_payout_is_in(self):
        """No version writes such a row. If one exists, the payout's own currency wins."""
        engine = _seeded(
            [
                _ACCOUNT.format(id=1, name="Main bank", currency="EUR", default=1),
                _SOURCE.format(id=1, name="Northwind Labs", currency="USD", default=1),
                "INSERT INTO freelance_payouts (id, source_id, week_start, amount, currency,"
                " fx_rate, account_id) VALUES (1, 1, '2026-11-02', 1900, 'USD', 1.1165, 1)",
            ]
        )
        before = _rows(engine, "freelance_payouts")
        _upgrade(engine, "0013")
        assert _rows(engine, "freelance_payouts") == before
        assert _legs(engine) == {1: [("USD account", 1900.0, True)]}
        engine.dispose()

    def test_the_default_goes_first_and_templates_keep_their_order(self):
        engine = _seeded(
            [
                _ACCOUNT.format(id=1, name="Wise", currency="EUR", default=0),
                _ACCOUNT.format(id=2, name="Main bank", currency="EUR", default=1),
                _SOURCE.format(id=1, name="Local consulting", currency="EUR", default=0),
                _SOURCE.format(id=2, name="Northwind Labs", currency="USD", default=1),
                "INSERT INTO templates (id, name, start_time, end_time, breaks) VALUES"
                " (3, 'Short day', '09:00', '14:00', '[]'),"
                " (7, 'Long day', '08:00', '18:00', '[]')",
            ]
        )
        _upgrade(engine, "0013")
        with engine.connect() as conn:
            order = {
                table: [
                    r[0] for r in conn.execute(text(f"SELECT name FROM {table} ORDER BY position"))
                ]
                for table in ("accounts", "income_sources", "templates")
            }
        assert order == {
            "accounts": ["Main bank", "Wise"],
            "income_sources": ["Northwind Labs", "Local consulting"],
            "templates": ["Short day", "Long day"],
        }
        engine.dispose()

    def test_a_name_that_differs_only_by_its_case_is_taken_too(self):
        """The app refuses two accounts called the same but for the case, and so does a restore."""
        engine = _seeded(
            [
                _ACCOUNT.format(id=1, name="USD Account", currency="USD", default=0),
                _SOURCE.format(id=1, name="Northwind Labs", currency="USD", default=1),
                "INSERT INTO freelance_payouts (id, source_id, week_start, amount, currency,"
                " fx_rate) VALUES (1, 1, '2026-11-02', 1900, 'USD', 1.1165)",
            ]
        )
        _upgrade(engine, "0013")
        assert _legs(engine) == {1: [("USD account 2", 1900.0, True)]}
        engine.dispose()

    def test_a_sent_side_without_a_currency_is_in_its_accounts_or_else_the_sources(self):
        """Only a restored backup can hold such a row: an amount sent and no currency with it."""
        engine = _seeded(
            [
                _ACCOUNT.format(id=1, name="Main bank", currency="EUR", default=1),
                _ACCOUNT.format(id=2, name="Wise", currency="EUR", default=0),
                _SOURCE.format(id=1, name="Northwind Labs", currency="USD", default=1),
                "INSERT INTO freelance_payouts (id, source_id, week_start, amount, currency,"
                " account_id, sent_amount, from_account_id) VALUES"
                " (1, 1, '2026-11-02', 894.76, 'EUR', 1, 900, 2),"
                " (2, 1, '2026-10-26', 880, 'EUR', 1, 990, NULL)",
            ]
        )
        _upgrade(engine, "0013")
        assert _legs(engine) == {
            # sent from a euro account though the source bills in dollars: the account's wins
            1: [("Wise", 900.0, True), ("Main bank", 894.76, True)],
            2: [("USD account", 990.0, True), ("Main bank", 880.0, True)],
        }
        engine.dispose()

    def test_rows_that_point_nowhere_still_get_a_chain(self):
        """Foreign keys are off while a migration runs, and were off for anyone who wrote to the
        file by hand: a payout whose source or account is gone keeps its figures and gets its
        leg, and a source's default that is gone is not put in its chain."""
        engine = _seeded(
            [
                _SOURCE.format(id=1, name="Northwind Labs", currency="USD", default=1),
                "UPDATE income_sources SET default_account_id = 99, default_from_account_id = 98",
                "INSERT INTO freelance_payouts (id, source_id, week_start, amount, currency,"
                " fx_rate, account_id, sent_amount, from_account_id) VALUES"
                " (1, 77, '2026-11-02', 1900, 'USD', 1.1165, NULL, NULL, NULL),"
                " (2, 1, '2026-10-26', 800, 'EUR', NULL, 99, 850, 98)",
            ]
        )
        before = _rows(engine, "freelance_payouts")
        _upgrade(engine, "0013")
        assert _rows(engine, "freelance_payouts") == before
        assert _legs(engine) == {
            1: [("USD account", 1900.0, True)],
            2: [("USD account", 850.0, True), ("EUR account", 800.0, True)],
        }
        assert _rows(engine, "income_source_accounts") == []
        engine.dispose()

    def test_a_run_cut_short_is_finished_by_the_next_one(self):
        """SQLite keeps the new tables of a migration that failed half way, with the revision
        still the old one. The next start must finish the job, not die on "already exists"."""
        engine = _engine(script=(ERAS / "v57.sql").read_text("utf-8"))
        snapshot = _snapshot(engine)
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TRIGGER cut BEFORE INSERT ON accounts"
                    " BEGIN SELECT RAISE(ABORT, 'cut short'); END"
                )
            )
            conn.commit()
        with pytest.raises(Exception, match="cut short"):
            _upgrade(engine, "0013")
        with engine.connect() as conn:
            # the control: the failure really left the half-done state this test is about
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0012"
            names = set(conn.execute(text("SELECT name FROM sqlite_master")).scalars())
            assert "freelance_payout_legs" in names
            # and rows a cut run might have left are not in the way of the next one
            conn.execute(
                text(
                    "INSERT INTO freelance_payout_legs"
                    " (payout_id, position, account_id, amount, fixed) VALUES (1, 0, 1, 1.0, 1)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO income_source_accounts (source_id, position, account_id)"
                    " VALUES (1, 0, 2)"
                )
            )
            conn.execute(text("DROP TRIGGER cut"))
            conn.commit()
        _upgrade(engine, "0013")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0013"
        _assert_nothing_moved(engine, snapshot, made_accounts=len(MADE["v57"]))
        want = {pid: [(n, a, True) for n, a in chain] for pid, chain in LEGS_V57.items()}
        assert _legs(engine) == want
        engine.dispose()

    def test_it_goes_down_again_and_everything_is_as_it_was(self):
        engine = _engine(script=(ERAS / "v57.sql").read_text("utf-8"))
        snapshot = _snapshot(engine)
        _upgrade(engine, "0013")
        cfg = _config()
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "0012")
            conn.commit()
        assert set(_snapshot(engine)) == set(snapshot)  # the two new tables are gone
        for table in ("accounts", "income_sources", "templates"):
            assert _columns(engine, table) == snapshot[table][0], table
        # the accounts made on the way up stay: nothing says they were not kept
        _assert_nothing_moved(engine, snapshot, made_accounts=len(MADE["v57"]))
        engine.dispose()
