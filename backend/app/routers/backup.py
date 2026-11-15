"""Backup and restore — full data portability.

GET  /api/backup   → download a self-contained JSON snapshot
POST /api/restore  → wipe current entries and reimport from snapshot

The backup format is intentionally simple (version 6):
{
  "version": 6,
  "exported_at": "<ISO-8601 UTC>",
  "settings": { "daily_target_hours": 8.0, "cumulative_start_date": "2025-01-01" },
  "entries": [
    { "date": "2025-03-10", "day_type": "work", "fraction": 1.0,
      "start_time": "09:00", "end_time": "17:30",
      "notes": null, "breaks": [{"break_minutes": 60, "start_time": null, "end_time": null}] },
    ...
  ],
  "plans": [
    { "date": "2025-12-24", "day_type": "vacation", "fraction": 1.0, "notes": "Christmas" },
    ...
  ],
  "accounts": [ { "id": 1, "name": "Deutsche Bank", "currency": "EUR", "kind": "bank", ... } ],
  "income_sources": [ { "id": 1, "name": "ACME", "hourly_rate": 90.0, "currency": "USD", ... } ],
  "freelance_blocks": [ { "date": "2026-03-02", "source_id": 1, "minutes": 120, ... } ],
  "freelance_tax_years": [ { "year": 2026, "salary_annual": 55000.0, ... } ],
  "freelance_payouts": [ { "source_id": 1, "week_start": "2026-03-02", "amount": 900.0, ... } ]
}

Version 6 drops what the chains replaced: no account ``role``, no source ``default_account_id`` /
``default_from_account_id``, no payout ``sent_amount`` / ``sent_currency`` / ``from_account_id``.
A file of an older version still restores and may hold them: the role is read and ignored, a
source's defaults become its chain when the file has none for it, and a payout's sent side and
arrival become its legs when the file has none for it, by the rule the migration that dropped
those columns used. A payout's account is always its last leg's.
Accounts (where a payout landed, each with a currency, with their ids) and, on a payout, its
account, where its rate came from and the day it is of ride in version 4 as optional keys: a file
without them restores no accounts and leaves the current ones alone.
Version 5 adds the chain of accounts and the hand-made order, and removes nothing (the older keys
stay): every account and every income source carries its ``position``; a source its ``chain``,
the account ids it is usually paid through, in order; a payout its ``legs``, a list of
``{account_id, amount, fixed}`` from the first account to the last, the last being what the payout
is worth (its amount and its account's currency are the payout's own). A restore takes them as the
file says and refuses with a 422 naming the payout's week or the source's name a leg or a chain
that names an unknown account, that has more than four accounts or one twice, or a last leg that
is not the payout's amount and currency. A file without them (versions 1 to 4, or a payout without
``legs`` or with an empty list) is given them by the rule the migration used: a payout's legs from
its account, its sent side and its amount (making a "USD account" for a side that has none), a
source's chain from "Paid from" then "Paid into" (once if the same, an archived account left out),
the positions in the order shown before (the default first, then by id). So a restore never leaves
a payout without legs.
Version 4 adds the freelance payouts: what a source paid for an ISO week, in the source's
currency, with the exchange rate it was saved with; they reference the sources' ids like the
blocks do, and a file of an older version restores none (they are data, so they are wiped).
Version 3 adds the freelance side: the income sources (with their ids, which the blocks
reference), the hour blocks with the rate, currency and exchange rate they were saved with,
and the tax inputs per year; the settings gain the projection's two numbers. Version 2 added
``fraction`` to every entry — partial leave days also carry the hours worked. Older files still
restore (no fraction → whole day, no freelance → none); an older Kronos refuses a newer file
rather than silently dropping what it does not know.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from datetime import date as date_

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import (  # Break imported for explicit pre-delete
    Account,
    Break,
    FreelanceBlock,
    FreelancePayout,
    FreelanceTaxYear,
    IncomeSource,
    PayoutLeg,
    Plan,
    SourceAccount,
    WorkEntry,
)
from app.schemas import (
    BACKUP_VERSION,
    SUPPORTED_BACKUP_VERSIONS,
    ConfigOut,
    DailyTargetRow,
    FreelancePayoutBackup,
    RestoreIn,
)
from app.services import chains, countries, numbers
from app.services.computations import DailyTargetSchedule
from app.services.settings import (
    PROFILE_EMPLOYER,
    PROFILE_EXTRA,
    PROFILE_NAME,
    get_country,
    get_cumulative_start_date,
    get_daily_target_hours,
    get_daily_target_schedule,
    get_freelance_days_off,
    get_freelance_hours_per_week,
    get_number_format,
    get_profile,
    set_country,
    set_cumulative_start_date,
    set_daily_target_hours,
    set_daily_target_schedule,
    set_freelance_days_off,
    set_freelance_hours_per_week,
    set_number_format,
    set_profile_field,
)
from app.services.views import entry_from_body

router = APIRouter(prefix="/api", tags=["backup"])


def _refuse(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def _positions(rows: list[tuple[int, bool, int | None]]) -> dict[int, int]:
    """id -> position for a list of (id, is_default, position in the file). A file that gives
    every row its position is taken as it says; otherwise the rows are numbered from 0 in the
    order they were shown before positions existed: the default first, then by id."""
    if all(position is not None for _, _, position in rows):
        return {row_id: position for row_id, _, position in rows}
    ordered = sorted(rows, key=lambda r: (not r[1], r[0]))
    return {row_id: i for i, (row_id, _, _) in enumerate(ordered)}


def _check_legs(
    p: FreelancePayoutBackup,
    account_info: dict[int, tuple[str, bool]],
    known_accounts: set[int],
) -> None:
    """422, naming the payout's week, unless its legs (when it has any) are a chain: at most four
    known accounts, none twice, the last one being the payout's own amount and currency."""
    if not p.legs:
        return
    week = p.week_start.isoformat()
    if len(p.legs) > chains.MAX_LEGS:
        raise _refuse(f"freelance payout for week {week} has more than {chains.MAX_LEGS} legs")
    ids = [leg.account_id for leg in p.legs]
    for account_id in ids:
        if account_id not in known_accounts:
            raise _refuse(
                f"freelance payout for week {week} references unknown account {account_id}"
            )
    if len(set(ids)) != len(ids):
        raise _refuse(f"freelance payout for week {week} has the same account twice in its chain")
    last = p.legs[-1]
    if abs(last.amount - p.amount) > 1e-9:
        raise _refuse(
            f"freelance payout for week {week}: its last leg is {last.amount} "
            f"but the payout is {p.amount}"
        )
    if account_info[last.account_id][0] != p.currency:
        raise _refuse(
            f"freelance payout for week {week}: its last leg is in "
            f"{account_info[last.account_id][0]} but the payout is in {p.currency}"
        )


@router.get("/backup")
def download_backup(session: Session = Depends(get_session)) -> Response:
    """Return a self-contained JSON snapshot as a file download."""
    settings = ConfigOut(
        daily_target_hours=get_daily_target_hours(session),
        daily_target_schedule=[
            DailyTargetRow(effective_from=eff, hours=hours)
            for eff, hours in get_daily_target_schedule(session).rows
        ],
        cumulative_start_date=get_cumulative_start_date(session),
        country=get_country(session),
        number_format=get_number_format(session),
        freelance_hours_per_week=get_freelance_hours_per_week(session),
        freelance_days_off=get_freelance_days_off(session),
        **get_profile(session),
    )

    rows = session.scalars(select(WorkEntry).order_by(WorkEntry.date)).all()
    entries = [
        {
            "date": e.date.isoformat(),
            "day_type": e.day_type,
            "fraction": e.fraction,
            "start_time": e.start_time,
            "end_time": e.end_time,
            "notes": e.notes,
            # A break keeps its time range when it was entered as one (older files only
            # have the minutes; they restore as untimed breaks).
            "breaks": [
                {
                    "break_minutes": b.break_minutes,
                    "start_time": b.start_time,
                    "end_time": b.end_time,
                }
                for b in e.breaks
            ],
        }
        for e in rows
    ]

    plans = [
        {
            "date": p.date.isoformat(),
            "day_type": p.day_type,
            "fraction": p.fraction,
            "notes": p.notes,
        }
        for p in session.scalars(select(Plan).order_by(Plan.date))
    ]

    accounts = [
        {
            "id": a.id,
            "name": a.name,
            "currency": a.currency,
            "kind": a.kind,
            "is_default": bool(a.is_default),
            "archived": bool(a.archived),
            "created_at": a.created_at.isoformat(),
            "position": a.position,
        }
        for a in session.scalars(select(Account).order_by(Account.id))
    ]
    income_sources = [
        {
            "id": s.id,
            "name": s.name,
            "hourly_rate": s.hourly_rate,
            "currency": s.currency,
            "is_default": bool(s.is_default),
            "archived": bool(s.archived),
            "position": s.position,
            "chain": [link.account_id for link in s.chain],
        }
        for s in session.scalars(select(IncomeSource).order_by(IncomeSource.id))
    ]
    freelance_blocks = [
        {
            "date": b.date.isoformat(),
            "source_id": b.source_id,
            "minutes": b.minutes,
            "start_time": b.start_time,
            "end_time": b.end_time,
            "notes": b.notes,
            "rate": b.rate,
            "currency": b.currency,
            "fx_rate": b.fx_rate,
        }
        for b in session.scalars(
            select(FreelanceBlock).order_by(FreelanceBlock.date, FreelanceBlock.id)
        )
    ]
    freelance_payouts = [
        {
            "source_id": p.source_id,
            "week_start": p.week_start.isoformat(),
            "amount": p.amount,
            "currency": p.currency,
            "fx_rate": p.fx_rate,
            "note": p.note,
            "account_id": p.account_id,
            "rate_source": p.rate_source,
            "rate_date": None if p.rate_date is None else p.rate_date.isoformat(),
            "legs": [
                {"account_id": leg.account_id, "amount": leg.amount, "fixed": bool(leg.fixed)}
                for leg in p.legs
            ],
        }
        for p in session.scalars(
            select(FreelancePayout).order_by(FreelancePayout.week_start, FreelancePayout.id)
        )
    ]
    freelance_tax_years = [
        {
            "year": t.year,
            "salary_annual": t.salary_annual,
            "tarifa_plana": bool(t.tarifa_plana),
            "inicio_actividad": bool(t.inicio_actividad),
            "set_aside_share": t.set_aside_share,
            "gestoria_annual": t.gestoria_annual,
            "other_expenses": t.other_expenses,
        }
        for t in session.scalars(select(FreelanceTaxYear).order_by(FreelanceTaxYear.year))
    ]

    payload = {
        "version": BACKUP_VERSION,
        "exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "settings": settings.model_dump(mode="json", exclude={"new_database"}),
        "entries": entries,
        "plans": plans,
        "accounts": accounts,
        "income_sources": income_sources,
        "freelance_blocks": freelance_blocks,
        "freelance_tax_years": freelance_tax_years,
        "freelance_payouts": freelance_payouts,
    }

    filename = f"kronos_backup_{date_.today().isoformat()}.json"
    return Response(
        content=json.dumps(payload, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/restore", status_code=200)
def restore_backup(
    payload: RestoreIn,
    session: Session = Depends(get_session),
) -> dict[str, int]:
    """Wipe the current entry set and reimport from a backup payload.

    Settings are also restored when ``payload.settings`` is present.
    Entries are validated by the same rules as the normal create endpoint
    (Pydantic raises 422 before we touch the DB if anything is invalid).
    """
    if payload.version not in SUPPORTED_BACKUP_VERSIONS:
        supported = ", ".join(str(v) for v in SUPPORTED_BACKUP_VERSIONS)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"unsupported backup version {payload.version!r}; supported: {supported}",
        )

    # Delete breaks first, then entries.  We do this explicitly rather than
    # relying on the FK ondelete=CASCADE so the operation is correct even in
    # environments where PRAGMA foreign_keys is not set (e.g. the test engine).
    session.execute(delete(Break))
    session.execute(delete(WorkEntry))
    session.execute(delete(Plan))
    session.execute(delete(FreelanceBlock))
    # The legs go before their payouts, for the same reason as the breaks above.
    session.execute(delete(PayoutLeg))
    session.execute(delete(FreelancePayout))
    # Sources and tax years are settings-like, but a file with freelance data replaces
    # them (its blocks reference its sources' ids); a file without leaves them alone.
    has_freelance = bool(
        payload.accounts
        or payload.income_sources
        or payload.freelance_blocks
        or payload.freelance_tax_years
        or payload.freelance_payouts
    )
    if has_freelance:
        session.execute(delete(FreelanceTaxYear))
        session.execute(delete(SourceAccount))
        session.execute(delete(IncomeSource))
    if payload.accounts:
        session.execute(delete(Account))
    session.flush()

    known_sources = {s.id for s in payload.income_sources}
    known_accounts = {a.id for a in payload.accounts}
    if not payload.accounts:  # an older file: the accounts stay, and so may be referenced
        known_accounts = set(session.scalars(select(Account.id)))
    names = [a.name.casefold() for a in payload.accounts]
    if len(set(names)) != len(names):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "two accounts in the file share a name"
        )
    for s in payload.income_sources:
        if s.default_account_id is not None and s.default_account_id not in known_accounts:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"source {s.name!r} references unknown account {s.default_account_id}",
            )
        if (
            s.default_from_account_id is not None
            and s.default_from_account_id not in known_accounts
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"source {s.name!r} references unknown account {s.default_from_account_id}",
            )
    # What each account is, to check a chain against: the file's accounts, or (a file without
    # any) the ones the database keeps.
    if payload.accounts:
        account_info = {a.id: (a.currency, a.archived) for a in payload.accounts}
    else:
        account_info = {
            i: (currency, bool(archived))
            for i, currency, archived in session.execute(
                select(Account.id, Account.currency, Account.archived)
            )
        }
    usable = {i for i, (_, archived) in account_info.items() if not archived}
    source_chains: dict[int, list[int]] = {}
    for s in payload.income_sources:
        if s.chain is None:  # an older file: "Paid from", then "Paid into"
            source_chains[s.id] = chains.chain_from_defaults(
                s.default_from_account_id, s.default_account_id, usable
            )
            continue
        if len(s.chain) > chains.MAX_LEGS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"source {s.name!r} has more than {chains.MAX_LEGS} accounts in its chain",
            )
        if len(set(s.chain)) != len(s.chain):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"source {s.name!r} has the same account twice in its chain",
            )
        for account_id in s.chain:
            if account_id not in known_accounts:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"source {s.name!r} references unknown account {account_id}",
                )
        source_chains[s.id] = list(s.chain)
    for b in payload.freelance_blocks:
        if b.source_id not in known_sources:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"freelance block on {b.date.isoformat()} references unknown source {b.source_id}",
            )
    for p in payload.freelance_payouts:
        if p.source_id not in known_sources:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"freelance payout for week {p.week_start.isoformat()} "
                f"references unknown source {p.source_id}",
            )
        if p.account_id is not None and p.account_id not in known_accounts:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"freelance payout for week {p.week_start.isoformat()} "
                f"references unknown account {p.account_id}",
            )
        if p.from_account_id is not None and p.from_account_id not in known_accounts:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"freelance payout for week {p.week_start.isoformat()} "
                f"references unknown account {p.from_account_id}",
            )
        _check_legs(p, account_info, known_accounts)
    # Positions as the file says; a file without them keeps the order shown before: the default
    # first, then by id.
    account_positions = _positions([(a.id, a.is_default, a.position) for a in payload.accounts])
    source_positions = _positions(
        [(s.id, s.is_default, s.position) for s in payload.income_sources]
    )
    for a in payload.accounts:
        session.add(
            Account(
                id=a.id,
                name=a.name,
                currency=a.currency,
                kind=a.kind,
                is_default=a.is_default,
                archived=a.archived,
                position=account_positions[a.id],
                **({} if a.created_at is None else {"created_at": a.created_at}),
            )
        )
    session.flush()
    for s in payload.income_sources:
        session.add(
            IncomeSource(
                id=s.id,
                name=s.name,
                hourly_rate=s.hourly_rate,
                currency=s.currency,
                is_default=s.is_default,
                archived=s.archived,
                position=source_positions[s.id],
                chain=[
                    SourceAccount(position=i, account_id=account_id)
                    for i, account_id in enumerate(source_chains[s.id])
                ],
            )
        )
    session.flush()
    for b in payload.freelance_blocks:
        session.add(
            FreelanceBlock(
                date=b.date,
                source_id=b.source_id,
                minutes=b.minutes,
                start_time=b.start_time,
                end_time=b.end_time,
                notes=b.notes,
                rate=b.rate,
                currency=b.currency,
                fx_rate=b.fx_rate,
            )
        )
    restored: list[tuple[FreelancePayout, FreelancePayoutBackup]] = []
    for p in payload.freelance_payouts:
        payout = FreelancePayout(
            source_id=p.source_id,
            week_start=p.week_start,
            amount=p.amount,
            currency=p.currency,
            fx_rate=p.fx_rate,
            note=p.note,
            account_id=p.account_id,
            rate_source=p.rate_source,
            rate_date=p.rate_date,
        )
        payout.legs.extend(
            PayoutLeg(position=i, account_id=leg.account_id, amount=leg.amount, fixed=leg.fixed)
            for i, leg in enumerate(p.legs or [])
        )
        session.add(payout)
        restored.append((payout, p))
    session.flush()
    # A payout the file gives no legs (an older file, or none written) gets them from what the
    # file says of its arrival and its sent side, in the order the file lists them: a restore
    # never leaves a payout without a chain. The payout's account is its last leg's.
    for payout, p in restored:
        if p.legs:
            payout.account_id = p.legs[-1].account_id
        else:
            chains.legs_from_sides(
                session, payout, p.sent_amount, p.sent_currency, p.from_account_id
            )
    for t in payload.freelance_tax_years:
        session.add(
            FreelanceTaxYear(
                year=t.year,
                salary_annual=t.salary_annual,
                tarifa_plana=t.tarifa_plana,
                inicio_actividad=t.inicio_actividad,
                set_aside_share=t.set_aside_share,
                gestoria_annual=t.gestoria_annual,
                other_expenses=t.other_expenses,
            )
        )

    for entry_in in payload.entries:
        session.add(entry_from_body(entry_in.date, entry_in))

    for plan_in in payload.plans:
        session.add(
            Plan(
                date=plan_in.date,
                day_type=plan_in.day_type.value,
                fraction=plan_in.fraction,
                notes=plan_in.notes,
            )
        )

    if payload.settings:
        set_cumulative_start_date(session, payload.settings.cumulative_start_date)
        # Prefer the full date-effective timeline; older backups without one fall back
        # to the single value (restored non-destructively via set_daily_target_hours).
        if payload.settings.daily_target_schedule:
            set_daily_target_schedule(
                session,
                DailyTargetSchedule.from_rows(
                    [(r.effective_from, r.hours) for r in payload.settings.daily_target_schedule]
                ),
            )
        else:
            set_daily_target_hours(session, payload.settings.daily_target_hours)
        # Profile lines ride in the settings too; older files simply have none.
        set_profile_field(session, PROFILE_NAME, payload.settings.profile_name)
        set_profile_field(session, PROFILE_EMPLOYER, payload.settings.profile_employer)
        set_profile_field(session, PROFILE_EXTRA, payload.settings.profile_extra)
        set_freelance_hours_per_week(session, payload.settings.freelance_hours_per_week)
        set_freelance_days_off(session, payload.settings.freelance_days_off)
        # Region and format: a file from before them keeps the ones the database has.
        given = payload.settings.model_fields_set
        if "country" in given and countries.valid(payload.settings.country):
            set_country(session, payload.settings.country)
        if "number_format" in given and numbers.valid(payload.settings.number_format):
            set_number_format(session, payload.settings.number_format)

    session.commit()
    return {"restored_entries": len(payload.entries)}
