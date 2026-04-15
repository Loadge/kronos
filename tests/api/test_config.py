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
