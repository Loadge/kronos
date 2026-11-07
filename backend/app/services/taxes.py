"""Which tax module a country uses: the one place that decides.

Spain has its own (``tax.py``: RETA, IRPF brackets, the modelo 130). Every other country gets the
Simple one (``tax_simple.py``: a share of every payment set aside). Both answer the same calls and
return the same ``Figures``, so the callers never ask which country they are serving.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.services import tax, tax_simple
from app.services.tax import Figures, TaxParams

SPAIN = "ES"
SPAIN_SHARE = 0.4  # what Kronos has always set aside by default for Spain


@dataclass(frozen=True)
class TaxModule:
    name: str  # "spain" | "simple"
    figures: Callable[[float, TaxParams, int, float], Figures]
    rate_from_net: Callable[[float, int, TaxParams, int, float], float | None]
    quarterly: bool  # whether the year has quarterly payments to show (the modelo 130)


def _spain_figures(g: float, p: TaxParams, year: int, share: float) -> Figures:
    return tax.figures(g, p, year)


def _spain_rate_from_net(
    net: float, billable: int, p: TaxParams, year: int, share: float
) -> float | None:
    return tax.rate_from_net(net, billable, p, year)


SPAIN_MODULE = TaxModule("spain", _spain_figures, _spain_rate_from_net, True)
SIMPLE_MODULE = TaxModule("simple", tax_simple.figures, tax_simple.rate_from_net, False)


def module_for(country: str) -> TaxModule:
    return SPAIN_MODULE if country == SPAIN else SIMPLE_MODULE


def default_share(country: str) -> float:
    """The share set aside when the user has not written one: 40 % in Spain, 30 % elsewhere."""
    return SPAIN_SHARE if country == SPAIN else tax_simple.DEFAULT_SHARE
