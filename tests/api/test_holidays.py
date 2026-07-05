"""API tests for /api/holidays/* — the Nager.Date network calls are monkeypatched."""

from __future__ import annotations

import urllib.error

import pytest
from app.routers import holidays

# National (global) + two regional holidays for different subdivisions.
SAMPLE = [
    {
        "date": "2026-01-01",
        "localName": "Año Nuevo",
        "name": "New Year's Day",
        "global": True,
        "counties": None,
    },
    {
        "date": "2026-05-01",
        "localName": "Día del Trabajador",
        "name": "Labour Day",
        "global": True,
        "counties": None,
    },
    {
        "date": "2026-05-02",
        "localName": "Fiesta de la Comunidad de Madrid",
        "name": "Madrid Day",
        "global": False,
        "counties": ["ES-MD"],
    },
    {
        "date": "2026-02-28",
        "localName": "Día de Andalucía",
        "name": "Andalusia Day",
        "global": False,
        "counties": ["ES-AN"],
    },
]


@pytest.fixture
def mock_holidays(monkeypatch):
    monkeypatch.setattr(holidays, "_fetch_holidays", lambda country, year: SAMPLE)


class TestImport:
    def test_national_only(self, client, mock_holidays):
        resp = client.post("/api/holidays/import?country=ES&year=2026")
        assert resp.status_code == 200
        body = resp.json()
        # Only the two global holidays — no regional ones.
        assert body["imported"] == ["2026-01-01", "2026-05-01"]
        assert body["skipped"] == []

        by_date = {e["date"]: e for e in client.get("/api/entries").json()}
        assert by_date["2026-01-01"]["day_type"] == "holiday"
        assert by_date["2026-01-01"]["notes"] == "Año Nuevo"
        assert "2026-05-02" not in by_date  # ES-MD excluded without a region

    def test_with_region_adds_that_subdivision(self, client, mock_holidays):
        body = client.post("/api/holidays/import?country=ES&year=2026&region=ES-MD").json()
        # Global + ES-MD, but NOT ES-AN.
        assert body["imported"] == ["2026-01-01", "2026-05-01", "2026-05-02"]
        by_date = {e["date"]: e for e in client.get("/api/entries").json()}
        assert by_date["2026-05-02"]["notes"] == "Fiesta de la Comunidad de Madrid"
        assert "2026-02-28" not in by_date

    def test_skips_existing_dates(self, client, mock_holidays, work_body):
        client.post("/api/entries", json=work_body(date="2026-01-01", notes="worked NYE"))
        body = client.post("/api/holidays/import?country=ES&year=2026").json()
        assert body["imported"] == ["2026-05-01"]
        assert body["skipped"] == ["2026-01-01"]
        # The pre-existing work day is untouched.
        assert client.get("/api/entries/2026-01-01").json()["day_type"] == "work"

    def test_bad_country_code_rejected(self, client, mock_holidays):
        assert client.post("/api/holidays/import?country=ESP&year=2026").status_code == 422

    def test_network_error_returns_502(self, client, monkeypatch):
        def boom(country, year):
            raise urllib.error.URLError("no route to host")

        monkeypatch.setattr(holidays, "_fetch_holidays", boom)
        resp = client.post("/api/holidays/import?country=ES&year=2026")
        assert resp.status_code == 502
        assert "holiday service" in resp.json()["detail"]


class TestSubdivisions:
    def test_lists_distinct_sorted_counties(self, client, mock_holidays):
        resp = client.get("/api/holidays/subdivisions?country=ES&year=2026")
        assert resp.status_code == 200
        assert resp.json() == ["ES-AN", "ES-MD"]


class TestCountries:
    def test_proxied_and_sorted_by_name(self, client, monkeypatch):
        monkeypatch.setattr(
            holidays,
            "_fetch_countries",
            lambda: [
                {"countryCode": "US", "name": "United States"},
                {"countryCode": "ES", "name": "Spain"},
            ],
        )
        body = client.get("/api/holidays/countries").json()
        assert body == [
            {"code": "ES", "name": "Spain"},
            {"code": "US", "name": "United States"},
        ]

    def test_network_error_returns_502(self, client, monkeypatch):
        def boom():
            raise TimeoutError("timed out")

        monkeypatch.setattr(holidays, "_fetch_countries", boom)
        assert client.get("/api/holidays/countries").status_code == 502
