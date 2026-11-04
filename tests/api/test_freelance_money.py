"""Payouts in the freelance money: a (source, ISO week) with a payout counts the payout, spread
over the week's days by the blocks' estimates; a week without one counts the estimates.

Every figure is worked out by hand in a comment. Sources: U = USD $60/h, E = EUR 50/h. Every
USD block and payout carries its fx_rate explicitly (or has none on purpose): the ECB is never
asked, `fx.for_date` answers "unavailable".
"""

from __future__ import annotations

import app.services.fx as fx
import pytest


@pytest.fixture(autouse=True)
def _no_ecb(monkeypatch):
    monkeypatch.setattr(fx, "for_date", lambda on, now=None: {"available": False})


def _source(client, name, rate, currency) -> int:
    r = client.post(
        "/api/freelance/sources", json={"name": name, "hourly_rate": rate, "currency": currency}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _block(client, day, source, hours, fx_rate=None) -> dict:
    body = {"date": day, "source_id": source, "hours": hours}
    if fx_rate is not None:
        body["fx_rate"] = fx_rate
    r = client.post("/api/freelance/blocks", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _payout(client, monday, source, amount, fx_rate=None) -> dict:
    body = {"source_id": source, "week_start": monday, "amount": amount}
    if fx_rate is not None:
        body["fx_rate"] = fx_rate
    r = client.post("/api/freelance/payouts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def world(client):
    """The three weeks of the specification's worked example."""
    u = _source(client, "U", 60, "USD")
    e = _source(client, "E", 50, "EUR")
    w = {"u": u, "e": e}
    # Week Mon 2025-12-29 crosses the year. U blocks: Dec 30 3 h at fx 1.2 = 180 / 1.2 = 150.00
    # and Jan 2 2 h = 120 / 1.2 = 100.00. U payout $330 at fx 1.1 = 300.00, spread 3:2 =
    # 180.00 on Dec 30 and 120.00 on Jan 2 (and $198.00 / $132.00 in dollars).
    w["b_dec30"] = _block(client, "2025-12-30", u, 3, 1.2)
    w["b_jan2"] = _block(client, "2026-01-02", u, 2, 1.2)
    w["p_dec29"] = _payout(client, "2025-12-29", u, 330, 1.1)
    # Week Mon 2026-01-05: E blocks Jan 5 4 h = 200.00 and Jan 7 2 h = 100.00; E payout
    # 250.00 spread 2:1 = 166.666.. and 83.333..: largest remainder gives 166.67 and 83.33.
    w["b_jan5"] = _block(client, "2026-01-05", e, 4)
    w["b_jan7"] = _block(client, "2026-01-07", e, 2)
    w["p_jan5"] = _payout(client, "2026-01-05", e, 250)
    # Week Mon 2026-01-12: U payout $110 at fx 1.1 = 100.00 and no U blocks (one line on
    # Sunday Jan 18 with 0 minutes); E block Jan 13 3 h = 150.00 with no E payout: estimated.
    w["p_jan12"] = _payout(client, "2026-01-12", u, 110, 1.1)
    w["b_jan13"] = _block(client, "2026-01-13", e, 3)
    return w


def _summary(client, year, today):
    r = client.get(f"/api/freelance/summary?year={year}&today={today}")
    assert r.status_code == 200, r.text
    return r.json()


class TestWeekCrossingTheYear:
    def test_2025_gets_the_dec_30_share(self, client, world):
        s = _summary(client, 2025, "2026-02-01")
        assert s["total"]["gross_eur"] == 180.0
        assert s["total"]["hours"] == 3.0
        assert s["total"]["paid_out_eur"] == 180.0
        assert s["total"]["estimated_eur"] == 0.0

    def test_2026_gets_the_jan_2_share(self, client, world):
        # 2026 total: 120.00 + 166.67 + 83.33 + 100.00 + 150.00 = 620.00; the Jan 2 block is
        # the only one of the crossing week that falls in 2026.
        by_source = {x["name"]: x for x in _summary(client, 2026, "2026-02-01")["by_source"]}
        assert by_source["U"]["gross_eur"] == 220.0  # 120.00 + the $110 payout's 100.00
        assert by_source["U"]["hours"] == 2.0


class TestYear2026:
    def test_the_totals(self, client, world):
        s = _summary(client, 2026, "2026-02-01")
        # hours: Jan 2 2 h + Jan 5 4 h + Jan 7 2 h + Jan 13 3 h = 11 h; 620.00 / 11 = 56.3636
        assert s["total"] == {
            "hours": 11.0,
            "gross_eur": 620.0,
            "eur_per_hour": 56.36,
            "blocks": 4,  # Jan 2, 5, 7, 13: the payout-only line is not a block
            "missing_fx": 0,
            "paid_out_eur": 470.0,  # 120.00 + 250.00 + 100.00
            "estimated_eur": 150.0,  # the E block of Jan 13
        }

    def test_month_and_quarter_use_the_payouts(self, client, world):
        s = _summary(client, 2026, "2026-02-01")
        assert s["by_month"][0]["gross_eur"] == 620.0
        assert s["quarters"][0]["gross_eur"] == 620.0
        assert s["projection"]["rate_eur"] == 56.36  # the realised rate, not the estimates'

    def test_the_week_without_a_payout_is_awaited(self, client, world):
        # Only E's week of Jan 12 has blocks and no payout, and its Sunday (Jan 18) is past.
        assert _summary(client, 2026, "2026-02-01")["awaiting_payout"] == 1
        # Before that Sunday it is still running, not awaited.
        assert _summary(client, 2026, "2026-01-18")["awaiting_payout"] == 0

    def test_by_source_gross_and_amount(self, client, world):
        by_source = {x["name"]: x for x in _summary(client, 2026, "2026-02-01")["by_source"]}
        # U: the $330 payout's $132.00 on Jan 2 plus the $110 payout = $242.00; E: 250 + 150.
        assert (by_source["U"]["gross_eur"], by_source["U"]["amount"]) == (220.0, 242.0)
        assert (by_source["E"]["gross_eur"], by_source["E"]["amount"]) == (400.0, 400.0)

    def test_the_blocks_endpoint_shows_what_counts(self, client, world):
        rows = client.get("/api/freelance/blocks?from=2026-01-01&to=2026-01-31").json()
        by_id = {r["id"]: r for r in rows}
        jan2 = by_id[world["b_jan2"]["id"]]
        assert jan2["effective_eur"] == 120.0
        assert jan2["payout_id"] == world["p_dec29"]["id"]
        assert jan2["amount_eur"] == 100.0  # its own estimate is still reported
        assert by_id[world["b_jan5"]["id"]]["effective_eur"] == 166.67
        assert by_id[world["b_jan7"]["id"]]["effective_eur"] == 83.33
        jan13 = by_id[world["b_jan13"]["id"]]
        assert jan13["effective_eur"] == 150.0
        assert jan13["payout_id"] is None
        single = client.get(f"/api/freelance/blocks/{world['b_jan2']['id']}").json()
        assert (single["effective_eur"], single["payout_id"]) == (120.0, world["p_dec29"]["id"])

    def test_the_payouts_endpoint_carries_the_estimate_to_compare(self, client, world):
        rows = {p["id"]: p for p in client.get("/api/freelance/payouts").json()}
        crossing = rows[world["p_dec29"]["id"]]
        assert (crossing["blocks"], crossing["minutes"]) == (2, 300)
        assert (crossing["estimate_eur"], crossing["estimate_amount"]) == (250.0, 300.0)
        only = rows[world["p_jan12"]["id"]]
        assert (only["blocks"], only["minutes"]) == (0, 0)
        assert (only["estimate_eur"], only["estimate_amount"]) == (0.0, 0.0)


class TestMissingRate:
    def test_a_usd_payout_without_a_rate_is_missing_not_one_to_one(self, client):
        u = _source(client, "U", 60, "USD")
        _block(client, "2026-02-03", u, 1, 1.2)  # 60 / 1.2 = 50.00 estimated
        _payout(client, "2026-02-02", u, 100)  # no fx_rate, and none is available
        s = _summary(client, 2026, "2026-03-01")
        # The estimate is NOT used (the payout decides), and $100 is not valued at 1:1.
        assert s["total"] == {
            "hours": 1.0,
            "gross_eur": 0.0,
            "eur_per_hour": 0.0,
            "blocks": 1,
            "missing_fx": 1,
            "paid_out_eur": 0.0,
            "estimated_eur": 0.0,
        }
        row = client.get("/api/freelance/blocks").json()[0]
        assert (row["effective_eur"], row["amount_eur"]) == (None, 50.0)


class TestWeights:
    def test_a_block_without_an_estimate_makes_the_split_go_by_minutes(self, client):
        u = _source(client, "U", 60, "USD")
        a = _block(client, "2026-03-02", u, 2, 1.2)  # estimate 100.00
        b = _block(client, "2026-03-03", u, 1)  # no rate: no estimate
        # $330 at 1.1 = 300.00, split by minutes 120:60 = 200.00 / 100.00. By the one estimate
        # that exists it would be all on the first block.
        _payout(client, "2026-03-02", u, 330, 1.1)
        rows = {r["id"]: r for r in client.get("/api/freelance/blocks").json()}
        assert rows[a["id"]]["effective_eur"] == 200.0
        assert rows[b["id"]]["effective_eur"] == 100.0
        assert _summary(client, 2026, "2026-04-01")["total"]["missing_fx"] == 0


class TestAWeekWithoutPayoutsIsUnchanged:
    def test_the_whole_summary_is_what_it_was_before_payouts(self, client):
        u = _source(client, "U", 60, "USD")
        e = _source(client, "E", 50, "EUR")
        # Blocks: Jan 5 3 h USD at 1.25, Jan 7 2 h EUR, Feb 10 1 h USD with no rate,
        # Apr 14 1.5 h EUR, Apr 15 1.25 h USD at 1.2. No payouts at all.
        _block(client, "2026-01-05", u, 3, 1.25)
        _block(client, "2026-01-07", e, 2)
        _block(client, "2026-02-10", u, 1)
        _block(client, "2026-04-14", e, 1.5)
        _block(client, "2026-04-15", u, 1.25, 1.2)
        got = _summary(client, 2026, "2026-04-20")
        # Captured from the code before the payouts rule existed; the keys it added are
        # taken out here, so this fails if a number of a week without payouts moves.
        for part in [got["total"], got["week"], got["month"], *got["by_month"], *got["by_source"]]:
            part.pop("paid_out_eur")
            part.pop("estimated_eur")
        got.pop("awaiting_payout")
        assert got == PINNED_SUMMARY


PINNED_SUMMARY = {
    "by_month": [
        {
            "blocks": 2,
            "eur_per_hour": 48.8,
            "gross_eur": 244.0,
            "hours": 5.0,
            "missing_fx": 0,
            "month": 1,
        },
        {
            "blocks": 1,
            "eur_per_hour": 0.0,
            "gross_eur": 0.0,
            "hours": 1.0,
            "missing_fx": 1,
            "month": 2,
        },
        {
            "blocks": 0,
            "eur_per_hour": 0.0,
            "gross_eur": 0.0,
            "hours": 0.0,
            "missing_fx": 0,
            "month": 3,
        },
        {
            "blocks": 2,
            "eur_per_hour": 50.0,
            "gross_eur": 137.5,
            "hours": 2.75,
            "missing_fx": 0,
            "month": 4,
        },
        {
            "blocks": 0,
            "eur_per_hour": 0.0,
            "gross_eur": 0.0,
            "hours": 0.0,
            "missing_fx": 0,
            "month": 5,
        },
        {
            "blocks": 0,
            "eur_per_hour": 0.0,
            "gross_eur": 0.0,
            "hours": 0.0,
            "missing_fx": 0,
            "month": 6,
        },
        {
            "blocks": 0,
            "eur_per_hour": 0.0,
            "gross_eur": 0.0,
            "hours": 0.0,
            "missing_fx": 0,
            "month": 7,
        },
        {
            "blocks": 0,
            "eur_per_hour": 0.0,
            "gross_eur": 0.0,
            "hours": 0.0,
            "missing_fx": 0,
            "month": 8,
        },
        {
            "blocks": 0,
            "eur_per_hour": 0.0,
            "gross_eur": 0.0,
            "hours": 0.0,
            "missing_fx": 0,
            "month": 9,
        },
        {
            "blocks": 0,
            "eur_per_hour": 0.0,
            "gross_eur": 0.0,
            "hours": 0.0,
            "missing_fx": 0,
            "month": 10,
        },
        {
            "blocks": 0,
            "eur_per_hour": 0.0,
            "gross_eur": 0.0,
            "hours": 0.0,
            "missing_fx": 0,
            "month": 11,
        },
        {
            "blocks": 0,
            "eur_per_hour": 0.0,
            "gross_eur": 0.0,
            "hours": 0.0,
            "missing_fx": 0,
            "month": 12,
        },
    ],
    "by_source": [
        {
            "amount": 315.0,
            "blocks": 3,
            "currency": "USD",
            "eur_per_hour": 39.33,
            "gross_eur": 206.5,
            "hours": 5.25,
            "missing_fx": 1,
            "name": "U",
            "source_id": 1,
        },
        {
            "amount": 175.0,
            "blocks": 2,
            "currency": "EUR",
            "eur_per_hour": 50.0,
            "gross_eur": 175.0,
            "hours": 3.5,
            "missing_fx": 0,
            "name": "E",
            "source_id": 2,
        },
    ],
    "month": {
        "blocks": 2,
        "eur_per_hour": 50.0,
        "gross_eur": 137.5,
        "hours": 2.75,
        "missing_fx": 0,
    },
    "projection": {
        "days_off": 0.0,
        "eur_per_hour_gross": 43.6,
        "eur_per_hour_net": -238.75,
        "figures": {
            "employment_net": 0.0,
            "expenses": 0.0,
            "fiscal_year": 2026,
            "gestoria": 0.0,
            "gross": 381.5,
            "hard_to_justify": 0.0,
            "irpf": 0.0,
            "irpf_effective": 0.0,
            "net": -2089.07,
            "net_share": -5.4759,
            "other_expenses": 0.0,
            "pago_fraccionado": 0.0,
            "region": "Andalucía",
            "reintegro": 0.0,
            "renta": 0.0,
            "reta_annual": 2470.57,
            "reta_base": 653.59,
            "reta_monthly": 205.88,
            "reta_monthly_yield": 29.57,
            "reta_tramo": 1,
            "salary": 0.0,
            "startup_reduction": 0.0,
            "tarifa_plana": False,
            "taxable": -2089.07,
        },
        "hours_per_week": 0.0,
        "planned_gross_eur": 0.0,
        "planned_hours": 0.0,
        "projected_gross_eur": 381.5,
        "projected_hours": 8.75,
        "rate_basis": "realised",
        "rate_eur": 43.6,
        "weeks_left": 36.43,
    },
    "quarters": [
        {
            "cumulative": 0.0,
            "deadline": "2026-04-20",
            "fixed_ytd": 617.64,
            "from": "2026-01-01",
            "gross_eur": 244.0,
            "gross_ytd": 244.0,
            "hours": 6.0,
            "label": "Q1",
            "payment": 0.0,
            "quarter": 1,
            "status": "due",
            "to": "2026-03-31",
            "yield_ytd": 0.0,
        },
        {
            "cumulative": 0.0,
            "deadline": "2026-07-20",
            "fixed_ytd": 1235.29,
            "from": "2026-04-01",
            "gross_eur": 137.5,
            "gross_ytd": 381.5,
            "hours": 2.75,
            "label": "Q2",
            "payment": 0.0,
            "quarter": 2,
            "status": "current",
            "to": "2026-06-30",
            "yield_ytd": 0.0,
        },
        {
            "cumulative": 0.0,
            "deadline": "2026-10-20",
            "fixed_ytd": 1852.93,
            "from": "2026-07-01",
            "gross_eur": 0.0,
            "gross_ytd": 381.5,
            "hours": 0.0,
            "label": "Q3",
            "payment": 0.0,
            "quarter": 3,
            "status": "future",
            "to": "2026-09-30",
            "yield_ytd": 0.0,
        },
        {
            "cumulative": 0.0,
            "deadline": "2027-01-30",
            "fixed_ytd": 2470.57,
            "from": "2026-10-01",
            "gross_eur": 0.0,
            "gross_ytd": 381.5,
            "hours": 0.0,
            "label": "Q4",
            "payment": 0.0,
            "quarter": 4,
            "status": "future",
            "to": "2026-12-31",
            "yield_ytd": 0.0,
        },
    ],
    "set_aside": {"month": 55.0, "week": 0.0, "year": 152.6},
    "set_aside_share": 0.4,
    "tax_inputs": {
        "gestoria_annual": 0.0,
        "inherited_from": None,
        "inicio_actividad": False,
        "is_default": True,
        "other_expenses": 0.0,
        "salary_annual": 0.0,
        "set_aside_share": 0.4,
        "tarifa_plana": False,
        "year": 2026,
    },
    "today": "2026-04-20",
    "total": {
        "blocks": 5,
        "eur_per_hour": 43.6,
        "gross_eur": 381.5,
        "hours": 8.75,
        "missing_fx": 1,
    },
    "week": {"blocks": 0, "eur_per_hour": 0.0, "gross_eur": 0.0, "hours": 0.0, "missing_fx": 0},
    "year": 2026,
}
