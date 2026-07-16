"""API tests for /api/config."""

from __future__ import annotations

import pytest


class TestConfig:
    def test_defaults(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["daily_target_hours"] == 8.0
        # The conftest uses an in-memory DB seeded fresh by create_all (no migration insert),
        # so the service falls back to DEFAULT_CUMULATIVE_START_DATE.
        assert data["cumulative_start_date"] == "2025-01-01"

    def test_update_daily_target(self, client):
        resp = client.put("/api/config", json={"daily_target_hours": 7.5})
        assert resp.status_code == 200
        assert resp.json()["daily_target_hours"] == 7.5
        # GET reflects the update.
        assert client.get("/api/config").json()["daily_target_hours"] == 7.5

    def test_update_cumulative_start_date(self, client):
        resp = client.put("/api/config", json={"cumulative_start_date": "2026-01-01"})
        assert resp.status_code == 200
        assert resp.json()["cumulative_start_date"] == "2026-01-01"

    def test_partial_update_leaves_other_fields(self, client):
        client.put("/api/config", json={"daily_target_hours": 7.5})
        client.put("/api/config", json={"cumulative_start_date": "2026-01-01"})
        data = client.get("/api/config").json()
        assert data["daily_target_hours"] == 7.5
        assert data["cumulative_start_date"] == "2026-01-01"

    @pytest.mark.parametrize(
        "payload,reason",
        [
            ({"daily_target_hours": 0}, "zero target"),
            ({"daily_target_hours": -1}, "negative target"),
            ({"daily_target_hours": 25}, "target over 24h"),
            ({"cumulative_start_date": "not-a-date"}, "malformed date"),
        ],
    )
    def test_rejects_invalid(self, client, payload, reason):
        resp = client.put("/api/config", json=payload)
        assert resp.status_code == 422, reason


class TestDailyTargetSchedule:
    def test_default_is_one_row_from_current_target(self, client):
        resp = client.get("/api/config/daily-target-schedule")
        assert resp.status_code == 200
        rows = resp.json()["rows"]
        assert len(rows) == 1
        assert rows[0]["hours"] == 8.0
        # Anchored at the cumulative start so it shows a sensible date.
        assert rows[0]["effective_from"] == "2025-01-01"

    def test_put_persists_and_sorts_rows(self, client):
        # Rows sent out of order; the API stores them ascending by date.
        payload = {
            "rows": [
                {"effective_from": "2026-07-01", "hours": 6.0},
                {"effective_from": "2025-01-01", "hours": 8.0},
            ]
        }
        resp = client.put("/api/config/daily-target-schedule", json=payload)
        assert resp.status_code == 200
        assert resp.json()["rows"] == [
            {"effective_from": "2025-01-01", "hours": 8.0},
            {"effective_from": "2026-07-01", "hours": 6.0},
        ]
        assert client.get("/api/config/daily-target-schedule").json() == resp.json()

    def test_schedule_appears_in_config(self, client):
        client.put(
            "/api/config/daily-target-schedule",
            json={
                "rows": [
                    {"effective_from": "2025-01-01", "hours": 8.0},
                    {"effective_from": "2026-07-01", "hours": 6.0},
                ]
            },
        )
        cfg = client.get("/api/config").json()
        assert cfg["daily_target_hours"] == 6.0  # current = latest row
        assert cfg["daily_target_schedule"] == [
            {"effective_from": "2025-01-01", "hours": 8.0},
            {"effective_from": "2026-07-01", "hours": 6.0},
        ]

    def test_single_field_update_is_non_destructive(self, client):
        client.put(
            "/api/config/daily-target-schedule",
            json={
                "rows": [
                    {"effective_from": "2025-01-01", "hours": 8.0},
                    {"effective_from": "2026-07-01", "hours": 6.0},
                ]
            },
        )
        # Changing the simple single field only touches the current (latest) row.
        client.put("/api/config", json={"daily_target_hours": 5.0})
        assert client.get("/api/config/daily-target-schedule").json()["rows"] == [
            {"effective_from": "2025-01-01", "hours": 8.0},
            {"effective_from": "2026-07-01", "hours": 5.0},
        ]

    def test_dashboard_cumulative_bills_each_day_at_its_own_rate(self, client, work_body):
        # 8h→6h on 2026-07-01. Two June work days (8h target) + two July (6h target),
        # each 7h worked. Cumulative target must be 28, not 4×8=32.
        client.put(
            "/api/config/daily-target-schedule",
            json={
                "rows": [
                    {"effective_from": "2025-01-01", "hours": 8.0},
                    {"effective_from": "2026-07-01", "hours": 6.0},
                ]
            },
        )
        for d in ("2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02"):
            assert client.post("/api/entries", json=work_body(date=d)).status_code == 201

        data = client.get("/api/dashboard?today=2026-07-02").json()
        assert data["cumulative"]["target_hours"] == 28.0
        assert data["cumulative"]["net_hours"] == 28.0  # 7 × 4
        assert data["cumulative"]["surplus_hours"] == 0.0
        assert data["daily_target_hours"] == 6.0  # today's effective target

    @pytest.mark.parametrize(
        "payload,reason",
        [
            ({"rows": []}, "empty rows"),
            ({"rows": [{"effective_from": "2025-01-01", "hours": 0}]}, "zero hours"),
            ({"rows": [{"effective_from": "2025-01-01", "hours": 25}]}, "hours over 24"),
            ({"rows": [{"effective_from": "not-a-date", "hours": 8}]}, "bad date"),
        ],
    )
    def test_rejects_invalid(self, client, payload, reason):
        resp = client.put("/api/config/daily-target-schedule", json=payload)
        assert resp.status_code == 422, reason


class TestDashboardLayout:
    def test_defaults(self, client):
        resp = client.get("/api/config/dashboard-layout")
        assert resp.status_code == 200
        assert resp.json() == {
            "hero": ["week", "month", "cumulative"],
            "tiles": ["yoy", "logging_streak", "on_target_streak"],
            "aux": ["forecast", "quick_log", "vacation"],
        }

    def test_update_persists_custom_order(self, client):
        payload = {
            "hero": ["cumulative", "week", "month"],
            "tiles": ["logging_streak", "on_target_streak", "yoy"],
            "aux": ["quick_log", "vacation", "forecast"],
        }
        resp = client.put("/api/config/dashboard-layout", json=payload)
        assert resp.status_code == 200
        assert resp.json() == payload
        # GET reflects the update.
        assert client.get("/api/config/dashboard-layout").json() == payload

    @pytest.mark.parametrize(
        "payload,reason",
        [
            ({"hero": [], "tiles": ["yoy"], "aux": ["forecast"]}, "empty hero list"),
            ({"tiles": ["yoy"], "aux": ["forecast"]}, "missing hero key"),
        ],
    )
    def test_rejects_invalid(self, client, payload, reason):
        resp = client.put("/api/config/dashboard-layout", json=payload)
        assert resp.status_code == 422, reason
