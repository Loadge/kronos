"""Set-up for tests that only need a payout to exist: one leg, in an account in the source's
currency, worth the amount given. What such a test asserts is the payout's figures, not how it
was written."""

from __future__ import annotations


def account_in(client, source_id: int) -> int:
    """An account in the source's currency (made, as "Paid in <CUR>", the first time)."""
    currency = next(
        s["currency"] for s in client.get("/api/freelance/sources").json() if s["id"] == source_id
    )
    for a in client.get("/api/freelance/accounts").json():
        if a["currency"] == currency and a["name"] == f"Paid in {currency}":
            return a["id"]
    r = client.post(
        "/api/freelance/accounts", json={"name": f"Paid in {currency}", "currency": currency}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def body(
    client, source_id: int, week_start: str, amount: float, fx_rate=None, account_id=None, **extra
) -> dict:
    """A request body of one leg. `fx_rate` (units per EUR, what a payout used to be given by
    hand) becomes the euro value that gives it: `eur_amount` = amount / rate, so that the server
    works the same rate back out of the two (checked: it must come back to the digit)."""
    if fx_rate is not None:
        extra["eur_amount"] = amount / fx_rate
        assert amount / extra["eur_amount"] == fx_rate, "pick a rate that survives the division"
    into = account_in(client, source_id) if account_id is None else account_id
    legs = [{"account_id": into, "amount": amount}]
    return {"source_id": source_id, "week_start": week_start, "legs": legs, **extra}


def post(client, source_id: int, week_start: str, amount: float, **extra) -> dict:
    r = client.post(
        "/api/freelance/payouts", json=body(client, source_id, week_start, amount, **extra)
    )
    assert r.status_code == 201, r.text
    return r.json()
