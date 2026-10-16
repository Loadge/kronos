"""API tests for /api/holidays/* — network calls (Nager.Date, BOE) are monkeypatched.

Spain comes from the BOE (real XML in tests/fixtures/boe); every other country from
Nager.Date. The Nager tests below use Portugal with a synthetic sample: the country only
picks the source, the filter logic is what they test.
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

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
        resp = client.post("/api/holidays/import?country=PT&year=2026")
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
        body = client.post("/api/holidays/import?country=PT&year=2026&region=ES-MD").json()
        # Global + ES-MD, but NOT ES-AN.
        assert body["imported"] == ["2026-01-01", "2026-05-01", "2026-05-02"]
        by_date = {e["date"]: e for e in client.get("/api/entries").json()}
        assert by_date["2026-05-02"]["notes"] == "Fiesta de la Comunidad de Madrid"
        assert "2026-02-28" not in by_date

    def test_skips_existing_dates(self, client, mock_holidays, work_body):
        client.post("/api/entries", json=work_body(date="2026-01-01", notes="worked NYE"))
        body = client.post("/api/holidays/import?country=PT&year=2026").json()
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
        resp = client.post("/api/holidays/import?country=PT&year=2026")
        assert resp.status_code == 502
        assert "holiday service" in resp.json()["detail"]


class TestPreview:
    def test_national_only_sorted_with_flags(self, client, mock_holidays):
        body = client.get("/api/holidays/preview?country=PT&year=2026").json()
        assert body == [
            {"date": "2026-01-01", "name": "Año Nuevo", "regional": False, "exists": False},
            {
                "date": "2026-05-01",
                "name": "Día del Trabajador",
                "regional": False,
                "exists": False,
            },
        ]

    def test_region_included_and_marked_regional(self, client, mock_holidays):
        body = client.get("/api/holidays/preview?country=PT&year=2026&region=ES-MD").json()
        dates = [h["date"] for h in body]
        assert dates == ["2026-01-01", "2026-05-01", "2026-05-02"]  # sorted, ES-AN excluded
        madrid = next(h for h in body if h["date"] == "2026-05-02")
        assert madrid["regional"] is True

    def test_exists_flag_reflects_logged_dates(self, client, mock_holidays, work_body):
        client.post("/api/entries", json=work_body(date="2026-01-01"))
        body = client.get("/api/holidays/preview?country=PT&year=2026").json()
        by_date = {h["date"]: h for h in body}
        assert by_date["2026-01-01"]["exists"] is True
        assert by_date["2026-05-01"]["exists"] is False

    def test_network_error_returns_502(self, client, monkeypatch):
        def boom(country, year):
            raise urllib.error.URLError("down")

        monkeypatch.setattr(holidays, "_fetch_holidays", boom)
        assert client.get("/api/holidays/preview?country=PT&year=2026").status_code == 502


class TestSubdivisions:
    def test_lists_distinct_sorted_counties(self, client, mock_holidays):
        resp = client.get("/api/holidays/subdivisions?country=PT&year=2026")
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


# ---------- Spain: the official BOE list, never Nager ----------------------

BOE_FIXTURES = Path(__file__).parents[1] / "fixtures" / "boe"

# Com. de Madrid, BOE-A-2026-21254. A weekend-blind source (Nager) gives 2027-05-02 and
# 2027-08-15 instead of 2027-03-19 and 2027-08-16: both fall on a Sunday, and Madrid
# chose San José and the Monday after the Assumption.
MADRID_2027 = [
    "2027-01-01", "2027-01-06", "2027-03-19", "2027-03-25", "2027-03-26", "2027-05-01",
    "2027-08-16", "2027-10-12", "2027-11-01", "2027-12-06", "2027-12-08", "2027-12-25",
]  # fmt: skip


@pytest.fixture
def boe_only(monkeypatch):
    """Serve the real BOE XML from disk, and fail the test if Nager is asked about Spain."""

    def fetch_boe(boe_id):
        return (BOE_FIXTURES / f"{boe_id}.xml").read_bytes()

    def no_nager(country, year):
        raise AssertionError(f"Nager.Date asked for {country} {year}: Spain must come from the BOE")

    monkeypatch.setattr(holidays, "_fetch_boe", fetch_boe)
    monkeypatch.setattr(holidays, "_fetch_holidays", no_nager)


class TestSpainFromBoe:
    def test_import_madrid_2027_is_exactly_the_official_list(self, client, boe_only):
        body = client.post("/api/holidays/import?country=ES&year=2027&region=ES-MD").json()
        assert body["imported"] == MADRID_2027
        by_date = {e["date"]: e for e in client.get("/api/entries").json()}
        assert sorted(by_date) == MADRID_2027
        assert by_date["2027-03-19"]["notes"] == "San José"
        assert all(e["day_type"] == "holiday" for e in by_date.values())

    def test_preview_marks_only_the_regions_own_holiday_as_regional(self, client, boe_only):
        body = client.get("/api/holidays/preview?country=ES&year=2026&region=ES-MD").json()
        assert [h["date"] for h in body if h["regional"]] == ["2026-05-02"]
        # The Sunday holidays are on the Monday Madrid moved them to.
        dates = [h["date"] for h in body]
        assert "2026-11-02" in dates and "2026-12-07" in dates
        assert "2026-11-01" not in dates and "2026-12-06" not in dates

    def test_without_region_only_the_holidays_every_region_has(self, client, boe_only):
        body = client.get("/api/holidays/preview?country=ES&year=2027").json()
        assert [h["date"] for h in body] == [
            "2027-01-01", "2027-01-06", "2027-03-26", "2027-05-01", "2027-10-12",
            "2027-11-01", "2027-12-06", "2027-12-08", "2027-12-25",
        ]  # fmt: skip
        assert not any(h["regional"] for h in body)

    def test_subdivisions_are_the_19_boe_columns(self, client, boe_only):
        codes = client.get("/api/holidays/subdivisions?country=ES&year=2027").json()
        assert len(codes) == 19
        assert "ES-MD" in codes and "ES-CN" in codes and "ES-ML" in codes

    def test_year_without_a_known_resolution_is_an_error_not_nager(self, client, boe_only):
        resp = client.post("/api/holidays/import?country=ES&year=2028&region=ES-MD")
        assert resp.status_code == 404
        assert "2028" in resp.json()["detail"]
        assert client.get("/api/entries").json() == []

    def test_unknown_region_rejected(self, client, boe_only):
        resp = client.get("/api/holidays/preview?country=ES&year=2027&region=ES-XX")
        assert resp.status_code == 422

    def test_unreadable_boe_document_returns_502(self, client, monkeypatch):
        monkeypatch.setattr(holidays, "_fetch_boe", lambda boe_id: b"<documento/>")
        resp = client.post("/api/holidays/import?country=ES&year=2027&region=ES-MD")
        assert resp.status_code == 502
        assert "BOE-A-2026-21254" in resp.json()["detail"]

    def test_boe_network_error_returns_502(self, client, monkeypatch):
        def boom(boe_id):
            raise urllib.error.URLError("no route to host")

        monkeypatch.setattr(holidays, "_fetch_boe", boom)
        resp = client.get("/api/holidays/preview?country=ES&year=2027&region=ES-MD")
        assert resp.status_code == 502
