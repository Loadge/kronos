"""GET /api/fx: the European Central Bank's EUR/USD reference rate — the latest, or a date's.

The app's one external data source, fetched lazily: only when a request arrives and the last
attempt is an hour old, never on a timer, so an unused Kronos never touches the network. The
answer is always 200: `available` says whether a rate is on hand and `stale` that the value is
from an earlier fetch because the latest attempt failed. With ``?date=`` the answer is the rate
the ECB last published on or before that date (a weekend takes Friday's).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query

from app.services import fx

router = APIRouter(prefix="/api", tags=["fx"])


@router.get("/fx")
def get_fx(
    on: date | None = Query(None, alias="date", description="The rate in force on this date."),
) -> dict:
    """The latest EUR/USD reference rate (or the one of a date), or the unavailable shape."""
    if on is not None:
        return fx.for_date(on)
    return fx.latest()
