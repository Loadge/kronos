"""API tests for POST /api/import/csv."""

from __future__ import annotations

HEADER = "date,day_type,start_time,end_time,total_break_minutes,net_hours,target_hours,surplus_hours,notes"


def _import(client, content):
    return client.post("/api/import/csv", json={"content": content})


class TestCsvImport:
    def test_round_trip_from_export(self, client, work_body):
        # Seed a work day, a vacation day, and a longer work day, then export.
        client.post("/api/entries", json=work_body(date="2026-04-14", notes="shipped feature"))
        client.post("/api/entries", json={"date": "2026-04-15", "day_type": "vacation"})
        client.post("/api/entries", json=work_body(date="2026-04-16", start="08:00", end="19:00"))
        exported = client.get("/api/export.csv").text

        # Clear via the per-entry endpoint (ORM cascade removes breaks cleanly),
        # then import the exact export back in.
        for d in ("2026-04-14", "2026-04-15", "2026-04-16"):
            client.delete(f"/api/entries/{d}")
        assert client.get("/api/entries").json() == []

        resp = _import(client, exported)
        assert resp.status_code == 200
        body = resp.json()
        assert body["imported"] == ["2026-04-14", "2026-04-15", "2026-04-16"]
        assert body["skipped"] == []
        assert body["errors"] == []

        by_date = {e["date"]: e for e in client.get("/api/entries").json()}
        assert by_date["2026-04-14"]["day_type"] == "work"
        assert by_date["2026-04-14"]["start_time"] == "09:00"
        assert by_date["2026-04-14"]["end_time"] == "17:00"
        assert by_date["2026-04-14"]["total_break_minutes"] == 60
        assert by_date["2026-04-14"]["net_hours"] == 7.0
        assert by_date["2026-04-14"]["notes"] == "shipped feature"
        assert by_date["2026-04-15"]["day_type"] == "vacation"
        assert by_date["2026-04-15"]["start_time"] is None
        assert by_date["2026-04-16"]["net_hours"] == 10.0

    def test_skips_existing_dates(self, client, work_body):
        client.post("/api/entries", json=work_body(date="2026-04-14", notes="original"))
        content = (
            f"{HEADER}\n"
            "2026-04-14,work,08:00,16:00,0,8.00,8.00,0.00,replacement\n"
            "2026-04-20,vacation,,,0,0.00,0.00,0.00,\n"
        )
        body = _import(client, content).json()
        assert body["imported"] == ["2026-04-20"]
        assert body["skipped"] == ["2026-04-14"]

        # The existing entry is untouched (not overwritten).
        existing = client.get("/api/entries/2026-04-14").json()
        assert existing["start_time"] == "09:00"
        assert existing["notes"] == "original"

    def test_skips_in_file_duplicate_dates(self, client):
        content = (
            f"{HEADER}\n"
            "2026-05-01,vacation,,,0,0.00,0.00,0.00,\n"
            "2026-05-01,sick,,,0,0.00,0.00,0.00,\n"
        )
        body = _import(client, content).json()
        assert body["imported"] == ["2026-05-01"]
        assert body["skipped"] == ["2026-05-01"]
        assert client.get("/api/entries/2026-05-01").json()["day_type"] == "vacation"

    def test_invalid_rows_collected_not_aborting(self, client):
        content = (
            f"{HEADER}\n"
            ",work,09:00,17:00,0,0,0,0,\n"  # missing date
            "2026-06-02,work,,,0,0,0,0,\n"  # work day with no start_time
            "2026-06-03,vacation,,,0,0.00,0.00,0.00,valid\n"  # good
        )
        body = _import(client, content).json()
        assert body["imported"] == ["2026-06-03"]
        assert len(body["errors"]) == 2
        assert body["errors"][0].startswith("row 2:")
        assert body["errors"][1].startswith("row 3:")

    def test_blank_rows_ignored(self, client):
        content = f"{HEADER}\n\n2026-07-01,holiday,,,0,0.00,0.00,0.00,\n\n"
        body = _import(client, content).json()
        assert body["imported"] == ["2026-07-01"]
        assert body["errors"] == []

    def test_missing_required_columns_rejected(self, client):
        resp = _import(client, "foo,bar\n1,2\n")
        assert resp.status_code == 422
        assert "date" in resp.json()["detail"]

    def test_reconstructs_break_from_total_minutes(self, client):
        content = f"{HEADER}\n2026-08-03,work,09:00,17:00,45,7.25,8.00,-0.75,\n"
        body = _import(client, content).json()
        assert body["imported"] == ["2026-08-03"]
        entry = client.get("/api/entries/2026-08-03").json()
        assert entry["total_break_minutes"] == 45
        assert entry["net_hours"] == 7.25
