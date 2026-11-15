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
from sqlalchemy.orm import Session, selectinload

from app.database import get_session
from app.models import (
    Account,
    FreelanceBlock,
    FreelancePayout,
    FreelanceTaxYear,
    IncomeSource,
    PayoutLeg,
)
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
    FreelancePayoutPreview,
    FreelancePayoutPreviewIn,
    FreelanceTaxYearIn,
    FreelanceTaxYearOut,
    IncomeSourceIn,
    IncomeSourceOut,
    IncomeSourceUpdate,
    OrderIn,
    PayoutLegOut,
    PayoutLegPreview,
    week_end_of,
)
from app.services import chains, currencies, freelance, fx, tax
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
        chain=[c.account_id for c in s.chain],
        blocks=blocks,
        position=s.position,
    )


def _clear_default(session: Session, keep: IncomeSource | None) -> None:
    for other in session.scalars(select(IncomeSource).where(IncomeSource.is_default.is_(True))):
        if other is not keep:
            other.is_default = False


@router.get("/sources", response_model=list[IncomeSourceOut])
def list_sources(session: Session = Depends(get_session)) -> list[IncomeSourceOut]:
    """Every source, archived ones included (the picker filters them out), in the order the
    user set; a new one goes last and the default stays where it is."""
    counts = _block_counts(session)
    rows = session.scalars(select(IncomeSource).order_by(IncomeSource.position, IncomeSource.id))
    return [_source_out(s, counts.get(s.id, 0)) for s in rows]


# Declared before "/sources/{source_id}" so that "order" is not read as an id.
@router.put("/sources/order", response_model=list[IncomeSourceOut])
def set_source_order(
    body: OrderIn, session: Session = Depends(get_session)
) -> list[IncomeSourceOut]:
    chains.set_order(session, IncomeSource, body.ids)
    session.commit()
    return list_sources(session)


@router.post("/sources", response_model=IncomeSourceOut, status_code=status.HTTP_201_CREATED)
def create_source(body: IncomeSourceIn, session: Session = Depends(get_session)) -> IncomeSourceOut:
    chains.check_chain(session, body.chain or [])
    # The first source is the default whatever the body says: a single source must be pickable.
    first = session.scalar(select(func.count()).select_from(IncomeSource)) == 0
    src = IncomeSource(
        name=body.name.strip(),
        hourly_rate=body.hourly_rate,
        currency=body.currency,
        is_default=body.is_default or first,
        archived=body.archived,
        position=chains.next_position(session, IncomeSource),
    )
    if src.is_default:
        _clear_default(session, None)
    session.add(src)
    if body.chain:
        session.flush()
        chains.set_chain(session, src, body.chain)
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
    if body.chain is not None:
        chains.check_chain(session, body.chain)
        chains.set_chain(session, src, body.chain)
    if body.name is not None:
        src.name = body.name.strip()
    if body.hourly_rate is not None:
        src.hourly_rate = body.hourly_rate
    if body.currency is not None:
        src.currency = body.currency
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


def _account_out(a: Account, payouts: int) -> AccountOut:
    return AccountOut(
        id=a.id,
        name=a.name,
        currency=a.currency,
        kind=a.kind,
        is_default=bool(a.is_default),
        archived=bool(a.archived),
        created_at=a.created_at,
        payouts=payouts,
        position=a.position,
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
    """Every account, archived ones included (flagged), in the order the user set; a new one
    goes last and the default stays where it is."""
    counts = chains.leg_counts(session)
    rows = session.scalars(select(Account).order_by(Account.position, Account.id))
    return [_account_out(a, counts.get(a.id, 0)) for a in rows]


# Declared before "/accounts/{account_id}" so that "order" is not read as an id.
@router.put("/accounts/order", response_model=list[AccountOut])
def set_account_order(body: OrderIn, session: Session = Depends(get_session)) -> list[AccountOut]:
    chains.set_order(session, Account, body.ids)
    session.commit()
    return list_accounts(session)


@router.post("/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(body: AccountIn, session: Session = Depends(get_session)) -> AccountOut:
    _refuse_duplicate_account(session, body.name)
    account = Account(
        name=body.name,
        currency=body.currency,
        kind=body.kind,
        is_default=body.is_default and not body.archived,
        archived=body.archived,
        position=chains.next_position(session, Account),
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
    used = chains.leg_counts(session).get(account.id, 0)
    if (
        body.currency is not None
        and body.currency != account.currency
        and chains.account_in_use(session, account.id)
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
    if body.archived is not None:
        account.archived = body.archived
        if body.archived:
            account.is_default = False
            chains.remove_account_from_chains(session, account.id)
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
    """Delete an account nothing uses. One in a payout's legs is a 409: archive it. One that is
    only in source chains goes, and leaves those chains with their positions closed up."""
    account = session.get(Account, account_id)
    if not account:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
    if chains.account_in_use(session, account.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "this account is in use by payouts; archive it instead of deleting it",
        )
    chains.remove_account_from_chains(session, account.id)
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
    return FreelancePayoutOut(**_payout_fields(p, blocks))


def _payout_fields(p: FreelancePayout, blocks: list[FreelanceBlock]) -> dict:
    """Every field of a payout's answer, from the payout and the blocks of its week. A preview
    builds its own answer from the same fields."""
    eur = p.amount_eur
    billed = freelance.billed_for(p, blocks)
    return dict(
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
        legs=[
            PayoutLegOut(
                position=leg.position,
                account_id=leg.account.id,  # not leg.account_id: a preview's leg is not flushed
                account_name=leg.account.name,
                currency=leg.account.currency,
                amount=leg.amount,
                fixed=bool(leg.fixed),
            )
            for leg in p.legs
        ],
        gap=chains.gap(p, billed),
        gap_currency=billed.currency,
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
    stmt = (
        select(FreelancePayout)
        .options(selectinload(FreelancePayout.legs))
        .order_by(FreelancePayout.week_start, FreelancePayout.id)
    )
    if from_:
        stmt = stmt.where(FreelancePayout.week_start >= from_)
    if to:
        stmt = stmt.where(FreelancePayout.week_start <= to)
    if source_id is not None:
        stmt = stmt.where(FreelancePayout.source_id == source_id)
    return _payout_outs(session, list(session.scalars(stmt)))


def _settle_payout(
    session: Session,
    payout: FreelancePayout,
    src: IncomeSource,
    account: Account,
    amount: float,
    body: FreelancePayoutIn,
) -> None:
    """Fill a payout's account, currency, rate and their provenance from its last leg (`account`
    and `amount`) and the body.

    The currency is the account's. In a currency other than EUR the euro value comes from, in
    order: `eur_amount` (typed by hand), the ECB's or CoinGecko's rate of `paid_on` (default: the
    week's Sunday). A stored rate is kept on an update that changes nothing it depends on; with no
    rate available the payout is saved with `fx_rate` None and counts as missing.
    """
    new = payout.id is None
    old_account, old_currency = payout.account_id, payout.currency
    currency = account.currency
    paid_on = body.paid_on or week_end_of(body.week_start)
    unchanged = (
        not new
        and body.paid_on is None
        and body.week_start == payout.week_start
        and payout.source_id == src.id
        and account.id == old_account
        and currency == old_currency
    )
    payout.account_id = account.id
    payout.currency = currency
    if currency == "EUR":
        payout.fx_rate = None
        payout.rate_source = None
        if not unchanged or payout.rate_date is None:
            payout.rate_date = paid_on
        return
    if body.eur_amount is not None:
        payout.fx_rate = amount / body.eur_amount
        payout.rate_source, payout.rate_date = "manual", paid_on
    elif new or not unchanged or payout.fx_rate is None:
        found = currencies.rate_for(currency, paid_on)
        if found["available"]:
            payout.fx_rate = found["per_eur"]
            payout.rate_source = found["source"]
            payout.rate_date = date.fromisoformat(found["date"])
        else:
            payout.fx_rate, payout.rate_source, payout.rate_date = None, None, paid_on


def _settle_chain(
    session: Session,
    payout: FreelancePayout,
    src: IncomeSource,
    body: FreelancePayoutIn,
    lenient: bool = False,
) -> list[chains.Leg]:
    """Settle the legs, then give the payout the LAST leg's figures.

    The last leg's account and amount go through `_settle_payout`, which gives the payout its
    account, currency, rate and their provenance. A single leg on a source with no chain yet
    becomes its chain.

    `lenient` is the preview's: a leg that cannot be worked out comes back without an amount, and
    then the payout is left as it was (it has no figures to take). A save is never lenient.
    """
    legs = chains.settle_legs(
        session, payout, src, body.legs, body.paid_on, week_start=body.week_start, lenient=lenient
    )
    if any(leg.amount is None for leg in legs):
        return legs
    last = legs[-1]
    _settle_payout(session, payout, src, last.account, last.amount, body)
    payout.amount = last.amount
    if len(legs) == 1:
        chains.remember_chain(session, src, last.account)
    return legs


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
        amount=0.0,
        currency=src.currency,
        fx_rate=None,
        note=(body.note or "").strip() or None,
    )
    _settle_chain(session, payout, src, body)
    session.add(payout)
    session.commit()
    session.refresh(payout)
    return _payout_outs(session, [payout])[0]


def _amount_text(amount: float, currency: str) -> str:
    """An amount with its currency's decimals: cents for euros, eight places for a coin."""
    return f"{currencies.quantize(amount, currency):.{currencies.decimals(currency)}f}"


def _leg_cells(legs) -> list[str]:
    """The chain as twelve cells: account, amount and currency of each of four legs, in order;
    empty for a leg the payout does not have."""
    cells: list[str] = []
    for n in range(4):
        if n < len(legs):
            leg = legs[n]
            cells += [leg.account_name, _amount_text(leg.amount, leg.currency), leg.currency]
        else:
            cells += ["", "", ""]
    return cells


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
    *(f"{name}_{n}" for n in range(1, 5) for name in ("account", "amount", "currency")),
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
                *_leg_cells(o.legs),
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="kronos_freelance_payouts.csv"'},
    )


@router.post("/payouts/preview", response_model=FreelancePayoutPreview)
def preview_payout(
    body: FreelancePayoutPreviewIn, session: Session = Depends(get_session)
) -> FreelancePayoutPreview:
    """What a save of this body would answer, worked out and never saved. It runs the code of the
    save on a payout that is never committed (the session is rolled back whatever happens), so
    the figures are the save's to the cent. A leg that cannot be worked out has no amount and
    says why. With ``payout_id`` it is that saved payout being changed. Declared before
    ``/payouts/{payout_id}``, like ``payouts_csv``."""
    try:
        return _preview(session, body)
    finally:
        session.rollback()


def _preview(session: Session, body: FreelancePayoutPreviewIn) -> FreelancePayoutPreview:
    src = _source_or_404(session, body.source_id)
    note = (body.note or "").strip() or None
    if body.payout_id is None:
        payout = FreelancePayout(
            source_id=src.id,
            week_start=body.week_start,
            amount=0.0,
            currency=src.currency,
            note=note,
        )
    else:
        payout = session.get(FreelancePayout, body.payout_id)
        if payout is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "payout not found")
    legs = _settle_chain(session, payout, src, body, lenient=True)
    end = week_end_of(body.week_start)
    blocks = [
        b for b in freelance.blocks_between(session, body.week_start, end) if b.source_id == src.id
    ]
    if all(leg.amount is not None for leg in legs):
        payout.source_id, payout.week_start, payout.note = src.id, body.week_start, note
        shown = payout
    else:
        # no last amount: nothing of the payout's own can be told, only what the week and the
        # first leg say. A stand-in carries them through the same code as a saved payout.
        last = legs[-1].account
        shown = FreelancePayout(
            source_id=src.id,
            week_start=body.week_start,
            amount=0.0,
            currency=last.currency,
            note=note,
            rate_date=body.paid_on or end,
        )
        first = legs[0]
        shown.legs = [
            PayoutLeg(
                position=0,
                account=first.account,
                amount=0.0 if first.amount is None else first.amount,
                fixed=first.fixed,
            )
        ]
    shown.source = src
    shown.account = session.get(Account, shown.account_id) if shown.account_id else None
    fields = _payout_fields(shown, blocks)
    fields["id"] = body.payout_id
    fields["legs"] = [
        PayoutLegPreview(
            position=i,
            account_id=leg.account.id,
            account_name=leg.account.name,
            currency=leg.account.currency,
            amount=leg.amount,
            fixed=leg.fixed,
            problem=leg.problem,
        )
        for i, leg in enumerate(legs)
    ]
    if legs[-1].amount is None:
        last = legs[-1].account
        fields.update(
            amount=None,
            amount_eur=None,
            fx_cost_eur=None,
            effective_rate=None,
            account_id=last.id,
            account_name=last.name,
        )
    return FreelancePayoutPreview(**fields)


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
    _settle_chain(session, payout, src, body)
    payout.source_id = src.id
    payout.week_start = body.week_start
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
    # The account column is where the block's source usually ends up: the last of its chain.
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
                account_names.get(b.source.chain[-1].account_id, "") if b.source.chain else "",
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="kronos_freelance.csv"'},
    )
