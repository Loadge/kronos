"""Freelance hours: sources, blocks, the tax inputs per year, the year's summary, the calculator,
the CSV.

Every money figure asserted here is worked out by hand in a comment (a calculator, not the
module's formulas); the two anchor cases of tests/unit/test_tax.py come out of /api/freelance/calc
to the cent. Blocks never move the employee's numbers: the dashboard, the entries and the
timesheet are the same with or without them.
"""

from __future__ import annotations

import app.services.fx as fx
import pytest

FX = 1.1172  # USD per EUR


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Saving a USD block asks the ECB for the day's rate: answer from a fixed document."""
    fx._reset()
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
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


def _source(client, name="Northwind", rate=95, currency="USD", **kw) -> int:
    r = client.post(
        "/api/freelance/sources",
        json={"name": name, "hourly_rate": rate, "currency": currency, **kw},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _block(client, **body):
    r = client.post("/api/freelance/blocks", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ── sources ───────────────────────────────────────────────────────────────────


class TestSources:
    def test_first_source_is_the_default_whatever_the_body_says(self, client):
        a = _source(client, "A", 50, "EUR", is_default=False)
        b = _source(client, "B", 60, "EUR")
        rows = client.get("/api/freelance/sources").json()
        assert [(s["id"], s["is_default"]) for s in rows] == [(a, True), (b, False)]

    def test_making_another_the_default_clears_the_old_one(self, client):
        a = _source(client, "A", 50, "EUR")
        b = _source(client, "B", 60, "EUR", is_default=True)
        rows = {s["id"]: s for s in client.get("/api/freelance/sources").json()}
        assert rows[a]["is_default"] is False and rows[b]["is_default"] is True
        client.put(f"/api/freelance/sources/{a}", json={"is_default": True})
        rows = {s["id"]: s for s in client.get("/api/freelance/sources").json()}
        assert rows[a]["is_default"] is True and rows[b]["is_default"] is False

    def test_validation(self, client):
        assert (
            client.post("/api/freelance/sources", json={"name": "", "hourly_rate": 1}).status_code
            == 422
        )
        assert (
            client.post("/api/freelance/sources", json={"name": "A", "hourly_rate": 0}).status_code
            == 422
        )
        r = client.post(
            "/api/freelance/sources", json={"name": "A", "hourly_rate": 1, "currency": "GBP"}
        )
        assert r.status_code == 422
        assert client.put("/api/freelance/sources/999", json={"name": "x"}).status_code == 404

    def test_a_source_with_blocks_is_archived_not_deleted(self, client):
        a = _source(client, "A", 50, "EUR")
        b = _source(client, "B", 60, "EUR")
        _block(client, date="2026-03-02", source_id=a, hours=2)
        r = client.delete(f"/api/freelance/sources/{a}")
        assert r.status_code == 409
        assert "archive" in r.json()["detail"]
        assert client.delete(f"/api/freelance/sources/{b}").status_code == 204
        r = client.put(f"/api/freelance/sources/{a}", json={"archived": True})
        assert r.json()["archived"] is True and r.json()["is_default"] is False
        assert r.json()["blocks"] == 1
        # the block keeps its label
        assert client.get("/api/freelance/blocks").json()[0]["source_name"] == "A"


# ── blocks ────────────────────────────────────────────────────────────────────


class TestBlocks:
    def test_eur_block_by_hours_bills_rate_times_hours(self, client):
        a = _source(client, "Local", 60, "EUR")
        b = _block(client, date="2026-03-02", source_id=a, hours=2.5, notes="  report  ")
        # 60 x 2.5 = 150.00
        assert (b["minutes"], b["hours"], b["rate"], b["currency"]) == (150, 2.5, 60, "EUR")
        assert (b["amount"], b["amount_eur"], b["fx_rate"]) == (150.0, 150.0, None)
        assert b["notes"] == "report" and b["source_name"] == "Local"
        assert b["start_time"] is None and b["end_time"] is None

    def test_block_by_times_fixes_the_hours(self, client):
        a = _source(client, "Local", 60, "EUR")
        b = _block(client, date="2026-03-02", source_id=a, start_time="18:00", end_time="19:45")
        assert (b["minutes"], b["hours"], b["start_time"], b["end_time"]) == (
            105,
            1.75,
            "18:00",
            "19:45",
        )
        assert b["amount"] == 105.0  # 60 x 1.75
        r = client.post(
            "/api/freelance/blocks",
            json={
                "date": "2026-03-02",
                "source_id": a,
                "start_time": "18:00",
                "end_time": "19:45",
                "hours": 3,
            },
        )
        assert r.status_code == 422 and "do not match" in r.text

    def test_usd_block_takes_the_ecb_rate_of_its_date_once(self, client):
        a = _source(client)  # USD 95/h
        # Saturday 2026-03-07: Friday the 6th's rate 1.1172
        b = _block(client, date="2026-03-07", source_id=a, hours=2)
        # 95 x 2 = 190 USD; / 1.1172 = 170.0680 EUR
        assert (b["amount"], b["fx_rate"], b["amount_eur"]) == (190.0, 1.1172, 170.07)
        # a later change of the source's rate leaves the block alone
        client.put(f"/api/freelance/sources/{a}", json={"hourly_rate": 120})
        again = client.get(f"/api/freelance/blocks/{b['id']}").json()
        assert again["rate"] == 95 and again["amount"] == 190.0
        # and a new block takes the new rate
        assert _block(client, date="2026-03-07", source_id=a, hours=1)["rate"] == 120

    def test_usd_block_with_a_hand_rate_and_a_hand_fx(self, client):
        a = _source(client)
        b = _block(client, date="2026-03-07", source_id=a, hours=1, rate=100, fx_rate=1.25)
        assert (b["rate"], b["fx_rate"], b["amount"], b["amount_eur"]) == (100, 1.25, 100.0, 80.0)

    def test_usd_block_without_a_rate_available_is_saved_with_none(self, client, monkeypatch):
        monkeypatch.setenv("KRONOS_FX_URL", "")
        a = _source(client)
        b = _block(client, date="2026-03-07", source_id=a, hours=2)
        assert b["fx_rate"] is None and b["amount_eur"] is None and b["amount"] == 190.0
        # the summary counts it as missing rather than valuing it 1:1
        s = client.get("/api/freelance/summary?year=2026&today=2026-03-10").json()
        assert s["total"]["missing_fx"] == 1 and s["total"]["gross_eur"] == 0
        assert s["total"]["hours"] == 2
        # a hand-set rate repairs it
        r = client.put(
            f"/api/freelance/blocks/{b['id']}",
            json={"date": "2026-03-07", "source_id": a, "hours": 2, "fx_rate": 1.1},
        )
        assert r.json()["amount_eur"] == 172.73  # 190 / 1.1 = 172.7272

    def test_update_keeps_the_snapshot_unless_asked(self, client):
        usd = _source(client)
        eur = _source(client, "Local", 60, "EUR")
        b = _block(client, date="2026-03-06", source_id=usd, hours=2)
        assert b["fx_rate"] == 1.1172
        client.put(f"/api/freelance/sources/{usd}", json={"hourly_rate": 120})
        # same source, more hours: the old rate and fx stay
        r = client.put(
            f"/api/freelance/blocks/{b['id']}",
            json={"date": "2026-03-06", "source_id": usd, "hours": 3, "notes": "longer"},
        ).json()
        assert (r["rate"], r["fx_rate"], r["hours"], r["notes"]) == (95, 1.1172, 3, "longer")
        # a hand rate
        r = client.put(
            f"/api/freelance/blocks/{b['id']}",
            json={"date": "2026-03-06", "source_id": usd, "hours": 3, "rate": 110},
        ).json()
        assert r["rate"] == 110
        # moving to the EUR source takes its rate and drops the fx
        r = client.put(
            f"/api/freelance/blocks/{b['id']}",
            json={"date": "2026-03-06", "source_id": eur, "hours": 3},
        ).json()
        assert (r["rate"], r["currency"], r["fx_rate"], r["amount_eur"]) == (60, "EUR", None, 180.0)

    def test_list_filters_and_delete(self, client):
        a = _source(client, "Local", 60, "EUR")
        _block(client, date="2025-12-31", source_id=a, hours=1)
        b = _block(client, date="2026-01-02", source_id=a, hours=1)
        _block(client, date="2026-02-02", source_id=a, hours=1)
        assert len(client.get("/api/freelance/blocks").json()) == 3
        assert len(client.get("/api/freelance/blocks?year=2026").json()) == 2
        assert [
            x["date"]
            for x in client.get("/api/freelance/blocks?from=2026-01-01&to=2026-01-31").json()
        ] == ["2026-01-02"]
        assert client.delete(f"/api/freelance/blocks/{b['id']}").status_code == 204
        assert client.delete(f"/api/freelance/blocks/{b['id']}").status_code == 404
        assert client.get(f"/api/freelance/blocks/{b['id']}").status_code == 404

    def test_validation(self, client):
        a = _source(client, "Local", 60, "EUR")
        bad = [
            {"date": "2026-03-02", "source_id": a},  # no duration
            {"date": "2026-03-02", "source_id": a, "hours": 0},
            {"date": "2026-03-02", "source_id": a, "hours": 25},
            {"date": "2026-03-02", "source_id": a, "start_time": "18:00"},  # half a range
            {"date": "2026-03-02", "source_id": a, "start_time": "19:00", "end_time": "18:00"},
            {"date": "2026-03-02", "source_id": 999, "hours": 1},  # unknown source
        ]
        for body in bad:
            assert client.post("/api/freelance/blocks", json=body).status_code == 422, body

    def test_blocks_never_touch_the_employee_side(self, client, work_body):
        client.post("/api/entries", json=work_body(date="2026-04-14"))  # 7h net, 8h target
        before = client.get("/api/dashboard?today=2026-04-14").json()
        sheet_before = client.get("/timesheet?from=2026-04-13&to=2026-04-17").text
        a = _source(client, "Local", 60, "EUR")
        _block(client, date="2026-04-14", source_id=a, hours=3)
        _block(client, date="2026-04-18", source_id=a, hours=4)  # a Saturday without an entry
        after = client.get("/api/dashboard?today=2026-04-14").json()
        assert after == before
        entry = client.get("/api/entries/2026-04-14").json()
        assert (entry["net_hours"], entry["surplus_hours"]) == (7.0, -1.0)
        assert client.get("/api/entries").json().__len__() == 1
        assert client.get("/timesheet?from=2026-04-13&to=2026-04-17").text == sheet_before
        streaks = client.get("/api/streaks?today=2026-04-14").json()
        assert streaks["total_logged_days"] == 1


# ── tax years ─────────────────────────────────────────────────────────────────


class TestTaxYears:
    def test_defaults_then_own_then_inherited(self, client):
        d = client.get("/api/freelance/tax-years/2026").json()
        assert d["is_default"] is True and d["inherited_from"] is None
        assert (d["salary_annual"], d["set_aside_share"], d["tarifa_plana"]) == (0, 0.4, False)
        assert (d["fiscal_year"], d["region"]) == (2026, "Andalucía")

        r = client.put(
            "/api/freelance/tax-years/2026",
            json={
                "year": 2026,
                "salary_annual": 55000,
                "gestoria_annual": 600,
                "set_aside_share": 0.35,
            },
        )
        assert r.status_code == 200 and r.json()["inherited_from"] is None
        own = client.get("/api/freelance/tax-years/2026").json()
        assert own["is_default"] is False and own["salary_annual"] == 55000

        # 2027 has no row: it uses 2026's and says so; 2025 is before any row: the defaults
        nxt = client.get("/api/freelance/tax-years/2027").json()
        assert (nxt["salary_annual"], nxt["inherited_from"], nxt["is_default"]) == (
            55000,
            2026,
            False,
        )
        assert nxt["fiscal_year"] == 2026  # no 2027 block in fiscal_es.json yet
        assert client.get("/api/freelance/tax-years/2025").json()["is_default"] is True
        assert [t["year"] for t in client.get("/api/freelance/tax-years").json()] == [2026]

        assert client.delete("/api/freelance/tax-years/2026").status_code == 204
        assert client.delete("/api/freelance/tax-years/2026").status_code == 404
        assert client.get("/api/freelance/tax-years/2027").json()["is_default"] is True

    def test_validation(self, client):
        assert client.put("/api/freelance/tax-years/2026", json={"year": 2025}).status_code == 422
        assert (
            client.put(
                "/api/freelance/tax-years/2026", json={"year": 2026, "set_aside_share": 1.5}
            ).status_code
            == 422
        )
        assert (
            client.put(
                "/api/freelance/tax-years/2026", json={"year": 2026, "salary_annual": -1}
            ).status_code
            == 422
        )


# ── the year ──────────────────────────────────────────────────────────────────


class TestSummary:
    def _year(self, client):
        """The side-job case spread over a year: 2h a day at $100, 220 days, by quarter 55
        days each, on top of the anchor's salary and gestoría — at $1.10 per euro, so every
        block is a round 2,000 EUR and the year a round 40,000."""
        usd = _source(client, "Northwind", 100, "USD")
        client.put(
            "/api/freelance/tax-years/2026",
            json={"year": 2026, "salary_annual": 55000, "gestoria_annual": 600},
        )
        # five 22 h blocks per quarter standing for its 55 days: 110 h a quarter
        for d in ("2026-02-10", "2026-05-10", "2026-08-10", "2026-11-10"):
            for _ in range(5):
                _block(client, date=d, source_id=usd, hours=22, fx_rate=1.1)
        return usd

    def test_totals_quarters_and_the_year_figures(self, client):
        self._year(client)
        # looked at in January, the year over: the fourth 130 is due, nothing is left to plan
        s = client.get("/api/freelance/summary?year=2026&today=2027-01-05").json()
        # 440 h x $100 = $44,000 / 1.1 = 40,000 EUR; 90.91 EUR/h
        assert s["total"]["hours"] == 440 and s["total"]["gross_eur"] == 40000.0
        assert s["total"]["eur_per_hour"] == 90.91
        assert s["total"]["blocks"] == 20 and s["total"]["missing_fx"] == 0
        assert s["set_aside_share"] == 0.4 and s["set_aside"]["year"] == 16000.0  # 40%
        # the year's figures, by hand (2026 rules, Andalucía):
        # RETA: (40000 - 600) x 0.93 / 12 = 3053.50/month -> tramo 11, base 1437.91
        #   -> 1437.91 x 0.315 x 12 = 5435.2998
        # activity: 40000 - 600 - 5435.2998 = 33964.7002; 5% = 1698.2350 -> taxable 32266.4652
        # tax(49425) = 12870.70 (the anchor); tax(49425 + 32266.4652 = 81691.4652):
        #   state 1182.75 + 930 + 2250 + 4588 + 21691.4652 x .225 (4880.5797) = 13831.3297
        #   - 527.25 = 13304.0797; Andalucía 1235 + 972 + 2115 + 4588 + 4880.5797 = 13790.5797
        #   - 550.05 = 13240.5297 -> 26544.6094; freelance IRPF = 13673.9094
        # 130: 32266.4652 x 0.2 = 6453.2930; net = 40000 - 600 - 5435.2998 - 13673.9094
        #   = 20290.7908; refund as the anchor (same tramo): 1562.2312
        f = s["projection"]["figures"]
        assert s["projection"]["planned_hours"] == 0
        assert s["projection"]["projected_gross_eur"] == 40000.0
        assert (f["reta_tramo"], f["reta_annual"]) == (11, 5435.3)
        assert f["taxable"] == 32266.47
        assert f["irpf"] == 13673.91 and f["pago_fraccionado"] == 6453.29
        assert f["net"] == 20290.79 and f["reintegro"] == 1562.23
        # net EUR/h: 20290.7908 / 440 = 46.1154
        assert s["projection"]["eur_per_hour_net"] == 46.12
        # the 130s: fixed costs 600 + 5435.2998 = 6035.2998 a year, 1508.8250 a quarter;
        # Q1: 10000 - 1508.8250 = 8491.1750, 5% = 424.5588 -> 8066.6163 x 0.2 = 1613.3233;
        # every quarter bills the same, so each pays the same
        q = s["quarters"]
        assert [x["payment"] for x in q] == [1613.32, 1613.32, 1613.32, 1613.32]
        assert q[0]["gross_eur"] == 10000.0 and q[3]["gross_ytd"] == 40000.0
        assert q[3]["yield_ytd"] == 32266.47 and q[3]["cumulative"] == 6453.29
        assert [x["deadline"] for x in q] == [
            "2026-04-20",
            "2026-07-20",
            "2026-10-20",
            "2027-01-30",
        ]
        assert [x["status"] for x in q] == ["paid", "paid", "paid", "due"]
        # the four add up to the year's 130 (same base, no startup reduction either way)
        assert round(sum(x["payment"] for x in q), 2) == 6453.28  # a cent of rounding a quarter
        assert [m["hours"] for m in s["by_month"]] == [0, 110, 0, 0, 110, 0, 0, 110, 0, 0, 110, 0]
        assert s["by_source"][0]["name"] == "Northwind"
        assert s["by_source"][0]["amount"] == 44000.0

    def test_blocks_add_up_at_the_cents_they_show(self, client):
        """Three blocks of $95 / 1.1172: 170.07 each on the page, 510.21 in the total."""
        usd = _source(client)
        for _ in range(3):
            _block(client, date="2026-03-06", source_id=usd, hours=2, fx_rate=FX)
        s = client.get("/api/freelance/summary?year=2026&today=2026-03-10").json()
        assert s["total"]["gross_eur"] == 510.21  # not 510.20 (3 x 170.0680 unrounded)

    def test_week_month_and_set_aside_for_the_dashboard(self, client):
        eur = _source(client, "Local", 60, "EUR")
        client.put("/api/freelance/tax-years/2026", json={"year": 2026, "set_aside_share": 0.3})
        _block(client, date="2026-03-03", source_id=eur, hours=2)  # Tue this week
        _block(client, date="2026-03-07", source_id=eur, hours=4)  # Sat this week
        _block(client, date="2026-03-10", source_id=eur, hours=1)  # next week, same month
        _block(client, date="2026-02-27", source_id=eur, hours=1)  # last month
        s = client.get("/api/freelance/summary?year=2026&today=2026-03-05").json()
        assert (s["week"]["hours"], s["week"]["gross_eur"]) == (6, 360.0)
        assert (s["month"]["hours"], s["month"]["gross_eur"]) == (7, 420.0)
        assert s["set_aside"] == {
            "year": 144.0,
            "week": 108.0,
            "month": 126.0,
        }  # 30% of 480 / 360 / 420
        assert [x["status"] for x in s["quarters"]] == ["current", "future", "future", "future"]

    def test_projection_from_hours_per_week_and_days_off(self, client):
        eur = _source(client, "Local", 80, "EUR")
        _block(client, date="2026-01-10", source_id=eur, hours=10)  # 800 EUR, 80/h realised
        client.put("/api/config", json={"freelance_hours_per_week": 7, "freelance_days_off": 28})
        # today 2026-07-01: 183 days left of 365;
        # weeks left = (183 - 28 x 183/365) / 7 = (183 - 14.0384) / 7 = 24.1374
        s = client.get("/api/freelance/summary?year=2026&today=2026-07-01").json()
        p = s["projection"]
        assert (p["hours_per_week"], p["days_off"], p["weeks_left"]) == (7, 28, 24.14)
        assert p["planned_hours"] == 168.96  # 24.1374 x 7
        assert p["rate_basis"] == "realised" and p["rate_eur"] == 80.0
        assert p["planned_gross_eur"] == 13516.93  # 168.9616 x 80
        assert p["projected_gross_eur"] == 14316.93
        assert p["projected_hours"] == 178.96
        assert p["figures"]["gross"] == 14316.93
        # nothing planned: the default source's rate stands in before any block
        client.put("/api/config", json={"freelance_hours_per_week": 0})
        s = client.get("/api/freelance/summary?year=2027&today=2027-01-01").json()
        assert (
            s["projection"]["rate_basis"] == "default_source"
            and s["projection"]["rate_eur"] == 80.0
        )
        assert s["projection"]["planned_hours"] == 0

    def test_empty_year(self, client):
        s = client.get("/api/freelance/summary?year=2026&today=2026-06-01").json()
        assert s["total"] == {
            "hours": 0,
            "gross_eur": 0.0,
            "eur_per_hour": 0.0,
            "blocks": 0,
            "missing_fx": 0,
            "paid_out_eur": 0.0,
            "estimated_eur": 0.0,
        }
        assert s["projection"]["rate_basis"] == "none" and s["projection"]["rate_eur"] is None
        assert s["projection"]["figures"]["net"] < 0  # the RETA's first tramo is still paid
        assert s["tax_inputs"]["is_default"] is True


# ── the calculator ────────────────────────────────────────────────────────────


class TestCalculator:
    SIDE = {
        "year": 2026,
        "currency": "USD",
        "fx_rate": FX,
        "billable_days": 220,
        "hours_per_day": 2,
        "salary_annual": 55000,
        "gestoria_annual": 600,
    }
    FULL = {
        "year": 2026,
        "currency": "USD",
        "fx_rate": FX,
        "billable_days": 220,
        "hours_per_day": 8,
        "gestoria_annual": 600,
    }

    def test_side_job_anchor_to_the_cent(self, client):
        r = client.post("/api/freelance/calc", json={**self.SIDE, "mode": "hourly", "value": 100})
        assert r.status_code == 200, r.text
        d = r.json()
        assert (d["hourly"], d["daily"]) == (100.0, 200.0)
        assert d["gross"] == 44000.0 and d["gross_eur"] == 39384.17
        assert d["net"] == 19938.23
        f = d["figures"]
        assert (f["reta_tramo"], f["reta_base"], f["reta_annual"]) == (11, 1437.91, 5435.3)
        assert f["hard_to_justify"] == 1667.44 and f["taxable"] == 31681.43
        assert f["employment_net"] == 49425.0
        assert f["irpf"] == 13410.64 and f["irpf_effective"] == 0.4233
        assert f["pago_fraccionado"] == 6336.29 and f["renta"] == 7074.36
        assert f["reintegro"] == 1562.23
        assert f["fiscal_year"] == 2026 and f["region"] == "Andalucía"
        assert d["hours_year"] == 440 and d["net_per_hour_eur"] == 45.31  # 19938.23 / 440
        # a month: gross 39384.17 / 12 = 3282.01; net 19938.23 / 12 = 1661.52
        assert d["month"] == {"gross_eur": 3282.01, "net_eur": 1661.52}

    def test_full_time_anchor_to_the_cent(self, client):
        d = client.post(
            "/api/freelance/calc", json={**self.FULL, "mode": "hourly", "value": 100}
        ).json()
        assert d["daily"] == 800.0 and d["gross_eur"] == 157536.7
        assert d["net"] == 93423.21
        assert d["figures"]["irpf"] == 56225.27 and d["figures"]["reintegro"] == 0

    def test_daily_drives_hourly(self, client):
        d = client.post(
            "/api/freelance/calc", json={**self.FULL, "mode": "daily", "value": 800}
        ).json()
        assert (d["hourly"], d["net"]) == (100.0, 93423.21)

    def test_net_drives_the_rate_back_to_the_anchor(self, client):
        d = client.post(
            "/api/freelance/calc", json={**self.FULL, "mode": "net", "value": 93423.2143}
        ).json()
        assert d["reachable"] is True
        assert d["daily"] == 800.0 and d["hourly"] == 100.0
        assert d["net"] >= 93423.21

    def test_eur_needs_no_fx_usd_does(self, client):
        d = client.post(
            "/api/freelance/calc",
            json={
                "year": 2026,
                "mode": "hourly",
                "value": 50,
                "currency": "EUR",
                "billable_days": 200,
                "hours_per_day": 4,
            },
        ).json()
        assert d["gross"] == 40000.0 and d["gross_eur"] == 40000.0 and d["fx_rate"] is None
        r = client.post(
            "/api/freelance/calc",
            json={"year": 2026, "mode": "hourly", "value": 50, "currency": "USD"},
        )
        assert r.status_code == 422

    def test_an_unreachable_net_says_so(self, client):
        # one billable day cannot reach a net of a thousand million euros, whatever the rate
        d = client.post(
            "/api/freelance/calc",
            json={**self.FULL, "mode": "net", "value": 1e9, "billable_days": 1},
        ).json()
        assert d["reachable"] is False and d["hourly"] == 0

    def test_validation(self, client):
        bad = [
            {"year": 2026, "mode": "weekly", "value": 1},
            {"year": 2026, "mode": "hourly", "value": -1},
            {"year": 2026, "mode": "hourly", "value": 1, "hours_per_day": 0},
            {"year": 2026, "mode": "hourly", "value": 1, "billable_days": 400},
        ]
        for body in bad:
            assert client.post("/api/freelance/calc", json=body).status_code == 422, body


# ── export ────────────────────────────────────────────────────────────────────


class TestExport:
    def test_csv_one_row_per_block(self, client):
        usd = _source(client)
        _block(
            client,
            date="2026-03-06",
            source_id=usd,
            start_time="18:00",
            end_time="20:00",
            notes="a\nb",
        )
        r = client.get("/api/freelance/export.csv")
        assert r.status_code == 200
        assert r.headers["content-disposition"].endswith('filename="kronos_freelance.csv"')
        lines = r.text.strip().splitlines()
        assert (
            lines[0]
            == "date,source,hours,start_time,end_time,rate,currency,fx_rate,amount,amount_eur,notes"
        )
        # 2h x 95 = 190 USD / 1.1172 = 170.07
        assert lines[1] == "2026-03-06,Northwind,2.00,18:00,20:00,95.0,USD,1.1172,190.00,170.07,a b"


# ── config ────────────────────────────────────────────────────────────────────


class TestProjectionSettings:
    def test_round_trip_and_bounds(self, client):
        r = client.put(
            "/api/config", json={"freelance_hours_per_week": 6.5, "freelance_days_off": 5}
        )
        assert r.status_code == 200
        cfg = client.get("/api/config").json()
        assert (cfg["freelance_hours_per_week"], cfg["freelance_days_off"]) == (6.5, 5)
        assert client.put("/api/config", json={"freelance_hours_per_week": 200}).status_code == 422
        assert client.put("/api/config", json={"freelance_days_off": 367}).status_code == 422


# ── the freelance timesheet ───────────────────────────────────────────────────


class TestFreelanceTimesheet:
    def _data(self, client):
        usd = _source(client)  # $95/h
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

    def test_rows_by_month_with_subtotals_and_totals(self, client):
        self._data(client)
        r = client.get(
            "/timesheet/freelance?from=2026-10-01&to=2026-11-30&notes=1&today=2026-11-02"
        )
        assert r.status_code == 200
        t = r.text
        # 2.5 h x $95 = $237.50 / 1.1172 = 212.59; 1.5 h x 60 = 90.00; 302.59 in all
        for needle in (
            "Freelance timesheet",
            "October 2026",
            "Oct subtotal",
            "$237.50",
            "€212.59",
            "€90.00",
            "€302.59",
            "€90.00 · $237.50",
            "call",
            "fix",
        ):
            assert needle in t, needle
        assert t.count('class="row-block') == 2
        assert "Northwind · Local" in t  # the sources included, in the header

    def test_sources_filter_and_an_empty_selection(self, client):
        usd, eur = self._data(client)
        main = client.get(f"/timesheet/freelance?from=2026-10-01&to=2026-11-30&sources={eur}").text
        body = main.split("<main")[1]
        assert "Local" in body and "Northwind" not in body
        assert body.count('class="row-block') == 1
        empty = client.get("/timesheet/freelance?from=2026-10-01&to=2026-11-30&sources=").text
        assert "No freelance blocks" in empty
        assert client.get("/timesheet/freelance?sources=x").status_code == 422

    def test_hm_hours_a_missing_rate_and_the_range_rules(self, client, monkeypatch):
        monkeypatch.setenv("KRONOS_FX_URL", "")
        usd = _source(client)
        _block(client, date="2026-03-07", source_id=usd, hours=2)  # saved without a rate
        t = client.get("/timesheet/freelance?from=2026-03-01&to=2026-03-31&hours=hm").text
        assert "2:00" in t and "no rate" in t and "1 without a rate" in t
        assert client.get("/timesheet/freelance?from=2026-03-31&to=2026-03-01").status_code == 422
        assert client.get("/timesheet/freelance?from=2020-01-01&to=2026-03-01").status_code == 422

    def test_the_employee_sheet_is_untouched(self, client, work_body):
        client.post("/api/entries", json=work_body(date="2026-10-27"))
        before = client.get("/timesheet?from=2026-10-01&to=2026-10-31").text
        self._data(client)
        assert client.get("/timesheet?from=2026-10-01&to=2026-10-31").text == before
