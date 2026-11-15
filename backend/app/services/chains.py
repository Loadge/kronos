"""The chain of accounts: a payout's legs and a source's usual chain.

A payout's money goes through one to four accounts (``PayoutLeg``). The LAST leg is what the
payout is worth: its amount is the payout's ``amount`` and its account's currency the payout's
``currency``, so every total keeps reading the columns it always read. Every write of a payout
keeps that invariant; the rules that keep it live here and nowhere else.

A source's usual chain (``SourceAccount``) is where a new payout of it starts. Changing it never
touches a saved payout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Account, FreelancePayout, IncomeSource, PayoutLeg, SourceAccount
from app.schemas import PayoutLegIn
from app.services import currencies, freelance

MAX_LEGS = 4


def _refuse(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


@dataclass
class Leg:
    """One leg as settled, before it is stored."""

    account: Account
    amount: float | None  # None only in a lenient settle, with the reason in `problem`
    fixed: bool
    problem: str | None = None


# ---------- the order of a list ----------------------------------------------------


def next_position(session: Session, model) -> int:
    """Where a new row of `model` (Account, IncomeSource or Template) goes: after every other."""
    top = session.scalar(select(func.max(model.position)))
    return (-1 if top is None else top) + 1


def set_order(session: Session, model, ids: list[int]) -> None:
    """Give the rows of `model` the positions 0..n-1 in the order of `ids`, which must be every
    id of the table, each once. Anything else is a 422 and nothing changes."""
    rows = {row.id: row for row in session.scalars(select(model))}
    if len(set(ids)) != len(ids):
        raise _refuse("an id is twice in the list")
    if set(ids) - rows.keys():
        raise _refuse("an id is not in the list")
    if rows.keys() - set(ids):
        raise _refuse("an id is missing: send every one, archived included")
    for position, row_id in enumerate(ids):
        rows[row_id].position = position


# ---------- the accounts the API makes ---------------------------------------------


def _is_made_name(name: str, currency: str) -> bool:
    """Whether `name` is "USD account" or "USD account 2" (any case) for `currency`."""
    pattern = re.escape(f"{currency} account".casefold()) + r"( \d+)?"
    return re.fullmatch(pattern, name.casefold()) is not None


def _made_account(session: Session, currency: str, taken: tuple[int, ...]) -> Account:
    """The account a side without a usable one lands in: the first live "other" account of that
    currency named "<CUR> account" (or "<CUR> account N") that the chain does not hold yet, else
    a new one. The same rule as the migration that introduced chains."""
    rows = session.scalars(
        select(Account)
        .where(
            Account.kind == "other",
            Account.currency == currency,
            Account.archived.is_(False),
        )
        .order_by(Account.id)
    )
    for account in rows:
        if account.id not in taken and _is_made_name(account.name, currency):
            return account
    names = {n.casefold() for n in session.scalars(select(Account.name))}
    base, n = f"{currency} account", 1
    name = base
    while name.casefold() in names:
        n += 1
        name = f"{base} {n}"
    account = Account(
        name=name,
        currency=currency,
        kind="other",
        is_default=False,
        archived=False,
        position=next_position(session, Account),
    )
    session.add(account)
    session.flush()
    return account


def _side_account(
    session: Session, account_id: int | None, currency: str, taken: tuple[int, ...]
) -> Account:
    """The account of one side of a payout: its own when it has one in that currency and the
    chain does not hold it yet, else a made one of that currency."""
    account = None if account_id is None else session.get(Account, account_id)
    if account is not None and account.currency == currency and account.id not in taken:
        return account
    return _made_account(session, currency, taken)


# ---------- a payout's legs -----------------------------------------------------


def _store(session: Session, payout: FreelancePayout, legs: list[Leg]) -> None:
    """Replace the payout's legs. The old rows go first and are flushed: there is a UNIQUE on
    (payout, position) and on (payout, account), and the unit of work inserts before it deletes."""
    if payout.legs:
        payout.legs.clear()
        session.flush()
    payout.legs.extend(
        PayoutLeg(position=i, account=leg.account, amount=leg.amount, fixed=leg.fixed)
        for i, leg in enumerate(legs)
    )


def legs_from_sides(
    session: Session,
    payout: FreelancePayout,
    sent_amount: float | None = None,
    sent_currency: str | None = None,
    sent_from_id: int | None = None,
) -> None:
    """Build the legs of a payout restored from a backup that gave it none, from what the file
    says (``payout.account_id`` and its amount and currency are what arrived; the three ``sent_*``
    are the sent side, which a file of an older version holds): one leg for what arrived, before
    it one for what was sent when that is recorded. All fixed. The same rule as the migration that
    dropped those columns. A side without a usable account (none, one in another currency, or
    the other leg's) takes a made one of its currency. The payout's account becomes the last
    leg's.
    """
    arrived = _side_account(session, payout.account_id, payout.currency, ())
    legs = [Leg(arrived, payout.amount, True)]
    if sent_amount is not None:
        sent_from = None if sent_from_id is None else session.get(Account, sent_from_id)
        currency = (
            sent_currency
            or (None if sent_from is None else sent_from.currency)
            or session.get(IncomeSource, payout.source_id).currency
        )
        account = _side_account(session, sent_from_id, currency, (arrived.id,))
        legs.insert(0, Leg(account, sent_amount, True))
    _store(session, payout, legs)
    payout.account_id = arrived.id


def settle_legs(
    session: Session,
    payout: FreelancePayout,
    source: IncomeSource,
    legs_in: list[PayoutLegIn],
    paid_on,
    week_start=None,
    lenient: bool = False,
) -> list[Leg]:
    """Settle the legs of the new request shape, store them on `payout` and return them.

    1 to 4 legs, no account twice, every account known; an archived one only when the payout
    already has it. An item with an amount is stored as given with the `fixed` the client sent
    (True when it did not say): a suggestion the client confirmed comes back as it showed it.
    An item without one is worked out: the first leg from what the week billed, any other from
    the leg before it, converted at the rate of `paid_on` (default: the week's Sunday) and
    stored `fixed=False`. A leg that cannot be converted for want of a rate is a 422.

    `lenient` (a preview) turns what the above refuses for want of a figure into an answer: such
    a leg comes back with `amount` None and a `problem` ("no rate for that day", "nothing billed
    that week"), and every leg worked out from a leg without an amount has none either ("needs the
    account before it"). Nothing is stored unless every leg has an amount. What the request
    itself gets wrong (count, repeats, unknown or archived accounts) is a 422 in both ways.
    """
    if not 1 <= len(legs_in) <= MAX_LEGS:
        raise _refuse(f"a payout goes through 1 to {MAX_LEGS} accounts")
    ids = [item.account_id for item in legs_in]
    if len(set(ids)) != len(ids):
        raise _refuse("an account can be in the chain only once")
    already = {leg.account_id for leg in payout.legs}
    accounts: list[Account] = []
    for account_id in ids:
        account = session.get(Account, account_id)
        if account is None:
            raise _refuse("unknown account")
        if account.archived and account.id not in already:
            raise _refuse("that account is archived")
        accounts.append(account)

    week = week_start or payout.week_start
    day = paid_on or week + timedelta(days=6)
    before: tuple[float | None, str] | None = None  # the leg before: its amount and currency
    legs: list[Leg] = []
    for item, account in zip(legs_in, accounts, strict=True):
        problem = None
        if item.amount is not None:
            amount, fixed = item.amount, True if item.fixed is None else item.fixed
        else:
            fixed = False
            if before is None:
                blocks = [
                    b
                    for b in freelance.blocks_between(session, week, week + timedelta(days=6))
                    if b.source_id == source.id
                ]
                before = freelance.week_amount(blocks, source.currency)
                if lenient and not blocks:
                    before = (None, before[1])
                    problem = "nothing billed that week"
            elif before[0] is None:
                problem = "needs the account before it"
            if problem is not None:
                amount = None
            else:
                amount = _converted(before[0], before[1], account.currency, day)
                if amount is None:
                    if not lenient:
                        raise _refuse("no rate for that day: type the amount")
                    problem = "no rate for that day"
                elif amount <= 0:
                    if not lenient:
                        raise _refuse("nothing to work out there: type the amount")
                    amount, problem = None, "nothing to work out there: type the amount"
        legs.append(Leg(account, amount, fixed, problem))
        before = (amount, account.currency)
    if all(leg.amount is not None for leg in legs):
        _store(session, payout, legs)
    return legs


def _converted(amount: float, frm: str, to: str, day) -> float | None:
    """`amount` of `frm` in `to` at the rate of `day`, rounded as `to` does; None without a rate."""
    if frm == to:
        return amount
    rate = currencies.cross_rate(frm, to, day)
    if rate is None:
        return None
    return currencies.quantize(amount * rate, to)


def gap(p: FreelancePayout, billed: freelance.Billed) -> float | None:
    """The first leg minus what the week billed, in the billed currency.

    None when nothing was billed that week, or when the first leg is in another currency and the
    payout's day has no rate. A first leg that was worked out from what was billed is 0.0 by
    definition, whatever a conversion would round to.
    """
    if not p.legs or not billed.blocks or not billed.amount:
        return None
    first = p.legs[0]
    if not first.fixed:
        return 0.0
    if first.account.currency == billed.currency:
        got = first.amount
    else:
        day = p.rate_date or (p.week_start + timedelta(days=6))
        rate = currencies.cross_rate(first.account.currency, billed.currency, day)
        if rate is None:
            return None
        got = currencies.quantize(first.amount * rate, billed.currency)
    return currencies.quantize(got - billed.amount, billed.currency)


def leg_counts(session: Session) -> dict[int, int]:
    """How many payouts have each account in their legs (a payout counts once for an account;
    the chain never repeats one)."""
    rows = session.execute(
        select(PayoutLeg.account_id, func.count(PayoutLeg.payout_id.distinct())).group_by(
            PayoutLeg.account_id
        )
    )
    return {account_id: n for account_id, n in rows}


def account_in_use(session: Session, account_id: int) -> bool:
    """Whether a payout's legs hold the account: then it cannot be deleted nor change currency."""
    return bool(
        session.scalar(
            select(func.count()).select_from(PayoutLeg).where(PayoutLeg.account_id == account_id)
        )
    )


# ---------- a source's chain ----------------------------------------------------


def check_chain(session: Session, ids: list[int]) -> None:
    """422 unless `ids` is at most four known, live accounts, none twice."""
    if len(ids) > MAX_LEGS:
        raise _refuse(f"a chain has at most {MAX_LEGS} accounts")
    if len(set(ids)) != len(ids):
        raise _refuse("an account can be in the chain only once")
    for account_id in ids:
        account = session.get(Account, account_id)
        if account is None:
            raise _refuse("unknown account")
        if account.archived:
            raise _refuse("that account is archived")


def set_chain(session: Session, source: IncomeSource, ids: list[int]) -> None:
    """Replace the source's chain: the old rows are deleted and flushed first (UNIQUE on
    (source, position)), then the new ones inserted."""
    source.chain.clear()
    session.flush()
    source.chain.extend(SourceAccount(position=i, account_id=a) for i, a in enumerate(ids))


def chain_from_defaults(
    paid_from: int | None, paid_into: int | None, usable: set[int]
) -> list[int]:
    """A source's chain from its two old defaults: "Paid from", then "Paid into". The same
    account twice is one, and an account that is not in `usable` (archived, or not there) is left
    out. The rule the migration that introduced chains applied, and a restore of an older file."""
    chain: list[int] = []
    for account_id in (paid_from, paid_into):
        if account_id in usable and account_id not in chain:
            chain.append(account_id)
    return chain


def remember_chain(session: Session, source: IncomeSource, account: Account) -> None:
    """A source with no chain yet takes the one account a payout went into as its chain."""
    if not source.chain and not account.archived:
        set_chain(session, source, [account.id])


def remove_account_from_chains(session: Session, account_id: int) -> None:
    """Take an account out of every source chain, the positions closing up behind it."""
    source_ids = list(
        session.scalars(
            select(SourceAccount.source_id).where(SourceAccount.account_id == account_id).distinct()
        )
    )
    for source_id in source_ids:
        source = session.get(IncomeSource, source_id)
        set_chain(
            session, source, [c.account_id for c in source.chain if c.account_id != account_id]
        )
