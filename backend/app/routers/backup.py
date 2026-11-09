"""Backup and restore — full data portability.

GET  /api/backup   → download a self-contained JSON snapshot
POST /api/restore  → wipe current entries and reimport from snapshot

The backup format is intentionally simple (version 4):
{
  "version": 4,
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

Accounts (where a payout landed, each with a currency, with their ids), the source's default
account and, on a payout, its account, where its rate came from and the day it is of ride in the
same version 4 as optional keys: a file without them restores no accounts and leaves the current
ones alone. So do an account's role, a source's "Paid from" and, on a payout, what was sent (amount,
currency, account): a file without them restores as before, every payout "as billed".
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
    Plan,
    WorkEntry,
)
from app.schemas import (
    BACKUP_VERSION,
    SUPPORTED_BACKUP_VERSIONS,
    ConfigOut,
    DailyTargetRow,
    RestoreIn,
)
from app.services import countries, numbers
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
            "role": a.role,
            "is_default": bool(a.is_default),
            "archived": bool(a.archived),
            "created_at": a.created_at.isoformat(),
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
            "default_account_id": s.default_account_id,
            "default_from_account_id": s.default_from_account_id,
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
            "sent_amount": p.sent_amount,
            "sent_currency": p.sent_currency,
            "from_account_id": p.from_account_id,
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
    for a in payload.accounts:
        session.add(
            Account(
                id=a.id,
                name=a.name,
                currency=a.currency,
                kind=a.kind,
                role=a.role,
                is_default=a.is_default,
                archived=a.archived,
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
                default_account_id=s.default_account_id,
                default_from_account_id=s.default_from_account_id,
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
    for p in payload.freelance_payouts:
        session.add(
            FreelancePayout(
                source_id=p.source_id,
                week_start=p.week_start,
                amount=p.amount,
                currency=p.currency,
                fx_rate=p.fx_rate,
                note=p.note,
                account_id=p.account_id,
                rate_source=p.rate_source,
                rate_date=p.rate_date,
                sent_amount=p.sent_amount,
                sent_currency=p.sent_currency,
                from_account_id=p.from_account_id,
            )
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
