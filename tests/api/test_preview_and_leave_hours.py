"""API tests for POST /api/entries/preview and for ``leave_hours`` as the alternative to
``fraction`` on entries, batch logging and planner drafts."""

from __future__ import annotations

import pytest


class TestPreview:
    def test_work_day_is_computed_and_not_written(self, client, work_body):
        resp = client.post("/api/entries/preview", json=work_body(start="09:00", end="18:00"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["net_hours"] == 8.0
        assert data["target_hours"] == 8.0
        assert data["surplus_hours"] == 0.0
        assert data["breaks"][0]["id"] == 1  # transient breaks are numbered, not null
        assert data["exists"] is False
        assert client.get("/api/entries/2026-04-14").status_code == 404
        assert client.get("/api/entries").json() == []

    def test_exists_flags_a_taken_date(self, client, work_body):
        client.post("/api/entries", json=work_body())
        data = client.post("/api/entries/preview", json=work_body(start="10:00")).json()
        assert data["exists"] is True
        # The stored day is untouched.
        assert client.get("/api/entries/2026-04-14").json()["start_time"] == "09:00"

    def test_validation_errors_surface(self, client, work_body):
        body = work_body(start="09:00", end="09:30", breaks_min=(60,))
        resp = client.post("/api/entries/preview", json=body)
        assert resp.status_code == 422
        assert "exceed" in resp.text

    def test_leave_hours_resolve_in_preview(self, client):
        resp = client.post(
            "/api/entries/preview",
            json={"date": "2026-04-14", "day_type": "vacation", "leave_hours": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["fraction"] == 0.375
        assert data["leave_hours"] == 3.0
        assert data["target_hours"] == 5.0


class TestLeaveHoursOnEntries:
    def test_create_partial_from_hours(self, client):
        resp = client.post(
            "/api/entries",
            json={
                "date": "2026-04-14",
                "day_type": "vacation",
                "leave_hours": 3,
                "start_time": "09:00",
                "end_time": "14:00",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["fraction"] == 0.375
        assert data["leave_hours"] == 3.0
        assert data["net_hours"] == 5.0
        assert data["target_hours"] == 5.0
        assert data["surplus_hours"] == 0.0

    def test_hours_equal_to_target_is_a_whole_day(self, client):
        resp = client.post(
            "/api/entries", json={"date": "2026-04-14", "day_type": "sick", "leave_hours": 8}
        )
        assert resp.status_code == 201
        assert resp.json()["fraction"] == 1.0

    def test_whole_day_from_hours_rejects_times(self, client):
        resp = client.post(
            "/api/entries",
            json={
                "date": "2026-04-14",
                "day_type": "sick",
                "leave_hours": 8,
                "start_time": "09:00",
                "end_time": "10:00",
            },
        )
        assert resp.status_code == 422
        assert "must not have" in resp.json()["detail"]

    def test_more_than_the_target_is_422(self, client):
        resp = client.post(
            "/api/entries", json={"date": "2026-04-14", "day_type": "vacation", "leave_hours": 9}
        )
        assert resp.status_code == 422
        assert "exceed the 8h target on 2026-04-14" in resp.json()["detail"]

    def test_uses_the_target_in_force_on_that_date(self, client):
        client.put(
            "/api/config/daily-target-schedule",
            json={
                "rows": [
                    {"effective_from": "2026-01-01", "hours": 8},
                    {"effective_from": "2026-06-01", "hours": 6},
                ]
            },
        )
        before = client.post(
            "/api/entries", json={"date": "2026-05-01", "day_type": "vacation", "leave_hours": 3}
        ).json()
        after = client.post(
            "/api/entries", json={"date": "2026-06-02", "day_type": "vacation", "leave_hours": 3}
        ).json()
        assert before["fraction"] == 0.375
        assert after["fraction"] == 0.5

    def test_both_fraction_and_hours_is_422(self, client):
        resp = client.post(
            "/api/entries",
            json={"date": "2026-04-14", "day_type": "vacation", "fraction": 0.5, "leave_hours": 4},
        )
        assert resp.status_code == 422
        assert "not both" in resp.text

    def test_hours_on_a_work_day_is_422(self, client, work_body):
        resp = client.post("/api/entries", json={**work_body(), "leave_hours": 2})
        assert resp.status_code == 422
        assert "work days have no leave_hours" in resp.text

    def test_update_from_hours(self, client, work_body):
        client.post("/api/entries", json=work_body())
        resp = client.put(
            "/api/entries/2026-04-14",
            json={"day_type": "flex", "leave_hours": 2, "start_time": "09:00", "end_time": "15:00"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["fraction"] == 0.25
        assert data["leave_hours"] == 2.0


class TestBatch:
    def test_leave_hours_resolve_per_date(self, client):
        client.put(
            "/api/config/daily-target-schedule",
            json={
                "rows": [
                    {"effective_from": "2026-01-01", "hours": 8},
                    {"effective_from": "2026-06-01", "hours": 4},
                ]
            },
        )
        resp = client.post(
            "/api/entries/batch",
            json={"dates": ["2026-05-29", "2026-06-01"], "day_type": "vacation", "leave_hours": 2},
        )
        assert resp.status_code == 200
        assert resp.json()["created"] == ["2026-05-29", "2026-06-01"]
        assert client.get("/api/entries/2026-05-29").json()["fraction"] == 0.25
        assert client.get("/api/entries/2026-06-01").json()["fraction"] == 0.5

    def test_notes_go_on_every_day(self, client):
        resp = client.post(
            "/api/entries/batch",
            json={"dates": ["2026-12-24", "2026-12-31"], "day_type": "vacation", "notes": "xmas"},
        )
        assert resp.status_code == 200
        assert client.get("/api/entries/2026-12-24").json()["notes"] == "xmas"
        assert client.get("/api/entries/2026-12-31").json()["notes"] == "xmas"

    def test_same_date_twice_is_created_once(self, client):
        resp = client.post(
            "/api/entries/batch", json={"dates": ["2026-12-24", "2026-12-24"], "day_type": "sick"}
        )
        assert resp.json() == {"created": ["2026-12-24"], "skipped": ["2026-12-24"]}

    def test_hours_over_target_is_422(self, client):
        resp = client.post(
            "/api/entries/batch",
            json={"dates": ["2026-12-24"], "day_type": "vacation", "leave_hours": 10},
        )
        assert resp.status_code == 422


class TestPlans:
    def test_leave_hours_on_drafts(self, client):
        resp = client.post(
            "/api/plans",
            json={"dates": ["2026-12-24"], "day_type": "vacation", "leave_hours": 4},
        )
        assert resp.status_code == 200
        assert resp.json()["drafted"] == ["2026-12-24"]
        plan = client.get("/api/plans?year=2026").json()[0]
        assert plan["fraction"] == 0.5
        assert plan["leave_hours"] == 4.0

    def test_same_date_twice_drafts_once(self, client):
        resp = client.post(
            "/api/plans", json={"dates": ["2026-12-24", "2026-12-24"], "day_type": "flex"}
        )
        assert resp.json()["drafted"] == ["2026-12-24"]
        assert resp.json()["replaced"] == ["2026-12-24"]
        assert len(client.get("/api/plans?year=2026").json()) == 1

    @pytest.mark.parametrize("hours", [0, -1, 25])
    def test_out_of_range_hours_is_422(self, client, hours):
        resp = client.post(
            "/api/plans",
            json={"dates": ["2026-12-24"], "day_type": "vacation", "leave_hours": hours},
        )
        assert resp.status_code == 422

    def test_commit_twice_in_one_request_creates_once(self, client):
        client.post("/api/plans", json={"dates": ["2026-12-24"], "day_type": "vacation"})
        resp = client.post("/api/plans/commit", json={"dates": ["2026-12-24", "2026-12-24"]})
        assert resp.json() == {"created": ["2026-12-24"], "skipped": [], "missing": ["2026-12-24"]}
        assert client.get("/api/entries/2026-12-24").status_code == 200


class TestHttpLayer:
    def test_large_json_is_gzipped_when_asked(self, client, work_body):
        for day in range(1, 29):
            client.post("/api/entries", json=work_body(date=f"2026-04-{day:02d}"))
        resp = client.get("/api/entries", headers={"Accept-Encoding": "gzip"})
        assert resp.status_code == 200
        assert resp.headers.get("content-encoding") == "gzip"
        assert len(resp.json()) == 28  # the client transparently decodes

    def test_small_bodies_are_not_gzipped(self, client):
        resp = client.get("/healthz", headers={"Accept-Encoding": "gzip"})
        assert resp.headers.get("content-encoding") is None

    def test_vendor_files_are_cached_for_a_year_and_versioned(self, client):
        resp = client.get("/static/vendor/alpine.min.js")
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert "cache-control" not in client.get("/static/app.js").headers
        html = client.get("/").text
        assert "/static/vendor/alpine.min.js?v=" in html
        assert "/static/vendor/pico.min.css?v=" in html
