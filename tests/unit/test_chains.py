"""The accounts made for a side that has none, and the seed's accounts and payouts.

The rule is the migration's (alembic/versions/0014_close_the_chain.py) applied by the app when a
backup of an older version is restored: the first live "other" account of the currency named
"<CUR> account" or "<CUR> account N", else a new one with the first free name.
"""

from __future__ import annotations

from datetime import date

from app.models import Account, FreelancePayout, IncomeSource
from app.services import chains
from seed import build_freelance
from sqlalchemy import select


def _account(session, name, currency, kind="other", archived=False, position=0) -> Account:
    account = Account(name=name, currency=currency, kind=kind, archived=archived, position=position)
    session.add(account)
    session.flush()
    return account


def _source(session, currency="USD") -> IncomeSource:
    source = IncomeSource(name="Northwind", hourly_rate=90, currency=currency)
    session.add(source)
    session.flush()
    return source


def _payout(
    session, source, sent_amount=None, sent_currency=None, sent_from=None, **kw
) -> FreelancePayout:
    """A payout restored from a file that gave it no legs: what arrived is in `kw`, what was
    sent (if anything) in the three `sent_*`."""
    values = {"week_start": date(2026, 11, 2), "amount": 100.0, "currency": source.currency}
    payout = FreelancePayout(source_id=source.id, **(values | kw))
    chains.legs_from_sides(session, payout, sent_amount, sent_currency, sent_from)
    session.add(payout)
    session.commit()
    return payout


def _names(payout) -> list[str]:
    return [leg.account.name for leg in payout.legs]


class TestMadeAccounts:
    def test_an_existing_one_is_reused_whatever_its_case_and_number(self, db_session):
        mine = _account(db_session, "usd ACCOUNT 3", "USD")
        payout = _payout(db_session, _source(db_session))
        assert [leg.account_id for leg in payout.legs] == [mine.id]
        assert db_session.scalar(select(Account.id).where(Account.id != mine.id)) is None

    def test_one_that_is_archived_other_in_kind_or_in_another_currency_is_not(self, db_session):
        _account(db_session, "USD account", "USD", archived=True, position=4)
        _account(db_session, "USD account 2", "USD", kind="bank", position=2)
        _account(db_session, "EUR account", "EUR", position=1)
        _account(db_session, "USD accounts", "USD")
        _account(db_session, "USD account x", "USD")
        payout = _payout(db_session, _source(db_session))
        (leg,) = payout.legs
        assert leg.account.name == "USD account 3"  # the first free of "USD account", " 2", ...
        assert (leg.account.kind, leg.account.currency) == ("other", "USD")
        assert (leg.account.is_default, leg.account.archived, leg.account.position) == (
            False,
            False,
            5,
        )  # one past the highest position

    def test_names_are_compared_without_their_case(self, db_session):
        _account(db_session, "usd Account", "USD", kind="bank")
        payout = _payout(db_session, _source(db_session))
        assert _names(payout) == ["USD account 2"]

    def test_the_first_one_that_matches_wins(self, db_session):
        first = _account(db_session, "USD account 2", "USD")
        _account(db_session, "USD account", "USD")
        payout = _payout(db_session, _source(db_session))
        assert payout.legs[0].account_id == first.id

    def test_an_account_of_another_currency_is_not_the_sides(self, db_session):
        euro = _account(db_session, "Main bank", "EUR", kind="bank")
        source = _source(db_session)
        payout = _payout(
            db_session, source, account_id=euro.id
        )  # a USD payout "into" a EUR account
        assert _names(payout) == ["USD account"]


class TestTheSentSide:
    def test_it_takes_the_sent_currency_then_the_accounts_then_the_sources(self, db_session):
        source = _source(db_session, "USD")
        eur = _account(db_session, "Wise", "EUR", kind="bank")
        by_currency = _payout(
            db_session,
            source,
            sent_amount=100,
            sent_currency="GBP",
            amount=90,
            week_start=date(2026, 11, 2),
        )
        by_account = _payout(
            db_session,
            source,
            sent_amount=100,
            sent_from=eur.id,
            amount=90,
            week_start=date(2026, 11, 9),
        )
        by_source = _payout(
            db_session, source, sent_amount=100, amount=90, week_start=date(2026, 11, 16)
        )
        assert [leg.account.currency for leg in by_currency.legs] == ["GBP", "USD"]
        assert [leg.account.currency for leg in by_account.legs] == ["EUR", "USD"]
        assert [leg.account.currency for leg in by_source.legs] == ["USD", "USD"]
        assert _names(by_source) == ["USD account 2", "USD account"]  # never the same twice

    def test_where_it_was_sent_from_is_where_it_arrived(self, db_session):
        source = _source(db_session, "EUR")
        wise = _account(db_session, "Wise", "EUR", kind="bank")
        payout = _payout(
            db_session,
            source,
            sent_amount=100,
            sent_currency="EUR",
            sent_from=wise.id,
            account_id=wise.id,
        )
        assert _names(payout) == ["EUR account", "Wise"]

    def test_accounts_on_every_side_that_needs_one_give_the_legs(self, db_session):
        """Replaces the same figures proved with no made account allowed (Stripe 999, Main
        bank 894.76): with accounts on both sides none is made."""
        stripe = _account(db_session, "Stripe", "USD", kind="bank")
        bank = _account(db_session, "Main bank", "EUR", kind="bank")
        payout = _payout(
            db_session,
            _source(db_session),
            sent_amount=999,
            sent_currency="USD",
            sent_from=stripe.id,
            account_id=bank.id,
            currency="EUR",
            amount=894.76,
        )
        assert [(leg.account.name, leg.amount) for leg in payout.legs] == [
            ("Stripe", 999.0),
            ("Main bank", 894.76),
        ]
        assert payout.account_id == bank.id
        assert len(db_session.scalars(select(Account)).all()) == 2  # none was made

    def test_the_payouts_account_is_the_last_legs(self, db_session):
        payout = _payout(db_session, _source(db_session), sent_amount=120, sent_currency="EUR")
        assert _names(payout) == ["EUR account", "USD account"]
        assert payout.account_id == payout.legs[-1].account_id


class TestTheSeedMakesChains:
    def test_seeded_payouts_all_have_legs_and_two_accounts_exist(self, db_session):
        build_freelance(db_session, today=date(2026, 11, 11))
        db_session.commit()
        payouts = list(db_session.scalars(select(FreelancePayout)))
        assert len(payouts) == 3
        assert all(p.legs for p in payouts)
        assert sorted(a.name for a in db_session.scalars(select(Account))) == [
            "Deutsche Bank",
            "Stripe",
        ]
