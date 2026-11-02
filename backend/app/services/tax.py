"""Tax and rate maths for freelance income: the single source of every tax figure Kronos shows.

The model is the one a Spanish autónomo actually pays, in estimación directa
simplificada:

- RETA by real income: the monthly net yield ((gross - expenses) less 7% generic expenses, / 12)
  picks a tramo, and the cuota is that tramo's minimum base x the rate; or the tarifa plana.
- IRPF by brackets, state + regional scale, each less the tax on its personal minimum. The
  activity's net yield is gross - expenses - RETA - hard-to-justify expenses (5%, capped), less the
  start-up reduction when it applies. With a salary (pluriactividad) the freelance IRPF is the tax
  on salary + activity minus the tax on the salary alone: the marginal rate on top of the salary.
- The 130 (pago fraccionado) is 20% of the activity's net yield, paid each quarter; the rest of
  the IRPF is paid (or returned) in the Renta.

The figures for each year live in `app/data/fiscal_es.json`, a year without a block using the latest
earlier one. They are planning estimates, not advice. Not modelled: family minimums, the reduction
for low employment income (art. 20 LIRPF), deductions, other income, a RETA base above the tramo's
minimum.

Every function here is pure and works on unrounded floats. Rounding is the caller's job, and
there is one rule for it: `round_half_up`, a half goes away from zero; `money` is that
rule at two decimals.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

FISCAL_FILE = Path(__file__).resolve().parent.parent / "data" / "fiscal_es.json"
DEFAULT_REGION = "andalucia"

Scale = tuple[tuple[float | None, float], ...]


@dataclass(frozen=True)
class TaxParams:
    gestoria_annual: float
    other_expenses: float
    hours_per_day: float
    salary_annual: float = 0.0
    tarifa_plana: bool = False
    inicio_actividad: bool = False

    @classmethod
    def from_config(cls, cfg) -> TaxParams:
        """Build from anything with the Config column names (the ORM row, a schema, a stub)."""
        return cls(
            gestoria_annual=cfg.gestoria_annual,
            other_expenses=cfg.other_expenses,
            hours_per_day=cfg.hours_per_day,
            salary_annual=cfg.salary_annual,
            tarifa_plana=bool(cfg.tarifa_plana),
            inicio_actividad=bool(cfg.inicio_actividad),
        )


@dataclass(frozen=True)
class Rules:
    """One year's block of fiscal_es.json. `year` is the block's year, which may be earlier than the
    year asked for."""

    year: int
    reta_rate: float
    reta_cc_rate: float
    reta_generic_expenses: float
    reta_tramos: Scale
    tarifa_plana_monthly: float
    pluriactividad_limit: float
    employee_ss_rate: float
    employee_cc_rate: float
    employee_base_max: float
    state_scale: Scale
    state_minimum: float
    region_name: str
    region_scale: Scale
    region_minimum: float
    hard_to_justify_rate: float
    hard_to_justify_max: float
    employment_other_expenses: float
    startup_reduction: float
    pago_fraccionado: float
    pago_fraccionado_deadlines: tuple[tuple[int, int], ...]  # (month, day) per quarter


def _scale(rows: list[list[Any]]) -> Scale:
    return tuple((None if hi is None else float(hi), float(v)) for hi, v in rows)


@cache
def _blocks() -> dict[int, dict[str, Any]]:
    data = json.loads(FISCAL_FILE.read_text(encoding="utf-8"))
    return {int(y): block for y, block in data["years"].items()}


def rules_for(year: int, region: str = DEFAULT_REGION) -> Rules:
    """The rules of `year`: its own block, else the latest earlier one, else the earliest one."""
    blocks = _blocks()
    earlier = [y for y in blocks if y <= year]
    used = max(earlier) if earlier else min(blocks)
    b = blocks[used]
    reta, emp, irpf = b["reta"], b["employee_ss"], b["irpf"]
    reg = irpf["regions"][region]
    return Rules(
        year=used,
        reta_rate=reta["rate"],
        reta_cc_rate=reta["cc_rate"],
        reta_generic_expenses=reta["generic_expenses"],
        reta_tramos=_scale(reta["tramos"]),
        tarifa_plana_monthly=reta["tarifa_plana_monthly"],
        pluriactividad_limit=reta["pluriactividad_limit"],
        employee_ss_rate=emp["rate"],
        employee_cc_rate=emp["cc_rate"],
        employee_base_max=emp["base_max_annual"],
        state_scale=_scale(irpf["state_scale"]),
        state_minimum=irpf["state_minimum"],
        region_name=reg["name"],
        region_scale=_scale(reg["scale"]),
        region_minimum=reg["minimum"],
        hard_to_justify_rate=irpf["hard_to_justify_rate"],
        hard_to_justify_max=irpf["hard_to_justify_max"],
        employment_other_expenses=irpf["employment_other_expenses"],
        startup_reduction=irpf["startup_reduction"],
        pago_fraccionado=irpf["pago_fraccionado"],
        pago_fraccionado_deadlines=tuple(
            (int(m), int(d)) for m, d in irpf["pago_fraccionado_deadlines"]
        ),
    )


def scale_tax(base: float, scale: Scale) -> float:
    """Tax on `base` by brackets: each slice of the base at its own rate. Nothing on a base <= 0."""
    total, lower = 0.0, 0.0
    for upper, rate in scale:
        top = base if upper is None else min(base, upper)
        if top <= lower:
            break
        total += (top - lower) * rate
        lower = upper if upper is not None else lower
    return total


def income_tax(base: float, r: Rules) -> float:
    """IRPF of a general taxable base: state + regional scale, each less the tax on its minimum."""
    base = max(0.0, base)
    state = scale_tax(base, r.state_scale) - scale_tax(min(base, r.state_minimum), r.state_scale)
    region = scale_tax(base, r.region_scale) - scale_tax(
        min(base, r.region_minimum), r.region_scale
    )
    return state + region


def employment_net(salary: float, r: Rules) -> float:
    """Net employment income: salary - the worker's Social Security - the flat 2,000 expenses."""
    if salary <= 0:
        return 0.0
    ss = min(salary, r.employee_base_max) * r.employee_ss_rate
    return max(0.0, salary - ss - r.employment_other_expenses)


def reta_tramo(monthly_yield: float, r: Rules) -> tuple[int, float]:
    """(tramo number from 1, its minimum base) for a monthly net yield."""
    for i, (upper, base) in enumerate(r.reta_tramos, start=1):
        if upper is None or monthly_yield <= upper:
            return i, base
    raise AssertionError("the last tramo has no upper limit")


def gross(rate: float, billable: int) -> float:
    return rate * billable


@dataclass(frozen=True)
class Figures:
    """One year of freelance figures, unrounded."""

    fiscal_year: int
    region: str
    gross: float
    gestoria: float
    other_expenses: float
    reta_monthly_yield: float
    reta_tramo: int
    reta_base: float
    tarifa_plana: bool
    reta_annual: float
    hard_to_justify: float
    startup_reduction: float
    taxable: float  # the activity's net yield, the base the IRPF and the 130 see
    salary: float
    employment_net: float
    irpf: float  # the freelance share of the IRPF: tax(salary + activity) - tax(salary)
    pago_fraccionado: float
    renta: float  # irpf - pago_fraccionado: what is left to pay in the Renta (negative: returned)
    reintegro: float  # pluriactividad refund of RETA contributions, paid the year after
    net: float

    @property
    def expenses(self) -> float:
        return self.gestoria + self.other_expenses

    @property
    def irpf_effective(self) -> float:
        """The freelance IRPF over the activity's net yield (0 when there is no positive yield)."""
        return self.irpf / self.taxable if self.taxable > 0 else 0.0


def figures(g: float, p: TaxParams, year: int) -> Figures:
    """Every figure of a year with gross income `g` (in euros)."""
    r = rules_for(year)
    expenses = p.gestoria_annual + p.other_expenses

    monthly_yield = max(0.0, g - expenses) * (1 - r.reta_generic_expenses) / 12
    tramo, base = reta_tramo(monthly_yield, r)
    reta = r.tarifa_plana_monthly * 12 if p.tarifa_plana else base * r.reta_rate * 12

    before = g - expenses - reta
    hard = min(before * r.hard_to_justify_rate, r.hard_to_justify_max) if before > 0 else 0.0
    yield_ = before - hard
    startup = yield_ * r.startup_reduction if p.inicio_actividad and yield_ > 0 else 0.0
    taxable = yield_ - startup

    work = employment_net(p.salary_annual, r)
    irpf = income_tax(work + taxable, r) - income_tax(work, r)
    pf = max(0.0, yield_) * r.pago_fraccionado

    reintegro = 0.0
    if p.salary_annual > 0 and not p.tarifa_plana:
        reta_cc = base * r.reta_cc_rate * 12
        work_cc = min(p.salary_annual, r.employee_base_max) * r.employee_cc_rate
        excess = max(0.0, work_cc + reta_cc - r.pluriactividad_limit)
        reintegro = min(excess * 0.5, reta_cc * 0.5)

    return Figures(
        fiscal_year=r.year,
        region=r.region_name,
        gross=g,
        gestoria=p.gestoria_annual,
        other_expenses=p.other_expenses,
        reta_monthly_yield=monthly_yield,
        reta_tramo=tramo,
        reta_base=base,
        tarifa_plana=p.tarifa_plana,
        reta_annual=reta,
        hard_to_justify=hard,
        startup_reduction=startup,
        taxable=taxable,
        salary=p.salary_annual,
        employment_net=work,
        irpf=irpf,
        pago_fraccionado=pf,
        renta=irpf - pf,
        reintegro=reintegro,
        net=g - expenses - reta - irpf,
    )


def net_from_rate(rate: float, billable: int, p: TaxParams, year: int) -> float:
    """Unrounded annual net for a daily rate and a number of billable days."""
    return figures(gross(rate, billable), p, year).net


RATE_CEILING = 1e7  # EUR/day: past this no real net is asked for


def rate_from_net(net: float, billable: int, p: TaxParams, year: int) -> float | None:
    """A daily rate whose net reaches `net` (the boundary, to 1e-9), unrounded; None if none does.

    There is no closed form (brackets, tramos), so it bisects. The net is not strictly increasing:
    crossing into a higher RETA tramo raises the cuota by a step (up to ~500 EUR a year), so just
    past a tramo limit the net dips a little, and a net inside that dip is reached by more than one
    rate, a few euros a day apart. The bisection returns one of them, not necessarily the lowest.
    None when there are no billable days, when the net asked for is negative, or when not even
    RATE_CEILING reaches it.
    """
    if billable <= 0 or net < 0:
        return None
    if net_from_rate(0.0, billable, p, year) >= net:
        return 0.0
    hi = 1.0
    while net_from_rate(hi, billable, p, year) < net:
        hi *= 2
        if hi > RATE_CEILING:
            return None
    lo = 0.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if net_from_rate(mid, billable, p, year) >= net:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-9:
            break
    return hi


@dataclass(frozen=True)
class QuarterPayment:
    """One quarter's modelo 130, unrounded.

    The 130 is cumulative: 20% of the activity's net yield since 1 January, less what the
    earlier quarters already paid, never below zero (a bad quarter pays nothing and is not
    refunded until the Renta).
    """

    quarter: int  # 1..4
    gross_ytd: float  # income since 1 January, to the end of the quarter
    fixed_ytd: float  # the expenses and the RETA accrued so far (a twelfth a month)
    yield_ytd: float  # gross - fixed - hard-to-justify expenses, floored at 0
    cumulative: float  # 20% of yield_ytd: what the year has owed so far
    payment: float  # cumulative less the earlier quarters' payments, floored at 0
    deadline_month: int
    deadline_day: int

    @property
    def deadline_in_next_year(self) -> bool:
        return self.quarter == 4


def quarter_payments(
    gross_by_quarter: tuple[float, float, float, float], fixed_annual: float, year: int
) -> tuple[QuarterPayment, ...]:
    """The four modelo 130 payments of a year from the gross income of each quarter.

    `fixed_annual` is what the year costs whatever the income — the deductible expenses and
    the RETA cuota — accrued at a twelfth a month, so the base of each quarter is the income so
    far less the costs so far. The 5% hard-to-justify expenses (capped) come off like in
    `figures`, the start-up reduction does not (it only lowers the Renta).
    """
    r = rules_for(year)
    out: list[QuarterPayment] = []
    gross_ytd = paid = 0.0
    for q, g in enumerate(gross_by_quarter, start=1):
        gross_ytd += g
        fixed_ytd = fixed_annual * 3 * q / 12
        before = gross_ytd - fixed_ytd
        hard = min(before * r.hard_to_justify_rate, r.hard_to_justify_max) if before > 0 else 0.0
        yield_ytd = max(0.0, before - hard)
        cumulative = yield_ytd * r.pago_fraccionado
        payment = max(0.0, cumulative - paid)
        paid += payment
        month, day = r.pago_fraccionado_deadlines[q - 1]
        out.append(
            QuarterPayment(
                quarter=q,
                gross_ytd=gross_ytd,
                fixed_ytd=fixed_ytd,
                yield_ytd=yield_ytd,
                cumulative=cumulative,
                payment=payment,
                deadline_month=month,
                deadline_day=day,
            )
        )
    return tuple(out)


def month_figures(rate: float, billable: int, annual: Figures) -> tuple[float, float]:
    """(gross, net) of one month: a twelfth of the expenses and the RETA, and the month's share of
    the year's IRPF by its share of the year's gross. The twelve nets add up to the annual net."""
    m_gross = rate * billable
    share = m_gross / annual.gross if annual.gross > 0 else 0.0
    m_fixed = (annual.expenses + annual.reta_annual) / 12
    return m_gross, m_gross - m_fixed - annual.irpf * share


def hourly_to_daily(h: float, p: TaxParams) -> float:
    return h * p.hours_per_day


def daily_to_hourly(d: float, p: TaxParams) -> float:
    return d / p.hours_per_day


def round_half_up(x: float, nd: int = 0) -> float:
    """Round to `nd` decimals, a half going away from zero (the one rounding rule of the app).

    Python's round() sends an exact tie to the even digit (round(0.125, 2) is 0.12, round(2.5) is
    2) and f"{x:.0f}" does the same; the browser rounds a half up. This is floor(|x| * 10**nd +
    0.5) / 10**nd with the sign put back, so a page that rounds the same way in JavaScript agrees
    to the last bit. Never returns -0.0.

    Two limits. A value that is a tie only on paper has no exact
    binary form, and the product |x| * 10**nd decides: 0.015 and 2.675 land exactly on .5 and go
    up, 1.005 lands just below and goes down (Python's round() reads the binary value instead, so
    it differs from this on about half of such values). And past 2**52 / 10**nd (4.5e13 euros at
    two decimals) a double has no fraction left to round, so the value is returned as it is.
    """
    scale = 10**nd
    y = abs(x) * scale
    if math.isfinite(y) and y >= 2**52:
        # past 2**52 a double has no fraction left, and y + 0.5 would round to the even integer
        # (a wrong cent): nothing to round
        return x + 0.0
    r = math.floor(y + 0.5) / scale  # OverflowError when y is inf (x near 1e308, or infinite)
    return (r if x >= 0 else -r) + 0.0


def money(x: float) -> float:
    """A figure in euros and cents."""
    try:
        return round_half_up(x, 2)
    except OverflowError:  # |x| * 100 overflowed: far past 2**52, there is no cent to round
        return x
