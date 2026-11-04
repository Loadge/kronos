"""Freelance payouts: what a source actually paid for an ISO week.

One row per source and week, in the source's currency, with the ECB rate of the week's Sunday
for USD. Only storage here: a payout changes no sum yet (that is a later unit). The exchange
rate is never guessed: a USD payout with no rate keeps ``fx_rate`` null, and so ``amount_eur``.
"""

from __future__ import annotations

from datetime import date

import app.services.fx as fx
import pytest

FX = 1.1172  # USD per EUR, the ECB document below has its last publication on Friday 2026-03-06

MONDAY = "2026-03-02"
SUNDAY = date(2026, 3, 8)
NEXT_MONDAY = "2026-03-09"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Saving a USD payout asks the ECB for the Sunday's rate: answer from a fixed document."""
    fx._reset()
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-03-13"><Cube currency="USD" rate="1.1300"/></Cube>
    <Cube time="2026-03-06"><Cube currency="USD" rate="1.1172"/></Cube>
    <Cube time="2026-03-05"><Cube currency="USD" rate="1.1150"/></Cube>
  </Cube>
</gesmes:Envelope>
"""
    monkeypatch.setattr(fx, "_fetch", lambda url, timeout=3: xml.encode())
    monkeypatch.setenv("KRONOS_FX_URL", "https://fx.example.invalid/daily.xml")
    monkeypatch.setenv("KRONOS_FX_HIST90_URL", "https://fx.example.invalid/90d.xml")
    monkeypatch.setenv("KRONOS_FX_HIST_URL", "https://fx.example.invalid/all.xml")
    yield
    fx._reset()


@pytest.fixture
def asked(monkeypatch) -> list[date]:
    """Every date the ECB is asked for, while still answering from the fixed document."""
    real = fx.for_date
    dates: list[date] = []

    def spy(on, now=None):
        dates.append(on)
        return real(on, now)

    monkeypatch.setattr(fx, "for_date", spy)
    return dates


def _source(client, name="Northwind", rate=95, currency="USD", **kw) -> int:
    r = client.post(
        "/api/freelance/sources",
        json={"name": name, "hourly_rate": rate, "currency": currency, **kw},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _payout(client, **body):
    r = client.post("/api/freelance/payouts", json=body)
    assert r.status_code == 201, r.text
    return r.json()


class TestCreate:
    def test_eur_payout_has_no_rate_and_amount_eur_is_the_amount(self, client):
        a = _source(client, "Acme", 60, "EUR")
        p = _payout(client, source_id=a, week_start=MONDAY, amount=900, note="  march  ")
        assert (p["currency"], p["fx_rate"], p["amount"], p["amount_eur"]) == (
            "EUR",
            None,
            900.0,
            900.0,
        )
        assert (p["week_start"], p["week_end"], p["note"]) == (MONDAY, "2026-03-08", "march")

    def test_eur_ignores_a_given_fx_rate(self, client):
        a = _source(client, "Acme", 60, "EUR")
        p = _payout(client, source_id=a, week_start=MONDAY, amount=100, fx_rate=1.2)
        assert p["fx_rate"] is None and p["amount_eur"] == 100.0

    def test_usd_takes_the_rate_of_the_weeks_sunday(self, client, asked):
        a = _source(client)
        p = _payout(client, source_id=a, week_start=MONDAY, amount=1117.2)
        assert asked == [SUNDAY]  # the Sunday, not the Monday
        # the ECB did not publish on the weekend: Friday's rate is the one in force
        assert p["currency"] == "USD" and p["fx_rate"] == FX
        # 1117.20 / 1.1172 = 1000.00
        assert p["amount_eur"] == 1000.0

    def test_usd_with_a_given_rate_does_not_ask_the_ecb(self, client, asked):
        a = _source(client)
        p = _payout(client, source_id=a, week_start=MONDAY, amount=1200, fx_rate=1.2)
        assert asked == []
        assert (p["fx_rate"], p["amount_eur"]) == (1.2, 1000.0)

    def test_usd_without_any_rate_is_saved_with_null_never_one_to_one(self, client, monkeypatch):
        monkeypatch.setattr(fx, "for_date", lambda on, now=None: {"available": False})
        a = _source(client)
        p = _payout(client, source_id=a, week_start=MONDAY, amount=500)
        assert p["fx_rate"] is None and p["amount_eur"] is None
        assert p["amount"] == 500.0

    def test_a_non_monday_is_422(self, client):
        a = _source(client)
        for day in ("2026-03-03", "2026-03-08"):
            r = client.post(
                "/api/freelance/payouts", json={"source_id": a, "week_start": day, "amount": 10}
            )
            assert r.status_code == 422, day

    def test_amount_must_be_positive(self, client):
        a = _source(client)
        for amount in (0, -5):
            r = client.post(
                "/api/freelance/payouts",
                json={"source_id": a, "week_start": MONDAY, "amount": amount},
            )
            assert r.status_code == 422

    def test_a_second_payout_for_the_same_source_and_week_is_409(self, client):
        a = _source(client)
        _payout(client, source_id=a, week_start=MONDAY, amount=100)
        r = client.post(
            "/api/freelance/payouts", json={"source_id": a, "week_start": MONDAY, "amount": 5}
        )
        assert r.status_code == 409
        assert len(client.get("/api/freelance/payouts").json()) == 1

    def test_the_same_week_for_another_source_is_fine(self, client):
        a, b = _source(client, "A"), _source(client, "B", 60, "EUR")
        _payout(client, source_id=a, week_start=MONDAY, amount=100)
        _payout(client, source_id=b, week_start=MONDAY, amount=100)
        assert len(client.get("/api/freelance/payouts").json()) == 2

    def test_unknown_source_is_404(self, client):
        r = client.post(
            "/api/freelance/payouts", json={"source_id": 99, "week_start": MONDAY, "amount": 1}
        )
        assert r.status_code == 404

    def test_an_archived_source_still_takes_payouts(self, client):
        # Same as blocks: nothing rejects an archived source, it is only hidden from the picker.
        _source(client, "Default")
        old = _source(client, "Old", 60, "EUR", archived=True)
        r = client.post(
            "/api/freelance/payouts", json={"source_id": old, "week_start": MONDAY, "amount": 1}
        )
        assert r.status_code == 201


class TestReadUpdateDelete:
    def test_get_one_and_404(self, client):
        a = _source(client)
        p = _payout(client, source_id=a, week_start=MONDAY, amount=100, fx_rate=1.25)
        assert client.get(f"/api/freelance/payouts/{p['id']}").json() == p
        assert client.get("/api/freelance/payouts/999").status_code == 404

    def test_put_keeps_the_stored_rate_when_the_week_and_source_stay(self, client, asked):
        a = _source(client)
        p = _payout(client, source_id=a, week_start=MONDAY, amount=100, fx_rate=1.25)
        r = client.put(
            f"/api/freelance/payouts/{p['id']}",
            json={"source_id": a, "week_start": MONDAY, "amount": 250, "note": "fixed"},
        )
        assert r.status_code == 200
        body = r.json()
        assert (body["amount"], body["fx_rate"], body["note"]) == (250.0, 1.25, "fixed")
        assert body["amount_eur"] == 200.0  # 250 / 1.25
        assert asked == []

    def test_put_with_a_rate_overrides_it(self, client):
        a = _source(client)
        p = _payout(client, source_id=a, week_start=MONDAY, amount=100, fx_rate=1.25)
        body = client.put(
            f"/api/freelance/payouts/{p['id']}",
            json={"source_id": a, "week_start": MONDAY, "amount": 100, "fx_rate": 1.0},
        ).json()
        assert body["fx_rate"] == 1.0

    def test_put_changing_the_week_asks_the_ecb_for_the_new_sunday(self, client, asked):
        a = _source(client)
        p = _payout(client, source_id=a, week_start=MONDAY, amount=100)
        assert asked == [SUNDAY]
        r = client.put(
            f"/api/freelance/payouts/{p['id']}",
            json={"source_id": a, "week_start": NEXT_MONDAY, "amount": 100},
        )
        assert r.status_code == 200
        assert asked == [SUNDAY, date(2026, 3, 15)]
        # the Sunday 2026-03-15 is covered by Friday the 13th's publication
        assert r.json()["fx_rate"] == 1.13
        assert r.json()["week_end"] == "2026-03-15"

    def test_put_changing_the_source_recopies_the_currency(self, client):
        usd = _source(client)
        eur = _source(client, "Acme", 60, "EUR")
        p = _payout(client, source_id=usd, week_start=MONDAY, amount=100)
        assert p["currency"] == "USD" and p["fx_rate"] == FX
        body = client.put(
            f"/api/freelance/payouts/{p['id']}",
            json={"source_id": eur, "week_start": MONDAY, "amount": 100},
        ).json()
        assert (body["currency"], body["fx_rate"], body["amount_eur"]) == ("EUR", None, 100.0)

    def test_put_onto_another_payouts_week_is_409(self, client):
        a = _source(client)
        _payout(client, source_id=a, week_start=MONDAY, amount=1)
        other = _payout(client, source_id=a, week_start=NEXT_MONDAY, amount=1)
        r = client.put(
            f"/api/freelance/payouts/{other['id']}",
            json={"source_id": a, "week_start": MONDAY, "amount": 1},
        )
        assert r.status_code == 409

    def test_put_unknown_payout_404_and_non_monday_422(self, client):
        a = _source(client)
        ok = {"source_id": a, "week_start": MONDAY, "amount": 1}
        assert client.put("/api/freelance/payouts/999", json=ok).status_code == 404
        p = _payout(client, **ok)
        bad = {**ok, "week_start": "2026-03-04"}
        assert client.put(f"/api/freelance/payouts/{p['id']}", json=bad).status_code == 422

    def test_delete(self, client):
        a = _source(client)
        p = _payout(client, source_id=a, week_start=MONDAY, amount=1)
        assert client.delete(f"/api/freelance/payouts/{p['id']}").status_code == 204
        assert client.get(f"/api/freelance/payouts/{p['id']}").status_code == 404
        assert client.delete(f"/api/freelance/payouts/{p['id']}").status_code == 404


class TestListFilters:
    def test_range_is_on_week_start_and_source_filters(self, client):
        a, b = _source(client, "A"), _source(client, "B", 60, "EUR")
        for source, week in (
            (a, "2026-02-23"),
            (a, MONDAY),
            (b, MONDAY),
            (a, NEXT_MONDAY),
            (a, "2026-03-16"),
        ):
            _payout(client, source_id=source, week_start=week, amount=10)

        def weeks(**params):
            rows = client.get("/api/freelance/payouts", params=params).json()
            return [(r["source_id"], r["week_start"]) for r in rows]

        assert [w for _, w in weeks()] == [
            "2026-02-23",
            MONDAY,
            MONDAY,
            NEXT_MONDAY,
            "2026-03-16",
        ]
        assert weeks(**{"from": MONDAY, "to": NEXT_MONDAY}) == [
            (a, MONDAY),
            (b, MONDAY),
            (a, NEXT_MONDAY),
        ]
        assert weeks(**{"from": NEXT_MONDAY}) == [(a, NEXT_MONDAY), (a, "2026-03-16")]
        assert weeks(to="2026-02-23") == [(a, "2026-02-23")]
        assert weeks(source_id=b) == [(b, MONDAY)]
        assert weeks(source_id=a, **{"from": MONDAY, "to": MONDAY}) == [(a, MONDAY)]


class TestSourceDeleteRule:
    def test_a_source_with_payouts_cannot_be_deleted(self, client):
        a = _source(client)
        p = _payout(client, source_id=a, week_start=MONDAY, amount=1)
        assert client.delete(f"/api/freelance/sources/{a}").status_code == 409
        client.delete(f"/api/freelance/payouts/{p['id']}")
        assert client.delete(f"/api/freelance/sources/{a}").status_code == 204

    def test_a_payout_only_source_lists_zero_blocks_and_still_refuses_delete(self, client):
        a = _source(client)
        _payout(client, source_id=a, week_start=MONDAY, amount=1)
        assert client.get("/api/freelance/sources").json()[0]["blocks"] == 0
        r = client.delete(f"/api/freelance/sources/{a}")
        assert r.status_code == 409
        assert "payouts" in r.json()["detail"]
