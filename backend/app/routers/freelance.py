"""Freelance hours: income sources, hour blocks, the per-year tax inputs, the year's picture
and the calculator.

Blocks live apart from ``work_entries``: nothing here touches the employee's target, balance,
streaks or the timesheet. A block snapshots its source's rate and currency when it is saved
(and, for USD, the ECB rate of its date, fetched on demand exactly then), so a later change of
a rate never rewrites the past.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import FreelanceBlock, FreelanceTaxYear, IncomeSource
from app.schemas import (
    FreelanceBlockIn,
    FreelanceBlockOut,
    FreelanceBlockUpdate,
    FreelanceCalcIn,
    FreelanceTaxYearIn,
    FreelanceTaxYearOut,
    IncomeSourceIn,
    IncomeSourceOut,
    IncomeSourceUpdate,
)
from app.services import freelance, fx, tax
from app.services.clock import local_today
from app.services.settings import (
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
        blocks=blocks,
    )


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
    # The first source is the default whatever the body says: a single source must be pickable.
    first = session.scalar(select(func.count()).select_from(IncomeSource)) == 0
    src = IncomeSource(
        name=body.name.strip(),
        hourly_rate=body.hourly_rate,
        currency=body.currency,
        is_default=body.is_default or first,
        archived=body.archived,
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
    """Delete a source nothing bills to. One with blocks is a 409: archive it instead."""
    src = session.get(IncomeSource, source_id)
    if not src:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "income source not found")
    if _block_counts(session).get(src.id, 0):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "this source has blocks billed to it; archive it instead of deleting it",
        )
    session.delete(src)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- blocks ----------------------------------------------------------------


def block_out(b: FreelanceBlock) -> FreelanceBlockOut:
    eur = b.amount_eur
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
    )


def _fx_for(on: date) -> float | None:
    """The ECB rate of a date, asked for exactly once, when a USD block is saved."""
    answer = fx.for_date(on)
    return answer["usd_per_eur"] if answer["available"] else None


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
    return [block_out(b) for b in session.scalars(stmt)]


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
    if src.currency == "USD":
        block.fx_rate = body.fx_rate if body.fx_rate is not None else _fx_for(body.date)
    session.add(block)
    session.commit()
    session.refresh(block)
    return block_out(block)


@router.get("/blocks/{block_id}", response_model=FreelanceBlockOut)
def get_block(block_id: int, session: Session = Depends(get_session)) -> FreelanceBlockOut:
    block = session.get(FreelanceBlock, block_id)
    if not block:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "block not found")
    return block_out(block)


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
    if block.currency == "USD":
        if body.fx_rate is not None:
            block.fx_rate = body.fx_rate
        elif source_changed or date_changed or block.fx_rate is None:
            block.fx_rate = _fx_for(body.date)
    else:
        block.fx_rate = None
    session.commit()
    session.refresh(block)
    return block_out(block)


@router.delete("/blocks/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_block(block_id: int, session: Session = Depends(get_session)) -> Response:
    block = session.get(FreelanceBlock, block_id)
    if not block:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "block not found")
    session.delete(block)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- tax inputs per year -----------------------------------------------------


def _tax_year_out(session: Session, year: int) -> FreelanceTaxYearOut:
    t = freelance.tax_inputs_for(session, year)
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

    The ECB is asked only when the projection needs a rate it has nowhere else (a USD default
    source before the first block of the year) — on this request, never on a timer.
    """
    today = today or local_today()
    year = year or today.year
    latest: float | None = None
    src = freelance.default_source(session)
    if src is not None and src.currency == "USD":
        has_blocks = session.scalar(
            select(func.count())
            .select_from(FreelanceBlock)
            .where(
                FreelanceBlock.date >= date(year, 1, 1), FreelanceBlock.date <= date(year, 12, 31)
            )
        )
        if not has_blocks:
            answer = fx.latest()
            latest = answer["usd_per_eur"] if answer["available"] else None
    return freelance.year_summary(
        session,
        year,
        today,
        hours_per_week=get_freelance_hours_per_week(session),
        days_off=get_freelance_days_off(session),
        latest_usd_per_eur=latest,
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
]


@router.get("/export.csv")
def export_csv(session: Session = Depends(get_session)) -> Response:
    """One row per block, oldest first — the freelance side of the CSV export."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
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
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="kronos_freelance.csv"'},
    )
