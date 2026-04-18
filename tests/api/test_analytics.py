"""API tests for /api/dashboard and /api/analytics/*."""

from __future__ import annotations


def _post_work(client, work_body, date, start="09:00", end="17:00", breaks=(60,)):
    return client.post("/api/entries", json=work_body(date=date, start=start, end=end, breaks_min=breaks))


def _post_nonwork(client, date, day_type):
    return client.post("/api/entries", json={"date": date, "day_type": day_type})


class TestDashboard:
    def test_empty(self, client):
        resp = client.get("/api/dashboard?today=2026-04-14")
        assert resp.status_code == 200
        data = resp.json()
        assert data["today"] == "2026-04-14"
        assert data["daily_target_hours"] == 8.0
        for period in ("week", "month", "cumulative"):
            assert data[period] == {
                "net_hours": 0.0,
                "target_hours": 0.0,
                "work_days": 0,
                "non_work_days": 0,
                "surplus_hours": 0.0,
            }

    def test_week_math_with_mixed_days(self, client, work_body):
        # Week of 2026-04-13 (Mon) .. 2026-04-19 (Sun)
        for d in ["2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16", "2026-04-17"]:
            _post_work(client, work_body, d)  # 7h each
        _post_nonwork(client, "2026-04-18", "vacation")
        _post_nonwork(client, "2026-04-19", "holiday")

        resp = client.get("/api/dashboard?today=2026-04-17")
        data = resp.json()
        assert data["week"]["net_hours"] == 35.0
        assert data["week"]["target_hours"] == 40.0
        assert data["week"]["surplus_hours"] == -5.0
        assert data["week"]["work_days"] == 5
        assert data["week"]["non_work_days"] == 2

    def test_cumulative_excludes_future_entries(self, client, work_body):
        _post_work(client, work_body, "2026-04-13")
        _post_work(client, work_body, "2026-04-14")
        _post_work(client, work_body, "2026-04-20")  # later than "today"
        resp = client.get("/api/dashboard?today=2026-04-14")
        # cumulative from default 2025-01-01 → 2026-04-14
        assert resp.json()["cumulative"]["work_days"] == 2

    def test_respects_custom_cumulative_start_date(self, client, work_body):
        _post_work(client, work_body, "2026-03-15")
        _post_work(client, work_body, "2026-04-14")

        client.put("/api/config", json={"cumulative_start_date": "2026-04-01"})
        resp = client.get("/api/dashboard?today=2026-04-14")
        data = resp.json()
        # Only the April entry falls in the cumulative window
        assert data["cumulative"]["work_days"] == 1
        assert data["cumulative"]["net_hours"] == 7.0
        assert data["cumulative_start_date"] == "2026-04-01"

    def test_respects_custom_daily_target(self, client, work_body):
        _post_work(client, work_body, "2026-04-14", start="09:00", end="17:00")  # 7h
        client.put("/api/config", json={"daily_target_hours": 7.0})
        resp = client.get("/api/dashboard?today=2026-04-14")
        data = resp.json()
        assert data["daily_target_hours"] == 7.0
        assert data["week"]["target_hours"] == 7.0
        assert data["week"]["surplus_hours"] == 0.0


class TestCumulativeAsOf:
    def test_requires_as_of(self, client):
        assert client.get("/api/analytics/cumulative").status_code == 422

    def test_cumulative_up_to_date(self, client, work_body):
        _post_work(client, work_body, "2026-04-13")  # 7h
        _post_work(client, work_body, "2026-04-14")  # 7h
        _post_work(client, work_body, "2026-04-15")  # 7h (beyond as_of)

        resp = client.get("/api/analytics/cumulative?as_of=2026-04-14")
        assert resp.status_code == 200
        data = resp.json()
        assert data["net_hours"] == 14.0
        assert data["work_days"] == 2
        assert data["target_hours"] == 16.0
        assert data["surplus_hours"] == -2.0


class TestMonthlyBreakdown:
    def test_empty(self, client):
        assert client.get("/api/analytics/monthly").json() == []

    def test_groups_by_month(self, client, work_body):
        _post_work(client, work_body, "2026-03-15")
        _post_work(client, work_body, "2026-03-20")
        _post_work(client, work_body, "2026-04-10")
        _post_nonwork(client, "2026-04-11", "vacation")

        rows = client.get("/api/analytics/monthly").json()
        assert [r["label"] for r in rows] == ["2026-03", "2026-04"]
        assert rows[0]["net_hours"] == 14.0  # 2 × 7h
        assert rows[0]["target_hours"] == 16.0  # 2 × 8h
        assert rows[0]["work_days"] == 2
        assert rows[0]["non_work_days"] == 0
        assert rows[1]["net_hours"] == 7.0
        assert rows[1]["target_hours"] == 8.0
        assert rows[1]["work_days"] == 1
        assert rows[1]["non_work_days"] == 1


class TestRecords:
    def test_empty(self, client):
        data = client.get("/api/analytics/records").json()
        assert data["longest_positive_streak"] == 0
        assert all(v is None for k, v in data.items() if k != "longest_positive_streak")

    def test_longest_and_shortest_work_day(self, client, work_body):
        _post_work(client, work_body, "2026-04-13", start="09:00", end="17:00")  # 7h
        _post_work(client, work_body, "2026-04-14", start="08:00", end="19:00")  # 10h
        _post_work(client, work_body, "2026-04-15", start="10:00", end="15:00", breaks=(30,))  # 4.5h

        data = client.get("/api/analytics/records").json()
        assert data["longest_work_day"] == {"date": "2026-04-14", "net_hours": 10.0}
        assert data["shortest_work_day"] == {"date": "2026-04-15", "net_hours": 4.5}

    def test_month_records(self, client, work_body):
        # March: 2 × 7h = 14h net, target 16h, surplus -2
        _post_work(client, work_body, "2026-03-02")
        _post_work(client, work_body, "2026-03-03")
        # April: 1 × 10h = 10h net, target 8h, surplus +2
        _post_work(client, work_body, "2026-04-01", start="08:00", end="19:00")

        data = client.get("/api/analytics/records").json()
        assert data["longest_month"]["label"] == "2026-03"
        assert data["most_surplus_month"]["label"] == "2026-04"
        assert data["most_deficit_month"]["label"] == "2026-03"
