#!/usr/bin/env python
"""kronos — read and log days from a terminal, a script or a bot.

Why this exists
---------------
An agent (an agentic coder, a chat bot) that wants to know the balance or log a day
should not have to click the web UI or touch the database. This script talks only to
the HTTP API of a running Kronos — local, INT or PROD — and prints either a short
human report or, with ``--json``, the API's own payloads.

Usage
-----
    python bin/kronos.py [--target local|int|prod] [--json] <command> ...

    today                                   today's day, the balances, the streaks
    balance                                 week / month / cumulative
    days [--month 2026-10 | --from D --to D]
    plan [--year 2026]                      drafts and the year-end projection
    config                                  the settings
    check                                   GET-only health report (exit 1 on any FAIL)
    targets                                 where local / int / prod point

    log DATE... [--start 8:30 --end 16:45 --break 45 ...] [--note ...] [--replace]
    log DATE... --type vacation|sick|holiday|flex [--hours 4] [--note ...]
    clock in  [--at 8:30] [--date D] [--note ...]
    clock out [--at 16:45] [--date D] [--break 45 ...] [--note ...]
    plan add DATE... --type vacation|holiday|flex [--hours 4] [--note ...]
    plan rm DATE...
    plan commit DATE... | --year 2026
    holidays import [--country ES] [--region ES-MD] [--year 2026]
    backup [--out FILE]
    restore FILE --yes

A DATE is ``2026-10-27``, ``today``, ``yesterday`` or a range ``2026-12-24..2026-12-31``.
Every write takes ``--dry-run``: the request is printed, the server is asked what the
day would look like, and nothing is written.

Targets
-------
URLs never live in the repo (it is mirrored publicly). They come from the environment —
``KRONOS_LOCAL_URL``, ``KRONOS_INT_URL``, ``KRONOS_PROD_URL`` — or from a git-ignored
``kronos.env`` next to this repo's root (see ``kronos.env.example``); the environment
wins. ``local`` falls back to http://localhost:8765; ``int`` and ``prod`` must be set.

Safety
------
A write to PROD first downloads a backup to ``backups/prod/`` (``KRONOS_BACKUP_DIR`` to
move it) and refuses to go on if that fails; the newest 50 are kept. ``restore`` wipes
the target before loading, so it takes that backup on every target and needs ``--yes``.

Exit codes: 0 ok · 1 the API refused or a check failed · 2 usage · 3 target unreachable
(or the safety backup could not be taken).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / "kronos.env"
DEFAULT_BACKUP_DIR = REPO / "backups"

TARGETS = ("local", "int", "prod")
DEFAULT_LOCAL_URL = "http://localhost:8765"
BACKUP_KEEP = 50
TIMEOUT = 30.0  # seconds per request

LEAVE_TYPES = ("vacation", "sick", "holiday", "flex")
PLANNABLE_TYPES = ("vacation", "holiday", "flex")
DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

EXIT_OK = 0
EXIT_API = 1
EXIT_USAGE = 2
EXIT_UNREACHABLE = 3


class Fail(Exception):
    """An error whose message tells the caller what to do next, with its exit code."""

    def __init__(self, message: str, code: int = EXIT_API) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# targets
# --------------------------------------------------------------------------


def env_var(target: str) -> str:
    return f"KRONOS_{target.upper()}_URL"


def parse_env_file(path: Path) -> dict[str, str]:
    """``KEY=value`` lines; blank lines and ``#`` comments ignored; quotes stripped."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def resolve_targets(
    environ: Mapping[str, str] | None = None, env_file: Path | None = None
) -> dict[str, tuple[str | None, str]]:
    """Every target's URL and where it came from.

    ``{target: (url or None, source)}`` with source one of env / file / default / unset.
    """
    environ = os.environ if environ is None else environ
    file_values = parse_env_file(ENV_FILE if env_file is None else env_file)
    out: dict[str, tuple[str | None, str]] = {}
    for target in TARGETS:
        key = env_var(target)
        if environ.get(key):
            out[target] = (environ[key].rstrip("/"), "env")
        elif file_values.get(key):
            out[target] = (file_values[key].rstrip("/"), "file")
        elif target == "local":
            out[target] = (DEFAULT_LOCAL_URL, "default")
        else:
            out[target] = (None, "unset")
    return out


def resolve_target(
    target: str, environ: Mapping[str, str] | None = None, env_file: Path | None = None
) -> str:
    if target not in TARGETS:
        raise Fail(f"unknown target {target!r}; one of {', '.join(TARGETS)}", EXIT_USAGE)
    url, _source = resolve_targets(environ, env_file)[target]
    if not url:
        file_hint = ENV_FILE if env_file is None else env_file
        raise Fail(
            f"target {target!r} has no URL. Set {env_var(target)} in the environment or in "
            f"{file_hint} (see kronos.env.example).",
            EXIT_USAGE,
        )
    if not url.startswith(("http://", "https://")):
        raise Fail(
            f"{env_var(target)} must start with http:// or https://, got {url!r}", EXIT_USAGE
        )
    return url


def backup_root(environ: Mapping[str, str] | None = None) -> Path:
    environ = os.environ if environ is None else environ
    raw = environ.get("KRONOS_BACKUP_DIR")
    return Path(raw) if raw else DEFAULT_BACKUP_DIR


# --------------------------------------------------------------------------
# http
# --------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, status: int, detail: str, method: str, path: str) -> None:
        super().__init__(f"{method} {path} → HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class Api:
    """The thinnest client: JSON in, JSON out, one exception per kind of failure."""

    def __init__(self, base_url: str, target: str) -> None:
        self.base_url = base_url
        self.target = target
        self.opener = urllib.request.build_opener()
        self.opener.addheaders = [("User-Agent", "kronos-cli"), ("Accept", "application/json")]

    def raw(self, method: str, path: str, body: object | None = None) -> tuple[int, bytes]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(req, timeout=TIMEOUT) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise Fail(
                f"cannot reach {self.target} at {self.base_url} ({reason}). "
                f"Is Kronos running there, and is {env_var(self.target)} right?",
                EXIT_UNREACHABLE,
            ) from exc

    def call(self, method: str, path: str, body: object | None = None) -> object:
        status, payload = self.raw(method, path, body)
        text = payload.decode("utf-8", errors="replace")
        parsed: object = None
        if text:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = text
        if status >= 400:
            raise ApiError(status, _detail(parsed), method, path)
        return parsed

    def get(self, path: str) -> object:
        return self.call("GET", path)

    def post(self, path: str, body: object | None = None) -> object:
        return self.call("POST", path, body if body is not None else {})

    def put(self, path: str, body: object) -> object:
        return self.call("PUT", path, body)

    def delete(self, path: str) -> object:
        return self.call("DELETE", path)


def _detail(parsed: object) -> str:
    """FastAPI's error body as one line: a string detail, or the validation list."""
    if isinstance(parsed, dict) and "detail" in parsed:
        detail = parsed["detail"]
        if isinstance(detail, list):
            parts = []
            for item in detail:
                loc = ".".join(str(x) for x in item.get("loc", ()) if x != "body")
                msg = item.get("msg", "invalid value")
                parts.append(f"{loc}: {msg}" if loc else msg)
            return "; ".join(parts)
        return str(detail)
    return str(parsed)[:300] if parsed else "no detail"


# --------------------------------------------------------------------------
# arguments: dates, times, breaks
# --------------------------------------------------------------------------


def parse_hhmm(raw: str) -> str:
    """``8:30`` or ``08:30`` → ``08:30``."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", raw)
    if not m or not (0 <= int(m.group(1)) < 24 and 0 <= int(m.group(2)) < 60):
        raise Fail(f"expected a time like 8:30 or 16:45, got {raw!r}", EXIT_USAGE)
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def parse_break(raw: str) -> dict:
    """``45`` → 45 minutes; ``13:00-13:45`` → that range (the API derives the minutes)."""
    text = raw.strip()
    if text.isdigit():
        minutes = int(text)
        if minutes <= 0:
            raise Fail(f"a break needs at least one minute, got {raw!r}", EXIT_USAGE)
        return {"break_minutes": minutes}
    if "-" in text:
        start, _, end = text.partition("-")
        return {"start_time": parse_hhmm(start), "end_time": parse_hhmm(end)}
    raise Fail(
        f"expected a break as minutes (45) or a range (13:00-13:45), got {raw!r}", EXIT_USAGE
    )


def parse_date(raw: str, today: date | None = None) -> date:
    today = today or date.today()
    text = raw.strip().lower()
    if text == "today":
        return today
    if text == "yesterday":
        return today - timedelta(days=1)
    if text == "tomorrow":
        return today + timedelta(days=1)
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise Fail(
            f"expected a date like 2026-10-27 (or today / yesterday), got {raw!r}", EXIT_USAGE
        ) from None


def parse_dates(raws: Iterable[str], today: date | None = None) -> list[date]:
    """Each argument is a date or an inclusive range ``A..B``; duplicates dropped, order kept."""
    out: list[date] = []
    for raw in raws:
        if ".." in raw:
            a, _, b = raw.partition("..")
            start, end = parse_date(a, today), parse_date(b, today)
            if end < start:
                raise Fail(f"range {raw!r} ends before it starts", EXIT_USAGE)
            if (end - start).days > 366:
                raise Fail(
                    f"range {raw!r} is longer than a year — that is a mistake, not a plan",
                    EXIT_USAGE,
                )
            d = start
            while d <= end:
                out.append(d)
                d += timedelta(days=1)
        else:
            out.append(parse_date(raw, today))
    seen: set[date] = set()
    unique = []
    for d in out:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


def parse_month(raw: str) -> tuple[date, date]:
    m = re.fullmatch(r"\s*(\d{4})-(\d{1,2})\s*", raw)
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise Fail(f"expected a month like 2026-10, got {raw!r}", EXIT_USAGE)
    y, mo = int(m.group(1)), int(m.group(2))
    first = date(y, mo, 1)
    last = (date(y + 1, 1, 1) if mo == 12 else date(y, mo + 1, 1)) - timedelta(days=1)
    return first, last


# --------------------------------------------------------------------------
# backups
# --------------------------------------------------------------------------


def backup_filename(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"kronos_backup_{now.strftime('%Y-%m-%dT%H-%M-%SZ')}.json"


def unique_path(path: Path) -> Path:
    """``path``, or ``name-2.json``, ``name-3.json``… if a write in the same second exists:
    a safety backup never overwrites an earlier one."""
    candidate = path
    n = 1
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
    return candidate


def prune_backups(folder: Path, keep: int = BACKUP_KEEP) -> list[Path]:
    """Delete the oldest automatic backups beyond ``keep``; returns what was removed.

    Only files of the exact automatic shape are candidates — anything else a human
    dropped in the folder is left alone.
    """
    pattern = re.compile(r"^kronos_backup_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z)(?:-(\d+))?\.json$")
    stamped = []
    for p in folder.iterdir():
        m = pattern.match(p.name)
        if m and p.is_file():
            # Oldest first: by the stamp, then by the same-second counter.
            stamped.append(((m.group(1), int(m.group(2) or 1)), p))
    files = [p for _key, p in sorted(stamped)]
    removed = []
    for old in files[: max(len(files) - keep, 0)]:
        old.unlink()
        removed.append(old)
    return removed


def take_backup(api: Api, folder: Path) -> Path:
    """Download the snapshot into ``folder`` (created on demand). Fails closed."""
    try:
        status, payload = api.raw("GET", "/api/backup")
    except Fail as exc:
        raise Fail(f"safety backup failed: {exc}", EXIT_UNREACHABLE) from exc
    if status != 200:
        raise Fail(
            f"safety backup failed: GET /api/backup answered HTTP {status} — nothing was written",
            EXIT_UNREACHABLE,
        )
    try:
        snapshot = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise Fail(
            "safety backup failed: /api/backup did not return JSON", EXIT_UNREACHABLE
        ) from exc
    if not isinstance(snapshot, dict) or "version" not in snapshot or "entries" not in snapshot:
        raise Fail(
            "safety backup failed: /api/backup returned something that is not a snapshot",
            EXIT_UNREACHABLE,
        )
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = unique_path(folder / backup_filename())
        tmp = path.with_suffix(".json.part")
        tmp.write_bytes(payload)
        tmp.replace(path)
        prune_backups(folder)
    except OSError as exc:
        raise Fail(
            f"safety backup failed: cannot write under {folder} ({exc})", EXIT_UNREACHABLE
        ) from exc
    return path


# --------------------------------------------------------------------------
# context and output
# --------------------------------------------------------------------------


class Ctx:
    """What every command needs: the target, its client, the output mode, the dry-run flag."""

    def __init__(self, target: str, api: Api, as_json: bool, dry_run: bool = False) -> None:
        self.target = target
        self.api = api
        self.json = as_json
        self.dry_run = dry_run
        self.backup_path: Path | None = None
        self.lines: list[str] = []

    def say(self, line: str = "") -> None:
        """Human output, buffered so a JSON run prints exactly one document."""
        if not self.json:
            print(line)

    def guard_write(self, *, always: bool = False) -> Path | None:
        """The safety backup before a write: on PROD always, elsewhere when asked.

        Once per run — a command that makes several writes (a range, a replace that
        falls back to a create) still snapshots the state before the first.
        """
        if self.dry_run or self.backup_path is not None:
            return self.backup_path
        if self.target != "prod" and not always:
            return None
        folder = backup_root() / self.target
        self.backup_path = take_backup(self.api, folder)
        self.say(f"backup  {self.backup_path}")
        return self.backup_path

    def emit(self, payload: object) -> None:
        """The JSON document of a run (with the backup path when one was taken)."""
        if self.json:
            if isinstance(payload, dict) and self.backup_path is not None:
                payload = {**payload, "backup": str(self.backup_path)}
            print(json.dumps(payload, indent=2, ensure_ascii=False))


def fmt_h(hours: float) -> str:
    return f"{hours:.2f}h"


def fmt_delta(hours: float) -> str:
    sign = "+" if hours > 0.005 else ("-" if hours < -0.005 else "±")
    return f"{sign}{abs(hours):.2f}h"


def fmt_days(days: float) -> str:
    return f"{days:g}"


def table(rows: list[list[str]], headers: list[str] | None = None) -> str:
    """Left-aligned columns, the simplest thing that reads well in a terminal."""
    if headers:
        rows = [headers, *rows]
    if not rows:
        return ""
    widths = [max(len(str(r[i])) for r in rows if i < len(r)) for i in range(len(rows[0]))]
    lines = []
    for r in rows:
        lines.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)).rstrip())
    return "\n".join(lines)


def describe_entry(e: dict | None) -> str:
    """One line for a day: type, times, breaks, net of target, Δ."""
    if e is None:
        return "not logged"
    kind = e["day_type"]
    parts = []
    if kind == "work":
        if e["end_time"]:
            parts.append(f"{e['start_time']} → {e['end_time']}")
        else:
            parts.append(f"in progress since {e['start_time']}")
    else:
        label = kind
        if e.get("fraction", 1.0) < 1.0:
            label += f" · {e['leave_hours']:g}h"
        parts.append(label)
        if e.get("start_time"):
            parts.append(f"worked {e['start_time']} → {e['end_time'] or '…'}")
    if e.get("total_break_minutes"):
        parts.append(f"break {e['total_break_minutes']}min")
    if kind == "work" or e.get("start_time"):
        parts.append(f"{fmt_h(e['net_hours'])} of {e['target_hours']:g}h")
    parts.append(fmt_delta(e["surplus_hours"]))
    line = " · ".join(parts)
    if e.get("notes"):
        line += f" — {e['notes']}"
    return line


def day_row(e: dict) -> list[str]:
    d = date.fromisoformat(e["date"])
    kind = e["day_type"]
    if kind != "work" and e.get("fraction", 1.0) < 1.0:
        kind = f"{kind} · {e['leave_hours']:g}h"
    times = ""
    if e.get("start_time"):
        times = f"{e['start_time']}–{e['end_time'] or '…'}"
    return [
        e["date"],
        DOW[d.weekday()],
        kind,
        times,
        str(e["total_break_minutes"]) if e.get("total_break_minutes") else "",
        f"{e['net_hours']:.2f}",
        f"{e['target_hours']:.2f}",
        fmt_delta(e["surplus_hours"]),
        (e.get("notes") or "").replace("\n", " "),
    ]


def period_line(label: str, p: dict) -> str:
    return (
        f"{label:<8} {fmt_delta(p['surplus_hours']):>9}   net {p['net_hours']:.2f} / "
        f"target {p['target_hours']:.2f}   ({fmt_days(p['work_days'])} work · "
        f"{fmt_days(p['non_work_days'])} off)"
    )


def show_request(ctx: Ctx, method: str, path: str, body: object | None) -> None:
    ctx.say(f"dry-run  {method} {path}")
    if body is not None:
        for line in json.dumps(body, indent=2, ensure_ascii=False).splitlines():
            ctx.say(f"         {line}")


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------


def cmd_today(ctx: Ctx, args) -> int:
    dashboard = ctx.api.get("/api/dashboard")
    today = dashboard["today"]
    try:
        entry = ctx.api.get(f"/api/entries/{today}")
    except ApiError as exc:
        if exc.status != 404:
            raise
        entry = None
    streaks = ctx.api.get("/api/streaks")
    ctx.emit({"today": today, "entry": entry, "dashboard": dashboard, "streaks": streaks})
    d = date.fromisoformat(today)
    ctx.say(f"{DOW[d.weekday()]} {today} · {describe_entry(entry)}")
    ctx.say()
    ctx.say(period_line("week", dashboard["week"]))
    ctx.say(period_line("month", dashboard["month"]))
    ctx.say(period_line("overall", dashboard["cumulative"]))
    ctx.say()
    ctx.say(
        f"streaks  logging {streaks['logging_streak']}d · on target {streaks['on_target_streak']}d"
        f" · {streaks['total_logged_days']} days logged"
    )
    return EXIT_OK


def cmd_balance(ctx: Ctx, args) -> int:
    dashboard = ctx.api.get("/api/dashboard")
    ctx.emit(
        {
            "today": dashboard["today"],
            "week": dashboard["week"],
            "month": dashboard["month"],
            "cumulative": dashboard["cumulative"],
            "cumulative_start_date": dashboard["cumulative_start_date"],
        }
    )
    ctx.say(period_line("week", dashboard["week"]))
    ctx.say(period_line("month", dashboard["month"]))
    ctx.say(
        period_line("overall", dashboard["cumulative"])
        + f"   since {dashboard['cumulative_start_date']}"
    )
    return EXIT_OK


def cmd_days(ctx: Ctx, args) -> int:
    if args.month:
        if args.from_ or args.to:
            raise Fail("use --month or --from/--to, not both", EXIT_USAGE)
        start, end = parse_month(args.month)
    elif args.from_ or args.to:
        start = parse_date(args.from_) if args.from_ else None
        end = parse_date(args.to) if args.to else None
        if start and end and end < start:
            raise Fail("--to is before --from", EXIT_USAGE)
    else:
        start, end = parse_month(date.today().strftime("%Y-%m"))
    query = "&".join(
        f"{k}={v.isoformat()}" for k, v in (("from", start), ("to", end)) if v is not None
    )
    entries = ctx.api.get("/api/entries" + (f"?{query}" if query else ""))
    ctx.emit(entries)
    if not entries:
        ctx.say("no days logged in that range")
        return EXIT_OK
    ctx.say(
        table(
            [day_row(e) for e in entries],
            ["date", "day", "type", "hours", "break", "net", "target", "Δ", "note"],
        )
    )
    net = sum(e["net_hours"] for e in entries)
    target = sum(e["target_hours"] for e in entries)
    ctx.say()
    ctx.say(
        f"{len(entries)} days · net {net:.2f} / target {target:.2f} → {fmt_delta(net - target)}"
    )
    return EXIT_OK


def cmd_plan_show(ctx: Ctx, args) -> int:
    year = args.year or date.today().year
    plans = ctx.api.get(f"/api/plans?year={year}")
    projection = ctx.api.get(f"/api/plans/projection?year={year}")
    ctx.emit({"year": year, "plans": plans, "projection": projection})
    if plans:
        rows = []
        for p in plans:
            d = date.fromisoformat(p["date"])
            kind = p["day_type"] + (f" · {p['leave_hours']:g}h" if p["fraction"] < 1.0 else "")
            rows.append(
                [
                    p["date"],
                    DOW[d.weekday()],
                    kind,
                    "logged" if p["exists"] else "draft",
                    p.get("notes") or "",
                ]
            )
        ctx.say(table(rows, ["date", "day", "type", "state", "note"]))
    else:
        ctx.say(f"no drafts for {year}")
    ctx.say()
    ctx.say(
        f"{year} at Dec 31: on target {fmt_delta(projection['on_target'])} · at your pace "
        f"{fmt_delta(projection['at_pace'])} "
        f"(balance today {fmt_delta(projection['balance_today'])})"
    )
    ctx.say(
        f"vacation: {fmt_days(projection['vacation_used_days'])} used · "
        f"{fmt_days(projection['vacation_drafted_days'])} planned · "
        f"{fmt_days(projection['vacation_remaining_after_plan'])} left of "
        f"{fmt_days(projection['vacation_budget_days'])}"
    )
    return EXIT_OK


def cmd_config(ctx: Ctx, args) -> int:
    config = ctx.api.get("/api/config")
    ctx.emit(config)
    rows = []
    for key, value in config.items():
        if key == "daily_target_schedule":
            value = ", ".join(f"{r['hours']:g}h from {r['effective_from']}" for r in value)
        elif key == "work_week_days":
            value = " ".join(DOW[i] for i in value)
        rows.append([key, str(value)])
    ctx.say(table(rows))
    return EXIT_OK


def cmd_targets(ctx: Ctx, args) -> int:
    resolved = resolve_targets()
    ctx.emit({t: {"url": url, "source": source} for t, (url, source) in resolved.items()})
    rows = [[t, url or "(unset)", source] for t, (url, source) in resolved.items()]
    ctx.say(table(rows, ["target", "url", "from"]))
    ctx.say()
    ctx.say(f"backups  {backup_root()}")
    return EXIT_OK


# ---------- check -----------------------------------------------------------

Check = tuple[str, str, Callable[[object], str | None]]


def _is_dict_with(*keys: str) -> Callable[[object], str | None]:
    def check(data: object) -> str | None:
        if not isinstance(data, dict):
            return f"expected a JSON object, got {type(data).__name__}"
        missing = [k for k in keys if k not in data]
        return f"missing {', '.join(missing)}" if missing else None

    return check


def _is_list(data: object) -> str | None:
    return None if isinstance(data, list) else f"expected a JSON list, got {type(data).__name__}"


CHECKS: list[Check] = [
    ("healthz", "/healthz", _is_dict_with("status")),
    ("config", "/api/config", _is_dict_with("daily_target_hours", "cumulative_start_date")),
    ("today", "/api/dashboard", _is_dict_with("today", "week", "month", "cumulative")),
    ("balance", "/api/streaks", _is_dict_with("logging_streak", "total_logged_days")),
    ("days", "/api/entries", _is_list),
    ("plan", "/api/plans", _is_list),
    ("projection", "/api/plans/projection", _is_dict_with("on_target", "at_pace")),
]


def cmd_check(ctx: Ctx, args) -> int:
    """GET-only: every read the other commands rely on, with its expected shape."""
    results = []
    unreachable = 0
    for name, path, validate in CHECKS:
        try:
            status, payload = ctx.api.raw("GET", path)
            if status != 200:
                reason = f"HTTP {status}"
            else:
                try:
                    reason = validate(json.loads(payload))
                except json.JSONDecodeError:
                    reason = "body is not JSON"
        except Fail as exc:
            reason = str(exc)
            unreachable += 1
        results.append({"check": name, "path": path, "ok": reason is None, "reason": reason})
        ctx.say(
            f"{'OK  ' if reason is None else 'FAIL'}  {name:<11} GET {path}"
            + (f"  {reason}" if reason else "")
        )
    passed = sum(1 for r in results if r["ok"])
    ctx.emit(
        {
            "target": ctx.target,
            "url": ctx.api.base_url,
            "passed": passed,
            "total": len(results),
            "checks": results,
        }
    )
    ctx.say(f"check: {passed}/{len(results)} passed against {ctx.target} ({ctx.api.base_url})")
    if unreachable == len(results):
        return EXIT_UNREACHABLE
    return EXIT_OK if passed == len(results) else EXIT_API


# --------------------------------------------------------------------------
# writes
# --------------------------------------------------------------------------


def _leave_body(day_type: str, hours: float | None, note: str | None) -> dict:
    body: dict = {"day_type": day_type}
    if hours is not None:
        body["leave_hours"] = hours
    if note is not None:
        body["notes"] = note
    return body


def build_log_body(args, on: date) -> dict:
    """The single-day request for ``log``; usage errors are raised here, before any call."""
    day_type = args.type or "work"
    breaks = [parse_break(b) for b in (args.breaks or [])]
    start = parse_hhmm(args.start) if args.start else None
    end = parse_hhmm(args.end) if args.end else None
    if day_type == "work":
        if args.hours is not None:
            raise Fail("--hours is for leave (--type vacation|sick|holiday|flex)", EXIT_USAGE)
        if not start:
            raise Fail("a work day needs --start (and --end once it is over)", EXIT_USAGE)
        body: dict = {"date": on.isoformat(), "day_type": "work", "start_time": start}
    else:
        body = {"date": on.isoformat(), **_leave_body(day_type, args.hours, None)}
        if (start or end or breaks) and args.hours is None:
            raise Fail(
                "times on a leave day need --hours (the part of the day that is leave)", EXIT_USAGE
            )
        if start:
            body["start_time"] = start
    if end:
        body["end_time"] = end
    if breaks:
        body["breaks"] = breaks
    if args.note is not None:
        body["notes"] = args.note
    return body


def cmd_log(ctx: Ctx, args) -> int:
    dates = parse_dates(args.dates)
    if len(dates) > 1:
        return _log_many(ctx, args, dates)
    on = dates[0]
    body = build_log_body(args, on)
    path = f"/api/entries/{on.isoformat()}"

    if ctx.dry_run:
        show_request(
            ctx, "PUT" if args.replace else "POST", path if args.replace else "/api/entries", body
        )
        preview = ctx.api.post("/api/entries/preview", body)
        ctx.emit({"dry_run": True, "request": body, "preview": preview})
        ctx.say(f"would be  {DOW[on.weekday()]} {on.isoformat()} · {describe_entry(preview)}")
        if preview["exists"]:
            ctx.say(
                "note      that date is already logged"
                + ("" if args.replace else " — add --replace to overwrite it")
            )
        return EXIT_OK

    ctx.guard_write()
    if args.replace:
        update = {k: v for k, v in body.items() if k != "date"}
        try:
            entry = ctx.api.put(path, update)
            action = "replaced"
        except ApiError as exc:
            if exc.status != 404:
                raise
            entry = ctx.api.post("/api/entries", body)
            action = "logged"
    else:
        try:
            entry = ctx.api.post("/api/entries", body)
            action = "logged"
        except ApiError as exc:
            if exc.status == 409:
                raise Fail(
                    f"{on.isoformat()} is already logged — add --replace to overwrite it"
                ) from exc
            raise
    ctx.emit({"action": action, "entry": entry})
    ctx.say(f"{action}  {DOW[on.weekday()]} {on.isoformat()} · {describe_entry(entry)}")
    return EXIT_OK


def _log_many(ctx: Ctx, args, dates: list[date]) -> int:
    day_type = args.type or "work"
    if day_type == "work" or args.start or args.end or args.breaks:
        raise Fail(
            "several dates at once take one leave type (--type) and no times; "
            "log work days one by one",
            EXIT_USAGE,
        )
    if args.replace:
        raise Fail(
            "--replace works on a single date; a range never overwrites logged days", EXIT_USAGE
        )
    body = {"dates": [d.isoformat() for d in dates], **_leave_body(day_type, args.hours, args.note)}
    if ctx.dry_run:
        show_request(ctx, "POST", "/api/entries/batch", body)
        previews = []
        for d in dates:
            single = {"date": d.isoformat(), **{k: v for k, v in body.items() if k != "dates"}}
            previews.append(ctx.api.post("/api/entries/preview", single))
        ctx.emit({"dry_run": True, "request": body, "previews": previews})
        rows = [
            [
                p["date"],
                DOW[date.fromisoformat(p["date"]).weekday()],
                describe_entry(p),
                "skip (logged)" if p["exists"] else "create",
            ]
            for p in previews
        ]
        ctx.say(table(rows, ["date", "day", "would be", "action"]))
        return EXIT_OK
    ctx.guard_write()
    result = ctx.api.post("/api/entries/batch", body)
    ctx.emit(result)
    ctx.say(
        f"logged   {len(result['created'])} {day_type} day(s)"
        + (f", skipped {len(result['skipped'])} already logged" if result["skipped"] else "")
    )
    return EXIT_OK


def cmd_clock(ctx: Ctx, args) -> int:
    body: dict = {}
    if args.at:
        body["at"] = parse_hhmm(args.at)
    if args.date:
        on = parse_date(args.date)
        if not args.at and on != date.today():
            # The server applies the same rule with *its* today; this just saves the
            # round trip for the obvious case. "Now" on another day is never a time.
            raise Fail(
                f"clock {args.direction} on {on.isoformat()} needs --at HH:MM — "
                "without it the current time would be stamped onto another day",
                EXIT_USAGE,
            )
        body["date"] = on.isoformat()
    if args.note is not None:
        body["notes"] = args.note
    if args.direction == "out" and args.breaks:
        body["breaks"] = [parse_break(b) for b in args.breaks]
    path = f"/api/clock/{args.direction}"
    if ctx.dry_run:
        show_request(ctx, "POST", path, body)
        preview = ctx.api.post(path, {**body, "dry_run": True})
        ctx.emit({"dry_run": True, "request": body, "preview": preview})
        ctx.say(f"would be  {preview['date']} · {describe_entry(preview)}")
        return EXIT_OK
    ctx.guard_write()
    entry = ctx.api.post(path, body)
    ctx.emit({"action": f"clock {args.direction}", "entry": entry})
    ctx.say(f"clock {args.direction:<4} {entry['date']} · {describe_entry(entry)}")
    return EXIT_OK


def cmd_plan_add(ctx: Ctx, args) -> int:
    dates = parse_dates(args.dates)
    body = {
        "dates": [d.isoformat() for d in dates],
        **_leave_body(args.type, args.hours, args.note),
    }
    if ctx.dry_run:
        show_request(ctx, "POST", "/api/plans", body)
        lo, hi = min(dates), max(dates)
        logged = {e["date"] for e in ctx.api.get(f"/api/entries?from={lo}&to={hi}")}
        drafted = set()
        for year in range(lo.year, hi.year + 1):
            drafted |= {p["date"] for p in ctx.api.get(f"/api/plans?year={year}")}
        outcome = {
            d.isoformat(): (
                "skip (logged)"
                if d.isoformat() in logged
                else "replace"
                if d.isoformat() in drafted
                else "draft"
            )
            for d in dates
        }
        ctx.emit({"dry_run": True, "request": body, "outcome": outcome})
        ctx.say(
            table(
                [[d, DOW[date.fromisoformat(d).weekday()], what] for d, what in outcome.items()],
                ["date", "day", "action"],
            )
        )
        return EXIT_OK
    ctx.guard_write()
    result = ctx.api.post("/api/plans", body)
    ctx.emit(result)
    ctx.say(
        f"drafted {len(result['drafted'])} · replaced {len(result['replaced'])} · "
        f"skipped (logged) {len(result['skipped'])}"
    )
    return EXIT_OK


def cmd_plan_rm(ctx: Ctx, args) -> int:
    dates = parse_dates(args.dates)
    if ctx.dry_run:
        for d in dates:
            show_request(ctx, "DELETE", f"/api/plans/{d.isoformat()}", None)
        drafted = set()
        for year in sorted({d.year for d in dates}):
            drafted |= {p["date"] for p in ctx.api.get(f"/api/plans?year={year}")}
        outcome = {
            d.isoformat(): ("remove" if d.isoformat() in drafted else "no draft") for d in dates
        }
        ctx.emit({"dry_run": True, "outcome": outcome})
        ctx.say(table([[d, what] for d, what in outcome.items()], ["date", "action"]))
        return EXIT_OK
    ctx.guard_write()
    removed, missing = [], []
    for d in dates:
        try:
            ctx.api.delete(f"/api/plans/{d.isoformat()}")
            removed.append(d.isoformat())
        except ApiError as exc:
            if exc.status != 404:
                raise
            missing.append(d.isoformat())
    ctx.emit({"removed": removed, "missing": missing})
    ctx.say(
        f"removed {len(removed)} draft(s)"
        + (f", no draft on {', '.join(missing)}" if missing else "")
    )
    return EXIT_OK


def cmd_plan_commit(ctx: Ctx, args) -> int:
    if args.dates:
        dates = [d.isoformat() for d in parse_dates(args.dates)]
    elif args.year:
        dates = [p["date"] for p in ctx.api.get(f"/api/plans?year={args.year}") if not p["exists"]]
        if not dates:
            ctx.emit({"created": [], "skipped": [], "missing": []})
            ctx.say(f"nothing to commit for {args.year}")
            return EXIT_OK
    else:
        raise Fail("plan commit needs dates or --year", EXIT_USAGE)
    body = {"dates": dates}
    if ctx.dry_run:
        show_request(ctx, "POST", "/api/plans/commit", body)
        drafts = {}
        for year in sorted({d[:4] for d in dates}):
            drafts.update({p["date"]: p for p in ctx.api.get(f"/api/plans?year={year}")})
        rows = []
        outcome = {}
        for d in dates:
            p = drafts.get(d)
            what = (
                "no draft"
                if p is None
                else (
                    "skip (logged)"
                    if p["exists"]
                    else f"create {p['day_type']}"
                    + (f" · {p['leave_hours']:g}h" if p["fraction"] < 1 else "")
                )
            )
            outcome[d] = what
            rows.append([d, what])
        ctx.emit({"dry_run": True, "request": body, "outcome": outcome})
        ctx.say(table(rows, ["date", "action"]))
        return EXIT_OK
    ctx.guard_write()
    result = ctx.api.post("/api/plans/commit", body)
    ctx.emit(result)
    ctx.say(
        f"committed {len(result['created'])} · skipped (logged) {len(result['skipped'])} · "
        f"no draft {len(result['missing'])}"
    )
    return EXIT_OK


def cmd_holidays_import(ctx: Ctx, args) -> int:
    config = ctx.api.get("/api/config")
    country = (args.country or config.get("holiday_country") or "").upper()
    region = args.region if args.region is not None else (config.get("holiday_region") or "")
    year = args.year or date.today().year
    if not country:
        raise Fail("no country: pass --country ES (Settings → Holidays remembers one)", EXIT_USAGE)
    query = f"country={country}&year={year}" + (f"&region={region}" if region else "")
    if ctx.dry_run:
        show_request(ctx, "POST", f"/api/holidays/import?{query}", None)
        preview = ctx.api.get(f"/api/holidays/preview?{query}")
        ctx.emit(
            {
                "dry_run": True,
                "country": country,
                "region": region,
                "year": year,
                "preview": preview,
            }
        )
        rows = [
            [
                h["date"],
                DOW[date.fromisoformat(h["date"]).weekday()],
                h["name"],
                "regional" if h["regional"] else "national",
                "skip (logged)" if h["exists"] else "import",
            ]
            for h in preview
        ]
        ctx.say(table(rows, ["date", "day", "holiday", "scope", "action"]))
        return EXIT_OK
    ctx.guard_write()
    result = ctx.api.post(f"/api/holidays/import?{query}")
    ctx.emit({"country": country, "region": region, "year": year, **result})
    ctx.say(
        f"imported {len(result['imported'])} holiday(s) for {country}"
        f"{' ' + region if region else ''} {year}"
        + (f", skipped {len(result['skipped'])} already logged" if result["skipped"] else "")
    )
    return EXIT_OK


def cmd_backup(ctx: Ctx, args) -> int:
    out = (
        Path(args.out)
        if args.out
        else Path(f"kronos_backup_{ctx.target}_{date.today().isoformat()}.json")
    )
    if ctx.dry_run:
        show_request(ctx, "GET", "/api/backup", None)
        ctx.emit({"dry_run": True, "path": str(out)})
        ctx.say(f"would write  {out}")
        return EXIT_OK
    status, payload = ctx.api.raw("GET", "/api/backup")
    if status != 200:
        raise ApiError(status, _detail(_maybe_json(payload)), "GET", "/api/backup")
    snapshot = json.loads(payload)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    ctx.emit(
        {
            "path": str(out),
            "version": snapshot.get("version"),
            "entries": len(snapshot.get("entries", [])),
            "plans": len(snapshot.get("plans", [])),
        }
    )
    ctx.say(
        f"wrote {out} · version {snapshot.get('version')} · "
        f"{len(snapshot.get('entries', []))} entries · {len(snapshot.get('plans', []))} drafts"
    )
    return EXIT_OK


def _maybe_json(payload: bytes) -> object:
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload.decode("utf-8", errors="replace")


def cmd_restore(ctx: Ctx, args) -> int:
    path = Path(args.file)
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise Fail(f"cannot read {path}: {exc}", EXIT_USAGE) from exc
    except json.JSONDecodeError as exc:
        raise Fail(f"{path} is not JSON: {exc}", EXIT_USAGE) from exc
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("entries"), list):
        raise Fail(f"{path} is not a Kronos backup (no entries list)", EXIT_USAGE)
    summary = {
        "path": str(path),
        "version": snapshot.get("version"),
        "entries": len(snapshot["entries"]),
        "plans": len(snapshot.get("plans") or []),
        "settings": snapshot.get("settings") is not None,
    }
    if ctx.dry_run:
        show_request(
            ctx,
            "POST",
            "/api/restore",
            {
                "version": summary["version"],
                "entries": f"<{summary['entries']} entries>",
                "plans": f"<{summary['plans']} drafts>",
                "settings": "<settings>" if summary["settings"] else None,
            },
        )
        ctx.emit({"dry_run": True, **summary})
        ctx.say(
            f"would restore {summary['entries']} entries, {summary['plans']} drafts"
            f"{' and the settings' if summary['settings'] else ''} from {path} "
            f"(backup version {summary['version']}) onto {ctx.target} — wiping it first"
        )
        return EXIT_OK
    if not args.yes:
        raise Fail(
            f"restore wipes {ctx.target} before loading {path}; add --yes to confirm "
            "(or --dry-run to look first)",
            EXIT_USAGE,
        )
    ctx.guard_write(always=True)
    result = ctx.api.post("/api/restore", snapshot)
    ctx.emit({**summary, **result})
    ctx.say(
        f"restored {result.get('restored_entries', summary['entries'])} entries "
        f"onto {ctx.target} from {path}"
    )
    return EXIT_OK


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def _common(parser: argparse.ArgumentParser, *, write: bool, top: bool = False) -> None:
    """``--target`` / ``--json`` (and ``--dry-run`` on writes) accepted before or after
    the command: the sub-level copies default to SUPPRESS so they never shadow the
    top-level values."""
    default = (lambda v: v) if top else (lambda v: argparse.SUPPRESS)
    parser.add_argument(
        "--target", choices=TARGETS, default=default("local"), help="which Kronos (default: local)"
    )
    parser.add_argument(
        "--json", action="store_true", default=default(False), help="print the API payloads as JSON"
    )
    if write or top:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=default(False),
            help="print the request and the resulting day; write nothing",
        )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kronos",
        description="Read and log days in a running Kronos through its HTTP API.",
        epilog=(
            "examples:\n"
            "  python bin/kronos.py today\n"
            "  python bin/kronos.py log today --start 8:30 --end 16:45 --break 45\n"
            "  python bin/kronos.py log 2026-12-24..2026-12-31 --type vacation --dry-run\n"
            "  python bin/kronos.py --target prod clock in\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _common(p, write=True, top=True)
    sub = p.add_subparsers(dest="command", required=True, metavar="command")

    def add(name: str, func, help: str, *, write: bool = False) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help, description=help)
        _common(sp, write=write)
        sp.set_defaults(func=func)
        return sp

    add("today", cmd_today, "today's day, the week / month / overall balance and the streaks")
    add("balance", cmd_balance, "week, month and cumulative balance")
    days = add("days", cmd_days, "the days of a month (default: this month) or a range")
    days.add_argument("--month", help="YYYY-MM")
    days.add_argument("--from", dest="from_", help="first date")
    days.add_argument("--to", help="last date")
    add("config", cmd_config, "the settings")
    add("check", cmd_check, "GET-only health report against the target (exit 1 on any FAIL)")
    add("targets", cmd_targets, "where local / int / prod point, and where backups go")

    log = add("log", cmd_log, "log a day (or one leave type over several dates)", write=True)
    log.add_argument(
        "dates", nargs="+", metavar="DATE", help="2026-10-27, today, yesterday, or a range A..B"
    )
    log.add_argument("--type", choices=LEAVE_TYPES, help="a leave day (default: a work day)")
    log.add_argument("--start", help="work start, e.g. 8:30")
    log.add_argument("--end", help="work end, e.g. 16:45")
    log.add_argument(
        "--break",
        dest="breaks",
        action="append",
        metavar="BREAK",
        help="45 (minutes) or 13:00-13:45; repeatable",
    )
    log.add_argument(
        "--hours",
        type=float,
        help="hours of leave on a partial day (the rest may carry --start/--end)",
    )
    log.add_argument("--note", help="free text")
    log.add_argument(
        "--replace", action="store_true", help="overwrite the day if it is already logged"
    )

    clock = add("clock", cmd_clock, "clock in / out — the server stamps its own time", write=True)
    clock.add_argument("direction", choices=("in", "out"))
    clock.add_argument("--at", help="a time instead of now, e.g. 8:30 (required with --date)")
    clock.add_argument("--date", help="a day instead of today; needs --at")
    clock.add_argument(
        "--break",
        dest="breaks",
        action="append",
        metavar="BREAK",
        help="(clock out) 45 or 13:00-13:45; repeatable",
    )
    clock.add_argument("--note", help="free text")

    plan = sub.add_parser(
        "plan", help="drafts: show, add, rm, commit", description="The time-off planner."
    )
    _common(plan, write=True)
    plan.set_defaults(func=cmd_plan_show, year=None)
    plan.add_argument("--year", type=int, help="calendar year (default: this one)")
    psub = plan.add_subparsers(dest="plan_command", metavar="action")

    def padd(name: str, func, help: str) -> argparse.ArgumentParser:
        sp = psub.add_parser(name, help=help, description=help)
        _common(sp, write=True)
        sp.set_defaults(func=func)
        return sp

    pa = padd(
        "add", cmd_plan_add, "draft leave on dates (re-drafts existing drafts, skips logged dates)"
    )
    pa.add_argument("dates", nargs="+", metavar="DATE")
    pa.add_argument("--type", choices=PLANNABLE_TYPES, required=True)
    pa.add_argument("--hours", type=float, help="hours of leave for a partial day")
    pa.add_argument("--note", help="free text")
    pr = padd("rm", cmd_plan_rm, "drop drafts")
    pr.add_argument("dates", nargs="+", metavar="DATE")
    pc = padd("commit", cmd_plan_commit, "turn drafts into real entries (a logged date wins)")
    pc.add_argument("dates", nargs="*", metavar="DATE")
    pc.add_argument("--year", type=int, help="every standing draft of the year")

    hol = sub.add_parser("holidays", help="holidays: import", description="Public holidays.")
    _common(hol, write=True)
    hsub = hol.add_subparsers(dest="holidays_command", metavar="action", required=True)
    hi = hsub.add_parser(
        "import",
        help="import a year's public holidays as holiday days",
        description="Import public holidays.",
    )
    _common(hi, write=True)
    hi.set_defaults(func=cmd_holidays_import)
    hi.add_argument("--country", help="ISO code, default: the one in Settings")
    hi.add_argument(
        "--region",
        help="ISO-3166-2 code, e.g. ES-MD; default: the one in Settings ('' for national only)",
    )
    hi.add_argument("--year", type=int, help="default: this year")

    bk = add("backup", cmd_backup, "download a JSON snapshot", write=True)
    bk.add_argument("--out", help="file to write (default: ./kronos_backup_<target>_<date>.json)")
    rs = add(
        "restore", cmd_restore, "wipe the target and load a snapshot (needs --yes)", write=True
    )
    rs.add_argument("file")
    rs.add_argument("--yes", action="store_true", help="confirm: the target is wiped first")

    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(LookupError, ValueError, OSError):
            stream.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = bool(getattr(args, "json", False))
    try:
        url = resolve_target(args.target)
        ctx = Ctx(
            args.target, Api(url, args.target), as_json, bool(getattr(args, "dry_run", False))
        )
        return args.func(ctx, args)
    except ApiError as exc:
        return _fail(as_json, f"{exc.detail}", EXIT_API, status=exc.status)
    except Fail as exc:
        return _fail(as_json, str(exc), exc.code)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # `kronos days | head`: the reader went away, which is not an error of ours.
        with contextlib.suppress(OSError):
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return EXIT_OK


def _fail(as_json: bool, message: str, code: int, status: int | None = None) -> int:
    if as_json:
        doc: dict = {"error": message, "exit": code}
        if status is not None:
            doc["status"] = status
        print(json.dumps(doc, ensure_ascii=False))
    else:
        print(f"kronos: {message}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
