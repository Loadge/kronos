"""The sample data has two accounts, the chains of its sources and payouts saved as chains.

The weak point is a seeded payout that looks right but is not what the API would have stored: so
the main test sends the same legs to the API, with the ECB stubbed at the sample rate as the API
tests stub it, and compares every column of the payout and of its legs. Nothing here reaches the
network or depends on the day the suite runs.
"""

from __future__ import annotations

from datetime import date, timedelta

import app.services.crypto as crypto
import app.services.fx as fx
import pytest
from app.database import Base, get_session
from app.main import app as fastapi_app
from app.models import (
    Account,
    FreelanceBlock,
    FreelancePayout,
    IncomeSource,
    PayoutLeg,
    SourceAccount,
)
from app.services import currencies
from fastapi.testclient import TestClient
from seed import SAMPLE_ACCOUNTS, SAMPLE_CHAINS, SAMPLE_FX, build_freelance
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TODAY = date(2026, 11, 11)

_DAYS = [date(2026, 7, 1) + timedelta(days=n) for n in range(0, 140)]
_CUBES = "".join(
    f'<Cube time="{d.isoformat()}"><Cube currency="USD" rate="{SAMPLE_FX}"/></Cube>'
    for d in reversed(_DAYS)
)
ECB = f"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>{_CUBES}</Cube>
</gesmes:Envelope>
"""


@pytest.fixture
def stubbed_ecb(monkeypatch):
    """The ECB at the sample rate on every day, and no other request: as the API tests do."""
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


@pytest.fixture
def api_world(stubbed_ecb):
    """A second, empty database behind the app, with the two sample accounts and sources made
    through the API the way a person would. Yields (client, session factory)."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
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
            ids = {}
            for name, currency, kind, is_default in SAMPLE_ACCOUNTS:
                r = c.post(
                    "/api/freelance/accounts",
                    json={
                        "name": name,
                        "currency": currency,
                        "kind": kind,
                        "is_default": is_default,
                    },
                )
                assert r.status_code == 201, r.text
                ids[name] = r.json()["id"]
            for name, rate, currency, is_default in (
                ("Northwind Labs", 95.0, "USD", True),
                ("Local consulting", 60.0, "EUR", False),
            ):
                r = c.post(
                    "/api/freelance/sources",
                    json={
                        "name": name,
                        "hourly_rate": rate,
                        "currency": currency,
                        "is_default": is_default,
                        "chain": [ids[n] for n in SAMPLE_CHAINS[name]],
                    },
                )
                assert r.status_code == 201, r.text
            yield c, factory
    finally:
        fastapi_app.dependency_overrides.clear()
        engine.dispose()


def _seeded(session, today=TODAY):
    build_freelance(session, today=today)
    session.commit()
    return list(session.scalars(select(FreelancePayout).order_by(FreelancePayout.id)))


def _columns(row, skip: set[str]) -> dict:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in skip}


def _stored(session, payout_id: int) -> tuple[dict, list[dict]]:
    payout = session.get(FreelancePayout, payout_id)
    legs = sorted(payout.legs, key=lambda leg: leg.position)
    return (
        _columns(payout, {"id"}),
        [_columns(leg, {"id", "payout_id"}) for leg in legs],
    )


def _world(session) -> dict:
    """Everything the sample makes, without its ids' history: accounts, chains, payouts, legs."""
    return {
        "accounts": [
            _columns(a, {"created_at"})
            for a in session.scalars(select(Account).order_by(Account.id))
        ],
        "chains": [
            _columns(c, set())
            for c in session.scalars(select(SourceAccount).order_by(SourceAccount.id))
        ],
        "payouts": [
            (_columns(p, set()), [_columns(leg, set()) for leg in p.legs])
            for p in session.scalars(select(FreelancePayout).order_by(FreelancePayout.id))
        ],
    }


def _wipe_as_the_seed_endpoint_does(session):
    session.execute(delete(PayoutLeg))
    session.execute(delete(FreelancePayout))
    session.execute(delete(FreelanceBlock))
    session.commit()


class TestWhatTheSeedStores:
    def test_every_seeded_payout_is_what_the_api_stores_for_the_same_legs(
        self, db_session, api_world
    ):
        client, factory = api_world
        payouts = _seeded(db_session)
        assert len(payouts) == 3
        compared = 0
        with factory() as api_session:
            for p in payouts:
                seeded_row, seeded_legs = _stored(db_session, p.id)
                body = {
                    "source_id": p.source_id,
                    "week_start": p.week_start.isoformat(),
                    "note": p.note,
                    # What the seed meant: a typed leg carries its amount, any other is worked out.
                    "legs": [
                        {"account_id": leg["account_id"], "amount": leg["amount"], "fixed": True}
                        if leg["fixed"]
                        else {"account_id": leg["account_id"]}
                        for leg in seeded_legs
                    ],
                }
                r = client.post("/api/freelance/payouts", json=body)
                assert r.status_code == 201, r.text
                api_row, api_legs = _stored(api_session, r.json()["id"])
                assert seeded_row == api_row
                assert seeded_legs == api_legs
                compared += len(seeded_legs)
        # Positive control: the comparison covers the figures a wrong seed would get wrong.
        assert {"amount", "currency", "fx_rate", "rate_source", "rate_date", "account_id"} <= set(
            seeded_row
        )
        assert {"position", "account_id", "amount", "fixed"} <= set(seeded_legs[0])
        assert compared == 5

    def test_the_dollar_payouts_go_through_stripe_then_the_bank(self, db_session):
        payouts = _seeded(db_session)
        by_source = {}
        for p in payouts:
            by_source.setdefault(p.source.name, []).append(p)
        assert [len(v) for v in by_source.values()] == [2, 1]
        for p in by_source["Northwind Labs"]:
            assert [(leg.account.name, leg.fixed) for leg in p.legs] == [
                ("Stripe", True),
                ("Deutsche Bank", False),
            ]
            assert (p.account.name, p.currency) == ("Deutsche Bank", "EUR")
            assert p.legs[-1].amount == p.amount
            assert p.legs[-1].amount == currencies.quantize(p.legs[0].amount / SAMPLE_FX, "EUR")
        (euro,) = by_source["Local consulting"]
        assert [(leg.account.name, leg.fixed) for leg in euro.legs] == [("Deutsche Bank", True)]

    def test_no_sample_payout_is_saved_without_legs(self, db_session):
        assert all(p.legs for p in _seeded(db_session))

    def test_the_seed_does_not_leave_its_rate_behind(self, db_session):
        before = currencies.rate_for
        _seeded(db_session)
        assert currencies.rate_for is before

    def test_a_rate_the_sample_does_not_have_is_refused_not_fetched(self, db_session):
        from seed import sample_rates  # noqa: PLC0415

        with sample_rates(), pytest.raises(AssertionError):
            currencies.rate_for("GBP", TODAY)

    def test_the_two_exact_and_inexact_payouts_carry_their_notes(self, db_session):
        notes = {(p.source.name, p.note) for p in _seeded(db_session)}
        assert notes == {
            ("Local consulting", "sample payout"),
            ("Northwind Labs", None),
            ("Northwind Labs", "sample payout"),
        }

    def test_two_seeds_at_once_leave_the_real_rate_back(self):
        """The first holds the block open until the second has tried to enter and, if it can,
        got in; the second leaves only after the first has gone. Without the lock they
        interleave and the sample rate is put back for good."""
        import threading  # noqa: PLC0415

        from seed import sample_rates  # noqa: PLC0415

        original = currencies.rate_for
        second_tried, second_in, first_out = (threading.Event() for _ in range(3))
        problems: list[str] = []

        def first():
            with sample_rates():
                second_tried.wait(5)
                second_in.wait(1)  # a second that can enter does at once; a locked-out one waits
            first_out.set()

        def second():
            second_tried.set()
            with sample_rates():
                second_in.set()
                if not first_out.wait(5):
                    problems.append("the first never left")

        threads = [threading.Thread(target=first), threading.Thread(target=second)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        assert not problems
        assert all(not t.is_alive() for t in threads)
        assert currencies.rate_for is original


class TestTheAccountsAndChains:
    def test_an_account_with_a_sample_name_in_another_currency_is_not_the_sample_one(
        self, db_session
    ):
        db_session.add_all(
            [
                Account(name="Stripe", currency="EUR", kind="bank"),
                Account(name="Deutsche Bank", currency="EUR", kind="bank"),
            ]
        )
        db_session.commit()
        build_freelance(db_session, today=TODAY)
        db_session.commit()
        assert db_session.scalars(select(SourceAccount)).all() == []
        assert db_session.scalars(select(FreelancePayout)).all() == []

    def test_two_accounts_come_with_the_sample_sources(self, db_session):
        _seeded(db_session)
        accounts = list(db_session.scalars(select(Account).order_by(Account.position)))
        assert [(a.name, a.currency, a.kind, a.is_default, a.archived) for a in accounts] == [
            ("Stripe", "USD", "wallet", False, False),
            ("Deutsche Bank", "EUR", "bank", True, False),
        ]

    def test_the_chains_are_in_order(self, db_session):
        _seeded(db_session)
        chains_by_source = {
            s.name: [c.account.name for c in s.chain]
            for s in db_session.scalars(select(IncomeSource))
        }
        assert chains_by_source == {
            "Northwind Labs": ["Stripe", "Deutsche Bank"],
            "Local consulting": ["Deutsche Bank"],
        }


class TestSeedingTwice:
    def test_a_second_seed_gives_the_same_data(self, db_session):
        _seeded(db_session)
        first = _world(db_session)
        _wipe_as_the_seed_endpoint_does(db_session)
        build_freelance(db_session, today=TODAY)
        db_session.commit()
        db_session.expire_all()
        second = _world(db_session)
        assert len(second["accounts"]) == 2
        assert len(second["chains"]) == 3
        assert len(second["payouts"]) == 3
        # The payouts are new rows, so their ids move; everything else is the same.
        strip = lambda w: [  # noqa: E731
            (
                {k: v for k, v in p.items() if k != "id"},
                [{k: v for k, v in leg.items() if k not in ("id", "payout_id")} for leg in legs],
            )  # noqa: E501
            for p, legs in w["payouts"]
        ]
        assert second["accounts"] == first["accounts"]
        assert second["chains"] == first["chains"]
        assert strip(second) == strip(first)

    def test_the_endpoint_twice_keeps_two_accounts_and_three_payouts(self, client):
        for _ in range(2):
            assert client.post("/api/data/seed").status_code == 200
        accounts = client.get("/api/freelance/accounts").json()
        payouts = client.get("/api/freelance/payouts").json()
        assert [a["name"] for a in accounts] == ["Stripe", "Deutsche Bank"]
        assert len(payouts) == 3
        assert all(p["legs"] for p in payouts)
        sources = client.get("/api/freelance/sources").json()
        assert [len(s["chain"]) for s in sources] == [2, 1]


class TestSomeoneElsesData:
    def test_other_sources_get_blocks_and_nothing_more(self, db_session):
        db_session.add(IncomeSource(name="Acme", hourly_rate=50, currency="EUR", is_default=True))
        db_session.commit()
        build_freelance(db_session, today=TODAY)
        db_session.commit()
        assert db_session.scalars(select(Account)).all() == []
        assert db_session.scalars(select(SourceAccount)).all() == []
        assert db_session.scalars(select(FreelancePayout)).all() == []
        assert db_session.scalars(select(FreelanceBlock)).all() != []

    def test_sample_sources_next_to_someone_elses_accounts_get_nothing_made(self, db_session):
        db_session.add(Account(name="Mine", currency="EUR", kind="bank"))
        db_session.commit()
        build_freelance(db_session, today=TODAY)
        db_session.commit()
        assert [a.name for a in db_session.scalars(select(Account))] == ["Mine"]
        assert db_session.scalars(select(SourceAccount)).all() == []
        assert db_session.scalars(select(FreelancePayout)).all() == []

    def test_a_chain_someone_set_is_left_and_gets_no_payouts(self, db_session):
        _seeded(db_session)
        northwind = db_session.scalars(
            select(IncomeSource).where(IncomeSource.name == "Northwind Labs")
        ).one()
        bank = db_session.scalars(select(Account).where(Account.name == "Deutsche Bank")).one()
        from app.services import chains  # noqa: PLC0415

        chains.set_chain(db_session, northwind, [bank.id])
        _wipe_as_the_seed_endpoint_does(db_session)
        build_freelance(db_session, today=TODAY)
        db_session.commit()
        db_session.expire_all()
        assert [c.account.name for c in northwind.chain] == ["Deutsche Bank"]
        assert db_session.scalars(select(FreelancePayout)).all() == []
