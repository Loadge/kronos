"""The "Simple" tax module: for every country that has no module of its own.

It knows no brackets and no social security. A share of every payment is set aside for the tax
office, and what is left after the expenses is the net:

    net = gross - expenses - gross x share

The share is the user's own (``FreelanceTaxYear.set_aside_share``). The result is the same
``Figures`` the Spanish module returns, so the screens that draw it need no second shape: every
Spanish field is zero here. Pure and on unrounded floats, like ``tax.py``.
"""

from __future__ import annotations

from app.services.tax import RATE_CEILING, Figures, TaxParams

DEFAULT_SHARE = 0.30


def figures(g: float, p: TaxParams, year: int, share: float = DEFAULT_SHARE) -> Figures:
    """Every figure of a year with gross income `g`. The gestoria is a Spanish cost and counts
    for nothing here; only `other_expenses` are expenses."""
    expenses = p.other_expenses
    aside = g * share
    return Figures(
        fiscal_year=year,
        region="",
        gross=g,
        gestoria=0.0,
        other_expenses=expenses,
        reta_monthly_yield=0.0,
        reta_tramo=0,
        reta_base=0.0,
        tarifa_plana=False,
        reta_annual=0.0,
        hard_to_justify=0.0,
        startup_reduction=0.0,
        taxable=g - expenses,
        salary=0.0,
        employment_net=0.0,
        irpf=0.0,
        pago_fraccionado=0.0,
        renta=0.0,
        reintegro=0.0,
        net=g - expenses - aside,
        set_aside=aside,
    )


def rate_from_net(
    net: float, billable: int, p: TaxParams, year: int, share: float = DEFAULT_SHARE
) -> float | None:
    """The daily rate whose net reaches `net`: it has a closed form here. None when there are no
    billable days, the net is negative, the whole payment is set aside, or not even RATE_CEILING
    reaches it (the same contract as ``tax.rate_from_net``)."""
    if billable <= 0 or net < 0 or share >= 1:
        return None
    rate = max(0.0, (net + p.other_expenses) / ((1 - share) * billable))
    return rate if rate <= RATE_CEILING else None
