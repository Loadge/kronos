"""Tests for GET /api/backup and POST /api/restore."""

from __future__ import annotations

import json


# ── helpers ────────────────────────────────────────────────────────────────

def _payload(entries=None, settings=None, version=1):
    return {
        "version": version,
        "exported_at": "2026-01-01T00:00:00Z",
        "settings": settings or {
            "daily_target_hours": 8.0,
            "cumulative_start_date": "2025-01-01",
        },
        "entries": entries or [],
    }


def _work_entry(date="2026-03-10", start="09:00", end="17:00", breaks=(60,), notes=None):
    return {
        "date": date,
        "day_type": "work",
        "start_time": start,
        "end_time": end,
        "notes": notes,
        "breaks": [{"break_minutes": m} for m in breaks],
    }


def _off_entry(date, day_type="vacation"):
    return {"date": date, "day_type": day_type, "start_time": None, "end_time": None, "notes": None, "breaks": []}


# ── GET /api/backup ────────────────────────────────────────────────────────

class TestDownloadBackup:
    def test_empty_db_returns_valid_structure(self, client):
        r = client.get("/api/backup")
        assert r.status_code == 200
        body = r.json()
        assert body["version"] == 1
        assert "exported_at" in body
        assert body["entries"] == []
        assert "settings" in body
        assert "daily_target_hours" in body["settings"]
        assert "cumulative_start_date" in body["settings"]

    def test_content_disposition_header(self, client):
        r = client.get("/api/backup")
        cd = r.headers["content-disposition"]
        assert "attachment" in cd
        assert "kronos_backup_" in cd
        assert cd.endswith('.json"')

    def test_backup_contains_entries(self, client, work_body):
        client.post("/api/entries", json=work_body(date="2026-04-14", breaks_min=(30,)))
        body = client.get("/api/backup").json()
        assert len(body["entries"]) == 1
        e = body["entries"][0]
        assert e["date"] == "2026-04-14"
        assert e["day_type"] == "work"
        assert e["start_time"] == "09:00"
        assert e["breaks"] == [{"break_minutes": 30}]

    def test_backup_contains_non_work_entries(self, client):
        client.post("/api/entries", json={"date": "2026-04-14", "day_type": "vacation", "breaks": []})
        body = client.get("/api/backup").json()
        e = body["entries"][0]
        assert e["day_type"] == "vacation"
        assert e["start_time"] is None
        assert e["breaks"] == []

    def test_backup_reflects_current_settings(self, client):
        client.put("/api/config", json={"daily_target_hours": 7.5, "cumulative_start_date": "2024-06-01"})
        body = client.get("/api/backup").json()
        assert body["settings"]["daily_target_hours"] == 7.5
        assert body["settings"]["cumulative_start_date"] == "2024-06-01"

    def test_backup_entries_ordered_by_date(self, client, work_body):
        for d in ["2026-04-16", "2026-04-14", "2026-04-15"]:
            client.post("/api/entries", json=work_body(date=d))
        dates = [e["date"] for e in client.get("/api/backup").json()["entries"]]
        assert dates == sorted(dates)


# ── POST /api/restore ──────────────────────────────────────────────────────

class TestRestoreBackup:
    def test_restore_empty_payload(self, client):
        r = client.post("/api/restore", json=_payload())
        assert r.status_code == 200
        assert r.json()["restored_entries"] == 0

    def test_restore_imports_work_entries(self, client):
        payload = _payload(entries=[_work_entry("2026-03-10", breaks=(30, 15))])
        r = client.post("/api/restore", json=payload)
        assert r.status_code == 200
        assert r.json()["restored_entries"] == 1

        entries = client.get("/api/entries").json()
        assert len(entries) == 1
        e = entries[0]
        assert e["date"] == "2026-03-10"
        assert e["total_break_minutes"] == 45

    def test_restore_imports_non_work_entries(self, client):
        payload = _payload(entries=[
            _off_entry("2026-03-10", "vacation"),
            _off_entry("2026-03-11", "sick"),
            _off_entry("2026-03-12", "holiday"),
        ])
        r = client.post("/api/restore", json=payload)
        assert r.status_code == 200
        assert r.json()["restored_entries"] == 3

    def test_restore_wipes_existing_entries(self, client, work_body):
        client.post("/api/entries", json=work_body(date="2099-12-31"))
        assert len(client.get("/api/entries").json()) == 1

        client.post("/api/restore", json=_payload(entries=[_work_entry("2026-01-02")]))

        entries = client.get("/api/entries").json()
        assert len(entries) == 1
        assert entries[0]["date"] == "2026-01-02"

    def test_restore_cascades_old_breaks(self, client, work_body):
        """Old break rows must not survive after restore (no orphans)."""
        client.post("/api/entries", json=work_body(date="2026-04-14", breaks_min=(30, 45)))
        client.post("/api/restore", json=_payload())
        # Re-creating the same date must succeed — PK is free
        r = client.post("/api/entries", json=work_body(date="2026-04-14"))
        assert r.status_code == 201

    def test_restore_applies_settings(self, client):
        payload = _payload(settings={
            "daily_target_hours": 6.5,
            "cumulative_start_date": "2024-06-01",
        })
        client.post("/api/restore", json=payload)
        cfg = client.get("/api/config").json()
        assert cfg["daily_target_hours"] == 6.5
        assert cfg["cumulative_start_date"] == "2024-06-01"

    def test_restore_without_settings_preserves_existing(self, client):
        client.put("/api/config", json={"daily_target_hours": 6.0})
        payload = _payload()
        payload["settings"] = None  # omit settings
        client.post("/api/restore", json=payload)
        assert client.get("/api/config").json()["daily_target_hours"] == 6.0

    def test_restore_unsupported_version(self, client):
        r = client.post("/api/restore", json={"version": 99, "entries": []})
        assert r.status_code == 422

    def test_restore_invalid_entry_rejected(self, client):
        """Work entry missing start_time → 422, DB unchanged."""
        payload = _payload(entries=[{
            "date": "2026-03-10", "day_type": "work",
            "start_time": None, "end_time": None, "breaks": [],
        }])
        r = client.post("/api/restore", json=payload)
        assert r.status_code == 422


class TestRoundtrip:
    def test_backup_restore_backup_produces_identical_entries(self, client, work_body):
        """Full roundtrip: seed → backup → wipe → restore → backup must match."""
        client.post("/api/entries", json=work_body(date="2026-04-14", breaks_min=(30, 45)))
        client.post("/api/entries", json={"date": "2026-04-15", "day_type": "vacation", "breaks": []})
        client.put("/api/config", json={"daily_target_hours": 7.0})

        backup1 = client.get("/api/backup").json()

        client.delete("/api/data")
        assert client.get("/api/entries").json() == []

        r = client.post("/api/restore", json=backup1)
        assert r.json()["restored_entries"] == 2

        backup2 = client.get("/api/backup").json()

        assert len(backup2["entries"]) == len(backup1["entries"])
        for e1, e2 in zip(backup1["entries"], backup2["entries"]):
            assert e1["date"] == e2["date"]
            assert e1["day_type"] == e2["day_type"]
            assert e1["breaks"] == e2["breaks"]
        assert backup2["settings"]["daily_target_hours"] == 7.0
