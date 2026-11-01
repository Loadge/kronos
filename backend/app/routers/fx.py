"""GET /api/fx: the European Central Bank's latest EUR/USD reference rate.

The app's one external data source, fetched lazily: only when a request arrives and the last
attempt is an hour old, never on a timer, so an unused Kronos never touches the network. The
answer is always 200: `available` says whether a rate is on hand and `stale` that the value is
from an earlier fetch because the latest attempt failed.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.services import fx

router = APIRouter(prefix="/api", tags=["fx"])


@router.get("/fx")
def get_fx() -> dict:
    """The latest EUR/USD reference rate, or the unavailable shape when there is none."""
    return fx.latest()
