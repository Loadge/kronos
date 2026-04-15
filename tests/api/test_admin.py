"""Tests for the admin / danger-zone endpoints."""

from __future__ import annotations


class TestSeedData:
    def test_seed_populates_entries(self, client):
        r = client.post("/api/data/seed")
        assert r.status_code == 200
        body = r.json()
        assert body["seeded"] > 0
        assert body["work"] > 0
        # non-work day types are present
        assert body["vacation"] + body["sick"] + body["holiday"] > 0
        assert body["work"] + body["vacation"] + body["sick"] + body["holiday"] == body["seeded"]

    def test_seed_entries_appear_in_list(self, client):
        client.post("/api/data/seed")
        entries = client.get("/api/entries").json()
        assert len(entries) > 0

    def test_seed_is_idempotent(self, client):
        r1 = client.post("/api/data/seed")
        r2 = client.post("/api/data/seed")
        assert r1.json() == r2.json()
        # After two seeds the DB should have the same count as after one.
        assert len(client.get("/api/entries").json()) == r2.json()["seeded"]

    def test_seed_wipes_existing_data_first(self, client, work_body):
        # Manually create a unique entry that the seed would never produce.
        client.post("/api/entries", json=work_body(date="2099-12-31"))
        assert client.get("/api/entries/2099-12-31").status_code == 200

        client.post("/api/data/seed")

        # That future entry should be gone after the seed wipe.
        assert client.get("/api/entries/2099-12-31").status_code == 404

    def test_seed_preserves_settings(self, client):
        client.put("/api/config", json={"daily_target_hours": 6.0})
        client.post("/api/data/seed")
        assert client.get("/api/config").json()["daily_target_hours"] == 6.0


class TestWipeAllData:
    def test_wipe_empty_db_returns_zero(self, client):
        r = client.delete("/api/data")
        assert r.status_code == 200
        assert r.json() == {"deleted_entries": 0}

    def test_wipe_deletes_all_entries(self, client, work_body):
        # Seed a handful of entries.
        for d in ["2026-04-14", "2026-04-15", "2026-04-16"]:
            assert client.post("/api/entries", json=work_body(date=d)).status_code == 201
        assert len(client.get("/api/entries").json()) == 3

        r = client.delete("/api/data")
        assert r.status_code == 200
        assert r.json() == {"deleted_entries": 3}
        assert client.get("/api/entries").json() == []

    def test_wipe_cascades_breaks(self, client, work_body):
        # Entry with multiple breaks — DELETE /api/data must not leave orphan break rows.
        body = work_body(date="2026-04-14", breaks_min=(30, 45, 60))
        assert client.post("/api/entries", json=body).status_code == 201

        r = client.delete("/api/data")
        assert r.status_code == 200
        assert r.json() == {"deleted_entries": 1}

        # Re-creating the same date should succeed (PK is free again).
        assert client.post("/api/entries", json=work_body(date="2026-04-14")).status_code == 201

    def test_wipe_preserves_settings(self, client):
        # Change a setting, wipe data, settings should still be there.
        client.put("/api/config", json={"daily_target_hours": 6.5})

        client.delete("/api/data")

        cfg = client.get("/api/config").json()
        assert cfg["daily_target_hours"] == 6.5

    def test_wipe_twice_is_idempotent(self, client, work_body):
        assert client.post("/api/entries", json=work_body()).status_code == 201

        first = client.delete("/api/data")
        assert first.json() == {"deleted_entries": 1}

        second = client.delete("/api/data")
        assert second.status_code == 200
        assert second.json() == {"deleted_entries": 0}
