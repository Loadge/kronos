"""API tests for /api/templates CRUD."""

from __future__ import annotations


_TPL = {"name": "Standard day", "start_time": "09:00", "end_time": "17:00", "breaks": [{"break_minutes": 60}]}
_TPL_NO_BREAKS = {"name": "Short day", "start_time": "09:00", "end_time": "13:00"}


class TestListTemplates:
    def test_empty_by_default(self, client):
        resp = client.get("/api/templates")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_created_templates(self, client):
        client.post("/api/templates", json=_TPL)
        client.post("/api/templates", json=_TPL_NO_BREAKS)
        resp = client.get("/api/templates")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestCreateTemplate:
    def test_happy_path(self, client):
        resp = client.post("/api/templates", json=_TPL)
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] is not None
        assert data["name"] == "Standard day"
        assert data["start_time"] == "09:00"
        assert data["end_time"] == "17:00"
        assert len(data["breaks"]) == 1
        assert data["breaks"][0]["break_minutes"] == 60

    def test_no_breaks(self, client):
        resp = client.post("/api/templates", json=_TPL_NO_BREAKS)
        assert resp.status_code == 201
        assert resp.json()["breaks"] == []

    def test_break_with_times(self, client):
        body = {"name": "Lunch break", "start_time": "08:00", "end_time": "17:00",
                "breaks": [{"start_time": "12:00", "end_time": "13:00"}]}
        resp = client.post("/api/templates", json=body)
        assert resp.status_code == 201
        b = resp.json()["breaks"][0]
        assert b["break_minutes"] == 60
        assert b["start_time"] == "12:00"
        assert b["end_time"] == "13:00"

    def test_name_too_long(self, client):
        body = {**_TPL, "name": "x" * 101}
        resp = client.post("/api/templates", json=body)
        assert resp.status_code == 422

    def test_empty_name_rejected(self, client):
        resp = client.post("/api/templates", json={**_TPL, "name": ""})
        assert resp.status_code == 422

    def test_breaks_exceed_span_rejected(self, client):
        body = {"name": "Bad", "start_time": "09:00", "end_time": "10:00",
                "breaks": [{"break_minutes": 90}]}
        resp = client.post("/api/templates", json=body)
        assert resp.status_code == 422


class TestDeleteTemplate:
    def test_delete_removes_template(self, client):
        created = client.post("/api/templates", json=_TPL).json()
        resp = client.delete(f"/api/templates/{created['id']}")
        assert resp.status_code == 204
        assert client.get("/api/templates").json() == []

    def test_delete_nonexistent_returns_404(self, client):
        resp = client.delete("/api/templates/9999")
        assert resp.status_code == 404
