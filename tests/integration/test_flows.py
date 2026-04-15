"""End-to-end request flows that cross multiple endpoints.

These exercise the path data takes from POST → GET dashboard → PUT → GET dashboard → DELETE,
making sure totals and targets recalculate correctly across state transitions.
"""

from __future__ import annotations


def _post(client, body):
    r = client.post("/api/entries", json=body)
    assert r.status_code == 201, r.text


def _put(client, date, body):
    r = client.put(f"/api/entries/{date}", json=body)
    assert r.status_code == 200, r.text


class TestLifecycle:
    def test_create_list_get_update_delete_cycle(self, client, work_body):
        # Nothing there yet
        assert client.get("/api/entries").json() == []

        # Create
        _post(client, work_body(date="2026-04-14"))
        assert len(client.get("/api/entries").json()) == 1

        # Get
        e = client.get("/api/entries/2026-04-14").json()
        assert e["net_hours"] == 7.0
        assert e["surplus_hours"] == -1.0

        # Update — extend the day
        _put(client, "2026-04-14", {
            "day_type": "work", "start_time": "08:00", "end_time": "18:00",
            "breaks": [{"break_minutes": 60}],
        })
        e = client.get("/api/entries/2026-04-14").json()
        assert e["net_hours"] == 9.0
        assert e["surplus_hours"] == 1.0

        # Delete
        assert client.delete("/api/entries/2026-04-14").status_code == 204
        assert client.get("/api/entries/2026-04-14").status_code == 404
        assert client.get("/api/entries").json() == []


class TestDashboardRecalcsAcrossStateChanges:
    def test_target_reduces_when_work_day_becomes_vacation(self, client, work_body):
        # Two work days — target = 16h
        _post(client, work_body(date="2026-04-13"))
        _post(client, work_body(date="2026-04-14"))

        dash = client.get("/api/dashboard?today=2026-04-14").json()
        assert dash["week"]["target_hours"] == 16.0
        assert dash["week"]["net_hours"] == 14.0
        assert dash["week"]["surplus_hours"] == -2.0

        # Convert one to vacation — target should drop by 8h
        _put(client, "2026-04-14", {"day_type": "vacation"})
        dash = client.get("/api/dashboard?today=2026-04-14").json()
        assert dash["week"]["target_hours"] == 8.0
        assert dash["week"]["net_hours"] == 7.0
        assert dash["week"]["surplus_hours"] == -1.0

    def test_daily_target_change_propagates(self, client, work_body):
        _post(client, work_body(date="2026-04-14"))
        assert client.get("/api/dashboard?today=2026-04-14").json()["week"]["surplus_hours"] == -1.0

        client.put("/api/config", json={"daily_target_hours": 7.0})
        assert client.get("/api/dashboard?today=2026-04-14").json()["week"]["surplus_hours"] == 0.0


class TestMonthBoundary:
    def test_week_spanning_two_months(self, client, work_body):
        # Week of Mon 2026-03-30 .. Sun 2026-04-05 crosses the boundary.
        for d in ["2026-03-30", "2026-03-31", "2026-04-01", "2026-04-02", "2026-04-03"]:
            _post(client, work_body(date=d))

        dash = client.get("/api/dashboard?today=2026-04-01").json()  # Wednesday of that week
        # Week spans the boundary — all 5 entries (both months) count toward the week.
        assert dash["week"]["work_days"] == 5
        assert dash["week"]["net_hours"] == 35.0
        # Month is the full calendar month (Apr 1–30), so only the 3 April entries count;
        # the two March entries are excluded even though they share the same ISO week.
        assert dash["month"]["work_days"] == 3
        assert dash["month"]["net_hours"] == 21.0

    def test_monthly_breakdown_across_boundary(self, client, work_body):
        _post(client, work_body(date="2026-03-31"))
        _post(client, work_body(date="2026-04-01"))
        rows = client.get("/api/analytics/monthly").json()
        assert len(rows) == 2
        assert [r["label"] for r in rows] == ["2026-03", "2026-04"]
        assert all(r["net_hours"] == 7.0 for r in rows)


class TestExportReflectsMixedData:
    def test_export_after_mixed_writes(self, client, work_body):
        _post(client, work_body(date="2026-04-14", notes="shipped v1"))
        _post(client, {"date": "2026-04-15", "day_type": "vacation"})
        _post(client, {"date": "2026-04-16", "day_type": "holiday"})
        _post(client, work_body(date="2026-04-17", start="08:00", end="19:00"))

        # Update one after export
        _put(client, "2026-04-14", {
            "day_type": "work", "start_time": "09:00", "end_time": "17:30",
            "breaks": [{"break_minutes": 30}],
        })

        json_export = client.get("/api/export.json").json()
        assert len(json_export) == 4
        updated = next(e for e in json_export if e["date"] == "2026-04-14")
        assert updated["net_hours"] == 8.0
        assert updated["total_break_minutes"] == 30
