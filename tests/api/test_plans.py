"""API tests for the time-off planner: drafts, commit, projection, backup, wipe."""

from __future__ import annotations

TODAY = "2026-10-26"  # a Monday; Dec 31 2026 is a Thursday


def _work(date, start="09:00", end="18:00", breaks=(60,)):
    return {
        "date": date,
        "day_type": "work",
        "start_time": start,
        "end_time": end,
        "breaks": [{"break_minutes": m} for m in breaks],
    }


def _draft(client, dates, day_type="vacation", **extra):
    return client.post("/api/plans", json={"dates": dates, "day_type": day_type, **extra})


# ── drafting ─────────────────────────────────────────────────────────────────


class TestDraft:
    def test_draft_and_list(self, client):
        r = _draft(client, ["2026-12-21", "2026-12-22"], notes="pre-Christmas")
        assert r.status_code == 200, r.text
        assert r.json() == {
            "drafted": ["2026-12-21", "2026-12-22"],
            "replaced": [],
            "skipped": [],
        }
        plans = client.get("/api/plans").json()
        assert [p["date"] for p in plans] == ["2026-12-21", "2026-12-22"]
        assert plans[0]["day_type"] == "vacation"
        assert plans[0]["fraction"] == 1.0
        assert plans[0]["leave_hours"] == 8.0
        assert plans[0]["notes"] == "pre-Christmas"
        assert plans[0]["exists"] is False

    def test_redraft_replaces(self, client):
        _draft(client, ["2026-12-21"], notes="a")
        r = _draft(client, ["2026-12-21"], day_type="flex", fraction=0.5, notes="b")
        assert r.json()["replaced"] == ["2026-12-21"]
        (p,) = client.get("/api/plans").json()
        assert (p["day_type"], p["fraction"], p["notes"]) == ("flex", 0.5, "b")

    def test_logged_date_is_skipped(self, client):
        client.post("/api/entries", json=_work("2026-12-21"))
        r = _draft(client, ["2026-12-21", "2026-12-22"])
        assert r.json()["skipped"] == ["2026-12-21"]
        assert r.json()["drafted"] == ["2026-12-22"]

    def test_only_plannable_types(self, client):
        assert _draft(client, ["2026-12-21"], day_type="sick").status_code == 422
        assert _draft(client, ["2026-12-21"], day_type="work").status_code == 422
        assert _draft(client, ["2026-12-21"], day_type="holiday").status_code == 200

    def test_fraction_validated(self, client):
        assert _draft(client, ["2026-12-21"], fraction=0).status_code == 422
        assert _draft(client, ["2026-12-21"], fraction=1.5).status_code == 422

    def test_list_by_year(self, client):
        _draft(client, ["2026-12-21", "2027-01-04"])
        assert [p["date"] for p in client.get("/api/plans", params={"year": 2027}).json()] == [
            "2027-01-04"
        ]

    def test_exists_flag_when_logged_after_drafting(self, client):
        _draft(client, ["2026-12-21"])
        client.post("/api/entries", json={"date": "2026-12-21", "day_type": "holiday"})
        (p,) = client.get("/api/plans").json()
        assert p["exists"] is True

    def test_leave_hours_follow_the_schedule(self, client):
        client.put(
            "/api/config/daily-target-schedule",
            json={
                "rows": [
                    {"effective_from": "2026-01-01", "hours": 8},
                    {"effective_from": "2026-12-01", "hours": 6},
                ]
            },
        )
        _draft(client, ["2026-12-21"], fraction=0.5)
        assert client.get("/api/plans").json()[0]["leave_hours"] == 3.0


class TestUpdateDelete:
    def test_update_notes_and_type(self, client):
        _draft(client, ["2026-12-21"], notes="a")
        r = client.put("/api/plans/2026-12-21", json={"notes": "b", "day_type": "flex"})
        assert r.status_code == 200
        assert r.json()["notes"] == "b"
        assert r.json()["day_type"] == "flex"

    def test_update_can_clear_notes(self, client):
        _draft(client, ["2026-12-21"], notes="a")
        assert client.put("/api/plans/2026-12-21", json={"notes": None}).json()["notes"] is None

    def test_update_keeps_notes_when_omitted(self, client):
        _draft(client, ["2026-12-21"], notes="a")
        assert client.put("/api/plans/2026-12-21", json={"fraction": 0.5}).json()["notes"] == "a"

    def test_update_rejects_sick(self, client):
        _draft(client, ["2026-12-21"])
        assert client.put("/api/plans/2026-12-21", json={"day_type": "sick"}).status_code == 422

    def test_update_missing_404(self, client):
        assert client.put("/api/plans/2026-12-21", json={"notes": "x"}).status_code == 404

    def test_delete(self, client):
        _draft(client, ["2026-12-21"])
        assert client.delete("/api/plans/2026-12-21").status_code == 204
        assert client.get("/api/plans").json() == []
        assert client.delete("/api/plans/2026-12-21").status_code == 404


# ── commit ───────────────────────────────────────────────────────────────────


class TestCommit:
    def test_commit_creates_entries_with_notes_and_drops_drafts(self, client):
        _draft(client, ["2026-12-21", "2026-12-22"], notes="pre-Christmas")
        _draft(client, ["2026-12-23"], day_type="flex", fraction=0.5)
        r = client.post("/api/plans/commit", json={"dates": ["2026-12-21", "2026-12-23"]})
        assert r.status_code == 200, r.text
        assert r.json() == {"created": ["2026-12-21", "2026-12-23"], "skipped": [], "missing": []}
        e = client.get("/api/entries/2026-12-21").json()
        assert e["day_type"] == "vacation"
        assert e["notes"] == "pre-Christmas"
        f = client.get("/api/entries/2026-12-23").json()
        assert f["day_type"] == "flex"
        assert f["fraction"] == 0.5
        assert [p["date"] for p in client.get("/api/plans").json()] == ["2026-12-22"]

    def test_commit_skips_logged_and_drops_the_draft(self, client):
        _draft(client, ["2026-12-21"])
        client.post("/api/entries", json=_work("2026-12-21"))
        r = client.post("/api/plans/commit", json={"dates": ["2026-12-21"]})
        assert r.json()["skipped"] == ["2026-12-21"]
        assert client.get("/api/plans").json() == []
        assert client.get("/api/entries/2026-12-21").json()["day_type"] == "work"

    def test_commit_missing(self, client):
        r = client.post("/api/plans/commit", json={"dates": ["2026-12-21"]})
        assert r.json() == {"created": [], "skipped": [], "missing": ["2026-12-21"]}

    def test_committed_day_counts_like_any_entry(self, client):
        _draft(client, ["2026-10-27"], day_type="flex")
        client.post("/api/plans/commit", json={"dates": ["2026-10-27"]})
        dash = client.get("/api/dashboard", params={"today": "2026-10-27"}).json()
        assert dash["week"]["surplus_hours"] == -8.0


# ── projection ───────────────────────────────────────────────────────────────


def _proj(client, **params):
    return client.get("/api/plans/projection", params={"today": TODAY, **params}).json()


class TestProjection:
    def test_empty_db(self, client):
        p = _proj(client)
        assert p["year"] == 2026
        assert p["horizon"] == "2026-12-31"
        assert p["balance_today"] == 0.0
        assert p["pace_per_day"] == 0.0
        assert p["on_target"] == 0.0
        assert p["at_pace"] == 0.0
        # Oct 27 – Dec 31 2026: 48 Mon–Fri days
        assert p["scheduled_days_left"] == 48
        assert p["open_days_left"] == 48

    def test_on_target_carries_the_balance_and_flex_drains(self, client):
        client.post("/api/entries", json=_work("2026-10-26", end="19:00"))  # +1
        _draft(client, ["2026-11-13"], day_type="flex")
        _draft(client, ["2026-12-21", "2026-12-22"])  # vacation: neutral
        p = _proj(client)
        assert p["balance_today"] == 1.0
        assert p["on_target"] == -7.0
        assert p["drafted_days"] == 3
        assert p["drafted_flex_hours"] == 8.0
        assert p["open_days_left"] == 45

    def test_at_pace(self, client):
        client.post("/api/entries", json=_work("2026-10-26", end="19:00"))  # +1, pace 1/day
        _draft(client, ["2026-12-21", "2026-12-22"])
        p = _proj(client)
        assert p["pace_per_day"] == 1.0
        assert p["at_pace"] == 1.0 + 46  # 46 open days × 1h

    def test_real_future_entries_count_and_beat_drafts(self, client):
        client.post("/api/entries", json={"date": "2026-12-25", "day_type": "holiday"})
        client.post("/api/entries", json={"date": "2026-12-08", "day_type": "flex"})
        _draft(client, ["2026-12-25"], day_type="flex")  # draft ignored: holiday is real
        p = _proj(client)
        assert p["on_target"] == -8.0  # only the real flex
        assert p["drafted_days"] == 0
        assert p["scheduled_days_left"] == 46

    def test_drafts_before_today_are_not_projected(self, client):
        _draft(client, ["2026-10-20"], day_type="flex")
        assert _proj(client)["on_target"] == 0.0

    def test_vacation_budget_after_plan(self, client):
        client.put("/api/config", json={"vacation_budget_days": 22.5})
        client.post("/api/entries", json={"date": "2026-03-02", "day_type": "vacation"})
        client.post("/api/entries", json={"date": "2026-12-28", "day_type": "vacation"})  # ahead
        client.post(
            "/api/entries", json={"date": "2026-03-03", "day_type": "vacation", "fraction": 0.5}
        )
        _draft(client, ["2026-12-21", "2026-12-22"])
        _draft(client, ["2026-12-23"], fraction=0.5)
        _draft(client, ["2026-12-24"], day_type="flex")  # not vacation
        _draft(client, ["2026-12-28"])  # stands behind a real entry: not counted
        p = _proj(client)
        assert p["vacation_budget_days"] == 22.5
        assert p["vacation_used_days"] == 2.5
        assert p["vacation_drafted_days"] == 2.5
        assert p["vacation_remaining_after_plan"] == 17.5

    def test_next_year_projection(self, client):
        client.post("/api/entries", json=_work("2026-10-26", end="19:00"))  # +1
        _draft(client, ["2027-01-04"], day_type="flex")
        _draft(client, ["2026-12-21"], day_type="flex")
        p = _proj(client, year=2027)
        assert p["horizon"] == "2027-12-31"
        # Both flex drafts lie between today and the horizon.
        assert p["on_target"] == 1.0 - 16
        assert p["vacation_used_days"] == 0

    def test_next_year_with_annual_reset_starts_from_zero(self, client):
        client.put("/api/config", json={"reset_annually": True})
        client.post("/api/entries", json=_work("2026-10-26", end="19:00"))  # +1 this year
        _draft(client, ["2026-12-21"], day_type="flex")  # this year: not in the 2027 balance
        _draft(client, ["2027-01-04"], day_type="flex")
        p = _proj(client, year=2027)
        assert p["balance_today"] == 0.0
        assert p["on_target"] == -8.0
        assert p["pace_per_day"] == 1.0  # pace still from what was worked
        assert _proj(client, year=2026)["on_target"] == -7.0

    def test_date_effective_target_for_future_flex(self, client):
        client.put(
            "/api/config/daily-target-schedule",
            json={
                "rows": [
                    {"effective_from": "2026-01-01", "hours": 8},
                    {"effective_from": "2026-12-01", "hours": 6},
                ]
            },
        )
        _draft(client, ["2026-11-13", "2026-12-14"], day_type="flex")
        assert _proj(client)["drafted_flex_hours"] == 14.0

    def test_custom_work_week(self, client):
        client.put("/api/config", json={"work_week_days": [0, 1, 2, 3]})
        assert _proj(client)["scheduled_days_left"] == 39  # 48 minus the 9 Fridays


# ── dashboard synergy ────────────────────────────────────────────────────────


class TestDashboardPlanned:
    def test_planned_fields(self, client):
        _draft(client, ["2026-11-13"], day_type="flex")
        _draft(client, ["2026-12-21", "2026-12-22"])
        _draft(client, ["2026-12-23"], fraction=0.5)
        _draft(client, ["2026-10-20"])  # past: not "remaining"
        _draft(client, ["2027-01-04"])  # next year: not this year's forecast
        d = client.get("/api/dashboard", params={"today": TODAY}).json()
        assert d["planned_days_remaining"] == 3.5
        assert d["planned_flex_hours"] == 8.0

    def test_logged_date_not_counted(self, client):
        _draft(client, ["2026-12-21"])
        client.post("/api/entries", json={"date": "2026-12-21", "day_type": "holiday"})
        d = client.get("/api/dashboard", params={"today": TODAY}).json()
        assert d["planned_days_remaining"] == 0


# ── backup / wipe / seed ─────────────────────────────────────────────────────


class TestPersistence:
    def test_backup_round_trip(self, client):
        _draft(client, ["2026-12-21"], notes="x", fraction=0.5)
        backup = client.get("/api/backup").json()
        assert backup["plans"] == [
            {"date": "2026-12-21", "day_type": "vacation", "fraction": 0.5, "notes": "x"}
        ]
        client.delete("/api/data")
        assert client.get("/api/plans").json() == []
        assert client.post("/api/restore", json=backup).status_code == 200
        (p,) = client.get("/api/plans").json()
        assert (p["fraction"], p["notes"]) == (0.5, "x")

    def test_restore_without_plans_key(self, client):
        _draft(client, ["2026-12-21"])
        r = client.post("/api/restore", json={"version": 2, "entries": []})
        assert r.status_code == 200
        assert client.get("/api/plans").json() == []  # restore wipes drafts too

    def test_restore_rejects_unplannable_draft(self, client):
        bad = {"version": 2, "plans": [{"date": "2026-12-21", "day_type": "sick"}]}
        assert client.post("/api/restore", json=bad).status_code == 422

    def test_wipe_deletes_plans(self, client):
        _draft(client, ["2026-12-21", "2026-12-22"])
        r = client.delete("/api/data")
        assert r.json()["deleted_plans"] == 2

    def test_seed_includes_drafts(self, client):
        r = client.post("/api/data/seed")
        assert r.json()["plans"] == 4
        plans = client.get("/api/plans").json()
        assert len(plans) == 4
        assert {p["day_type"] for p in plans} == {"vacation", "flex"}
        assert all(not p["exists"] for p in plans)
