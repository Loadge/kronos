"""E2E: bin/kronos.py against a real server.

The CLI is a subprocess, exactly as an agent runs it; the server is the suite's live
uvicorn. The targets are simulated by URL: ``KRONOS_PROD_URL`` aimed at the live server
is "prod" to the script, which is all the safety rules key on — so "a write to PROD
takes a backup first" is proven here without any network:

  * a PROD write leaves a valid version-2 snapshot under ``backups/prod/`` that was
    taken *before* the write (the new day is not in it);
  * a PROD write against a dead port exits 3, writes no entry and no file;
  * an INT write takes no backup; ``restore`` takes one on every target;
  * retention keeps exactly the newest 50.

Plus the reads, every write and its ``--dry-run`` (nothing written), ``--json`` on
both, the error contract, and ``check`` green against the server and red against a
dead port.
"""

from __future__ import annotations

import datetime
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = [sys.executable, "bin/kronos.py"]
TIMEOUT = 120

# Fixed, far-from-today dates so nothing here collides with the other modules' days.
D1 = "2024-03-04"  # Mon
D2 = "2024-03-05"  # Tue
D3 = "2024-03-06"  # Wed
D4 = "2024-03-07"  # Thu
D5 = "2024-03-08"  # Fri


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wipe(base_url: str) -> None:
    with httpx.Client(base_url=base_url) as c:
        c.delete("/api/data")
        c.put("/api/config", json={"daily_target_hours": 8, "vacation_budget_days": 22})


@pytest.fixture(autouse=True)
def _clean(base_url):
    _wipe(base_url)
    yield
    _wipe(base_url)


@pytest.fixture
def run(base_url, tmp_path):
    """Run the CLI with local/int/prod all pointing at the live server, backups in tmp."""
    backups = tmp_path / "backups"

    def _run(*argv: str, target_urls: dict[str, str] | None = None, check: bool = False):
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("KRONOS_")  # the sandbox's own targets never leak in
        }
        env.update(
            {
                "KRONOS_LOCAL_URL": base_url,
                "KRONOS_INT_URL": base_url,
                "KRONOS_PROD_URL": base_url,
                "KRONOS_BACKUP_DIR": str(backups),
                "PYTHONIOENCODING": "utf-8",
            }
        )
        env.update(target_urls or {})
        result = subprocess.run(
            [*CLI, *argv],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=TIMEOUT,
        )
        if check:
            assert result.returncode == 0, (
                f"exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    _run.backups = backups  # type: ignore[attr-defined]
    return _run


def _entry(base_url: str, day: str) -> dict | None:
    resp = httpx.get(f"{base_url}/api/entries/{day}")
    return resp.json() if resp.status_code == 200 else None


def _plans(base_url: str, year: int = 2024) -> list[dict]:
    return httpx.get(f"{base_url}/api/plans?year={year}").json()


# ---------- reads -----------------------------------------------------------


class TestReads:
    def test_today_balance_config_plan_days(self, run, base_url):
        httpx.post(
            f"{base_url}/api/entries",
            json={
                "date": D1,
                "day_type": "work",
                "start_time": "08:30",
                "end_time": "16:45",
                "breaks": [{"break_minutes": 45}],
                "notes": "cli read",
            },
        )
        today = run("today", check=True)
        assert "week" in today.stdout and "streaks" in today.stdout
        doc = json.loads(run("--json", "today", check=True).stdout)
        assert {"today", "entry", "dashboard", "streaks"} <= set(doc)
        assert (
            doc["dashboard"]["cumulative"]["surplus_hours"]
            == doc["dashboard"]["cumulative"]["surplus_hours"]
        )

        balance = run("balance", "--json", check=True)
        assert {"week", "month", "cumulative"} <= set(json.loads(balance.stdout))

        config = run("config", check=True)
        assert "daily_target_hours" in config.stdout

        days = run("days", "--month", "2024-03", check=True)
        assert D1 in days.stdout and "08:30–16:45" in days.stdout and "cli read" in days.stdout
        assert "1 days" in days.stdout
        days_json = json.loads(run("days", "--from", D1, "--to", D5, "--json", check=True).stdout)
        assert [e["date"] for e in days_json] == [D1]
        assert "no days logged" in run("days", "--month", "2023-01", check=True).stdout

        plan = run("plan", "--year", "2024", check=True)
        assert "no drafts for 2024" in plan.stdout and "2024 at Dec 31" in plan.stdout

    def test_targets_lists_the_simulated_urls(self, run, base_url):
        out = run("targets", check=True).stdout
        assert out.count(base_url) == 3
        doc = json.loads(run("targets", "--json", check=True).stdout)
        assert doc["prod"] == {"url": base_url, "source": "env"}


# ---------- log -------------------------------------------------------------


class TestLog:
    def test_work_day_dry_run_then_real_then_replace(self, run, base_url):
        dry = run(
            "log", D1, "--start", "8:30", "--end", "16:45", "--break", "45", "--dry-run", check=True
        )
        assert "dry-run  POST /api/entries" in dry.stdout
        assert (
            "would be  Mon 2024-03-04 · 08:30 → 16:45 · break 45min · 7.50h of 8h · -0.50h"
            in dry.stdout
        )
        assert _entry(base_url, D1) is None

        real = run(
            "log",
            D1,
            "--start",
            "8:30",
            "--end",
            "16:45",
            "--break",
            "45",
            "--note",
            "x",
            check=True,
        )
        assert real.stdout.startswith("logged  Mon 2024-03-04")
        assert _entry(base_url, D1)["net_hours"] == 7.5

        again = run("log", D1, "--start", "9:00", "--end", "17:00")
        assert again.returncode == 1
        assert "--replace" in again.stderr
        assert _entry(base_url, D1)["start_time"] == "08:30"

        dry2 = run("log", D1, "--start", "9:00", "--end", "17:00", "--dry-run", check=True)
        assert "already logged — add --replace" in dry2.stdout

        replaced = run(
            "--json", "log", D1, "--start", "9:00", "--end", "17:00", "--replace", check=True
        )
        doc = json.loads(replaced.stdout)
        assert doc["action"] == "replaced" and doc["entry"]["start_time"] == "09:00"
        assert _entry(base_url, D1)["breaks"] == []

        # --replace on a free date simply creates it.
        created = run("--json", "log", D2, "--start", "9:00", "--replace", check=True)
        assert json.loads(created.stdout)["action"] == "logged"
        assert _entry(base_url, D2)["end_time"] is None

    def test_partial_leave_with_hours(self, run, base_url):
        out = run(
            "--json",
            "log",
            D1,
            "--type",
            "vacation",
            "--hours",
            "3",
            "--start",
            "9:00",
            "--end",
            "14:00",
            check=True,
        )
        entry = json.loads(out.stdout)["entry"]
        assert (
            entry["fraction"] == 0.375 and entry["leave_hours"] == 3.0 and entry["net_hours"] == 5.0
        )
        human = run("days", "--month", "2024-03", check=True).stdout
        assert "vacation · 3h" in human

    def test_range_of_leave(self, run, base_url):
        dry = run("log", f"{D1}..{D3}", D5, "--type", "sick", "--dry-run", check=True)
        assert "dry-run  POST /api/entries/batch" in dry.stdout
        assert dry.stdout.count("create") == 4
        assert _entry(base_url, D1) is None

        out = run("log", f"{D1}..{D3}", D5, "--type", "sick", "--note", "flu", check=True)
        assert "logged   4 sick day(s)" in out.stdout
        assert _entry(base_url, D5)["notes"] == "flu"

        second = run("--json", "log", f"{D1}..{D4}", "--type", "sick", check=True)
        assert json.loads(second.stdout) == {"created": [D4], "skipped": [D1, D2, D3]}

    def test_usage_errors_exit_2(self, run, base_url):
        assert run("log", D1).returncode == 2  # a work day needs --start
        assert run("log", f"{D1}..{D2}", "--start", "9:00").returncode == 2
        assert run("log", f"{D1}..{D2}", "--type", "flex", "--replace").returncode == 2
        assert run("log", "2024-3-4x", "--start", "9:00").returncode == 2
        assert run("log", D1, "--start", "25:00").returncode == 2
        assert _entry(base_url, D1) is None

    def test_api_validation_exit_1_and_json_error(self, run, base_url):
        bad = run("--json", "log", D1, "--start", "9:00", "--end", "9:30", "--break", "60")
        assert bad.returncode == 1
        doc = json.loads(bad.stdout)
        assert doc["exit"] == 1 and doc["status"] == 422 and "exceed" in doc["error"]
        assert _entry(base_url, D1) is None


# ---------- clock -----------------------------------------------------------


class TestClock:
    def test_in_and_out(self, run, base_url):
        dry = run("clock", "in", "--date", D1, "--at", "7:55", "--dry-run", check=True)
        assert "would be  2024-03-04 · in progress since 07:55" in dry.stdout
        assert _entry(base_url, D1) is None

        run("clock", "in", "--date", D1, "--at", "7:55", "--note", "early", check=True)
        assert _entry(base_url, D1)["start_time"] == "07:55"

        twice = run("clock", "in", "--date", D1, "--at", "8:00")
        assert twice.returncode == 1 and "started 07:55" in twice.stderr

        dry_out = run(
            "clock", "out", "--date", D1, "--at", "16:10", "--break", "30", "--dry-run", check=True
        )
        assert "07:55 → 16:10 · break 30min · 7.75h of 8h · -0.25h — early" in dry_out.stdout
        assert _entry(base_url, D1)["end_time"] is None

        out = run(
            "--json", "clock", "out", "--date", D1, "--at", "16:10", "--break", "30", check=True
        )
        entry = json.loads(out.stdout)["entry"]
        assert entry["end_time"] == "16:10" and entry["total_break_minutes"] == 30

        again = run("clock", "out", "--date", D1, "--at", "17:00")
        assert again.returncode == 1 and "already ended at 16:10" in again.stderr

    def test_another_day_needs_at(self, run, base_url):
        """The finding: `clock out --date <other day>` without --at stamped the current time
        (22:41) onto that day. Now the CLI refuses before any request, and the API refuses
        too (tested in tests/api/test_clock.py) for a client that skips the CLI."""
        run("clock", "in", "--date", D1, "--at", "7:55", check=True)
        res = run("clock", "out", "--date", D1, "--break", "30")
        assert res.returncode == 2
        assert "needs --at" in res.stderr
        stored = _entry(base_url, D1)
        assert stored["end_time"] is None and stored["breaks"] == []

        res = run("clock", "in", "--date", D2)
        assert res.returncode == 2 and "needs --at" in res.stderr
        assert _entry(base_url, D2) is None
        # --dry-run is no exception: it would show a day the server would never write.
        assert run("clock", "in", "--date", D2, "--dry-run").returncode == 2

    def test_server_stamps_the_time(self, run, base_url):
        # No --at: the server's clock in its TZ — a real HH:MM, on the server's today.
        out = run("--json", "clock", "in", check=True)
        entry = json.loads(out.stdout)["entry"]
        assert len(entry["start_time"]) == 5 and entry["start_time"][2] == ":"
        today = httpx.get(f"{base_url}/api/dashboard").json()["today"]
        assert entry["date"] == today
        httpx.delete(f"{base_url}/api/entries/{today}")

    def test_out_without_in(self, run):
        res = run("clock", "out", "--date", D2, "--at", "17:00")
        assert res.returncode == 1 and "clock in first" in res.stderr


# ---------- plan ------------------------------------------------------------


class TestPlan:
    def test_add_show_rm_commit(self, run, base_url):
        dry = run(
            "plan",
            "add",
            f"{D1}..{D3}",
            "--type",
            "vacation",
            "--note",
            "trip",
            "--dry-run",
            check=True,
        )
        assert dry.stdout.count("draft") == 3 and _plans(base_url) == []

        run("plan", "add", f"{D1}..{D3}", "--type", "vacation", "--note", "trip", check=True)
        run("plan", "add", D4, "--type", "flex", "--hours", "4", check=True)
        plans = _plans(base_url)
        assert [p["date"] for p in plans] == [D1, D2, D3, D4]
        assert plans[3]["fraction"] == 0.5

        shown = run("plan", "--year", "2024", check=True).stdout
        assert "flex · 4h" in shown and "trip" in shown and "3 planned" in shown

        # Re-drafting replaces; a logged date is skipped.
        httpx.post(f"{base_url}/api/entries", json={"date": D2, "day_type": "sick"})
        redo = json.loads(
            run("--json", "plan", "add", f"{D1}..{D2}", "--type", "holiday", check=True).stdout
        )
        assert redo == {"drafted": [], "replaced": [D1], "skipped": [D2]}

        rm = run("plan", "rm", D3, D5, check=True)
        assert "removed 1 draft(s), no draft on 2024-03-08" in rm.stdout

        dry_commit = run("plan", "commit", "--year", "2024", "--dry-run", check=True)
        assert "create holiday" in dry_commit.stdout and "create flex · 4h" in dry_commit.stdout
        assert _entry(base_url, D1) is None

        commit = json.loads(run("--json", "plan", "commit", D1, D4, D5, check=True).stdout)
        assert commit == {"created": [D1, D4], "skipped": [], "missing": [D5]}
        assert _entry(base_url, D1)["day_type"] == "holiday"
        assert _entry(base_url, D4)["fraction"] == 0.5
        # D2's draft still stands (its date is logged) and gets dropped on commit.
        year_commit = json.loads(
            run("--json", "plan", "commit", "--year", "2024", check=True).stdout
        )
        assert year_commit == {"created": [], "skipped": [], "missing": []}
        assert "nothing to commit" in run("plan", "commit", "--year", "2024", check=True).stdout

    def test_commit_needs_dates_or_year(self, run):
        assert run("plan", "commit").returncode == 2


# ---------- holidays --------------------------------------------------------


class TestHolidays:
    def test_needs_a_country_and_reports_the_service(self, run):
        assert run("holidays", "import", "--year", "2026").returncode == 2
        # The sandbox has no network: the API answers 502 and the CLI relays it (exit 1).
        res = run("holidays", "import", "--country", "ES", "--year", "2025", "--dry-run")
        assert res.returncode == 1
        assert "holiday" in res.stderr.lower()


# ---------- backup / restore ------------------------------------------------


class TestBackupRestore:
    def test_round_trip_needs_yes_and_backs_up_everywhere(self, run, base_url, tmp_path):
        httpx.post(f"{base_url}/api/entries", json={"date": D1, "day_type": "vacation"})
        out = tmp_path / "snap.json"
        res = run("backup", "--out", str(out), check=True)
        assert "1 entries" in res.stdout
        snap = json.loads(out.read_text(encoding="utf-8"))
        assert snap["version"] == 4 and snap["entries"][0]["date"] == D1

        httpx.delete(f"{base_url}/api/entries/{D1}")
        httpx.post(f"{base_url}/api/entries", json={"date": D2, "day_type": "sick"})

        no_yes = run("restore", str(out))
        assert no_yes.returncode == 2 and "--yes" in no_yes.stderr
        dry = run("restore", str(out), "--dry-run", check=True)
        assert "would restore 1 entries" in dry.stdout
        assert _entry(base_url, D2) is not None  # nothing happened yet

        restored = run("--target", "local", "restore", str(out), "--yes", check=True)
        assert "restored 1 entries onto local" in restored.stdout
        assert _entry(base_url, D1) is not None and _entry(base_url, D2) is None
        # restore is the one write that backs up on every target, local included.
        local_backups = list((run.backups / "local").glob("kronos_backup_*.json"))
        assert len(local_backups) == 1
        pre = json.loads(local_backups[0].read_text(encoding="utf-8"))
        assert [e["date"] for e in pre["entries"]] == [D2]  # the state *before* the restore

    def test_restore_rejects_junk(self, run, tmp_path):
        junk = tmp_path / "junk.json"
        junk.write_text("not json", encoding="utf-8")
        assert run("restore", str(junk), "--yes").returncode == 2
        junk.write_text('{"hello": 1}', encoding="utf-8")
        assert run("restore", str(junk), "--yes").returncode == 2
        assert run("restore", str(tmp_path / "missing.json"), "--yes").returncode == 2


# ---------- the PROD rule ---------------------------------------------------


class TestProdSafety:
    def test_prod_write_takes_a_backup_first(self, run, base_url):
        httpx.post(f"{base_url}/api/entries", json={"date": D1, "day_type": "vacation"})
        res = run("--target", "prod", "log", D2, "--type", "flex", check=True)
        assert res.stdout.startswith("backup  ")
        files = list((run.backups / "prod").glob("kronos_backup_*.json"))
        assert len(files) == 1
        snapshot = json.loads(files[0].read_text(encoding="utf-8"))
        assert snapshot["version"] == 4
        assert [e["date"] for e in snapshot["entries"]] == [D1]  # taken before D2 was written
        assert _entry(base_url, D2)["day_type"] == "flex"

        # --json names the backup too.
        doc = json.loads(
            run("--target", "prod", "--json", "log", D3, "--type", "flex", check=True).stdout
        )
        assert doc["backup"].startswith(str(run.backups / "prod"))
        assert len(list((run.backups / "prod").glob("kronos_backup_*.json"))) == 2

    def test_prod_dry_run_takes_none(self, run, base_url):
        run("--target", "prod", "log", D2, "--type", "flex", "--dry-run", check=True)
        assert not (run.backups / "prod").exists()
        assert _entry(base_url, D2) is None

    def test_int_write_takes_none(self, run, base_url):
        run("--target", "int", "log", D2, "--type", "flex", check=True)
        assert not run.backups.exists()
        assert _entry(base_url, D2) is not None

    def test_dead_prod_fails_closed(self, run, base_url):
        dead = f"http://127.0.0.1:{_free_port()}"
        res = run(
            "--target", "prod", "log", D2, "--type", "flex", target_urls={"KRONOS_PROD_URL": dead}
        )
        assert res.returncode == 3
        assert "safety backup failed" in res.stderr and "KRONOS_PROD_URL" in res.stderr
        assert not run.backups.exists()
        assert _entry(base_url, D2) is None

    def test_retention_keeps_fifty(self, run, base_url):
        folder = run.backups / "prod"
        folder.mkdir(parents=True)
        for i in range(55):
            (folder / f"kronos_backup_2020-01-01T00-{i // 60:02d}-{i % 60:02d}Z.json").write_text(
                "{}"
            )
        (folder / "keep-me.json").write_text("{}")
        run("--target", "prod", "log", D2, "--type", "flex", check=True)
        auto = sorted(p.name for p in folder.glob("kronos_backup_*.json"))
        assert len(auto) == 50
        assert auto[0] == "kronos_backup_2020-01-01T00-00-06Z.json"  # the six oldest went
        assert auto[-1].startswith("kronos_backup_20") and not auto[-1].startswith(
            "kronos_backup_2020"
        )
        assert (folder / "keep-me.json").exists()


# ---------- check -----------------------------------------------------------


class TestCheck:
    def test_green_against_the_server(self, run, base_url):
        res = run("check", check=True)
        assert "check: 8/8 passed" in res.stdout and "FAIL" not in res.stdout
        doc = json.loads(run("check", "--json", check=True).stdout)
        assert doc["passed"] == doc["total"] == 8 and all(c["ok"] for c in doc["checks"])

    def test_red_against_a_dead_port(self, run):
        dead = f"http://127.0.0.1:{_free_port()}"
        res = run("--target", "int", "check", target_urls={"KRONOS_INT_URL": dead})
        assert res.returncode == 3
        assert res.stdout.count("FAIL") == 8

    def test_unreachable_read_exits_3(self, run):
        dead = f"http://127.0.0.1:{_free_port()}"
        res = run("today", target_urls={"KRONOS_LOCAL_URL": dead})
        assert res.returncode == 3 and "cannot reach local" in res.stderr

    def test_unset_target_exits_2(self, run):
        res = run("--target", "prod", "today", target_urls={"KRONOS_PROD_URL": ""})
        assert res.returncode == 2 and "KRONOS_PROD_URL" in res.stderr


def test_past_year_dates_never_collide_with_today() -> None:
    """The fixed dates above must stay in the past for 'today'-based commands."""
    assert datetime.date.fromisoformat(D5) < datetime.date.today()
