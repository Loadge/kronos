"""Backup fidelity: a backup restored into an empty Kronos must back up identically.

The single strongest guard for the portability promise. Every field that rides in the
file (entries with breaks and partial-day fractions, planner drafts with notes, the
target timeline, the profile) is exercised, so a field added to the model but
forgotten in backup *or* restore fails here.
"""

from __future__ import annotations


def _populate(client):
    client.put(
        "/api/config/daily-target-schedule",
        json={
            "rows": [
                {"effective_from": "2025-01-01", "hours": 8},
                {"effective_from": "2026-06-01", "hours": 6.5},
            ]
        },
    )
    client.put(
        "/api/config",
        json={
            "cumulative_start_date": "2025-01-01",
            "vacation_budget_days": 22.5,
            "profile_name": "Juan Pérez",
            "profile_employer": "ACME",
            "profile_extra": "nº 4711",
        },
    )
    client.post(
        "/api/entries",
        json={
            "date": "2026-03-02",
            "day_type": "work",
            "start_time": "08:45",
            "end_time": "18:15",
            "notes": "two breaks, one timed",
            "breaks": [{"break_minutes": 45}, {"start_time": "16:00", "end_time": "16:20"}],
        },
    )
    client.post(
        "/api/entries", json={"date": "2026-03-03", "day_type": "holiday", "notes": "fiesta"}
    )
    client.post(
        "/api/entries",
        json={
            "date": "2026-03-04",
            "day_type": "vacation",
            "fraction": 0.375,
            "start_time": "09:00",
            "end_time": "14:00",
        },
    )
    client.post("/api/entries", json={"date": "2026-03-05", "day_type": "flex", "fraction": 0.5})
    client.post(
        "/api/plans",
        json={"dates": ["2026-12-21", "2026-12-22"], "day_type": "vacation", "notes": "Christmas"},
    )
    client.post("/api/plans", json={"dates": ["2026-11-13"], "day_type": "flex", "fraction": 0.5})


def _wipe_everything(client):
    client.delete("/api/data")
    client.put(
        "/api/config/daily-target-schedule",
        json={"rows": [{"effective_from": "2020-01-01", "hours": 7}]},
    )
    client.put(
        "/api/config",
        json={
            "cumulative_start_date": "2020-01-01",
            "vacation_budget_days": 0,
            "profile_name": "",
            "profile_employer": "",
            "profile_extra": "",
        },
    )


def _strip(backup):
    return {k: v for k, v in backup.items() if k != "exported_at"}


class TestBreakTimesSurvive:
    """Found while writing the identity test: the file used to carry only the minutes."""

    def test_timed_break_restores_with_its_range(self, client):
        _populate(client)
        backup = client.get("/api/backup").json()
        timed = backup["entries"][0]["breaks"][1]
        assert (timed["start_time"], timed["end_time"], timed["break_minutes"]) == (
            "16:00",
            "16:20",
            20,
        )
        _wipe_everything(client)
        client.post("/api/restore", json=backup)
        breaks = client.get("/api/entries/2026-03-02").json()["breaks"]
        assert [(b["start_time"], b["end_time"], b["break_minutes"]) for b in breaks] == [
            (None, None, 45),
            ("16:00", "16:20", 20),
        ]

    def test_old_file_with_minutes_only_still_restores(self, client):
        old = {
            "version": 1,
            "entries": [
                {
                    "date": "2026-03-02",
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "breaks": [{"break_minutes": 30}],
                }
            ],
        }
        assert client.post("/api/restore", json=old).status_code == 200
        (b,) = client.get("/api/entries/2026-03-02").json()["breaks"]
        assert (b["break_minutes"], b["start_time"]) == (30, None)


class TestBackupRoundTripIsIdentity:
    def test_backup_restore_backup_is_identical(self, client):
        _populate(client)
        first = client.get("/api/backup").json()
        assert first["version"] == 2
        assert len(first["entries"]) == 4 and len(first["plans"]) == 3

        _wipe_everything(client)
        assert client.get("/api/entries").json() == []
        assert client.get("/api/plans").json() == []
        assert client.get("/api/config").json()["profile_name"] == ""

        assert client.post("/api/restore", json=first).status_code == 200
        second = client.get("/api/backup").json()
        assert _strip(second) == _strip(first)

    def test_restore_is_idempotent(self, client):
        _populate(client)
        first = client.get("/api/backup").json()
        client.post("/api/restore", json=first)
        client.post("/api/restore", json=first)
        assert _strip(client.get("/api/backup").json()) == _strip(first)
        assert len(client.get("/api/entries").json()) == 4

    def test_every_documented_field_is_in_the_file(self, client):
        """If a new field lands on an entry / plan / setting, it must show up here too."""
        _populate(client)
        backup = client.get("/api/backup").json()
        assert set(backup) == {"version", "exported_at", "settings", "entries", "plans"}
        assert set(backup["entries"][0]) == {
            "date",
            "day_type",
            "fraction",
            "start_time",
            "end_time",
            "notes",
            "breaks",
        }
        assert set(backup["entries"][0]["breaks"][0]) == {"break_minutes", "start_time", "end_time"}
        assert set(backup["plans"][0]) == {"date", "day_type", "fraction", "notes"}
        assert {
            "daily_target_hours",
            "daily_target_schedule",
            "cumulative_start_date",
            "profile_name",
            "profile_employer",
            "profile_extra",
        } <= set(backup["settings"])
