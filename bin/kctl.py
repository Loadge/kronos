#!/usr/bin/env python
"""kctl — the lever an agent pulls to drive a disposable Kronos.

Why this exists
---------------
Kronos normally runs against `data/kronos.db` — the real database, which an
agent verifying a change must not touch. `kctl` hands the agent an
environment it can treat without care: a fresh SQLite database in a
throwaway temp dir, a fixed port, an optional deterministic seed, and a
screenshot command for seeing the result.

Usage
-----
    python bin/kctl.py up --seed          # fresh instance on a temp DB + sample data
    python bin/kctl.py status
    python bin/kctl.py api GET /api/analytics/monthly
    python bin/kctl.py shot /#analytics --out .artifacts/kctl-analytics.png
    python bin/kctl.py logs --lines 40
    python bin/kctl.py down               # kill the instance, delete the temp dir

Every instance uses `sqlite:///<tmp>/kronos.db` with `<tmp>` from
`tempfile.mkdtemp(prefix="kctl-")`. The caller's DATABASE_URL is never read,
and `down` (or `up`, clearing a dead instance's leftovers) refuses to
delete anything that is not a `kctl-*` directory inside the system temp dir.
A pid is only killed while it is still the process kctl started (pid plus
creation time), never a stranger that inherited the number.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO / "backend"
STATE_DIR = REPO / ".kctl"
STATE_FILE = STATE_DIR / "state.json"
APP_LOG = STATE_DIR / "app.log"

PORT = int(os.getenv("KCTL_PORT", "8796"))
URL = f"http://127.0.0.1:{PORT}"

UP_HINT = "python bin/kctl.py up --seed"

# A screenshot is for *seeing* a change, so only the two viewports that
# matter: the layout an agent tests and the narrow one it must not break.
VIEWPORTS = {
    "desktop": (1280, 900),
    "phone": (390, 844),
}


class Fail(Exception):
    """An error whose message already tells the agent what to do next."""


# --------------------------------------------------------------------------
# process + state
# --------------------------------------------------------------------------


def read_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def write_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def process_started(pid: int) -> str | None:
    """When the live process `pid` was created, or None if there is none.

    A pid alone does not identify a process: the OS recycles it, and after a
    reboot or power cut state.json can name an unrelated process (2026-10-01:
    pid 45560 survived a power cut). The pid *and* its creation time together
    cannot match a stranger, so that pair is what state.json records.
    """
    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            # An exited process lingers while anyone holds a handle to it.
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                return None  # 259 = STILL_ACTIVE
            created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
            if not k32.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                return None
            return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
        finally:
            k32.CloseHandle(handle)
    out = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return out or None


def pid_alive(pid: int, started: str | None) -> bool:
    """True only while `pid` is still the process kctl spawned at `started`."""
    return started is not None and process_started(pid) == started


def kill_pid(pid: int, started: str | None) -> None:
    """Kill the process and its children — only if it is still ours."""
    if not pid_alive(pid, started):
        return
    if os.name == "nt":
        # /T because a child (alembic, seed) may still be owned by the tree.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
        )
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    for _ in range(20):
        if not pid_alive(pid, started):
            return
        time.sleep(0.25)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(os.getpgid(pid), signal.SIGKILL)


def spawn(env: dict, log_path: Path) -> tuple[int, str | None]:
    """Start uvicorn from backend/, detached, logging to `log_path`.

    Returns the pid and its creation time — the pair `pid_alive` checks.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("w", encoding="utf-8", errors="replace")
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "--no-access-log",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        **kwargs,
    )
    return proc.pid, process_started(proc.pid)


def ensure_port_free(port: int, timeout: float = 5.0) -> None:
    """Refuse to start on a port something else already holds.

    Otherwise `wait_healthy` takes the squatter's answer on /healthz for ours
    and reports success while our server has died on bind (WinError 10048).
    The test is the same bind uvicorn is about to do, so it fails exactly when
    uvicorn would; the retries give a process just killed time to let go.
    """
    deadline = time.time() + timeout
    while True:
        with socket.socket() as sock:
            if os.name != "nt":
                # As uvicorn does — a port in TIME_WAIT is free to it.
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return
            except OSError:
                pass
        if time.time() >= deadline:
            raise Fail(
                f"port {port} is already in use by a process kctl did not start. "
                f"Stop it, or run kctl on another port with KCTL_PORT=<n>."
            )
        time.sleep(0.25)


def wait_healthy(url: str, pid: int, started: str | None, log_path: Path, timeout: float) -> None:
    """Poll <url>/healthz until it answers, or explain why it never will."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not pid_alive(pid, started):
            tail = tail_file(log_path, 25)
            raise Fail(f"{url} died during startup. Last output:\n{tail}\nFull log: {log_path}")
        try:
            with urllib.request.urlopen(f"{url}/healthz", timeout=2) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.4)
    raise Fail(
        f"{url} did not answer /healthz within {timeout:.0f}s. "
        f"Check {log_path}, then run: python bin/kctl.py down"
    )


def tail_file(path: Path, lines: int) -> str:
    if not path.exists():
        return "(no log yet)"
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:]) or "(log is empty)"


# --------------------------------------------------------------------------
# http
# --------------------------------------------------------------------------


def opener() -> urllib.request.OpenerDirector:
    op = urllib.request.build_opener()
    op.addheaders = [("User-Agent", "kctl")]
    return op


def app_path(raw: str) -> str:
    """Undo Git Bash's MSYS path conversion on an app path.

    In Git Bash an argument that looks like a POSIX absolute path is rewritten
    into a Windows one *before this process ever sees it*: `/api/entries`
    arrives as `C:/Program Files/Git/api/entries`, and a bare `/` as
    `C:/Program Files/Git`. Every caller on this machine would otherwise have to
    remember `MSYS_NO_PATHCONV=1`, and the failure it produces (`InvalidURL`)
    points at the URL rather than at the shell.

    Recovery is deterministic because an app path always starts with one of the
    known roots below, or is `/`.
    """
    if not re.match(r"^[A-Za-z]:[\\/]", raw):
        return raw if raw.startswith("/") else "/" + raw
    unix = raw.replace("\\", "/")
    for marker in ("/api/", "/healthz", "/static/", "/sw.js", "/manifest.json", "/#"):
        index = unix.find(marker)
        if index != -1:
            return unix[index:]
    return "/"


def request(
    op: urllib.request.OpenerDirector,
    method: str,
    path: str,
    body: bytes | None = None,
    content_type: str | None = None,
) -> tuple[int, bytes]:
    url = path if path.startswith("http") else f"{URL}{app_path(path)}"
    req = urllib.request.Request(url, data=body, method=method.upper())
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with op.open(req, timeout=60) as resp:
            payload = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        status = exc.code
    except urllib.error.URLError as exc:
        raise Fail(
            f"cannot reach {url} ({exc.reason}) — no instance is up. Run: {UP_HINT}"
        ) from exc
    return status, payload


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def migrate(env: dict) -> None:
    """Apply alembic migrations to the throwaway DB (args mirror live_server)."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise Fail(f"alembic upgrade head failed:\n{(result.stderr or result.stdout).strip()}")


def seed(env: dict) -> None:
    result = subprocess.run(
        [sys.executable, "backend/seed.py"],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise Fail(f"seed failed:\n{(result.stderr or result.stdout).strip()}")


def cmd_up(args) -> int:
    state = read_state()
    if state.get("pid") and pid_alive(state["pid"], state.get("started")):
        raise Fail(
            f"an instance is already running (pid {state['pid']}, {state.get('url')}). "
            f"kctl never reuses an instance — a fresh DB is what makes runs reproducible. "
            f"Run: python bin/kctl.py down"
        )
    # The instance in state is dead (reboot, power cut, crash) but its temp dir
    # is not: clean it now, or overwriting state.json orphans it for good.
    if state.get("data_dir"):
        delete_data_dir(state["data_dir"])
    ensure_port_free(PORT)

    # Fresh throwaway data dir. KRONOS_DATA_DIR goes with it so the server
    # never mkdirs the repo's real data/ either.
    data_dir = Path(tempfile.mkdtemp(prefix="kctl-"))
    db_url = f"sqlite:///{(data_dir / 'kronos.db').as_posix()}"
    env = {
        **os.environ,
        "DATABASE_URL": db_url,
        "KRONOS_DATA_DIR": str(data_dir),
        "PYTHONPATH": str(BACKEND_DIR),
        # Captured pipes fall back to the locale codepage (cp1252 here), where
        # seed.py's "→" cannot encode. Force UTF-8 on every child's stdio.
        "PYTHONIOENCODING": "utf-8",
    }
    pid, started = 0, None
    try:
        migrate(env)
        if args.seed:
            seed(env)
        pid, started = spawn(env, APP_LOG)
        wait_healthy(URL, pid, started, APP_LOG, timeout=60)
    except Fail:
        if pid:
            kill_pid(pid, started)
        shutil.rmtree(data_dir, ignore_errors=True)
        raise

    state = {
        "pid": pid,
        "started": started,
        "port": PORT,
        "url": URL,
        "data_dir": str(data_dir),
        "seeded": bool(args.seed),
    }
    write_state(state)
    if args.json:
        print(json.dumps(state, indent=2))
    else:
        print(URL)
    return 0


def delete_data_dir(raw: str) -> None:
    """Delete a throwaway data dir — only if it is unambiguously one of ours.

    A refusal is a warning, not a failure: a dir the guard rejects is not one
    kctl made, so leaving it orphans nothing. Raising here kept the bad
    state.json in place, and with it every later `up` and `down` failed too.
    """
    path = Path(raw)
    resolved = path.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not path.name.startswith("kctl-"):
        reason = "its name does not start with 'kctl-'"
    elif temp_root not in resolved.parents:
        reason = f"it is not inside {temp_root}"
    else:
        shutil.rmtree(resolved, ignore_errors=True)
        return
    print(f"kctl: warning: left {path} alone ({reason}); forgot it", file=sys.stderr)


def cmd_down(args) -> int:
    state = read_state()
    stopped = False
    pid = state.get("pid")
    if pid and pid_alive(pid, state.get("started")):
        kill_pid(pid, state.get("started"))
        stopped = True
    if state.get("data_dir"):
        delete_data_dir(state["data_dir"])
    STATE_FILE.unlink(missing_ok=True)
    if args.json:
        print(json.dumps({"stopped": stopped, "data_dir": state.get("data_dir")}))
    else:
        print("stopped" + (f" pid {pid}" if stopped else " (nothing was running)"))
    return 0


def cmd_status(args) -> int:
    state = read_state()
    pid = state.get("pid") or 0
    up = bool(pid) and pid_alive(pid, state.get("started"))
    info = {
        "url": state.get("url") if up else None,
        "pid": pid if up else None,
        "data_dir": state.get("data_dir"),
        "seeded": state.get("seeded"),
        "up": up,
    }
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(f"url       {state.get('url') or '-'}")
        print(f"pid       {pid or '-'} ({'alive' if up else 'not running'})")
        print(f"data_dir  {state.get('data_dir') or '-'}")
        print(f"seeded    {state.get('seeded')}")
        if not up:
            print(f"down — start with: {UP_HINT}")
    return 0 if up else 1


def cmd_api(args) -> int:
    body, ctype = None, None
    if args.data is not None:
        body = args.data.encode()
        ctype = "application/json"
    status, payload = request(opener(), args.method, args.path, body, ctype)
    text = payload.decode(errors="replace")
    try:
        print(json.dumps(json.loads(text), indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print(text)
    print(f"HTTP {status} {args.method.upper()} {app_path(args.path)}", file=sys.stderr)
    return 0 if 200 <= status < 300 else 1


def cmd_shot(args) -> int:
    state = read_state()
    pid = state.get("pid")
    if not (pid and pid_alive(pid, state.get("started"))):
        raise Fail(f"no instance is up. Run: {UP_HINT}")
    url = state.get("url") or URL

    out = Path(args.out)
    if not out.is_absolute():
        out = REPO / out
    out.parent.mkdir(parents=True, exist_ok=True)

    # Playwright is only needed here — keep it out of the module imports so
    # the other commands work without it installed.
    from playwright.sync_api import sync_playwright

    errors: list[str] = []
    width, height = VIEWPORTS[args.viewport]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(
                locale="en-GB",
                color_scheme=args.theme,
                viewport={"width": width, "height": height},
            )
            page = context.new_page()
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(f"{url}{app_path(args.path)}", wait_until="networkidle")
            page.wait_for_timeout(500)
            page.screenshot(path=str(out), full_page=True)
        finally:
            browser.close()

    print(str(out))
    for err in errors:
        print(f"page error: {err}", file=sys.stderr)
    return 1 if errors else 0


def cmd_logs(args) -> int:
    print(tail_file(APP_LOG, args.lines))
    return 0


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kctl",
        description="Drive a disposable Kronos so an agent can verify its own work.",
        epilog=(
            "Typical loop:\n"
            "  python bin/kctl.py up --seed\n"
            "  python bin/kctl.py api GET /api/analytics/monthly\n"
            "  python bin/kctl.py shot /#analytics --out .artifacts/kctl-analytics.png\n"
            "  python bin/kctl.py down\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)

    up = sub.add_parser("up", help="start a fresh instance on a throwaway temp DB")
    up.add_argument("--seed", action="store_true", help="populate it with ~3 months of sample data")
    up.add_argument("--json", action="store_true")
    up.set_defaults(func=cmd_up)

    down = sub.add_parser("down", help="stop the instance and delete its temp data dir")
    down.add_argument("--json", action="store_true")
    down.set_defaults(func=cmd_down)

    st = sub.add_parser("status", help="is an instance up, and where its data lives")
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=cmd_status)

    api = sub.add_parser("api", help="send a request to the running instance")
    api.add_argument("method", help="GET, POST, PUT, PATCH, DELETE")
    api.add_argument("path", help="e.g. /api/analytics/monthly")
    api.add_argument("--data", help="JSON request body")
    api.set_defaults(func=cmd_api)

    shot = sub.add_parser("shot", help="screenshot a page of the running instance")
    shot.add_argument("path", help="app path, e.g. / or /#analytics")
    shot.add_argument(
        "--out",
        required=True,
        help="output .png (relative paths resolve against the repo root)",
    )
    shot.add_argument("--viewport", default="desktop", choices=sorted(VIEWPORTS))
    shot.add_argument("--theme", default="dark", choices=("dark", "light"))
    shot.add_argument("--json", action="store_true")
    shot.set_defaults(func=cmd_shot)

    logs = sub.add_parser("logs", help="tail the instance's output")
    logs.add_argument("--lines", type=int, default=40)
    logs.set_defaults(func=cmd_logs)

    return p


def main() -> int:
    # kctl output feeds other agents: keep it UTF-8 even when piped, where
    # Python would otherwise fall back to the locale codepage (cp1252 here).
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(LookupError, ValueError, OSError):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except Fail as exc:
        print(f"kctl: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
