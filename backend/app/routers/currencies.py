"""GET /api/currencies: the currencies Kronos knows (EUR, the ECB's, a few coins)."""

from __future__ import annotations

from fastapi import APIRouter

from app.services.currencies import CATALOGUE

router = APIRouter(prefix="/api", tags=["currencies"])


@router.get("/currencies")
def list_currencies() -> list[dict]:
    """Code, name, kind (fiat or crypto), rate source (none, ecb, coingecko) and decimals."""
    return [c.out() for c in CATALOGUE]
