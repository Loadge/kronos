"""Country and number format: stored with the other settings, carried by the backup, and the tax
module follows the country (Spain's own, or the Simple one for everybody else).

Spain's figures are pinned elsewhere (tests/unit/test_tax.py, test_freelance_money.py); here the
point is that choosing another country moves the module and nothing else.
"""

from __future__ import annotations

import app.services.fx as fx
import pytest


@pytest.fixture(autouse=True)
def _no_ecb(monkeypatch):
    monkeypatch.setattr(fx, "for_date", lambda on, now=None: {"available": False})


def _country(client, code):
    r = client.put("/api/config", json={"country": code})
    assert r.status_code == 200, r.text
    return r.json()


def _source(client, rate=100.0):
    r = client.post(
        "/api/freelance/sources", json={"name": "Acme", "hourly_rate": rate, "currency": "EUR"}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


class TestTheSettings:
    def test_a_database_with_nothing_chosen_is_spain_in_en_us(self, client):
        cfg = client.get("/api/config").json()
        assert cfg["country"] == "ES"
        assert cfg["number_format"] == "en-US"

    def test_a_new_database_may_be_offered_a_country_and_one_with_a_day_may_not(self, client):
        assert client.get("/api/config").json()["new_database"] is True
        client.post(
            "/api/entries", json={"date": "2026-11-02", "start_time": "09:00", "end_time": "17:00"}
        )
        assert client.get("/api/config").json()["new_database"] is False

    def test_choosing_a_country_ends_the_offer(self, client):
        _country(client, "DE")
        assert client.get("/api/config").json()["new_database"] is False

    def test_both_are_saved_and_read_back(self, client):
        r = client.put("/api/config", json={"country": "DE", "number_format": "es-ES"})
        assert r.status_code == 200
        assert r.json()["country"] == "DE"
        assert client.get("/api/config").json()["number_format"] == "es-ES"

    def test_an_unknown_country_or_format_is_refused_and_changes_nothing(self, client):
        assert client.put("/api/config", json={"country": "XX"}).status_code == 422
        assert client.put("/api/config", json={"country": "de"}).status_code == 422
        assert client.put("/api/config", json={"number_format": "en-GB"}).status_code == 422
        cfg = client.get("/api/config").json()
        assert (cfg["country"], cfg["number_format"]) == ("ES", "en-US")

    def test_the_static_country_list_has_names_and_works_without_a_network(self, client):
        rows = client.get("/api/config/countries").json()
        by_code = {c["code"]: c["name"] for c in rows}
        assert by_code["ES"] == "Spain"
        assert by_code["DE"] == "Germany"
        assert [c["name"] for c in rows] == sorted(c["name"] for c in rows)


class TestTheBackupCarriesThem:
    def test_they_survive_a_backup_and_restore(self, client):
        client.put("/api/config", json={"country": "FR", "number_format": "fr-FR"})
        backup = client.get("/api/backup").json()
        assert backup["settings"]["country"] == "FR"
        assert backup["settings"]["number_format"] == "fr-FR"
        assert "new_database" not in backup["settings"]
        client.put("/api/config", json={"country": "ES", "number_format": "en-US"})
        assert client.post("/api/restore", json=backup).status_code == 200
        cfg = client.get("/api/config").json()
        assert (cfg["country"], cfg["number_format"]) == ("FR", "fr-FR")

    def test_a_file_from_before_them_keeps_what_the_database_has(self, client):
        client.put("/api/config", json={"country": "DE", "number_format": "es-ES"})
        old = client.get("/api/backup").json()
        del old["settings"]["country"], old["settings"]["number_format"]
        assert client.post("/api/restore", json=old).status_code == 200
        cfg = client.get("/api/config").json()
        assert (cfg["country"], cfg["number_format"]) == ("DE", "es-ES")


class TestTheSimpleTaxModule:
    """gross 10 000, expenses 1 000, set aside 30 %: net = 10 000 - 1 000 - 3 000 = 6 000."""

    CALC = {
        "year": 2026,
        "mode": "daily",
        "value": 100,
        "billable_days": 100,
        "hours_per_day": 8,
        "other_expenses": 1000,
        "country": "DE",
        "set_aside_share": 0.3,
    }

    def test_the_net_is_gross_less_expenses_less_the_share(self, client):
        r = client.post("/api/freelance/calc", json=self.CALC).json()
        f = r["figures"]
        assert r["tax_module"] == "simple"
        assert (f["gross"], f["expenses"], f["set_aside"], f["net"]) == (10000, 1000, 3000, 6000)
        assert (f["reta_annual"], f["irpf"], f["pago_fraccionado"], f["renta"]) == (0, 0, 0, 0)
        assert r["month"]["net_eur"] == 500.0  # 6 000 over twelve months

    def test_the_inverse_finds_the_rate_for_a_net(self, client):
        r = client.post(
            "/api/freelance/calc", json={**self.CALC, "mode": "net", "value": 6000}
        ).json()
        assert r["reachable"] is True
        assert r["daily"] == 100.0  # (6 000 + 1 000) / (0.7 x 100)
        assert r["net"] == 6000.0

    def test_the_share_defaults_to_30_percent_outside_spain(self, client):
        body = {k: v for k, v in self.CALC.items() if k != "set_aside_share"}
        assert client.post("/api/freelance/calc", json=body).json()["figures"]["net"] == 6000.0

    def test_a_gestoria_is_not_an_expense_outside_spain(self, client):
        r = client.post("/api/freelance/calc", json={**self.CALC, "gestoria_annual": 500}).json()
        assert r["figures"]["net"] == 6000.0

    def test_spain_is_the_default_country_of_the_calculator_and_has_no_new_keys(self, client):
        body = {k: v for k, v in self.CALC.items() if k not in ("country", "set_aside_share")}
        r = client.post("/api/freelance/calc", json=body).json()
        assert "tax_module" not in r
        assert "set_aside" not in r["figures"]
        assert r["figures"]["reta_annual"] > 0

    def test_the_year_for_another_country_has_no_quarters_and_the_share_for_a_default(self, client):
        src = _source(client, rate=100)
        client.post(
            "/api/freelance/blocks", json={"date": "2026-03-02", "source_id": src, "hours": 10}
        )
        _country(client, "DE")
        s = client.get("/api/freelance/summary?year=2026&today=2026-06-30").json()
        assert s["tax_module"] == "simple"
        assert s["quarters"] == []
        assert s["set_aside_share"] == 0.3
        assert s["set_aside"]["year"] == 300.0  # 30 % of 1 000
        f = s["projection"]["figures"]
        assert f["irpf"] == 0 and f["reta_annual"] == 0
        assert f["set_aside"] == pytest.approx(f["gross"] * 0.3, abs=0.01)

    def test_spain_still_has_its_four_quarters(self, client):
        src = _source(client, rate=100)
        client.post(
            "/api/freelance/blocks", json={"date": "2026-03-02", "source_id": src, "hours": 10}
        )
        s = client.get("/api/freelance/summary?year=2026&today=2026-06-30").json()
        assert len(s["quarters"]) == 4
        assert "tax_module" not in s
        assert s["set_aside_share"] == 0.4

    def test_an_own_share_wins_over_the_default(self, client):
        _country(client, "DE")
        client.put(
            "/api/freelance/tax-years/2026",
            json={"year": 2026, "set_aside_share": 0.25},
        )
        assert client.get("/api/freelance/tax-years/2026").json()["set_aside_share"] == 0.25

    def test_the_tax_year_default_follows_the_country(self, client):
        assert client.get("/api/freelance/tax-years/2026").json()["set_aside_share"] == 0.4
        _country(client, "DE")
        assert client.get("/api/freelance/tax-years/2026").json()["set_aside_share"] == 0.3


class TestThePrintedSheetsFollowTheFormat:
    def _sheet(self, client):
        src = _source(client, rate=1234.5)
        client.post(
            "/api/freelance/blocks", json={"date": "2026-04-13", "source_id": src, "hours": 1}
        )
        return client.get(
            "/timesheet/freelance?from=2026-04-13&to=2026-04-19&today=2026-04-20"
        ).text

    def test_en_us_prints_what_it_always_did(self, client):
        assert "€1,234.50" in self._sheet(client)

    def test_es_es_prints_the_spanish_marks(self, client):
        client.put("/api/config", json={"number_format": "es-ES"})
        html = self._sheet(client)
        assert "€1.234,50" in html
        assert "€1,234.50" not in html
        assert "1,00" in html  # the hours of the block, in decimal style

    def test_the_example_label_is_not_frozen_by_the_first_request(self, client):
        client.get("/timesheet?from=2026-04-13&to=2026-04-13&today=2026-04-20")  # en-US first
        client.put("/api/config", json={"number_format": "es-ES"})
        html = client.get("/timesheet?from=2026-04-13&to=2026-04-13&today=2026-04-20").text
        assert ">7,50</label>" in html
        client.put("/api/config", json={"number_format": "en-US"})
        html = client.get("/timesheet?from=2026-04-13&to=2026-04-13&today=2026-04-20").text
        assert ">7.50</label>" in html

    def test_the_employee_sheet_follows_it_too(self, client):
        client.put("/api/config", json={"number_format": "es-ES"})
        client.post(
            "/api/entries",
            json={"date": "2026-04-13", "start_time": "09:00", "end_time": "17:30"},
        )
        html = client.get("/timesheet?from=2026-04-13&to=2026-04-13&today=2026-04-20").text
        assert "8,50" in html
        assert "8.50" not in html
