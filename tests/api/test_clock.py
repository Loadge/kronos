"""API tests for POST /api/clock/in and /api/clock/out — the server-stamped work day."""

from __future__ import annotations

import re
from datetime import date

import pytest
from app.routers import clock as clock_router

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@pytest.fixture
def frozen_clock(monkeypatch):
    """Pin the server's wall clock so the stamped times are deterministic."""
    monkeypatch.setattr(clock_router, "local_today", lambda: date(2026, 4, 14))
    monkeypatch.setattr(clock_router, "local_hhmm", lambda: "08:42")


class TestClockIn:
    def test_stamps_server_time_on_server_today(self, client, frozen_clock):
        resp = client.post("/api/clock/in", json={})
        assert resp.status_code == 201
        data = resp.json()
        assert data["date"] == "2026-04-14"
        assert data["day_type"] == "work"
        assert data["start_time"] == "08:42"
        assert data["end_time"] is None
        assert data["net_hours"] == 0
        assert data["exists"] is False
        # It is a real entry now.
        assert client.get("/api/entries/2026-04-14").status_code == 200

    def test_at_and_date_override(self, client, frozen_clock):
        resp = client.post(
            "/api/clock/in", json={"date": "2026-04-13", "at": "07:30", "notes": "early"}
        )
        assert resp.status_code == 201
        data = resp.json()
        assert (data["date"], data["start_time"], data["notes"]) == ("2026-04-13", "07:30", "early")

    def test_real_clock_is_hhmm(self, client):
        data = client.post("/api/clock/in", json={}).json()
        assert HHMM.match(data["start_time"])

    def test_dry_run_writes_nothing(self, client, frozen_clock):
        resp = client.post("/api/clock/in", json={"dry_run": True})
        assert resp.status_code == 201
        assert resp.json()["start_time"] == "08:42"
        assert client.get("/api/entries/2026-04-14").status_code == 404

    def test_existing_entry_is_409_and_names_the_start(self, client, frozen_clock):
        client.post("/api/clock/in", json={"at": "08:00"})
        resp = client.post("/api/clock/in", json={})
        assert resp.status_code == 409
        assert "08:00" in resp.json()["detail"]

    def test_leave_day_is_409(self, client, frozen_clock):
        client.post("/api/entries", json={"date": "2026-04-14", "day_type": "vacation"})
        assert client.post("/api/clock/in", json={}).status_code == 409

    def test_bad_time_is_422(self, client):
        assert client.post("/api/clock/in", json={"at": "8:30"}).status_code == 422

    @pytest.mark.parametrize("other", ["2026-04-13", "2026-04-15"])
    def test_another_day_without_at_is_422(self, client, frozen_clock, other):
        """There is no "now" on yesterday or tomorrow: the request must say the time."""
        resp = client.post("/api/clock/in", json={"date": other})
        assert resp.status_code == 422
        assert f"{other} is not today (2026-04-14)" in resp.json()["detail"]
        assert "`at`" in resp.json()["detail"]
        assert client.get(f"/api/entries/{other}").status_code == 404
        # dry_run takes the same rule: it must never show a day the server would refuse.
        assert (
            client.post("/api/clock/in", json={"date": other, "dry_run": True}).status_code == 422
        )

    def test_today_given_explicitly_without_at_is_fine(self, client, frozen_clock):
        resp = client.post("/api/clock/in", json={"date": "2026-04-14"})
        assert resp.status_code == 201
        assert resp.json()["start_time"] == "08:42"


class TestClockOut:
    def test_ends_the_started_day(self, client, frozen_clock):
        client.post("/api/clock/in", json={"at": "08:00"})
        monkey_out = "16:45"
        resp = client.post(
            "/api/clock/out", json={"at": monkey_out, "breaks": [{"break_minutes": 45}]}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["start_time"] == "08:00"
        assert data["end_time"] == "16:45"
        assert data["total_break_minutes"] == 45
        assert data["net_hours"] == 8.0
        assert data["surplus_hours"] == 0.0
        assert data["exists"] is True

    def test_stamps_server_time_by_default(self, client, frozen_clock):
        client.post("/api/clock/in", json={"at": "08:00"})
        resp = client.post("/api/clock/out", json={})
        assert resp.status_code == 200
        assert resp.json()["end_time"] == "08:42"

    def test_keeps_the_note_unless_given(self, client, frozen_clock):
        client.post("/api/clock/in", json={"at": "08:00", "notes": "standup"})
        assert client.post("/api/clock/out", json={"at": "12:00"}).json()["notes"] == "standup"
        client.delete("/api/entries/2026-04-14")
        client.post("/api/clock/in", json={"at": "08:00", "notes": "standup"})
        out = client.post("/api/clock/out", json={"at": "12:00", "notes": "left early"})
        assert out.json()["notes"] == "left early"

    def test_dry_run_writes_nothing(self, client, frozen_clock):
        client.post("/api/clock/in", json={"at": "08:00"})
        resp = client.post(
            "/api/clock/out",
            json={"at": "17:00", "breaks": [{"break_minutes": 60}], "dry_run": True},
        )
        assert resp.status_code == 200
        assert resp.json()["net_hours"] == 8.0
        stored = client.get("/api/entries/2026-04-14").json()
        assert stored["end_time"] is None
        assert stored["breaks"] == []

    def test_another_day_without_at_is_422(self, client, frozen_clock):
        """The finding: a clock-out on a future day stamped 22:41 onto it (a 14h day)."""
        client.post("/api/clock/in", json={"date": "2026-04-20", "at": "07:55"})
        resp = client.post(
            "/api/clock/out", json={"date": "2026-04-20", "breaks": [{"break_minutes": 30}]}
        )
        assert resp.status_code == 422
        assert "2026-04-20 is not today" in resp.json()["detail"]
        stored = client.get("/api/entries/2026-04-20").json()
        assert stored["end_time"] is None and stored["breaks"] == []
        ok = client.post(
            "/api/clock/out",
            json={"date": "2026-04-20", "at": "16:10", "breaks": [{"break_minutes": 30}]},
        )
        assert ok.status_code == 200 and ok.json()["net_hours"] == 7.75

    def test_no_entry_is_404(self, client, frozen_clock):
        resp = client.post("/api/clock/out", json={})
        assert resp.status_code == 404
        assert "clock in first" in resp.json()["detail"]

    def test_finished_day_is_409(self, client, frozen_clock):
        client.post("/api/clock/in", json={"at": "08:00"})
        client.post("/api/clock/out", json={"at": "16:00"})
        resp = client.post("/api/clock/out", json={"at": "17:00"})
        assert resp.status_code == 409
        assert "16:00" in resp.json()["detail"]

    def test_leave_day_is_409(self, client, frozen_clock):
        client.post("/api/entries", json={"date": "2026-04-14", "day_type": "sick"})
        assert client.post("/api/clock/out", json={"at": "17:00"}).status_code == 409

    def test_end_before_start_is_422(self, client, frozen_clock):
        client.post("/api/clock/in", json={"at": "09:00"})
        resp = client.post("/api/clock/out", json={"at": "08:00"})
        assert resp.status_code == 422
        assert "after" in resp.json()["detail"]

    def test_breaks_longer_than_span_is_422(self, client, frozen_clock):
        client.post("/api/clock/in", json={"at": "09:00"})
        resp = client.post(
            "/api/clock/out", json={"at": "09:30", "breaks": [{"break_minutes": 60}]}
        )
        assert resp.status_code == 422
        assert "exceed" in resp.json()["detail"]
