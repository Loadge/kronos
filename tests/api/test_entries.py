"""API tests for /api/entries CRUD."""

from __future__ import annotations

from sqlalchemy import func, select

import pytest

from app.models import Break


class TestCreateEntry:
    def test_work_entry_happy_path(self, client, work_body):
        resp = client.post("/api/entries", json=work_body())
        assert resp.status_code == 201
        data = resp.json()
        assert data["date"] == "2026-04-14"
        assert data["day_type"] == "work"
        assert data["start_time"] == "09:00"
        assert data["end_time"] == "17:00"
        assert data["net_hours"] == 7.0
        assert data["target_hours"] == 8.0
        assert data["surplus_hours"] == -1.0
        assert data["total_break_minutes"] == 60
        assert len(data["breaks"]) == 1
        assert data["breaks"][0]["break_minutes"] == 60
        assert data["breaks"][0]["id"] is not None

    @pytest.mark.parametrize("day_type", ["vacation", "sick", "holiday"])
    def test_non_work_entry(self, client, day_type):
        resp = client.post("/api/entries", json={"date": "2026-04-14", "day_type": day_type})
        assert resp.status_code == 201
        data = resp.json()
        assert data["day_type"] == day_type
        assert data["start_time"] is None
        assert data["end_time"] is None
        assert data["breaks"] == []
        assert data["net_hours"] == 0
        assert data["target_hours"] == 0
        assert data["surplus_hours"] == 0

    def test_multiple_breaks_sum_correctly(self, client, work_body):
        resp = client.post(
            "/api/entries", json=work_body(start="09:00", end="18:00", breaks_min=(60, 15))
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["total_break_minutes"] == 75
        # 9h gross - 75min breaks = 7h 45min = 7.75h
        assert data["net_hours"] == 7.75

    def test_duplicate_date_returns_409(self, client, work_body):
        assert client.post("/api/entries", json=work_body()).status_code == 201
        resp = client.post("/api/entries", json=work_body())
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"].lower()

    def test_notes_are_stored(self, client, work_body):
        resp = client.post(
            "/api/entries", json=work_body(notes="delayed start — lab meeting ran long")
        )
        assert resp.status_code == 201
        assert resp.json()["notes"] == "delayed start — lab meeting ran long"

    @pytest.mark.parametrize(
        "payload,reason",
        [
            (
                {"date": "2026-04-14", "day_type": "work"},
                "work day needs times",
            ),
            (
                {"date": "2026-04-14", "day_type": "work", "start_time": "09:00"},
                "work day needs both times",
            ),
            (
                {
                    "date": "2026-04-14",
                    "day_type": "work",
                    "start_time": "17:00",
                    "end_time": "09:00",
                    "breaks": [],
                },
                "end before start",
            ),
            (
                {
                    "date": "2026-04-14",
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "09:00",
                    "breaks": [],
                },
                "end equals start",
            ),
            (
                {
                    "date": "2026-04-14",
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "10:00",
                    "breaks": [{"break_minutes": 120}],
                },
                "break exceeds span",
            ),
            (
                {"date": "2026-04-14", "day_type": "vacation", "start_time": "09:00"},
                "vacation must not have times",
            ),
            (
                {"date": "2026-04-14", "day_type": "sick", "end_time": "17:00"},
                "sick must not have times",
            ),
            (
                {
                    "date": "2026-04-14",
                    "day_type": "holiday",
                    "breaks": [{"break_minutes": 30}],
                },
                "holiday must not have breaks",
            ),
            (
                {
                    "date": "2026-04-14",
                    "day_type": "work",
                    "start_time": "25:00",
                    "end_time": "17:00",
                    "breaks": [{"break_minutes": 60}],
                },
                "bad hour range",
            ),
            (
                {
                    "date": "2026-04-14",
                    "day_type": "work",
                    "start_time": "9:00",
                    "end_time": "17:00",
                    "breaks": [{"break_minutes": 60}],
                },
                "missing leading zero in time",
            ),
            (
                {
                    "date": "2026-04-14",
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "breaks": [{"break_minutes": 0}],
                },
                "zero-minute break",
            ),
            (
                {
                    "date": "2026-04-14",
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "breaks": [{"break_minutes": -10}],
                },
                "negative break",
            ),
            (
                {"date": "not-a-date", "day_type": "work"},
                "malformed date",
            ),
            (
                {"date": "2026-04-14", "day_type": "nope"},
                "unknown day_type",
            ),
        ],
    )
    def test_rejects_invalid(self, client, payload, reason):
        resp = client.post("/api/entries", json=payload)
        assert resp.status_code == 422, f"expected 422 ({reason}), got {resp.status_code}"


class TestListEntries:
    def test_empty(self, client):
        resp = client.get("/api/entries")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_sorted_asc(self, client, work_body):
        for d in ["2026-04-15", "2026-04-13", "2026-04-14"]:
            assert client.post("/api/entries", json=work_body(date=d)).status_code == 201
        dates = [e["date"] for e in client.get("/api/entries").json()]
        assert dates == ["2026-04-13", "2026-04-14", "2026-04-15"]

    def test_range_filter(self, client, work_body):
        for d in ["2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16"]:
            client.post("/api/entries", json=work_body(date=d))

        resp = client.get("/api/entries?from=2026-04-14")
        assert [e["date"] for e in resp.json()] == ["2026-04-14", "2026-04-15", "2026-04-16"]

        resp = client.get("/api/entries?to=2026-04-14")
        assert [e["date"] for e in resp.json()] == ["2026-04-13", "2026-04-14"]

        resp = client.get("/api/entries?from=2026-04-14&to=2026-04-15")
        assert [e["date"] for e in resp.json()] == ["2026-04-14", "2026-04-15"]


class TestGetEntry:
    def test_found(self, client, work_body):
        client.post("/api/entries", json=work_body())
        resp = client.get("/api/entries/2026-04-14")
        assert resp.status_code == 200
        assert resp.json()["date"] == "2026-04-14"

    def test_not_found(self, client):
        assert client.get("/api/entries/2026-04-14").status_code == 404

    def test_malformed_date_422(self, client):
        assert client.get("/api/entries/not-a-date").status_code == 422


class TestUpdateEntry:
    def test_full_replace(self, client, work_body):
        client.post("/api/entries", json=work_body())
        resp = client.put(
            "/api/entries/2026-04-14",
            json={
                "day_type": "work",
                "start_time": "08:00",
                "end_time": "18:00",
                "breaks": [{"break_minutes": 30}],
                "notes": "early start",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["start_time"] == "08:00"
        assert data["end_time"] == "18:00"
        assert data["total_break_minutes"] == 30
        assert data["net_hours"] == 9.5
        assert data["notes"] == "early start"

    def test_change_work_to_vacation(self, client, work_body):
        client.post("/api/entries", json=work_body())
        resp = client.put("/api/entries/2026-04-14", json={"day_type": "vacation"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["day_type"] == "vacation"
        assert data["start_time"] is None
        assert data["end_time"] is None
        assert data["breaks"] == []

    def test_change_vacation_to_work_rejects_without_times(self, client):
        client.post("/api/entries", json={"date": "2026-04-14", "day_type": "vacation"})
        # No times → 422 (matches user preference #9)
        resp = client.put("/api/entries/2026-04-14", json={"day_type": "work"})
        assert resp.status_code == 422

    def test_change_vacation_to_work_with_times(self, client):
        client.post("/api/entries", json={"date": "2026-04-14", "day_type": "vacation"})
        resp = client.put(
            "/api/entries/2026-04-14",
            json={
                "day_type": "work",
                "start_time": "09:00",
                "end_time": "17:00",
                "breaks": [{"break_minutes": 60}],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["net_hours"] == 7.0

    def test_put_replaces_breaks(self, client, work_body):
        client.post("/api/entries", json=work_body(breaks_min=(60, 15)))
        client.put(
            "/api/entries/2026-04-14",
            json={
                "day_type": "work",
                "start_time": "09:00",
                "end_time": "18:00",
                "breaks": [{"break_minutes": 30}],
            },
        )
        data = client.get("/api/entries/2026-04-14").json()
        assert len(data["breaks"]) == 1
        assert data["breaks"][0]["break_minutes"] == 30

    def test_update_nonexistent_returns_404(self, client, work_body):
        resp = client.put(
            "/api/entries/2026-04-14",
            json={
                "day_type": "work",
                "start_time": "09:00",
                "end_time": "17:00",
                "breaks": [{"break_minutes": 60}],
            },
        )
        assert resp.status_code == 404


class TestDeleteEntry:
    def test_delete_removes_entry(self, client, work_body):
        client.post("/api/entries", json=work_body())
        assert client.delete("/api/entries/2026-04-14").status_code == 204
        assert client.get("/api/entries/2026-04-14").status_code == 404

    def test_delete_cascades_breaks(self, client, db_session, work_body):
        client.post("/api/entries", json=work_body(breaks_min=(60, 15)))
        assert db_session.scalar(select(func.count()).select_from(Break)) == 2
        client.delete("/api/entries/2026-04-14")
        assert db_session.scalar(select(func.count()).select_from(Break)) == 0

    def test_delete_nonexistent_returns_404(self, client):
        assert client.delete("/api/entries/2026-04-14").status_code == 404
