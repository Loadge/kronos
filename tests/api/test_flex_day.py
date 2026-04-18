"""API tests for flex day creation, validation, and metrics."""

from __future__ import annotations


def _flex(date="2026-04-14"):
    return {"date": date, "day_type": "flex"}


def _work(date, start="09:00", end="18:00", breaks=()):
    return {
        "date": date,
        "day_type": "work",
        "start_time": start,
        "end_time": end,
        "breaks": [{"break_minutes": m} for m in breaks],
    }


class TestFlexDayCreation:
    def test_create_flex_day(self, client):
        r = client.post("/api/entries", json=_flex())
        assert r.status_code == 201
        e = r.json()
        assert e["day_type"] == "flex"
        assert e["net_hours"] == 0.0
        assert e["target_hours"] == 8.0
        assert e["surplus_hours"] == -8.0

    def test_flex_day_no_times(self, client):
        r = client.post("/api/entries", json=_flex())
        e = r.json()
        assert e["start_time"] is None
        assert e["end_time"] is None
        assert e["total_break_minutes"] == 0

    def test_flex_with_start_time_rejected(self, client):
        r = client.post("/api/entries", json={
            "date": "2026-04-14", "day_type": "flex",
            "start_time": "09:00", "end_time": "17:00",
        })
        assert r.status_code == 422

    def test_flex_with_breaks_rejected(self, client):
        r = client.post("/api/entries", json={
            "date": "2026-04-14", "day_type": "flex",
            "breaks": [{"break_minutes": 30}],
        })
        assert r.status_code == 422

    def test_flex_custom_target(self, client):
        client.put("/api/config", json={"daily_target_hours": 7.5})
        r = client.post("/api/entries", json=_flex())
        e = r.json()
        assert e["target_hours"] == 7.5
        assert e["surplus_hours"] == -7.5

    def test_update_work_to_flex(self, client):
        client.post("/api/entries", json=_work("2026-04-14"))
        r = client.put("/api/entries/2026-04-14", json={"day_type": "flex"})
        assert r.status_code == 200
        e = r.json()
        assert e["day_type"] == "flex"
        assert e["surplus_hours"] == -8.0

    def test_update_flex_to_work(self, client):
        client.post("/api/entries", json=_flex())
        r = client.put("/api/entries/2026-04-14", json=_work("2026-04-14"))
        assert r.status_code == 200
        assert r.json()["day_type"] == "work"


class TestFlexDayDashboard:
    def test_flex_counts_as_non_work_day(self, client):
        client.post("/api/entries", json=_flex("2026-04-14"))
        data = client.get("/api/dashboard?today=2026-04-14").json()
        assert data["week"]["non_work_days"] == 1
        assert data["week"]["work_days"] == 0

    def test_flex_drains_weekly_surplus(self, client):
        """4 work days × 9h net (8h target → +1h each) + 1 flex = +4h - 8h = -4h."""
        for d in ["2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10"]:
            client.post("/api/entries", json=_work(d, start="09:00", end="18:00"))
        client.post("/api/entries", json=_flex("2026-04-11"))

        data = client.get("/api/dashboard?today=2026-04-11").json()
        assert data["week"]["net_hours"] == 36.0    # 4 × 9h
        assert data["week"]["target_hours"] == 40.0  # 5 × 8h (4 work + 1 flex)
        assert data["week"]["surplus_hours"] == -4.0

    def test_vacation_does_not_drain_surplus(self, client):
        """Same week but vacation instead of flex — target stays 4×8=32, no drain."""
        for d in ["2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10"]:
            client.post("/api/entries", json=_work(d, start="09:00", end="18:00"))
        client.post("/api/entries", json={"date": "2026-04-11", "day_type": "vacation"})

        data = client.get("/api/dashboard?today=2026-04-11").json()
        assert data["week"]["target_hours"] == 32.0  # only 4 work days
        assert data["week"]["surplus_hours"] == 4.0  # +1h × 4

    def test_eight_days_overtime_then_flex_gives_zero(self, client):
        """User's own example: 8 days × +1h overtime, then flex = 0 cumulative."""
        dates = [f"2026-04-{d:02d}" for d in range(1, 9)]
        for d in dates:
            client.post("/api/entries", json=_work(d, start="09:00", end="18:00"))
        client.post("/api/entries", json=_flex("2026-04-09"))

        data = client.get("/api/analytics/cumulative?as_of=2026-04-09").json()
        assert data["net_hours"] == 72.0     # 8 × 9h
        assert data["target_hours"] == 72.0  # 9 × 8h (8 work + 1 flex)
        assert data["surplus_hours"] == 0.0


class TestFlexInExport:
    def test_flex_appears_in_csv_export(self, client):
        import csv, io
        client.post("/api/entries", json=_flex())
        resp = client.get("/api/export.csv")
        rows = list(csv.reader(io.StringIO(resp.text)))
        header, row = rows[0], rows[1]
        by_col = dict(zip(header, row))
        assert by_col["day_type"] == "flex"
        assert by_col["net_hours"] == "0.00"
        assert by_col["target_hours"] == "8.00"
        assert by_col["surplus_hours"] == "-8.00"

    def test_flex_appears_in_backup(self, client):
        client.post("/api/entries", json=_flex())
        body = client.get("/api/backup").json()
        assert body["entries"][0]["day_type"] == "flex"

    def test_flex_survives_restore_roundtrip(self, client):
        client.post("/api/entries", json=_flex())
        backup = client.get("/api/backup").json()
        client.delete("/api/data")
        client.post("/api/restore", json=backup)
        e = client.get("/api/entries/2026-04-14").json()
        assert e["day_type"] == "flex"
        assert e["surplus_hours"] == -8.0
