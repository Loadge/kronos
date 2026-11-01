"""Unit tests for bin/kronos.py — the parts that need no server.

Target resolution (env beats file, local's default, int/prod must be set), the
``kronos.env`` parser, the date / time / break arguments, the request ``log`` builds,
the backup retention and the safety-backup failure modes, the human formatting.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("kronos_cli", REPO / "bin" / "kronos.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


k = _load()


# ---------- targets ---------------------------------------------------------


class TestTargets:
    def test_local_defaults_to_localhost(self, tmp_path):
        assert k.resolve_target("local", {}, tmp_path / "none.env") == "http://localhost:8765"

    def test_int_and_prod_have_no_default(self, tmp_path):
        for target in ("int", "prod"):
            with pytest.raises(k.Fail) as exc:
                k.resolve_target(target, {}, tmp_path / "none.env")
            assert exc.value.code == k.EXIT_USAGE
            assert f"KRONOS_{target.upper()}_URL" in str(exc.value)
            assert "kronos.env.example" in str(exc.value)

    def test_env_wins_over_file(self, tmp_path):
        env_file = tmp_path / "kronos.env"
        env_file.write_text("KRONOS_PROD_URL=https://file.example\n", encoding="utf-8")
        environ = {"KRONOS_PROD_URL": "https://env.example/"}
        assert k.resolve_target("prod", environ, env_file) == "https://env.example"
        assert k.resolve_target("prod", {}, env_file) == "https://file.example"

    def test_sources_are_reported(self, tmp_path):
        env_file = tmp_path / "kronos.env"
        env_file.write_text("KRONOS_INT_URL=http://int.example\n", encoding="utf-8")
        resolved = k.resolve_targets({"KRONOS_PROD_URL": "http://prod.example"}, env_file)
        assert resolved == {
            "local": ("http://localhost:8765", "default"),
            "int": ("http://int.example", "file"),
            "prod": ("http://prod.example", "env"),
        }

    def test_unknown_target_and_bad_scheme(self, tmp_path):
        with pytest.raises(k.Fail):
            k.resolve_target("staging", {}, tmp_path / "none.env")
        with pytest.raises(k.Fail) as exc:
            k.resolve_target("prod", {"KRONOS_PROD_URL": "prod.example"}, tmp_path / "none.env")
        assert "http://" in str(exc.value)

    def test_env_file_parser(self, tmp_path):
        env_file = tmp_path / "kronos.env"
        env_file.write_text(
            "# where things are\n"
            "\n"
            "KRONOS_INT_URL = 'http://int.example'\n"
            'KRONOS_PROD_URL="https://prod.example"\n'
            "not a pair\n"
            "=novalue\n",
            encoding="utf-8",
        )
        assert k.parse_env_file(env_file) == {
            "KRONOS_INT_URL": "http://int.example",
            "KRONOS_PROD_URL": "https://prod.example",
        }
        assert k.parse_env_file(tmp_path / "missing.env") == {}

    def test_backup_root_override(self, tmp_path):
        assert k.backup_root({"KRONOS_BACKUP_DIR": str(tmp_path)}) == tmp_path
        assert k.backup_root({}) == REPO / "backups"


# ---------- arguments -------------------------------------------------------


class TestArguments:
    @pytest.mark.parametrize(
        "raw,want", [("8:30", "08:30"), ("08:30", "08:30"), ("16:45", "16:45")]
    )
    def test_hhmm(self, raw, want):
        assert k.parse_hhmm(raw) == want

    @pytest.mark.parametrize("raw", ["830", "25:00", "8:60", "abc", "8"])
    def test_bad_hhmm(self, raw):
        with pytest.raises(k.Fail) as exc:
            k.parse_hhmm(raw)
        assert exc.value.code == k.EXIT_USAGE

    def test_breaks(self):
        assert k.parse_break("45") == {"break_minutes": 45}
        assert k.parse_break("13:00-13:45") == {"start_time": "13:00", "end_time": "13:45"}
        for bad in ("0", "-5", "lunch", "13:00"):
            with pytest.raises(k.Fail):
                k.parse_break(bad)

    def test_dates_and_ranges(self):
        today = date(2026, 10, 27)
        assert k.parse_date("today", today) == today
        assert k.parse_date("yesterday", today) == date(2026, 10, 26)
        assert k.parse_dates(["2026-12-30..2027-01-02", "2026-12-31", "today"], today) == [
            date(2026, 12, 30),
            date(2026, 12, 31),
            date(2027, 1, 1),
            date(2027, 1, 2),
            today,
        ]
        with pytest.raises(k.Fail):
            k.parse_dates(["2026-12-31..2026-12-30"])
        with pytest.raises(k.Fail):
            k.parse_dates(["2026-01-01..2027-06-01"])
        with pytest.raises(k.Fail):
            k.parse_date("27/10/2026")

    def test_month(self):
        assert k.parse_month("2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
        assert k.parse_month("2026-12") == (date(2026, 12, 1), date(2026, 12, 31))
        with pytest.raises(k.Fail):
            k.parse_month("2026-13")


class TestLogBody:
    def _args(self, **kw):
        parser = k.build_parser()
        argv = ["log", *kw.pop("argv")]
        return parser.parse_args(argv)

    def test_work_day(self):
        args = self._args(
            argv=[
                "2026-10-27",
                "--start",
                "8:30",
                "--end",
                "16:45",
                "--break",
                "45",
                "--break",
                "13:00-13:15",
                "--note",
                "hi",
            ]
        )
        assert k.build_log_body(args, date(2026, 10, 27)) == {
            "date": "2026-10-27",
            "day_type": "work",
            "start_time": "08:30",
            "end_time": "16:45",
            "breaks": [{"break_minutes": 45}, {"start_time": "13:00", "end_time": "13:15"}],
            "notes": "hi",
        }

    def test_work_day_needs_a_start(self):
        args = self._args(argv=["2026-10-27"])
        with pytest.raises(k.Fail) as exc:
            k.build_log_body(args, date(2026, 10, 27))
        assert "--start" in str(exc.value)

    def test_in_progress_work_day(self):
        args = self._args(argv=["today", "--start", "9:00"])
        body = k.build_log_body(args, date(2026, 10, 27))
        assert body == {"date": "2026-10-27", "day_type": "work", "start_time": "09:00"}

    def test_whole_and_partial_leave(self):
        args = self._args(argv=["2026-10-27", "--type", "vacation"])
        assert k.build_log_body(args, date(2026, 10, 27)) == {
            "date": "2026-10-27",
            "day_type": "vacation",
        }
        args = self._args(
            argv=[
                "2026-10-27",
                "--type",
                "vacation",
                "--hours",
                "3",
                "--start",
                "9:00",
                "--end",
                "14:00",
            ]
        )
        assert k.build_log_body(args, date(2026, 10, 27)) == {
            "date": "2026-10-27",
            "day_type": "vacation",
            "leave_hours": 3.0,
            "start_time": "09:00",
            "end_time": "14:00",
        }

    def test_times_on_leave_need_hours(self):
        args = self._args(argv=["2026-10-27", "--type", "sick", "--start", "9:00"])
        with pytest.raises(k.Fail) as exc:
            k.build_log_body(args, date(2026, 10, 27))
        assert "--hours" in str(exc.value)

    def test_hours_on_a_work_day_is_usage(self):
        args = self._args(argv=["2026-10-27", "--start", "9:00", "--hours", "2"])
        with pytest.raises(k.Fail):
            k.build_log_body(args, date(2026, 10, 27))

    def test_global_flags_anywhere(self):
        parser = k.build_parser()
        a = parser.parse_args(["--target", "prod", "--json", "log", "today", "--start", "9:00"])
        b = parser.parse_args(
            ["log", "today", "--start", "9:00", "--target", "prod", "--json", "--dry-run"]
        )
        assert (a.target, a.json, a.dry_run) == ("prod", True, False)
        assert (b.target, b.json, b.dry_run) == ("prod", True, True)
        c = parser.parse_args(["plan", "add", "today", "--type", "flex", "--target", "int"])
        assert (c.target, c.func) == ("int", k.cmd_plan_add)
        d = parser.parse_args(["plan", "--year", "2027"])
        assert (d.year, d.func, d.target) == (2027, k.cmd_plan_show, "local")


# ---------- backups ---------------------------------------------------------


def _touch_backups(folder: Path, n: int) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(n):
        stamp = f"2026-01-{i // 24 + 1:02d}T{i % 24:02d}-00-00Z"
        p = folder / f"kronos_backup_{stamp}.json"
        p.write_text("{}", encoding="utf-8")
        paths.append(p)
    return paths


class TestBackups:
    def test_prune_keeps_the_newest_fifty(self, tmp_path):
        paths = _touch_backups(tmp_path, 60)
        (tmp_path / "mine.json").write_text("{}")  # a human's file is never touched
        removed = k.prune_backups(tmp_path)
        assert removed == paths[:10]
        left = sorted(p.name for p in tmp_path.iterdir())
        assert len(left) == 51
        assert "mine.json" in left
        assert paths[10].name in left and paths[9].name not in left

    def test_prune_below_the_limit_removes_nothing(self, tmp_path):
        _touch_backups(tmp_path, 3)
        assert k.prune_backups(tmp_path) == []

    def test_same_second_never_overwrites(self, tmp_path):
        first = tmp_path / "kronos_backup_2026-01-01T00-00-00Z.json"
        first.write_text("{}")
        assert k.unique_path(first).name == "kronos_backup_2026-01-01T00-00-00Z-2.json"
        (tmp_path / "kronos_backup_2026-01-01T00-00-00Z-2.json").write_text("{}")
        assert k.unique_path(first).name == "kronos_backup_2026-01-01T00-00-00Z-3.json"
        assert k.prune_backups(tmp_path, keep=1) == [first]

    def test_filename_shape(self):
        name = k.backup_filename()
        assert name.startswith("kronos_backup_") and name.endswith("Z.json")

    def test_take_backup_fails_closed(self, tmp_path):
        class Dead:
            target = "prod"

            def raw(self, method, path):
                raise k.Fail("cannot reach prod", k.EXIT_UNREACHABLE)

        with pytest.raises(k.Fail) as exc:
            k.take_backup(Dead(), tmp_path / "prod")
        assert exc.value.code == k.EXIT_UNREACHABLE
        assert not (tmp_path / "prod").exists()

        class NotASnapshot:
            def raw(self, method, path):
                return 200, b'{"status": "ok"}'

        with pytest.raises(k.Fail) as exc:
            k.take_backup(NotASnapshot(), tmp_path / "prod")
        assert "not a snapshot" in str(exc.value)

        class Broken:
            def raw(self, method, path):
                return 500, b"boom"

        with pytest.raises(k.Fail) as exc:
            k.take_backup(Broken(), tmp_path / "prod")
        assert "HTTP 500" in str(exc.value)

    def test_take_backup_writes_the_snapshot(self, tmp_path):
        snapshot = {"version": 2, "entries": [], "plans": [], "settings": {}}

        class Ok:
            def raw(self, method, path):
                assert (method, path) == ("GET", "/api/backup")
                return 200, json.dumps(snapshot).encode()

        path = k.take_backup(Ok(), tmp_path / "prod")
        assert path.parent == tmp_path / "prod"
        assert json.loads(path.read_text()) == snapshot
        assert not list((tmp_path / "prod").glob("*.part"))


# ---------- formatting ------------------------------------------------------


class TestFormatting:
    def test_delta(self):
        assert k.fmt_delta(1.25) == "+1.25h"
        assert k.fmt_delta(-0.5) == "-0.50h"
        assert k.fmt_delta(0.0) == "±0.00h"

    def test_describe_entry(self):
        work = {
            "day_type": "work",
            "start_time": "08:30",
            "end_time": "16:45",
            "total_break_minutes": 45,
            "net_hours": 7.5,
            "target_hours": 8.0,
            "surplus_hours": -0.5,
            "notes": "lab",
        }
        assert k.describe_entry(work) == "08:30 → 16:45 · break 45min · 7.50h of 8h · -0.50h — lab"
        started = {
            **work,
            "end_time": None,
            "total_break_minutes": 0,
            "net_hours": 0,
            "surplus_hours": -8,
            "notes": None,
        }
        assert k.describe_entry(started) == "in progress since 08:30 · 0.00h of 8h · -8.00h"
        partial = {
            "day_type": "vacation",
            "fraction": 0.375,
            "leave_hours": 3.0,
            "start_time": "09:00",
            "end_time": "14:00",
            "total_break_minutes": 0,
            "net_hours": 5.0,
            "target_hours": 5.0,
            "surplus_hours": 0.0,
            "notes": None,
        }
        assert (
            k.describe_entry(partial)
            == "vacation · 3h · worked 09:00 → 14:00 · 5.00h of 5h · ±0.00h"
        )
        assert k.describe_entry(None) == "not logged"

    def test_table_aligns_columns(self):
        out = k.table([["a", "bbb"], ["cc", "d"]], ["x", "y"])
        assert out == "x   y\na   bbb\ncc  d"

    def test_api_error_detail(self):
        assert k._detail({"detail": "nope"}) == "nope"
        assert (
            k._detail({"detail": [{"loc": ["body", "start_time"], "msg": "bad"}, {"msg": "x"}]})
            == "start_time: bad; x"
        )
        assert k._detail(None) == "no detail"
