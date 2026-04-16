"""Regression tests for previously-discovered bugs and boundary conditions.

Each class is named after the invariant it protects.  If a test in this file
ever starts failing it means a real regression occurred — these cover cases
that were either explicitly fixed during development or that are easy to break
when refactoring computation or persistence logic.
"""

from __future__ import annotations

import csv
import io


# ── helpers ───────────────────────────────────────────────────────────────────


def _post(client, body):
    r = client.post("/api/entries", json=body)
    assert r.status_code == 201, r.text
    return r


def _put(client, date, body):
    r = client.put(f"/api/entries/{date}", json=body)
    assert r.status_code == 200, r.text
    return r


def _work(date, start="09:00", end="17:00", breaks=(60,), notes=None):
    body = {
        "date": date,
        "day_type": "work",
        "start_time": start,
        "end_time": end,
        "breaks": [{"break_minutes": m} for m in breaks],
    }
    if notes is not None:
        body["notes"] = notes
    return body


def _off(date, day_type="vacation"):
    return {"date": date, "day_type": day_type}


def _backup_payload(entries=None, settings=None, version=1):
    return {
        "version": version,
        "exported_at": "2026-01-01T00:00:00Z",
        "settings": settings or {"daily_target_hours": 8.0, "cumulative_start_date": "2025-01-01"},
        "entries": entries or [],
    }


def _backup_work_entry(date, start="09:00", end="17:00", breaks=(60,), notes=None):
    return {
        "date": date,
        "day_type": "work",
        "start_time": start,
        "end_time": end,
        "notes": notes,
        "breaks": [{"break_minutes": m} for m in breaks],
    }


# ── TestCumulativeStartDateExclusion ─────────────────────────────────────────


class TestCumulativeStartDateExclusion:
    """Entries before the cumulative start date must never appear in the cumulative total."""

    def test_entry_on_start_date_is_included(self, client, work_body):
        client.put("/api/config", json={"cumulative_start_date": "2026-04-01"})
        _post(client, work_body(date="2026-04-01"))  # exactly on the boundary
        data = client.get("/api/dashboard?today=2026-04-14").json()
        assert data["cumulative"]["work_days"] == 1

    def test_entry_before_start_date_is_excluded(self, client, work_body):
        client.put("/api/config", json={"cumulative_start_date": "2026-04-01"})
        _post(client, work_body(date="2026-03-31"))  # one day before
        _post(client, work_body(date="2026-04-01"))
        data = client.get("/api/dashboard?today=2026-04-14").json()
        assert data["cumulative"]["work_days"] == 1
        assert data["cumulative"]["net_hours"] == 7.0

    def test_all_entries_before_start_date_gives_zero_cumulative(self, client, work_body):
        client.put("/api/config", json={"cumulative_start_date": "2026-04-01"})
        for d in ["2026-01-10", "2026-02-20", "2026-03-31"]:
            _post(client, work_body(date=d))
        data = client.get("/api/dashboard?today=2026-04-14").json()
        assert data["cumulative"]["work_days"] == 0
        assert data["cumulative"]["net_hours"] == 0.0
        assert data["cumulative"]["target_hours"] == 0.0
        assert data["cumulative"]["surplus_hours"] == 0.0

    def test_moving_start_date_forward_excludes_previously_counted_entries(self, client, work_body):
        _post(client, work_body(date="2026-03-01"))
        _post(client, work_body(date="2026-04-01"))

        # With default start (2025-01-01) both entries count
        data = client.get("/api/dashboard?today=2026-04-14").json()
        assert data["cumulative"]["work_days"] == 2

        # Move start date past the March entry
        client.put("/api/config", json={"cumulative_start_date": "2026-04-01"})
        data = client.get("/api/dashboard?today=2026-04-14").json()
        assert data["cumulative"]["work_days"] == 1


# ── TestAsOfBoundary ──────────────────────────────────────────────────────────


class TestAsOfBoundary:
    """GET /api/analytics/cumulative?as_of= boundary semantics."""

    def test_as_of_is_inclusive(self, client, work_body):
        _post(client, work_body(date="2026-04-14"))
        resp = client.get("/api/analytics/cumulative?as_of=2026-04-14")
        assert resp.json()["work_days"] == 1

    def test_as_of_excludes_day_after(self, client, work_body):
        _post(client, work_body(date="2026-04-14"))
        resp = client.get("/api/analytics/cumulative?as_of=2026-04-13")
        assert resp.json()["work_days"] == 0

    def test_empty_db_returns_zeros(self, client):
        resp = client.get("/api/analytics/cumulative?as_of=2026-04-14")
        assert resp.status_code == 200
        data = resp.json()
        assert data["net_hours"] == 0.0
        assert data["target_hours"] == 0.0
        assert data["surplus_hours"] == 0.0

    def test_as_of_honours_cumulative_start_date(self, client, work_body):
        client.put("/api/config", json={"cumulative_start_date": "2026-04-01"})
        _post(client, work_body(date="2026-03-31"))  # before window
        _post(client, work_body(date="2026-04-14"))  # inside window
        resp = client.get("/api/analytics/cumulative?as_of=2026-04-14")
        assert resp.json()["work_days"] == 1

    def test_missing_as_of_returns_422(self, client):
        assert client.get("/api/analytics/cumulative").status_code == 422


# ── TestFloatPrecision ────────────────────────────────────────────────────────


class TestFloatPrecision:
    """Surplus/deficit values must not accumulate floating-point drift."""

    def test_surplus_rounds_to_two_decimal_places(self, client):
        # 7h30m net (no breaks); target 8h; surplus = -0.5
        _post(client, _work("2026-04-14", start="09:00", end="16:30", breaks=()))
        e = client.get("/api/entries/2026-04-14").json()
        assert e["surplus_hours"] == -0.5

    def test_fractional_target_with_many_days_no_drift(self, client):
        """7.5h target × 4 work days; net each day = 8.5h → surplus = +4.0 total."""
        client.put("/api/config", json={"daily_target_hours": 7.5})
        dates = ["2026-04-07", "2026-04-08", "2026-04-09", "2026-04-10"]
        for d in dates:
            _post(client, _work(d, start="09:00", end="17:30", breaks=()))  # 8.5h net
        # 4 × 8.5 = 34.0 net, 4 × 7.5 = 30.0 target → surplus = +4.0
        resp = client.get("/api/analytics/cumulative?as_of=2026-04-10")
        data = resp.json()
        assert data["net_hours"] == 34.0
        assert data["target_hours"] == 30.0
        assert data["surplus_hours"] == 4.0

    def test_break_minutes_do_not_exceed_work_span(self, client):
        """Break > span is rejected with 422 — guard against negative net hours."""
        r = client.post("/api/entries", json=_work(
            "2026-04-14", start="09:00", end="10:00", breaks=(120,),  # 120 min break > 60 min span
        ))
        assert r.status_code == 422


# ── TestBackupRestorePreservesAllFields ───────────────────────────────────────


class TestBackupRestorePreservesAllFields:
    """Every field written in a backup must survive the restore→re-export cycle intact."""

    def test_notes_survive_roundtrip(self, client):
        notes_text = "shipped v2.0, pairing session with Kai, coffee ☕"
        payload = _backup_payload(entries=[_backup_work_entry("2026-04-14", notes=notes_text)])
        client.post("/api/restore", json=payload)
        e = client.get("/api/entries/2026-04-14").json()
        assert e["notes"] == notes_text

    def test_multiple_breaks_survive_roundtrip(self, client):
        breaks = (30, 15, 45)
        payload = _backup_payload(entries=[_backup_work_entry("2026-04-14", breaks=breaks)])
        client.post("/api/restore", json=payload)
        e = client.get("/api/entries/2026-04-14").json()
        assert e["total_break_minutes"] == sum(breaks)

    def test_settings_survive_roundtrip(self, client):
        payload = _backup_payload(settings={
            "daily_target_hours": 6.75,
            "cumulative_start_date": "2024-07-15",
        })
        client.post("/api/restore", json=payload)
        cfg = client.get("/api/config").json()
        assert cfg["daily_target_hours"] == 6.75
        assert cfg["cumulative_start_date"] == "2024-07-15"

    def test_all_day_types_survive_roundtrip(self, client):
        entries = [
            _backup_work_entry("2026-04-14"),
            {"date": "2026-04-15", "day_type": "vacation", "start_time": None, "end_time": None, "notes": None, "breaks": []},
            {"date": "2026-04-16", "day_type": "sick",     "start_time": None, "end_time": None, "notes": None, "breaks": []},
            {"date": "2026-04-17", "day_type": "holiday",  "start_time": None, "end_time": None, "notes": None, "breaks": []},
        ]
        client.post("/api/restore", json=_backup_payload(entries=entries))
        restored = client.get("/api/entries").json()
        assert len(restored) == 4
        day_types = {e["date"]: e["day_type"] for e in restored}
        assert day_types["2026-04-14"] == "work"
        assert day_types["2026-04-15"] == "vacation"
        assert day_types["2026-04-16"] == "sick"
        assert day_types["2026-04-17"] == "holiday"


# ── TestOrphanedBreaksAfterRestore ───────────────────────────────────────────


class TestOrphanedBreaksAfterRestore:
    """Regression: SQLite FK cascade does not fire without PRAGMA foreign_keys=ON.

    The restore endpoint must explicitly delete Break rows before deleting
    WorkEntry rows to avoid orphaned Break rows that cause count mismatches
    or PK conflicts on re-insert.
    """

    def test_no_orphaned_breaks_after_wipe_and_restore(self, client, work_body):
        # Seed an entry with breaks
        client.post("/api/entries", json=work_body(date="2026-04-14", breaks_min=(30, 45)))
        client.post("/api/entries", json=work_body(date="2026-04-15", breaks_min=(60,)))

        # Restore with a completely different payload
        payload = _backup_payload(entries=[_backup_work_entry("2026-04-20", breaks=(15,))])
        r = client.post("/api/restore", json=payload)
        assert r.json()["restored_entries"] == 1

        # Only the restored entry must exist — no old data
        entries = client.get("/api/entries").json()
        assert len(entries) == 1
        assert entries[0]["date"] == "2026-04-20"
        assert entries[0]["total_break_minutes"] == 15

    def test_recreating_same_date_after_restore_does_not_conflict(self, client, work_body):
        """After a restore wipes date X, creating date X again must succeed (no stale PK)."""
        client.post("/api/entries", json=work_body(date="2026-04-14", breaks_min=(30,)))
        client.post("/api/restore", json=_backup_payload())  # wipe everything

        r = client.post("/api/entries", json=work_body(date="2026-04-14", breaks_min=(60,)))
        assert r.status_code == 201

        e = client.get("/api/entries/2026-04-14").json()
        assert e["total_break_minutes"] == 60  # new value, not the old 30

    def test_break_count_is_exact_after_multiple_restores(self, client):
        """Running restore twice in a row must not double-count breaks."""
        payload = _backup_payload(entries=[_backup_work_entry("2026-04-14", breaks=(20, 10))])
        client.post("/api/restore", json=payload)
        client.post("/api/restore", json=payload)  # second restore

        e = client.get("/api/entries/2026-04-14").json()
        assert e["total_break_minutes"] == 30  # 20 + 10, not 60


# ── TestNonWorkDayMetrics ─────────────────────────────────────────────────────


class TestNonWorkDayMetrics:
    """Non-work days must contribute 0 to both net_hours and target_hours."""

    def test_all_vacation_week_has_zero_target(self, client):
        for d in ["2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16", "2026-04-17"]:
            _post(client, _off(d, "vacation"))
        data = client.get("/api/dashboard?today=2026-04-14").json()
        assert data["week"]["target_hours"] == 0.0
        assert data["week"]["net_hours"] == 0.0
        assert data["week"]["surplus_hours"] == 0.0
        assert data["week"]["non_work_days"] == 5

    def test_sick_day_has_zero_target_and_net(self, client):
        _post(client, _off("2026-04-14", "sick"))
        e = client.get("/api/entries/2026-04-14").json()
        assert e["net_hours"] == 0.0
        assert e["target_hours"] == 0.0
        assert e["surplus_hours"] == 0.0

    def test_holiday_does_not_inflate_weekly_target(self, client, work_body):
        # 4 work days + 1 holiday in the same week
        for d in ["2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16"]:
            _post(client, work_body(date=d))
        _post(client, _off("2026-04-17", "holiday"))

        data = client.get("/api/dashboard?today=2026-04-14").json()
        # target = 4 × 8 = 32 (holiday adds 0)
        assert data["week"]["target_hours"] == 32.0
        assert data["week"]["non_work_days"] == 1

    def test_mixed_non_work_types_all_contribute_zero(self, client):
        _post(client, _off("2026-04-13", "vacation"))
        _post(client, _off("2026-04-14", "sick"))
        _post(client, _off("2026-04-15", "holiday"))

        data = client.get("/api/dashboard?today=2026-04-14").json()
        assert data["week"]["target_hours"] == 0.0
        assert data["week"]["net_hours"] == 0.0
        assert data["week"]["non_work_days"] == 3


# ── TestCsvExportEdgeCases ────────────────────────────────────────────────────


class TestCsvExportEdgeCases:
    def test_empty_db_has_header_row_only(self, client):
        resp = client.get("/api/export.csv")
        assert resp.status_code == 200
        rows = list(csv.reader(io.StringIO(resp.text)))
        assert len(rows) == 1  # header only
        assert rows[0][0] == "date"

    def test_notes_with_commas_are_properly_quoted(self, client, work_body):
        notes = "shipped feature, added tests, deployed to prod"
        _post(client, work_body(date="2026-04-14", notes=notes))
        resp = client.get("/api/export.csv")
        rows = list(csv.reader(io.StringIO(resp.text)))
        header, data_row = rows[0], rows[1]
        notes_idx = header.index("notes")
        # csv.reader handles quoting transparently — the cell must match exactly
        assert data_row[notes_idx] == notes

    def test_notes_with_double_quotes_are_escaped(self, client, work_body):
        notes = 'said "hello", replied "world"'
        _post(client, work_body(date="2026-04-14", notes=notes))
        resp = client.get("/api/export.csv")
        rows = list(csv.reader(io.StringIO(resp.text)))
        header = rows[0]
        notes_idx = header.index("notes")
        assert rows[1][notes_idx] == notes  # csv.reader reverses the escaping

    def test_csv_row_count_matches_entry_count(self, client, work_body):
        for d in ["2026-04-14", "2026-04-15", "2026-04-16"]:
            _post(client, work_body(date=d))
        _post(client, _off("2026-04-17", "vacation"))
        resp = client.get("/api/export.csv")
        rows = list(csv.reader(io.StringIO(resp.text)))
        assert len(rows) == 5  # 1 header + 4 data rows

    def test_non_work_day_fields_are_empty_strings(self, client):
        _post(client, _off("2026-04-14", "vacation"))
        resp = client.get("/api/export.csv")
        rows = list(csv.reader(io.StringIO(resp.text)))
        header, row = rows[0], rows[1]
        by_col = dict(zip(header, row))
        assert by_col["start_time"] == ""
        assert by_col["end_time"] == ""
        assert by_col["net_hours"] == "0.00"
        assert by_col["target_hours"] == "0.00"
        assert by_col["surplus_hours"] == "0.00"
