"""API tests for partial-day leave.

Covers the entry validators (what a partial day may and may not carry), the derived
fields on the response, the vacation budget in fractional days, and the fraction's
round-trip through backup/restore and CSV export/import — including files written
before the column existed.
"""

from __future__ import annotations

import csv
import io


def _partial(day_type="vacation", fraction=0.5, date="2026-04-14", **extra):
    return {"date": date, "day_type": day_type, "fraction": fraction, **extra}


def _work(date="2026-04-14", start="09:00", end="18:00", breaks=(60,)):
    return {
        "date": date,
        "day_type": "work",
        "start_time": start,
        "end_time": end,
        "breaks": [{"break_minutes": m} for m in breaks],
    }


# ── create / validation ──────────────────────────────────────────────────────


class TestCreatePartialDay:
    def test_half_vacation_with_hours(self, client):
        r = client.post("/api/entries", json=_partial(start_time="09:00", end_time="13:00"))
        assert r.status_code == 201, r.text
        e = r.json()
        assert e["day_type"] == "vacation"
        assert e["fraction"] == 0.5
        assert e["leave_hours"] == 4.0
        assert e["start_time"] == "09:00"
        assert e["net_hours"] == 4.0
        assert e["target_hours"] == 4.0
        assert e["surplus_hours"] == 0.0

    def test_hours_are_optional(self, client):
        r = client.post("/api/entries", json=_partial(fraction=0.375))
        assert r.status_code == 201, r.text
        e = r.json()
        assert e["net_hours"] == 0.0
        assert e["target_hours"] == 5.0
        assert e["surplus_hours"] == -5.0
        assert e["leave_hours"] == 3.0

    def test_partial_flex_charges_full_target(self, client):
        r = client.post(
            "/api/entries", json=_partial("flex", 0.5, start_time="09:00", end_time="13:00")
        )
        assert r.status_code == 201
        e = r.json()
        assert e["target_hours"] == 8.0
        assert e["net_hours"] == 4.0
        assert e["surplus_hours"] == -4.0
        assert e["leave_hours"] == 4.0

    def test_breaks_count_against_the_worked_part(self, client):
        r = client.post(
            "/api/entries",
            json=_partial(
                "sick", 0.25, start_time="08:30", end_time="15:00", breaks=[{"break_minutes": 30}]
            ),
        )
        assert r.status_code == 201
        e = r.json()
        assert e["total_break_minutes"] == 30
        assert e["net_hours"] == 6.0
        assert e["target_hours"] == 6.0

    def test_whole_day_default_fraction(self, client):
        r = client.post("/api/entries", json={"date": "2026-04-14", "day_type": "vacation"})
        assert r.status_code == 201
        e = r.json()
        assert e["fraction"] == 1.0
        assert e["leave_hours"] == 8.0
        assert e["target_hours"] == 0.0

    def test_work_day_reports_fraction_one_and_no_leave(self, client):
        r = client.post("/api/entries", json=_work())
        assert r.status_code == 201
        assert r.json()["fraction"] == 1.0
        assert r.json()["leave_hours"] == 0.0

    def test_uses_target_in_force_on_that_date(self, client):
        client.put(
            "/api/config/daily-target-schedule",
            json={
                "rows": [
                    {"effective_from": "2026-01-01", "hours": 8},
                    {"effective_from": "2026-06-01", "hours": 6},
                ]
            },
        )
        r = client.post("/api/entries", json=_partial(fraction=0.5, date="2026-06-10"))
        assert r.json()["target_hours"] == 3.0
        assert r.json()["leave_hours"] == 3.0


class TestValidation:
    def test_fraction_must_be_in_zero_one(self, client):
        assert client.post("/api/entries", json=_partial(fraction=0)).status_code == 422
        assert client.post("/api/entries", json=_partial(fraction=1.5)).status_code == 422
        assert client.post("/api/entries", json=_partial(fraction=-0.5)).status_code == 422

    def test_work_day_rejects_fraction(self, client):
        body = {**_work(), "fraction": 0.5}
        r = client.post("/api/entries", json=body)
        assert r.status_code == 422
        assert "work days have no fraction" in r.text

    def test_work_day_accepts_explicit_one(self, client):
        body = {**_work(), "fraction": 1.0}
        assert client.post("/api/entries", json=body).status_code == 201

    def test_whole_day_leave_still_rejects_times(self, client):
        r = client.post(
            "/api/entries",
            json={"date": "2026-04-14", "day_type": "vacation", "start_time": "09:00"},
        )
        assert r.status_code == 422

    def test_whole_day_leave_still_rejects_breaks(self, client):
        r = client.post(
            "/api/entries",
            json={
                "date": "2026-04-14",
                "day_type": "vacation",
                "fraction": 1.0,
                "breaks": [{"break_minutes": 30}],
            },
        )
        assert r.status_code == 422

    def test_partial_end_without_start_rejected(self, client):
        r = client.post("/api/entries", json=_partial(end_time="13:00"))
        assert r.status_code == 422
        assert "end_time requires start_time" in r.text

    def test_partial_breaks_without_times_rejected(self, client):
        r = client.post("/api/entries", json=_partial(breaks=[{"break_minutes": 30}]))
        assert r.status_code == 422

    def test_partial_breaks_without_end_rejected(self, client):
        r = client.post(
            "/api/entries", json=_partial(start_time="09:00", breaks=[{"break_minutes": 30}])
        )
        assert r.status_code == 422

    def test_partial_breaks_exceeding_span_rejected(self, client):
        r = client.post(
            "/api/entries",
            json=_partial(start_time="09:00", end_time="10:00", breaks=[{"break_minutes": 90}]),
        )
        assert r.status_code == 422

    def test_partial_end_before_start_rejected(self, client):
        r = client.post("/api/entries", json=_partial(start_time="13:00", end_time="09:00"))
        assert r.status_code == 422


# ── update transitions ───────────────────────────────────────────────────────


class TestUpdate:
    def test_whole_to_partial_adds_hours(self, client):
        client.post("/api/entries", json={"date": "2026-04-14", "day_type": "vacation"})
        r = client.put(
            "/api/entries/2026-04-14",
            json={
                "day_type": "vacation",
                "fraction": 0.5,
                "start_time": "09:00",
                "end_time": "13:00",
            },
        )
        assert r.status_code == 200
        assert r.json()["fraction"] == 0.5
        assert r.json()["net_hours"] == 4.0

    def test_partial_to_work_resets_fraction(self, client):
        client.post("/api/entries", json=_partial(start_time="09:00", end_time="13:00"))
        r = client.put(
            "/api/entries/2026-04-14", json={k: v for k, v in _work().items() if k != "date"}
        )
        assert r.status_code == 200
        assert r.json()["fraction"] == 1.0
        assert r.json()["day_type"] == "work"

    def test_partial_to_whole_drops_hours(self, client):
        client.post("/api/entries", json=_partial(start_time="09:00", end_time="13:00"))
        r = client.put("/api/entries/2026-04-14", json={"day_type": "vacation"})
        assert r.status_code == 200
        e = r.json()
        assert e["fraction"] == 1.0
        assert e["start_time"] is None
        assert e["net_hours"] == 0.0

    def test_get_returns_fraction(self, client):
        client.post("/api/entries", json=_partial(fraction=0.25))
        assert client.get("/api/entries/2026-04-14").json()["fraction"] == 0.25


# ── batch ────────────────────────────────────────────────────────────────────


class TestBatch:
    def test_batch_defaults_to_whole_days(self, client):
        r = client.post(
            "/api/entries/batch", json={"dates": ["2026-04-14"], "day_type": "vacation"}
        )
        assert r.status_code == 200
        assert client.get("/api/entries/2026-04-14").json()["fraction"] == 1.0

    def test_batch_accepts_fraction(self, client):
        r = client.post(
            "/api/entries/batch",
            json={"dates": ["2026-04-14", "2026-04-15"], "day_type": "flex", "fraction": 0.5},
        )
        assert r.status_code == 200
        assert len(r.json()["created"]) == 2
        e = client.get("/api/entries/2026-04-15").json()
        assert e["fraction"] == 0.5
        assert e["target_hours"] == 8.0

    def test_batch_rejects_bad_fraction(self, client):
        r = client.post(
            "/api/entries/batch",
            json={"dates": ["2026-04-14"], "day_type": "vacation", "fraction": 2},
        )
        assert r.status_code == 422


# ── dashboard: counts and the vacation budget ────────────────────────────────


class TestDashboard:
    def test_fractional_day_counts(self, client):
        for d in ("2026-04-13", "2026-04-14", "2026-04-15"):
            client.post("/api/entries", json=_work(d))
        client.post(
            "/api/entries",
            json=_partial(date="2026-04-16", start_time="09:00", end_time="13:00"),
        )
        client.post("/api/entries", json={"date": "2026-04-17", "day_type": "vacation"})
        data = client.get("/api/dashboard", params={"today": "2026-04-17"}).json()
        assert data["week"]["work_days"] == 3.5
        assert data["week"]["non_work_days"] == 1.5
        assert data["week"]["target_hours"] == 28.0
        assert data["week"]["net_hours"] == 28.0  # 3 × 8 + 4
        assert data["week"]["surplus_hours"] == 0.0

    def test_vacation_days_used_sums_fractions(self, client):
        client.put("/api/config", json={"vacation_budget_days": 22.5})
        client.post("/api/entries", json={"date": "2026-02-02", "day_type": "vacation"})
        client.post("/api/entries", json=_partial(date="2026-03-03", fraction=0.5))
        client.post("/api/entries", json=_partial(date="2026-03-04", fraction=0.25))
        # Sick partial days don't count against the vacation budget.
        client.post("/api/entries", json=_partial("sick", 0.5, date="2026-03-05"))
        data = client.get("/api/dashboard", params={"today": "2026-04-01"}).json()
        assert data["vacation_days_used"] == 1.75
        assert data["vacation_budget_days"] == 22.5

    def test_vacation_days_used_is_zero_without_vacation(self, client):
        client.post("/api/entries", json=_work("2026-04-14"))
        data = client.get("/api/dashboard", params={"today": "2026-04-14"}).json()
        assert data["vacation_days_used"] == 0

    def test_monthly_and_yearly_rows_are_fractional(self, client):
        client.post("/api/entries", json=_partial(fraction=0.25))
        monthly = client.get("/api/analytics/monthly").json()
        assert monthly[0]["work_days"] == 0.75
        assert monthly[0]["non_work_days"] == 0.25
        yearly = client.get("/api/analytics/yearly").json()
        assert yearly[0]["non_work_days"] == 0.25


class TestStreaksAndRecords:
    def test_partial_day_neither_extends_nor_breaks_on_target_streak(self, client):
        client.post("/api/entries", json=_work("2026-04-13", end="18:00"))  # +0
        # Partial vacation with a 1h shortfall on the worked part: surplus −1.
        client.post(
            "/api/entries", json=_partial(date="2026-04-14", start_time="09:00", end_time="12:00")
        )
        client.post("/api/entries", json=_work("2026-04-15", end="18:00"))  # +0
        s = client.get("/api/streaks", params={"today": "2026-04-15"}).json()
        assert s["on_target_streak"] == 2

    def test_partial_day_not_a_record_work_day(self, client):
        client.post("/api/entries", json=_work("2026-04-13", start="09:00", end="17:00"))  # 7h
        client.post(
            "/api/entries", json=_partial(date="2026-04-14", start_time="09:00", end_time="10:00")
        )
        rec = client.get("/api/analytics/records").json()
        assert rec["shortest_work_day"]["date"] == "2026-04-13"


# ── config ───────────────────────────────────────────────────────────────────


class TestVacationBudget:
    def test_accepts_half_days(self, client):
        r = client.put("/api/config", json={"vacation_budget_days": 22.5})
        assert r.status_code == 200
        assert r.json()["vacation_budget_days"] == 22.5
        assert client.get("/api/config").json()["vacation_budget_days"] == 22.5

    def test_whole_budget_stays_whole(self, client):
        client.put("/api/config", json={"vacation_budget_days": 22})
        assert client.get("/api/config").json()["vacation_budget_days"] == 22

    def test_rejects_quarter_days(self, client):
        assert client.put("/api/config", json={"vacation_budget_days": 22.3}).status_code == 422


# ── backup / restore ─────────────────────────────────────────────────────────


class TestBackupRoundTrip:
    def test_fraction_and_hours_survive(self, client):
        client.post(
            "/api/entries",
            json=_partial(
                fraction=0.375,
                start_time="09:00",
                end_time="14:30",
                breaks=[{"break_minutes": 30}],
                notes="dentist",
            ),
        )
        backup = client.get("/api/backup").json()
        assert backup["version"] == 2
        (entry,) = backup["entries"]
        assert entry["fraction"] == 0.375
        assert entry["start_time"] == "09:00"

        client.delete("/api/data")
        assert client.post("/api/restore", json=backup).status_code == 200
        e = client.get("/api/entries/2026-04-14").json()
        assert e["fraction"] == 0.375
        assert e["net_hours"] == 5.0
        assert e["notes"] == "dentist"

    def test_version_1_backup_loads_as_whole_days(self, client):
        legacy = {
            "version": 1,
            "entries": [
                {"date": "2026-04-14", "day_type": "vacation"},
                {
                    "date": "2026-04-15",
                    "day_type": "work",
                    "start_time": "09:00",
                    "end_time": "17:00",
                    "breaks": [],
                },
            ],
        }
        assert client.post("/api/restore", json=legacy).status_code == 200
        assert client.get("/api/entries/2026-04-14").json()["fraction"] == 1.0
        assert client.get("/api/entries/2026-04-15").json()["fraction"] == 1.0

    def test_version_1_with_times_on_leave_still_rejected(self, client):
        legacy = {
            "version": 1,
            "entries": [{"date": "2026-04-14", "day_type": "vacation", "start_time": "09:00"}],
        }
        assert client.post("/api/restore", json=legacy).status_code == 422

    def test_unknown_version_rejected(self, client):
        r = client.post("/api/restore", json={"version": 3, "entries": []})
        assert r.status_code == 422
        assert "supported: 1, 2" in r.text

    def test_restore_settings_with_fractional_budget(self, client):
        backup = client.get("/api/backup").json()
        backup["settings"]["vacation_budget_days"] = 22.5
        assert client.post("/api/restore", json=backup).status_code == 200


# ── CSV ──────────────────────────────────────────────────────────────────────


class TestCsvRoundTrip:
    def test_export_has_fraction_and_hours(self, client):
        client.post("/api/entries", json=_partial(start_time="09:00", end_time="13:00"))
        client.post("/api/entries", json=_work("2026-04-15"))
        rows = list(csv.DictReader(io.StringIO(client.get("/api/export.csv").text)))
        by_date = {r["date"]: r for r in rows}
        assert by_date["2026-04-14"]["fraction"] == "0.5"
        assert by_date["2026-04-14"]["start_time"] == "09:00"
        assert by_date["2026-04-14"]["net_hours"] == "4.00"
        assert by_date["2026-04-14"]["target_hours"] == "4.00"
        assert by_date["2026-04-15"]["fraction"] == "1.0"

    def test_export_import_round_trip(self, client):
        client.post(
            "/api/entries",
            json=_partial(
                "sick", 0.375, start_time="09:00", end_time="14:30", breaks=[{"break_minutes": 30}]
            ),
        )
        text = client.get("/api/export.csv").text
        # Delete through the ORM (cascades breaks); the bulk wipe leaves orphaned breaks
        # under the test engine (PRAGMA foreign_keys is off there; production cascades).
        client.delete("/api/entries/2026-04-14")
        r = client.post("/api/import/csv", json={"content": text})
        assert r.status_code == 200, r.text
        assert r.json()["errors"] == []
        e = client.get("/api/entries/2026-04-14").json()
        assert e["fraction"] == 0.375
        assert e["day_type"] == "sick"
        assert e["net_hours"] == 5.0
        assert e["total_break_minutes"] == 30

    def test_legacy_csv_without_fraction_column(self, client):
        text = (
            "date,day_type,start_time,end_time,total_break_minutes,net_hours,target_hours,"
            "surplus_hours,notes\n"
            "2026-04-14,vacation,,,0,0.00,0.00,0.00,\n"
            "2026-04-15,work,09:00,17:00,60,7.00,8.00,-1.00,\n"
        )
        r = client.post("/api/import/csv", json={"content": text})
        assert r.json()["errors"] == []
        assert client.get("/api/entries/2026-04-14").json()["fraction"] == 1.0
        assert client.get("/api/entries/2026-04-15").json()["net_hours"] == 7.0

    def test_blank_fraction_cell_means_whole_day(self, client):
        text = "date,day_type,fraction\n2026-04-14,holiday,\n"
        r = client.post("/api/import/csv", json={"content": text})
        assert r.json()["errors"] == []
        assert client.get("/api/entries/2026-04-14").json()["fraction"] == 1.0

    def test_bad_fraction_is_a_row_error_not_fatal(self, client):
        text = "date,day_type,fraction\n2026-04-14,vacation,half\n2026-04-15,vacation,0.5\n"
        r = client.post("/api/import/csv", json={"content": text})
        assert r.status_code == 200
        assert r.json()["imported"] == ["2026-04-15"]
        assert "row 2" in r.json()["errors"][0]
        assert "fraction" in r.json()["errors"][0]

    def test_fraction_on_work_row_is_a_row_error(self, client):
        text = "date,day_type,fraction,start_time,end_time\n2026-04-14,work,0.5,09:00,17:00\n"
        r = client.post("/api/import/csv", json={"content": text})
        assert r.json()["imported"] == []
        assert "fraction" in r.json()["errors"][0]


class TestSeed:
    def test_seed_includes_partial_days(self, client):
        client.post("/api/data/seed")
        entries = client.get("/api/entries").json()
        partial = [e for e in entries if e["day_type"] != "work" and e["fraction"] < 1]
        assert len(partial) == 2
        assert all(e["start_time"] and e["end_time"] for e in partial)
