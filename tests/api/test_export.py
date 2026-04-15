"""API tests for /api/export.csv and /api/export.json."""

from __future__ import annotations

import csv
import io


def _post(client, body, url="/api/entries"):
    return client.post(url, json=body)


class TestCsvExport:
    def test_empty(self, client):
        resp = client.get("/api/export.csv")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "attachment" in resp.headers["content-disposition"]
        rows = list(csv.reader(io.StringIO(resp.text)))
        assert rows == [[
            "date", "day_type", "start_time", "end_time",
            "total_break_minutes", "net_hours", "target_hours", "surplus_hours", "notes",
        ]]

    def test_round_trip(self, client, work_body):
        _post(client, work_body(date="2026-04-14", notes="shipped feature"))
        _post(client, {"date": "2026-04-15", "day_type": "vacation"})
        _post(client, work_body(date="2026-04-16", start="08:00", end="19:00"))

        resp = client.get("/api/export.csv")
        assert resp.status_code == 200
        rows = list(csv.reader(io.StringIO(resp.text)))
        # header + 3 rows
        assert len(rows) == 4
        header, *data = rows
        by_date = {r[0]: dict(zip(header, r, strict=True)) for r in data}

        work_day = by_date["2026-04-14"]
        assert work_day["day_type"] == "work"
        assert work_day["start_time"] == "09:00"
        assert work_day["end_time"] == "17:00"
        assert work_day["total_break_minutes"] == "60"
        assert work_day["net_hours"] == "7.00"
        assert work_day["target_hours"] == "8.00"
        assert work_day["surplus_hours"] == "-1.00"
        assert work_day["notes"] == "shipped feature"

        vac = by_date["2026-04-15"]
        assert vac["day_type"] == "vacation"
        assert vac["start_time"] == ""
        assert vac["end_time"] == ""
        assert vac["total_break_minutes"] == "0"
        assert vac["net_hours"] == "0.00"
        assert vac["target_hours"] == "0.00"
        assert vac["surplus_hours"] == "0.00"

        long_day = by_date["2026-04-16"]
        assert long_day["net_hours"] == "10.00"
        assert long_day["surplus_hours"] == "2.00"

    def test_newlines_in_notes_are_flattened(self, client, work_body):
        _post(client, work_body(notes="line one\nline two"))
        resp = client.get("/api/export.csv")
        rows = list(csv.reader(io.StringIO(resp.text)))
        # Find the data row; ensure the notes cell is a single "line one line two"
        assert rows[1][-1] == "line one line two"


class TestJsonExport:
    def test_empty(self, client):
        resp = client.get("/api/export.json")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_mirrors_entries_list(self, client, work_body):
        _post(client, work_body())
        _post(client, {"date": "2026-04-15", "day_type": "vacation"})
        list_ = client.get("/api/entries").json()
        export = client.get("/api/export.json").json()
        assert export == list_
