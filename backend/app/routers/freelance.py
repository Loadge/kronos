"""Freelance hours: income sources, hour blocks, the per-year tax inputs, the year's picture
and the calculator.

Blocks live apart from ``work_entries``: nothing here touches the employee's target, balance,
streaks or the timesheet. A block snapshots its source's rate and currency when it is saved
(and, for any currency but EUR, the rate of its date, fetched on demand exactly then), so a
later change of a rate never rewrites the past.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Account, FreelanceBlock, FreelancePayout, FreelanceTaxYear, IncomeSource
from app.schemas import (
    AccountIn,
    AccountOut,
    AccountUpdate,
    FreelanceBlockIn,
    FreelanceBlockOut,
    FreelanceBlockUpdate,
    FreelanceCalcIn,
    FreelancePayoutIn,
    FreelancePayoutOut,
    FreelanceTaxYearIn,
    FreelanceTaxYearOut,
    IncomeSourceIn,
    IncomeSourceOut,
    IncomeSourceUpdate,
    week_end_of,
)
from app.services import currencies, freelance, fx, tax
from app.services.clock import local_today
from app.services.settings import (
    get_country,
    get_freelance_days_off,
    get_freelance_hours_per_week,
)
from app.services.tax import money

router = APIRouter(prefix="/api/freelance", tags=["freelance"])


# ---------- income sources ------------------------------------------------------


def _block_counts(session: Session) -> dict[int, int]:
    rows = session.execute(
        select(FreelanceBlock.source_id, func.count()).group_by(FreelanceBlock.source_id)
    )
    return {sid: n for sid, n in rows}


def _source_out(s: IncomeSource, blocks: int) -> IncomeSourceOut:
    return IncomeSourceOut(
        id=s.id,
        name=s.name,
        hourly_rate=s.hourly_rate,
        currency=s.currency,
        is_default=bool(s.is_default),
        archived=bool(s.archived),
        default_account_id=s.default_account_id,
        default_from_account_id=s.default_from_account_id,
        blocks=blocks,
    )


def _account_or_422(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown account")
    return account


def _into_or_422(session: Session, account_id: int, keep: int | None = None) -> Account:
    """An account a payout may land in: its role is not "origin" (unless `keep`, the account the
    payout already uses: an old row stays editable)."""
    account = _account_or_422(session, account_id)
    if account.role == "origin" and account.id != keep:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "that account only sends: it cannot receive"
        )
    return account


def _from_or_422(session: Session, account_id: int, keep: int | None = None) -> Account:
    """An account a payout may be sent from: its role is not "destination" (unless `keep`)."""
    account = _account_or_422(session, account_id)
    if account.role == "destination" and account.id != keep:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "that account only receives: it cannot send"
        )
    return account


def _clear_default(session: Session, keep: IncomeSource | None) -> None:
    for other in session.scalars(select(IncomeSource).where(IncomeSource.is_default.is_(True))):
        if other is not keep:
            other.is_default = False


@router.get("/sources", response_model=list[IncomeSourceOut])
def list_sources(session: Session = Depends(get_session)) -> list[IncomeSourceOut]:
    """Every source, archived ones included (the picker filters them out); default first."""
    counts = _block_counts(session)
    rows = session.scalars(
        select(IncomeSource).order_by(IncomeSource.is_default.desc(), IncomeSource.id)
    )
    return [_source_out(s, counts.get(s.id, 0)) for s in rows]


@router.post("/sources", response_model=IncomeSourceOut, status_code=status.HTTP_201_CREATED)
def create_source(body: IncomeSourceIn, session: Session = Depends(get_session)) -> IncomeSourceOut:
    if body.default_account_id is not None:
        _into_or_422(session, body.default_account_id)
    if body.default_from_account_id is not None:
        _from_or_422(session, body.default_from_account_id)
    # The first source is the default whatever the body says: a single source must be pickable.
    first = session.scalar(select(func.count()).select_from(IncomeSource)) == 0
    src = IncomeSource(
        name=body.name.strip(),
        hourly_rate=body.hourly_rate,
        currency=body.currency,
        is_default=body.is_default or first,
        archived=body.archived,
        default_account_id=body.default_account_id,
        default_from_account_id=body.default_from_account_id,
    )
    if src.is_default:
        _clear_default(session, None)
    session.add(src)
    session.commit()
    session.refresh(src)
    return _source_out(src, 0)


@router.put("/sources/{source_id}", response_model=IncomeSourceOut)
def update_source(
    source_id: int, body: IncomeSourceUpdate, session: Session = Depends(get_session)
) -> IncomeSourceOut:
    src = session.get(IncomeSource, source_id)
    if not src:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "income source not found")
    if body.name is not None:
        src.name = body.name.strip()
    if body.hourly_rate is not None:
        src.hourly_rate = body.hourly_rate
    if body.currency is not None:
        src.currency = body.currency
    if "default_account_id" in body.model_fields_set:
        if body.default_account_id is not None:
            _into_or_422(session, body.default_account_id, keep=src.default_account_id)
        src.default_account_id = body.default_account_id
    if "default_from_account_id" in body.model_fields_set:
        if body.default_from_account_id is not None:
            _from_or_422(session, body.default_from_account_id, keep=src.default_from_account_id)
        src.default_from_account_id = body.default_from_account_id
    if body.archived is not None:
        src.archived = body.archived
        if body.archived:
            src.is_default = False
    if body.is_default is not None:
        if body.is_default:
            _clear_default(session, src)
            src.archived = False
        src.is_default = body.is_default
    session.commit()
    session.refresh(src)
    return _source_out(src, _block_counts(session).get(src.id, 0))


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: int, session: Session = Depends(get_session)) -> Response:
    """Delete a source nothing bills to. One with blocks or payouts is a 409: archive it."""
    src = session.get(IncomeSource, source_id)
    if not src:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "income source not found")
    has_payouts = session.scalar(
        select(func.count()).select_from(FreelancePayout).where(FreelancePayout.source_id == src.id)
    )
    if _block_counts(session).get(src.id, 0) or has_payouts:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "this source has blocks or payouts billed to it; archive it instead of deleting it",
        )
    session.delete(src)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- accounts --------------------------------------------------------------


def _payout_counts(session: Session) -> dict[int, int]:
    """How many payouts use each account, on either side (one that uses it twice counts once)."""
    counts: dict[int, int] = defaultdict(int)
    for into, sent_from in session.execute(
        select(FreelancePayout.account_id, FreelancePayout.from_account_id)
    ):
        for account_id in {into, sent_from} - {None}:
            counts[account_id] += 1
    return counts


def _is_a_default(session: Session, account_id: int) -> bool:
    """Whether a source names the account as its "Paid into" or its "Paid from"."""
    return (
        session.scalar(
            select(func.count())
            .select_from(IncomeSource)
            .where(
                (IncomeSource.default_account_id == account_id)
                | (IncomeSource.default_from_account_id == account_id)
            )
        )
        > 0
    )


def _account_out(a: Account, payouts: int) -> AccountOut:
    return AccountOut(
        id=a.id,
        name=a.name,
        currency=a.currency,
        kind=a.kind,
        role=a.role,
        is_default=bool(a.is_default),
        archived=bool(a.archived),
        created_at=a.created_at,
        payouts=payouts,
    )


def _refuse_duplicate_account(session: Session, name: str, own_id: int | None = None) -> None:
    wanted = name.casefold()
    for other in session.scalars(select(Account)):
        if other.id != own_id and other.name.casefold() == wanted:
            raise HTTPException(status.HTTP_409_CONFLICT, "an account with that name exists")


def _clear_default_account(session: Session, keep: Account | None) -> None:
    for other in session.scalars(select(Account).where(Account.is_default.is_(True))):
        if other is not keep:
            other.is_default = False


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(session: Session = Depends(get_session)) -> list[AccountOut]:
    """Every account, archived ones included (flagged); default first."""
    counts = _payout_counts(session)
    rows = session.scalars(select(Account).order_by(Account.is_default.desc(), Account.id))
    return [_account_out(a, counts.get(a.id, 0)) for a in rows]


@router.post("/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(body: AccountIn, session: Session = Depends(get_session)) -> AccountOut:
    _refuse_duplicate_account(session, body.name)
    account = Account(
        name=body.name,
        currency=body.currency,
        kind=body.kind,
        role=body.role,
        is_default=body.is_default and not body.archived,
        archived=body.archived,
    )
    if account.is_default:
        _clear_default_account(session, None)
    session.add(account)
    session.commit()
    session.refresh(account)
    return _account_out(account, 0)


@router.put("/accounts/{account_id}", response_model=AccountOut)
def update_account(
    account_id: int, body: AccountUpdate, session: Session = Depends(get_session)
) -> AccountOut:
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
    used = _payout_counts(session).get(account.id, 0)
    if (
        body.currency is not None
        and body.currency != account.currency
        and (used or _is_a_default(session, account.id))
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "this account is in use, in its currency; open another account instead",
        )
    if body.name is not None:
        _refuse_duplicate_account(session, body.name, own_id=account.id)
        account.name = body.name
    if body.currency is not None:
        account.currency = body.currency
    if body.kind is not None:
        account.kind = body.kind
    if body.role is not None:
        account.role = body.role
    if body.archived is not None:
        account.archived = body.archived
        if body.archived:
            account.is_default = False
    if body.is_default is not None:
        if body.is_default:
            _clear_default_account(session, account)
            account.archived = False
        account.is_default = body.is_default
    session.commit()
    session.refresh(account)
    return _account_out(account, used)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: int, session: Session = Depends(get_session)) -> Response:
    """Delete an account nothing uses. One a payout used, on either side, or that a source names
    as its "Paid into" or "Paid from" is a 409: archive it."""
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
    if _payout_counts(session).get(account.id, 0) or _is_a_default(session, account.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "this account is in use by payouts or a source; archive it instead of deleting it",
        )
    session.delete(account)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- blocks ----------------------------------------------------------------


def _lines_of_blocks(session: Session, blocks: list[FreelanceBlock]) -> dict[int, freelance.Line]:
    """The money line of each block, computed once for the span the blocks cover."""
    if not blocks:
        return {}
    lines = freelance.money_lines(session, min(b.date for b in blocks), max(b.date for b in blocks))
    return {ln.block_id: ln for ln in lines if ln.block_id is not None}


def block_out(b: FreelanceBlock, line: freelance.Line | None) -> FreelanceBlockOut:
    eur = b.amount_eur
    effective = None if line is None or line.eur is None else money(line.eur)
    return FreelanceBlockOut(
        id=b.id,
        date=b.date,
        source_id=b.source_id,
        source_name=b.source.name,
        minutes=b.minutes,
        hours=b.hours,
        start_time=b.start_time,
        end_time=b.end_time,
        notes=b.notes,
        rate=b.rate,
        currency=b.currency,
        fx_rate=b.fx_rate,
        amount=money(b.amount),
        amount_eur=None if eur is None else money(eur),
        effective_eur=effective,
        payout_id=None if line is None else line.payout_id,
    )


def _block_out_now(session: Session, b: FreelanceBlock) -> FreelanceBlockOut:
    return block_out(b, _lines_of_blocks(session, [b]).get(b.id))


def _fx_for(currency: str, on: date) -> float | None:
    """The rate of a date (units per EUR), asked for exactly once, when a block in a currency
    other than EUR is saved."""
    answer = currencies.rate_for(currency, on)
    return answer["per_eur"] if answer["available"] else None


def _source_or_422(session: Session, source_id: int) -> IncomeSource:
    src = session.get(IncomeSource, source_id)
    if src is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown income source")
    return src


@router.get("/blocks", response_model=list[FreelanceBlockOut])
def list_blocks(
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    year: int | None = None,
    session: Session = Depends(get_session),
) -> list[FreelanceBlockOut]:
    stmt = select(FreelanceBlock).order_by(FreelanceBlock.date, FreelanceBlock.id)
    if year is not None:
        stmt = stmt.where(
            FreelanceBlock.date >= date(year, 1, 1), FreelanceBlock.date <= date(year, 12, 31)
        )
    if from_:
        stmt = stmt.where(FreelanceBlock.date >= from_)
    if to:
        stmt = stmt.where(FreelanceBlock.date <= to)
    blocks = list(session.scalars(stmt))
    lines = _lines_of_blocks(session, blocks)
    return [block_out(b, lines.get(b.id)) for b in blocks]


@router.post("/blocks", response_model=FreelanceBlockOut, status_code=status.HTTP_201_CREATED)
def create_block(
    body: FreelanceBlockIn, session: Session = Depends(get_session)
) -> FreelanceBlockOut:
    src = _source_or_422(session, body.source_id)
    block = FreelanceBlock(
        date=body.date,
        source_id=src.id,
        minutes=body.minutes,
        start_time=body.start_time,
        end_time=body.end_time,
        notes=(body.notes or "").strip() or None,
        rate=body.rate if body.rate is not None else src.hourly_rate,
        currency=src.currency,
        fx_rate=None,
    )
    if src.currency != "EUR":
        block.fx_rate = (
            body.fx_rate if body.fx_rate is not None else _fx_for(src.currency, body.date)
        )
    session.add(block)
    session.commit()
    session.refresh(block)
    return _block_out_now(session, block)


@router.get("/blocks/{block_id}", response_model=FreelanceBlockOut)
def get_block(block_id: int, session: Session = Depends(get_session)) -> FreelanceBlockOut:
    block = session.get(FreelanceBlock, block_id)
    if not block:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "block not found")
    return _block_out_now(session, block)


@router.put("/blocks/{block_id}", response_model=FreelanceBlockOut)
def update_block(
    block_id: int, body: FreelanceBlockUpdate, session: Session = Depends(get_session)
) -> FreelanceBlockOut:
    block = session.get(FreelanceBlock, block_id)
    if not block:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "block not found")
    src = _source_or_422(session, body.source_id)
    source_changed = src.id != block.source_id
    date_changed = body.date != block.date
    block.date = body.date
    block.source_id = src.id
    block.minutes = body.minutes
    block.start_time = body.start_time
    block.end_time = body.end_time
    block.notes = (body.notes or "").strip() or None
    if body.rate is not None:
        block.rate = body.rate
    elif source_changed:
        block.rate = src.hourly_rate
    if source_changed:
        block.currency = src.currency
    if block.currency != "EUR":
        if body.fx_rate is not None:
            block.fx_rate = body.fx_rate
        elif source_changed or date_changed or block.fx_rate is None:
            block.fx_rate = _fx_for(block.currency, body.date)
    else:
        block.fx_rate = None
    session.commit()
    session.refresh(block)
    return _block_out_now(session, block)


@router.delete("/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_block(block_id: int, session: Session = Depends(get_session)) -> Response:
    block = session.get(FreelanceBlock, block_id)
    if not block:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "block not found")
    session.delete(block)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- payouts ---------------------------------------------------------------


def _payout_outs(session: Session, payouts: list[FreelancePayout]) -> list[FreelancePayoutOut]:
    """Payouts with the estimate of their week's blocks, read in one query for the lot."""
    weeks: dict[tuple[int, date], list[FreelanceBlock]] = defaultdict(list)
    if payouts:
        first = min(p.week_start for p in payouts)
        last = max(week_end_of(p.week_start) for p in payouts)
        for b in freelance.blocks_between(session, first, last):
            weeks[(b.source_id, freelance.monday_of(b.date))].append(b)
    return [_payout_out(p, weeks.get((p.source_id, p.week_start), [])) for p in payouts]


def _payout_out(p: FreelancePayout, blocks: list[FreelanceBlock]) -> FreelancePayoutOut:
    eur = p.amount_eur
    billed = freelance.billed_for(p, blocks)
    return FreelancePayoutOut(
        blocks=billed.blocks,
        minutes=billed.minutes,
        estimate_eur=billed.estimate_eur,
        estimate_amount=billed.amount,
        id=p.id,
        source_id=p.source_id,
        week_start=p.week_start,
        week_end=week_end_of(p.week_start),
        amount=p.amount,
        currency=p.currency,
        fx_rate=p.fx_rate,
        note=p.note,
        amount_eur=None if eur is None else money(eur),
        account_id=p.account_id,
        account_name=None if p.account is None else p.account.name,
        rate_source=p.rate_source,
        rate_date=p.rate_date,
        billed_amount=billed.amount,
        billed_currency=billed.currency,
        billed_eur=billed.eur,
        fx_cost_eur=billed.fx_cost_eur,
        effective_rate=billed.effective_rate,
        sent_amount=p.sent_amount,
        sent_currency=p.sent_currency,
        from_account_id=p.from_account_id,
        from_account_name=None if p.from_account is None else p.from_account.name,
        sent_gap=freelance.sent_gap(p, billed),
    )


def _source_or_404(session: Session, source_id: int) -> IncomeSource:
    src = session.get(IncomeSource, source_id)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "income source not found")
    return src


def _refuse_duplicate_week(
    session: Session, source_id: int, week_start: date, own_id: int | None = None
) -> None:
    stmt = select(FreelancePayout.id).where(
        FreelancePayout.source_id == source_id, FreelancePayout.week_start == week_start
    )
    found = session.scalar(stmt)
    if found is not None and found != own_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this source already has a payout for that week"
        )


@router.get("/payouts", response_model=list[FreelancePayoutOut])
def list_payouts(
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    source_id: int | None = None,
    session: Session = Depends(get_session),
) -> list[FreelancePayoutOut]:
    """Payouts whose week starts within [from, to], oldest week first."""
    stmt = select(FreelancePayout).order_by(FreelancePayout.week_start, FreelancePayout.id)
    if from_:
        stmt = stmt.where(FreelancePayout.week_start >= from_)
    if to:
        stmt = stmt.where(FreelancePayout.week_start <= to)
    if source_id is not None:
        stmt = stmt.where(FreelancePayout.source_id == source_id)
    return _payout_outs(session, list(session.scalars(stmt)))


def _settle_payout(
    session: Session, payout: FreelancePayout, src: IncomeSource, body: FreelancePayoutIn
) -> None:
    """Fill a payout's currency, rate and their provenance from the body.

    The currency is the account's when there is one, else the source's. In a currency other
    than EUR the euro value comes from, in order: `eur_amount` (typed by hand), `fx_rate`
    (typed by hand), the ECB's or CoinGecko's rate of `paid_on` (default: the week's Sunday).
    A stored rate is kept on an update that changes nothing it depends on; with no rate
    available the payout is saved with `fx_rate` None and counts as missing.
    """
    new = payout.id is None
    old_account, old_currency = payout.account_id, payout.currency
    account = (
        None
        if body.account_id is None
        else _into_or_422(session, body.account_id, keep=old_account)
    )
    if account is not None:
        currency = account.currency
    elif not new and old_account is None and payout.source_id == src.id:
        currency = old_currency  # a payout from before accounts keeps its own
    else:
        currency = src.currency
    paid_on = body.paid_on or week_end_of(body.week_start)
    unchanged = (
        not new
        and body.paid_on is None
        and body.week_start == payout.week_start
        and payout.source_id == src.id
        and (None if account is None else account.id) == old_account
        and currency == old_currency
    )
    payout.account_id = None if account is None else account.id
    payout.currency = currency
    if currency == "EUR":
        payout.fx_rate = None
        payout.rate_source = None
        if account is None:
            payout.rate_date = None
        elif not unchanged or payout.rate_date is None:
            payout.rate_date = paid_on
        return
    if body.eur_amount is not None:
        payout.fx_rate = body.amount / body.eur_amount
        payout.rate_source, payout.rate_date = "manual", paid_on
    elif body.fx_rate is not None:
        payout.fx_rate = body.fx_rate
        payout.rate_source, payout.rate_date = "manual", paid_on
    elif new or not unchanged or payout.fx_rate is None:
        found = currencies.rate_for(currency, paid_on)
        if found["available"]:
            payout.fx_rate = found["per_eur"]
            payout.rate_source = found["source"]
            payout.rate_date = date.fromisoformat(found["date"])
        else:
            payout.fx_rate, payout.rate_source, payout.rate_date = None, None, paid_on


def _settle_sent(
    session: Session, payout: FreelancePayout, src: IncomeSource, body: FreelancePayoutIn
) -> None:
    """Fill what was SENT from the body (the arrived side is `_settle_payout`'s).

    Nothing sent given: the payout is "as billed" and all three fields are cleared. An account
    gives the currency, and a ``sent_currency`` that disagrees with it is a 422; a bare currency
    stands for itself; an amount alone is in the source's currency. An amount is needed with any
    of them. One place, deterministic.
    """
    old_from = payout.from_account_id
    if body.sent_amount is None:
        if body.from_account_id is not None or body.sent_currency is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "give sent_amount with the sent side"
            )
        payout.sent_amount = payout.sent_currency = payout.from_account_id = None
        return
    sent_from = (
        None
        if body.from_account_id is None
        else _from_or_422(session, body.from_account_id, keep=old_from)
    )
    if sent_from is not None:
        if body.sent_currency is not None and body.sent_currency != sent_from.currency:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "sent_currency is not the currency of the account it was sent from",
            )
        currency = sent_from.currency
    else:
        currency = body.sent_currency or src.currency
    payout.sent_amount = body.sent_amount
    payout.sent_currency = currency
    payout.from_account_id = None if sent_from is None else sent_from.id


@router.get("/rate")
def get_rate(
    from_: str = Query(..., alias="from", description="The currency of one unit."),
    to: str = Query(..., description="The currency the answer is in."),
    on: date = Query(..., description="The day the rate is of."),
) -> dict:
    """Units of ``to`` for one unit of ``from`` on a day, through the same rates as a payout
    (the ECB's, a coin's): `{"rate": 0.8957}`, or `{"rate": null}` when there is none."""
    for code in (from_, to):
        if not currencies.is_known(code):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown currency {code}")
    return {"rate": currencies.cross_rate(from_, to, on)}


@router.post("/payouts", response_model=FreelancePayoutOut, status_code=status.HTTP_201_CREATED)
def create_payout(
    body: FreelancePayoutIn, session: Session = Depends(get_session)
) -> FreelancePayoutOut:
    src = _source_or_404(session, body.source_id)
    _refuse_duplicate_week(session, src.id, body.week_start)
    payout = FreelancePayout(
        source_id=src.id,
        week_start=body.week_start,
        amount=body.amount,
        currency=src.currency,
        fx_rate=None,
        note=(body.note or "").strip() or None,
    )
    _settle_payout(session, payout, src, body)
    _settle_sent(session, payout, src, body)
    session.add(payout)
    session.commit()
    session.refresh(payout)
    return _payout_outs(session, [payout])[0]


def _amount_text(amount: float, currency: str) -> str:
    """An amount with its currency's decimals: cents for euros, eight places for a coin."""
    return f"{currencies.quantize(amount, currency):.{currencies.decimals(currency)}f}"


PAYOUT_CSV_COLUMNS = [
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


@router.get("/payouts.csv")
def payouts_csv(session: Session = Depends(get_session)) -> Response:
    """One row per payout, oldest week first — the payouts' side of the CSV export. Declared
    before ``/payouts/{payout_id}`` so the path is not read as an id."""
    payouts = list(
        session.scalars(
            select(FreelancePayout).order_by(FreelancePayout.week_start, FreelancePayout.id)
        )
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(PAYOUT_CSV_COLUMNS)
    names = {p.id: p.source.name for p in payouts}
    for o in _payout_outs(session, payouts):
        writer.writerow(
            [
                o.week_start.isoformat(),
                o.week_end.isoformat(),
                names[o.id],
                o.currency,
                _amount_text(o.amount, o.currency),
                "" if o.fx_rate is None else repr(float(o.fx_rate)),
                "" if o.amount_eur is None else f"{o.amount_eur:.2f}",
                _amount_text(o.estimate_amount, o.billed_currency),
                "" if o.estimate_eur is None else f"{o.estimate_eur:.2f}",
                o.blocks,
                f"{o.minutes / 60:.2f}",
                (o.note or "").replace("\n", " "),
                o.account_name or "",
                o.rate_source or "",
                "" if o.rate_date is None else o.rate_date.isoformat(),
                _amount_text(o.billed_amount, o.billed_currency),
                "" if o.billed_eur is None else f"{o.billed_eur:.2f}",
                "" if o.fx_cost_eur is None else f"{o.fx_cost_eur:.2f}",
                "" if o.sent_amount is None else _amount_text(o.sent_amount, o.sent_currency),
                o.sent_currency or "",
                o.from_account_name or "",
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="kronos_freelance_payouts.csv"'},
    )


@router.get("/payouts/{payout_id}", response_model=FreelancePayoutOut)
def get_payout(payout_id: int, session: Session = Depends(get_session)) -> FreelancePayoutOut:
    payout = session.get(FreelancePayout, payout_id)
    if not payout:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "payout not found")
    return _payout_outs(session, [payout])[0]


@router.put("/payouts/{payout_id}", response_model=FreelancePayoutOut)
def update_payout(
    payout_id: int, body: FreelancePayoutIn, session: Session = Depends(get_session)
) -> FreelancePayoutOut:
    payout = session.get(FreelancePayout, payout_id)
    if not payout:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "payout not found")
    src = _source_or_404(session, body.source_id)
    _refuse_duplicate_week(session, src.id, body.week_start, own_id=payout.id)
    _settle_payout(session, payout, src, body)
    _settle_sent(session, payout, src, body)
    payout.source_id = src.id
    payout.week_start = body.week_start
    payout.amount = body.amount
    payout.note = (body.note or "").strip() or None
    session.commit()
    session.refresh(payout)
    return _payout_outs(session, [payout])[0]


@router.delete("/payouts/{payout_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payout(payout_id: int, session: Session = Depends(get_session)) -> Response:
    payout = session.get(FreelancePayout, payout_id)
    if not payout:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "payout not found")
    session.delete(payout)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- tax inputs per year -----------------------------------------------------


def _tax_year_out(session: Session, year: int) -> FreelanceTaxYearOut:
    t = freelance.tax_inputs_for(session, year, get_country(session))
    r = tax.rules_for(year)
    return FreelanceTaxYearOut(
        year=year,
        salary_annual=t.salary_annual,
        tarifa_plana=t.tarifa_plana,
        inicio_actividad=t.inicio_actividad,
        set_aside_share=t.set_aside_share,
        gestoria_annual=t.gestoria_annual,
        other_expenses=t.other_expenses,
        inherited_from=t.inherited_from,
        is_default=t.is_default,
        fiscal_year=r.year,
        region=r.region_name,
    )


@router.get("/tax-years", response_model=list[FreelanceTaxYearOut])
def list_tax_years(session: Session = Depends(get_session)) -> list[FreelanceTaxYearOut]:
    """The years with inputs of their own, oldest first."""
    years = session.scalars(select(FreelanceTaxYear.year).order_by(FreelanceTaxYear.year))
    return [_tax_year_out(session, y) for y in years]


@router.get("/tax-years/{year}", response_model=FreelanceTaxYearOut)
def read_tax_year(year: int, session: Session = Depends(get_session)) -> FreelanceTaxYearOut:
    """The inputs in force for `year`: its own, the latest earlier year's, or the defaults."""
    return _tax_year_out(session, year)


@router.put("/tax-years/{year}", response_model=FreelanceTaxYearOut)
def write_tax_year(
    year: int, body: FreelanceTaxYearIn, session: Session = Depends(get_session)
) -> FreelanceTaxYearOut:
    if body.year != year:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "year in body and URL differ")
    row = session.get(FreelanceTaxYear, year)
    if row is None:
        row = FreelanceTaxYear(year=year)
        session.add(row)
    row.salary_annual = body.salary_annual
    row.tarifa_plana = body.tarifa_plana
    row.inicio_actividad = body.inicio_actividad
    row.set_aside_share = body.set_aside_share
    row.gestoria_annual = body.gestoria_annual
    row.other_expenses = body.other_expenses
    session.commit()
    return _tax_year_out(session, year)


@router.delete("/tax-years/{year}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tax_year(year: int, session: Session = Depends(get_session)) -> Response:
    """Drop a year's own inputs so it inherits the latest earlier year's again."""
    row = session.get(FreelanceTaxYear, year)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no inputs of its own for that year")
    session.delete(row)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- the year and the calculator --------------------------------------------


@router.get("/summary")
def summary(
    year: int | None = Query(None, description="Calendar year; defaults to the current one."),
    today: date | None = Query(None, description="Override 'today' for testing."),
    session: Session = Depends(get_session),
) -> dict:
    """The year's freelance picture: totals, this week and month, per month, per source,
    the four 130s, the projection to Dec 31 and its tax figures.

    The ECB (or CoinGecko) is asked only when the projection needs a rate it has nowhere else
    (a default source not in euros, before the first block of the year) — on this request,
    never on a timer.
    """
    today = today or local_today()
    year = year or today.year
    latest: float | None = None
    src = freelance.default_source(session)
    if src is not None and src.currency != "EUR":
        has_blocks = session.scalar(
            select(func.count())
            .select_from(FreelanceBlock)
            .where(
                FreelanceBlock.date >= date(year, 1, 1), FreelanceBlock.date <= date(year, 12, 31)
            )
        )
        if not has_blocks:
            if src.currency == "USD":
                answer = fx.latest()
                latest = answer["usd_per_eur"] if answer["available"] else None
            else:
                answer = currencies.rate_for(src.currency, today)
                latest = answer["per_eur"] if answer["available"] else None
    return freelance.year_summary(
        session,
        year,
        today,
        hours_per_week=get_freelance_hours_per_week(session),
        days_off=get_freelance_days_off(session),
        latest_usd_per_eur=latest,
        country=get_country(session),
    )


@router.post("/calc")
def calc(body: FreelanceCalcIn) -> dict:
    """The calculator: hourly ⇄ daily ⇄ net yearly with every assumption in the body.

    Pure: reads nothing from the database, so the browser can send whatever it shows.
    """
    params = tax.TaxParams(
        gestoria_annual=body.gestoria_annual,
        other_expenses=body.other_expenses,
        hours_per_day=body.hours_per_day,
        salary_annual=body.salary_annual,
        tarifa_plana=body.tarifa_plana,
        inicio_actividad=body.inicio_actividad,
    )
    return freelance.calculate(
        mode=body.mode,
        value=body.value,
        currency=body.currency,
        fx_rate=body.fx_rate,
        billable_days=body.billable_days,
        hours_per_day=body.hours_per_day,
        params=params,
        year=body.year,
        country=body.country,
        set_aside_share=body.set_aside_share,
    )


# ---------- export ---------------------------------------------------------------------

CSV_COLUMNS = [
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


@router.get("/export.csv")
def export_csv(session: Session = Depends(get_session)) -> Response:
    """One row per block, oldest first — the freelance side of the CSV export."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    account_names = {a.id: a.name for a in session.scalars(select(Account))}
    for b in session.scalars(
        select(FreelanceBlock).order_by(FreelanceBlock.date, FreelanceBlock.id)
    ):
        eur = b.amount_eur
        writer.writerow(
            [
                b.date.isoformat(),
                b.source.name,
                f"{b.minutes / 60:.2f}",
                b.start_time or "",
                b.end_time or "",
                repr(float(b.rate)),
                b.currency,
                "" if b.fx_rate is None else repr(float(b.fx_rate)),
                f"{money(b.amount):.2f}",
                "" if eur is None else f"{money(eur):.2f}",
                (b.notes or "").replace("\n", " "),
                account_names.get(b.source.default_account_id, ""),
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="kronos_freelance.csv"'},
    )
