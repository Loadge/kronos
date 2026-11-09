"""Payouts on the freelance sheet and in their own CSV.

The sheet tells the same truth as the app: a week with a payout prints a payout line under its
blocks and the totals count the payout (through ``freelance.money_lines``, the one money rule).
Without payouts the sheet is what it was before payouts existed, byte for byte.
"""

from __future__ import annotations

import csv
import hashlib
import io

import app.services.fx as fx
import pytest

FX = 1.1172  # USD per EUR

SHEET = "/timesheet/freelance?from=2026-10-01&to=2026-11-30&notes=1&sign=1&today=2026-11-02"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    fx._reset()
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-03-06"><Cube currency="USD" rate="1.1172"/></Cube>
  </Cube>
</gesmes:Envelope>
"""
    monkeypatch.setattr(fx, "_fetch", lambda url, timeout=3: xml.encode())
    monkeypatch.setenv("KRONOS_FX_URL", "https://fx.example.invalid/daily.xml")
    monkeypatch.setenv("KRONOS_FX_HIST90_URL", "https://fx.example.invalid/90d.xml")
    monkeypatch.setenv("KRONOS_FX_HIST_URL", "https://fx.example.invalid/all.xml")
    yield
    fx._reset()


def _source(client, name, rate, currency) -> int:
    r = client.post(
        "/api/freelance/sources", json={"name": name, "hourly_rate": rate, "currency": currency}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _block(client, **body):
    r = client.post("/api/freelance/blocks", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _payout(client, **body):
    r = client.post("/api/freelance/payouts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _data(client):
    """A dollar week (Tue 27 Oct, 2.5 h) and a euro week (Mon 2 Nov, 1.5 h), no payouts."""
    usd = _source(client, "Northwind", 95, "USD")
    eur = _source(client, "Local", 60, "EUR")
    _block(
        client,
        date="2026-10-27",
        source_id=usd,
        start_time="19:00",
        end_time="21:30",
        fx_rate=FX,
        notes="call",
    )
    _block(client, date="2026-11-02", source_id=eur, hours=1.5, notes="fix")
    return usd, eur


class TestSheetWithoutPayouts:
    def test_the_sheet_is_what_it_was_before_payouts(self, client):
        """Pinned from the sheet rendered before payouts touched the builder (re-pinned when
        its inline handlers and script moved to /static/timesheet.js for the content security
        policy: that is the only markup that changed)."""
        _data(client)
        html = client.get(SHEET).text
        assert hashlib.sha256(html.encode()).hexdigest() == (
            "c4b2951a856c6ee1cb19ca8234f5fcb717e76da57bf4b896858dfa9ecca4e1b3"
        )


class TestSheetWithPayouts:
    def test_a_paid_week_prints_its_payout_and_the_totals_count_it(self, client):
        usd, eur = _data(client)
        # The dollar week: 2.5 h x $95 = $237.50 estimated; the client paid $300.00 at 1.1172
        # = 268.53 EUR. The euro week (1.5 h x 60 = 90.00) has no payout and counts its estimate.
        _payout(client, source_id=usd, week_start="2026-10-26", amount=300, fx_rate=FX)
        t = client.get(SHEET).text
        row = "W44 payout $300.00 · +$62.50 over the estimate"
        assert row in t
        block_at, payout_at = t.index('data-date="2026-10-27"'), t.index('class="row-payout')
        assert block_at < payout_at < t.index('data-date="2026-11-02"')  # under its own week
        assert "€212.59" in t  # the block row keeps its own estimate
        assert "€358.53" in t  # 268.53 + 90.00 in the totals
        assert "Weeks with a payout" not in t and "A payout line gives" in t

    def test_the_app_and_the_sheet_agree_to_the_cent(self, client):
        usd, eur = _data(client)
        _payout(client, source_id=usd, week_start="2026-10-26", amount=300, fx_rate=FX)
        gross = client.get("/api/freelance/summary?year=2026").json()["total"]["gross_eur"]
        assert gross == 358.53
        assert f"€{gross:,.2f}" in client.get(SHEET).text

    def test_a_payout_of_a_week_with_no_blocks_prints_alone(self, client):
        usd, eur = _data(client)
        _payout(client, source_id=eur, week_start="2026-11-09", amount=75)  # Sunday 15 Nov
        t = client.get(SHEET).text
        assert "W46 payout €75.00 · no blocks that week" in t
        assert "A payout line gives" in t
        # a payout outside the range prints nothing
        out = client.get("/timesheet/freelance?from=2026-10-01&to=2026-11-08&today=2026-11-02").text
        assert "W46 payout" not in out

    def test_a_payout_of_an_unticked_source_is_left_out(self, client):
        usd, eur = _data(client)
        _payout(client, source_id=usd, week_start="2026-10-26", amount=300, fx_rate=FX)
        t = client.get(f"/timesheet/freelance?from=2026-10-01&to=2026-11-30&sources={eur}").text
        assert "row-payout" not in t and "W44 payout" not in t


class TestPayoutsCsv:
    def test_header_and_one_row(self, client):
        usd, eur = _data(client)
        _payout(client, source_id=usd, week_start="2026-10-26", amount=300, fx_rate=FX, note="a, b")
        r = client.get("/api/freelance/payouts.csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert 'filename="kronos_freelance_payouts.csv"' in r.headers["content-disposition"]
        rows = list(csv.reader(io.StringIO(r.text)))
        assert rows[0] == [
            "week_start",
            "week_end",
            "source",
            "currency",
            "amount",
            "fx_rate",
            "amount_eur",
            "estimate_amount",
            "estimate_eur",
            "blocks",
            "hours",
            "note",
            "account",
            "rate_source",
            "rate_date",
            "billed_amount",
            "billed_eur",
            "fx_cost_eur",
            "sent_amount",
            "sent_currency",
            "from_account",
        ]
        # $300.00 / 1.1172 = 268.53; its week held 2.5 h x $95 = $237.50 = 212.59 EUR
        assert rows[1] == [
            "2026-10-26",
            "2026-11-01",
            "Northwind",
            "USD",
            "300.00",
            "1.1172",
            "268.53",
            "237.50",
            "212.59",
            "1",
            "2.50",
            "a, b",
            "",
            "manual",
            "2026-11-01",
            "237.50",
            "212.59",
            "",
            "",
            "",
            "",
        ]
        assert len(rows) == 2

    def test_oldest_week_first_and_not_read_as_an_id(self, client):
        usd, eur = _data(client)
        _payout(client, source_id=eur, week_start="2026-11-02", amount=80)
        _payout(client, source_id=usd, week_start="2026-10-26", amount=300, fx_rate=FX)
        rows = list(csv.reader(io.StringIO(client.get("/api/freelance/payouts.csv").text)))
        assert [r[0] for r in rows[1:]] == ["2026-10-26", "2026-11-02"]
        assert rows[2][6:9] == ["80.00", "90.00", "90.00"]  # EUR: no rate, estimate = blocks
        assert client.get("/api/freelance/payouts.csv").status_code != 422

    def test_empty_is_the_header_alone(self, client):
        r = client.get("/api/freelance/payouts.csv")
        assert r.status_code == 200 and len(r.text.strip().splitlines()) == 1


class TestSeedPayouts:
    def test_the_sample_data_has_paid_over_paid_under_and_one_unpaid_week(self, client):
        from datetime import date, timedelta

        for _ in range(2):  # a second seed gives the same: the wipe takes the payouts too
            assert client.post("/api/data/seed").status_code == 200
            payouts = client.get("/api/freelance/payouts").json()
            assert 3 <= len(payouts) <= 4
            by_cur = {p["currency"]: [] for p in payouts}
            for p in payouts:
                by_cur[p["currency"]].append(round(p["amount"] - p["estimate_amount"], 2))
            assert max(by_cur["USD"]) > 0 and min(by_cur["EUR"]) < 0
        blocks = client.get("/api/freelance/blocks").json()
        today = date.today()
        finished = {
            date.fromisoformat(b["date"]) - timedelta(days=date.fromisoformat(b["date"]).weekday())
            for b in blocks
            if date.fromisoformat(b["date"])
            - timedelta(days=date.fromisoformat(b["date"]).weekday())
            + timedelta(days=6)
            < today
        }
        latest = max(finished)
        assert latest.isoformat() not in {p["week_start"] for p in payouts}
