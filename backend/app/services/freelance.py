"""What the freelance hours add up to: sums of blocks, the year's tax picture, the calculator.

Everything in euros: a USD block is converted with the ECB rate stored on it (see
``FreelanceBlock.amount_eur``); a USD block without a rate is counted as *missing* and left out
of every sum, never silently valued at 1:1. The tax figures come from ``tax.py`` and nowhere
else — this module only decides what gross to hand it and rounds the answer for the API.

The year's tax picture is built on the **projected** gross (what was billed so far plus the
planned hours to Dec 31), because that is what a RETA tramo and an IRPF bracket are chosen by:
a year's cuota does not depend on how far into the year one looks. The quarterly 130s use the
real income of each quarter against the fixed costs that picture implies.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FreelanceBlock, FreelancePayout, FreelanceTaxYear, IncomeSource
from app.services import tax
from app.services.tax import Figures, TaxParams, money

DEFAULT_SET_ASIDE = 0.4
DEFAULT_HOURS_PER_DAY = 8.0
DEFAULT_BILLABLE_DAYS = 220


# ---------- tax inputs per year ---------------------------------------------


@dataclass(frozen=True)
class TaxYearInputs:
    """The inputs in force for a year: its own row, the latest earlier one, or the defaults."""

    year: int
    salary_annual: float
    tarifa_plana: bool
    inicio_actividad: bool
    set_aside_share: float
    gestoria_annual: float
    other_expenses: float
    inherited_from: int | None  # the row's year when it is not `year`'s own; None otherwise
    is_default: bool  # no row at all applies: the defaults

    def params(self, hours_per_day: float = DEFAULT_HOURS_PER_DAY) -> TaxParams:
        return TaxParams(
            gestoria_annual=self.gestoria_annual,
            other_expenses=self.other_expenses,
            hours_per_day=hours_per_day,
            salary_annual=self.salary_annual,
            tarifa_plana=self.tarifa_plana,
            inicio_actividad=self.inicio_actividad,
        )


def tax_inputs_for(session: Session, year: int) -> TaxYearInputs:
    row = session.scalar(
        select(FreelanceTaxYear)
        .where(FreelanceTaxYear.year <= year)
        .order_by(FreelanceTaxYear.year.desc())
        .limit(1)
    )
    if row is None:
        return TaxYearInputs(
            year=year,
            salary_annual=0.0,
            tarifa_plana=False,
            inicio_actividad=False,
            set_aside_share=DEFAULT_SET_ASIDE,
            gestoria_annual=0.0,
            other_expenses=0.0,
            inherited_from=None,
            is_default=True,
        )
    return TaxYearInputs(
        year=year,
        salary_annual=row.salary_annual,
        tarifa_plana=bool(row.tarifa_plana),
        inicio_actividad=bool(row.inicio_actividad),
        set_aside_share=row.set_aside_share,
        gestoria_annual=row.gestoria_annual,
        other_expenses=row.other_expenses,
        inherited_from=row.year if row.year != year else None,
        is_default=False,
    )


# ---------- blocks ----------------------------------------------------------


def blocks_between(session: Session, start: date, end: date) -> list[FreelanceBlock]:
    return list(
        session.scalars(
            select(FreelanceBlock)
            .where(FreelanceBlock.date >= start, FreelanceBlock.date <= end)
            .order_by(FreelanceBlock.date, FreelanceBlock.id)
        )
    )


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def split_cents(total_cents: int, weights: list[float]) -> list[int]:
    """Split `total_cents` in proportion to `weights` by largest remainder: every share is
    floored to the cent and the cents left over go one each to the largest fractional parts
    (ties to the earlier position), so the shares add up to `total_cents` exactly. Weights
    that add up to nothing split evenly."""
    n = len(weights)
    if n == 0:
        return []
    w = [Fraction(x) for x in weights]
    whole = sum(w)
    if whole <= 0:
        w, whole = [Fraction(1)] * n, Fraction(n)
    exact = [total_cents * x / whole for x in w]
    shares = [math.floor(x) for x in exact]
    leftover = total_cents - sum(shares)
    order = sorted(range(n), key=lambda i: (-(exact[i] - shares[i]), i))
    for i in order[:leftover]:
        shares[i] += 1
    return shares


@dataclass
class Line:
    """One piece of freelance money on one day: a block, or a payout with no blocks.

    ``eur`` is the money that counts (None: missing, a USD amount without a rate) and ``paid``
    says whether it comes from a payout; ``est_eur`` is the block's own estimate.
    """

    date: date
    source_id: int
    block_id: int | None
    minutes: int
    amount: float  # in the source's currency
    est_eur: float | None
    eur: float | None
    paid: bool
    payout_id: int | None
    currency: str = "EUR"


def money_lines(session: Session, start: date, end: date) -> list[Line]:
    """The one rule behind every freelance sum: the lines of [start, end].

    Whole ISO weeks are read, so a payout is always spread over all its week's blocks, then
    only the lines inside [start, end] are kept. A (source, week) with a payout counts the
    payout, split over the blocks by their euro estimate (by minutes when one block has none);
    without one, each block counts its own estimate.
    """
    first, last = monday_of(start), monday_of(end) + timedelta(days=6)
    blocks = blocks_between(session, first, last)
    payouts = {
        (p.source_id, p.week_start): p
        for p in session.scalars(
            select(FreelancePayout).where(
                FreelancePayout.week_start >= first, FreelancePayout.week_start <= last
            )
        )
    }
    groups: dict[tuple[int, date], list[FreelanceBlock]] = defaultdict(list)
    for b in blocks:  # already ordered by date, id
        groups[(b.source_id, monday_of(b.date))].append(b)

    lines: list[Line] = []
    for (sid, week), group in groups.items():
        ests = [None if b.amount_eur is None else money(b.amount_eur) for b in group]
        payout = payouts.get((sid, week))
        if payout is None:
            for b, est in zip(group, ests, strict=True):
                lines.append(
                    Line(b.date, sid, b.id, b.minutes, b.amount, est, est, False, None, b.currency)
                )
            continue
        if all(e is not None for e in ests) and sum(ests) > 0:
            weights = list(ests)
        else:
            weights = [float(b.minutes) for b in group]
        payout_eur = payout.amount_eur
        eur_shares = (
            None if payout_eur is None else split_cents(round(money(payout_eur) * 100), weights)
        )
        amount_shares = split_cents(round(money(payout.amount) * 100), weights)
        for i, (b, est) in enumerate(zip(group, ests, strict=True)):
            eur = None if eur_shares is None else eur_shares[i] / 100
            lines.append(
                Line(
                    b.date,
                    sid,
                    b.id,
                    b.minutes,
                    amount_shares[i] / 100,
                    est,
                    eur,
                    True,
                    payout.id,
                    b.currency,
                )
            )
    for (sid, week), payout in payouts.items():
        if (sid, week) in groups:
            continue
        eur = None if payout.amount_eur is None else money(payout.amount_eur)
        lines.append(
            Line(
                week + timedelta(days=6),
                sid,
                None,
                0,
                payout.amount,
                None,
                eur,
                True,
                payout.id,
                payout.currency,
            )
        )
    lines = [ln for ln in lines if start <= ln.date <= end]
    lines.sort(key=lambda ln: (ln.date, ln.block_id or 0, ln.source_id))
    return lines


@dataclass
class Sum:
    """Hours and euros of a set of lines; `missing` counts lines without a euro figure (a USD
    amount without a rate).

    Each line is added at the cents it shows, so a list of lines and its total agree to the
    cent wherever they are shown together. `paid_out_eur` is the part that comes from
    payouts, `estimated_eur` the part still counted from the blocks' estimates.
    """

    minutes: int = 0
    gross_eur: float = 0.0
    blocks: int = 0
    missing: int = 0
    paid_out_eur: float = 0.0
    estimated_eur: float = 0.0

    def add(self, ln: Line) -> None:
        if ln.block_id is not None:
            self.blocks += 1
        self.minutes += ln.minutes
        if ln.eur is None:
            self.missing += 1
        else:
            eur = money(ln.eur)
            self.gross_eur += eur
            if ln.paid:
                self.paid_out_eur += eur
            else:
                self.estimated_eur += eur

    @property
    def hours(self) -> float:
        return round(self.minutes / 60.0, 2)

    @property
    def eur_per_hour(self) -> float:
        return self.gross_eur / (self.minutes / 60.0) if self.minutes else 0.0

    def out(self) -> dict:
        return {
            "hours": self.hours,
            "gross_eur": money(self.gross_eur),
            "eur_per_hour": money(self.eur_per_hour),
            "blocks": self.blocks,
            "missing_fx": self.missing,
            "paid_out_eur": money(self.paid_out_eur),
            "estimated_eur": money(self.estimated_eur),
        }


def sum_lines(lines: Iterable[Line]) -> Sum:
    s = Sum()
    for ln in lines:
        s.add(ln)
    return s


def default_source(session: Session) -> IncomeSource | None:
    """The default source, else the first live one, else None."""
    live = list(
        session.scalars(
            select(IncomeSource)
            .where(IncomeSource.archived.is_(False))
            .order_by(IncomeSource.is_default.desc(), IncomeSource.id)
        )
    )
    return live[0] if live else None


# ---------- the year ---------------------------------------------------------


def figures_out(f: Figures) -> dict:
    """A ``Figures`` in euros and cents, for the API."""
    return {
        "fiscal_year": f.fiscal_year,
        "region": f.region,
        "gross": money(f.gross),
        "expenses": money(f.expenses),
        "gestoria": money(f.gestoria),
        "other_expenses": money(f.other_expenses),
        "reta_monthly_yield": money(f.reta_monthly_yield),
        "reta_tramo": f.reta_tramo,
        "reta_base": money(f.reta_base),
        "reta_monthly": money(f.reta_annual / 12),
        "reta_annual": money(f.reta_annual),
        "tarifa_plana": f.tarifa_plana,
        "hard_to_justify": money(f.hard_to_justify),
        "startup_reduction": money(f.startup_reduction),
        "taxable": money(f.taxable),
        "salary": money(f.salary),
        "employment_net": money(f.employment_net),
        "irpf": money(f.irpf),
        "irpf_effective": round(f.irpf_effective, 4),
        "pago_fraccionado": money(f.pago_fraccionado),
        "renta": money(f.renta),
        "reintegro": money(f.reintegro),
        "net": money(f.net),
        "net_share": round(f.net / f.gross, 4) if f.gross > 0 else 0.0,
    }


def _quarter_of(d: date) -> int:
    return (d.month - 1) // 3 + 1


def quarters_out(
    blocks_by_quarter: dict[int, Sum], fixed_annual: float, year: int, today: date
) -> list[dict]:
    gross = tuple(blocks_by_quarter[q].gross_eur for q in (1, 2, 3, 4))
    out = []
    for qp in tax.quarter_payments(gross, fixed_annual, year):
        q = qp.quarter
        q_start = date(year, 3 * (q - 1) + 1, 1)
        q_end = (
            date(year + 1, 1, 1) - timedelta(days=1)
            if q == 4
            else (date(year, 3 * q + 1, 1) - timedelta(days=1))
        )
        deadline = date(
            year + 1 if qp.deadline_in_next_year else year, qp.deadline_month, qp.deadline_day
        )
        if today > deadline:
            status = "paid"
        elif today > q_end:
            status = "due"
        elif today >= q_start:
            status = "current"
        else:
            status = "future"
        s = blocks_by_quarter[q]
        out.append(
            {
                "quarter": q,
                "label": f"Q{q}",
                "from": q_start,
                "to": q_end,
                "hours": s.hours,
                "gross_eur": money(s.gross_eur),
                "gross_ytd": money(qp.gross_ytd),
                "fixed_ytd": money(qp.fixed_ytd),
                "yield_ytd": money(qp.yield_ytd),
                "cumulative": money(qp.cumulative),
                "payment": money(qp.payment),
                "deadline": deadline,
                "status": status,
            }
        )
    return out


def _weeks_left(today: date, year: int, days_off: float) -> float:
    """Weeks of freelance work left in `year` after today, the days off spread over the year
    (nobody knows when they fall), never below zero."""
    jan1, dec31 = date(year, 1, 1), date(year, 12, 31)
    if today >= dec31:
        return 0.0
    days_left = (dec31 - jan1).days + 1 if today < jan1 else (dec31 - today).days
    days_in_year = (dec31 - jan1).days + 1
    weeks = (days_left - days_off * days_left / days_in_year) / 7
    return max(0.0, weeks)


def year_summary(
    session: Session,
    year: int,
    today: date,
    *,
    hours_per_week: float,
    days_off: float,
    latest_usd_per_eur: float | None,
) -> dict:
    """Everything the Freelance tab, the dashboard card and Analytics show for a year."""
    jan1, dec31 = date(year, 1, 1), date(year, 12, 31)
    lines = money_lines(session, jan1, dec31)
    total = sum_lines(lines)

    by_month = {m: Sum() for m in range(1, 13)}
    by_quarter = {q: Sum() for q in (1, 2, 3, 4)}
    by_source: dict[int, Sum] = defaultdict(Sum)
    currency_amount: dict[int, float] = defaultdict(float)
    for ln in lines:
        by_month[ln.date.month].add(ln)
        by_quarter[_quarter_of(ln.date)].add(ln)
        by_source[ln.source_id].add(ln)
        currency_amount[ln.source_id] += ln.amount
    source_names = {s.id: s.name for s in session.scalars(select(IncomeSource))}

    # Weeks of the year with blocks but no payout, already over: the payouts still to enter.
    awaiting = {
        (ln.source_id, monday_of(ln.date))
        for ln in lines
        if ln.block_id is not None
        and not ln.paid
        and monday_of(ln.date) + timedelta(days=6) < today
    }

    # This week / this month, for the dashboard card (only when `today` is in the year).
    monday = monday_of(today)
    week = sum_lines(ln for ln in lines if monday <= ln.date <= monday + timedelta(days=6))
    month = sum_lines(ln for ln in lines if ln.date.month == today.month and today.year == year)

    inputs = tax_inputs_for(session, year)
    params = inputs.params()

    # The projection: planned hours at the rate realised so far (the mix of sources in
    # euros), or the default source's rate before anything was billed this year.
    src = default_source(session)
    rate_eur: float | None = None
    rate_basis = "none"
    if total.minutes and total.gross_eur > 0:
        rate_eur = total.eur_per_hour
        rate_basis = "realised"
    elif src is not None:
        if src.currency == "EUR":
            rate_eur, rate_basis = src.hourly_rate, "default_source"
        elif latest_usd_per_eur:
            rate_eur, rate_basis = src.hourly_rate / latest_usd_per_eur, "default_source"
    weeks_left = _weeks_left(today, year, days_off)
    planned_hours = weeks_left * hours_per_week
    planned_gross = planned_hours * (rate_eur or 0.0)
    projected_gross = total.gross_eur + planned_gross
    projected_hours = total.minutes / 60.0 + planned_hours

    fig = tax.figures(projected_gross, params, year)
    fixed_annual = params.gestoria_annual + params.other_expenses + fig.reta_annual

    return {
        "year": year,
        "today": today,
        "total": total.out(),
        "awaiting_payout": len(awaiting),
        "week": week.out(),
        "month": month.out(),
        "set_aside_share": inputs.set_aside_share,
        "set_aside": {
            "year": money(total.gross_eur * inputs.set_aside_share),
            "week": money(week.gross_eur * inputs.set_aside_share),
            "month": money(month.gross_eur * inputs.set_aside_share),
        },
        "by_month": [{"month": m, **by_month[m].out()} for m in range(1, 13)],
        "by_source": [
            {
                "source_id": sid,
                "name": source_names.get(sid, ""),
                "currency": next((ln.currency for ln in lines if ln.source_id == sid), "EUR"),
                "amount": money(currency_amount[sid]),
                **s.out(),
            }
            for sid, s in sorted(by_source.items(), key=lambda kv: -kv[1].gross_eur)
        ],
        "quarters": quarters_out(by_quarter, fixed_annual, year, today),
        "tax_inputs": {
            "year": inputs.year,
            "salary_annual": inputs.salary_annual,
            "tarifa_plana": inputs.tarifa_plana,
            "inicio_actividad": inputs.inicio_actividad,
            "set_aside_share": inputs.set_aside_share,
            "gestoria_annual": inputs.gestoria_annual,
            "other_expenses": inputs.other_expenses,
            "inherited_from": inputs.inherited_from,
            "is_default": inputs.is_default,
        },
        "projection": {
            "hours_per_week": hours_per_week,
            "days_off": days_off,
            "weeks_left": round(weeks_left, 2),
            "planned_hours": round(planned_hours, 2),
            "rate_eur": money(rate_eur) if rate_eur is not None else None,
            "rate_basis": rate_basis,
            "planned_gross_eur": money(planned_gross),
            "projected_gross_eur": money(projected_gross),
            "projected_hours": round(projected_hours, 2),
            "eur_per_hour_net": money(fig.net / projected_hours) if projected_hours > 0 else 0.0,
            "eur_per_hour_gross": money(projected_gross / projected_hours)
            if projected_hours > 0
            else 0.0,
            "figures": figures_out(fig),
        },
    }


# ---------- the calculator --------------------------------------------------


def calculate(
    *,
    mode: str,
    value: float,
    currency: str,
    fx_rate: float | None,
    billable_days: int,
    hours_per_day: float,
    params: TaxParams,
    year: int,
) -> dict:
    """Hourly ⇄ daily ⇄ net yearly: the given field drives the other two.

    Rates are in `currency`; a USD rate needs `fx_rate` (USD per EUR). The net is always in
    euros — the taxes are. Returns every figure to the cent, plus the month and the rate the
    inverse found (None when no rate reaches the net asked for).
    """
    fx = fx_rate if currency == "USD" else 1.0
    if fx is None or fx <= 0:
        raise ValueError("a USD rate needs the USD per EUR exchange rate")
    p = tax.TaxParams(
        gestoria_annual=params.gestoria_annual,
        other_expenses=params.other_expenses,
        hours_per_day=hours_per_day,
        salary_annual=params.salary_annual,
        tarifa_plana=params.tarifa_plana,
        inicio_actividad=params.inicio_actividad,
    )
    reachable = True
    if mode == "hourly":
        hourly = value
        daily = tax.hourly_to_daily(hourly, p)
    elif mode == "daily":
        daily = value
        hourly = tax.daily_to_hourly(daily, p)
    elif mode == "net":
        daily_eur = tax.rate_from_net(value, billable_days, p, year)
        if daily_eur is None:
            reachable = False
            daily_eur = 0.0
        daily = daily_eur * fx
        hourly = tax.daily_to_hourly(daily, p)
    else:
        raise ValueError("mode must be hourly, daily or net")
    gross_eur = tax.gross(daily / fx, billable_days)
    fig = tax.figures(gross_eur, p, year)
    m_gross, m_net = tax.month_figures(daily / fx, billable_days / 12, fig)
    return {
        "mode": mode,
        "currency": currency,
        "fx_rate": fx if currency == "USD" else None,
        "reachable": reachable,
        "hourly": money(hourly),
        "daily": money(daily),
        "net": money(fig.net),
        "gross": money(gross_eur * fx),
        "gross_eur": money(gross_eur),
        "billable_days": billable_days,
        "hours_per_day": hours_per_day,
        "hours_year": round(billable_days * hours_per_day, 2),
        "net_per_hour_eur": money(fig.net / (billable_days * hours_per_day))
        if billable_days * hours_per_day > 0
        else 0.0,
        "month": {"gross_eur": money(m_gross), "net_eur": money(m_net)},
        "figures": figures_out(fig),
    }
