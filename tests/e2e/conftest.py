"""Playwright E2E fixtures.

A session-scoped live server is started once for the entire E2E suite.
It uses a temporary SQLite file (not :memory:, because uvicorn runs in a
subprocess) so each test module starts against a real, isolated database.

Usage
-----
Run the suite explicitly (excluded from the default `make test` run):

    pytest tests/e2e -v --headed          # visible browser
    pytest tests/e2e -v                   # headless (CI-friendly)

Prerequisites
-------------
    pip install pytest-playwright
    playwright install chromium            # first time only
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Browser
from pytest_playwright_visual_snapshot.plugin import SnapshotPaths

# The address of each tab id: the page where days are logged is #days (id "log"), the weekly one
# is #weeks (id "days"), the year charts are #year (id "analytics"). Tests looping over ids use it.
HASH_OF = {"log": "days", "days": "weeks", "analytics": "year"}

# Weeks opens only the current week's rows. A test with fixed dates opens them all, so it does not
# depend on which week the suite runs in.
OPEN_ALL_WEEKS = (
    "async () => { const d = Alpine.$data(document.querySelector('main'));"
    " for (let i = 0; i < 50 && !d.entries.length; i++) await new Promise(r => setTimeout(r, 100));"
    " d.daysWeeksSetAll(true); }"
)

# ── helpers ───────────────────────────────────────────────────────────────────

BACKEND_DIR = Path(__file__).parent.parent.parent / "backend"
DEMO_NOW = "2026-11-04T10:12:00+01:00"  # the day docs/demo/seed_demo.py was made for


# httpx gives a server 5 seconds; a runner with eight workers has taken longer than that to answer a
# fixture. A slow answer is not a failed test, so the clients of this suite wait longer.
_client_init = httpx.Client.__init__


def _patient_client(self, *args, **kwargs):
    kwargs.setdefault("timeout", 30)
    _client_init(self, *args, **kwargs)


httpx.Client.__init__ = _patient_client


def _find_free_port() -> int:
    """Return a free TCP port (best-effort)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: float = 15.0) -> None:
    """Block until the server is accepting connections or raise TimeoutError."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"Server on port {port} did not start within {timeout}s")


# ── the snapshot plugin under xdist ───────────────────────────────────────────


def pytest_configure(config):
    """Empty the picture diffs once, before the workers start."""
    if not hasattr(config, "workerinput"):
        shutil.rmtree(config.getini("playwright_visual_snapshot_failures_path"), ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def cleanup_snapshot_failures(pytestconfig):
    """Replaces the plugin's fixture, which empties the folder in every worker: one worker
    deleting it while another creates it fills a run with FileExistsError, and could wipe the
    diffs of a test that has already failed. It only sets the paths here."""
    SnapshotPaths.snapshots_path = Path(pytestconfig.getini("playwright_visual_snapshots_path"))
    SnapshotPaths.failures_path = Path(
        pytestconfig.getini("playwright_visual_snapshot_failures_path")
    )
    SnapshotPaths.failures_path.mkdir(parents=True, exist_ok=True)


# ── the logo's callout ────────────────────────────────────────────────────────

# "New: press the logo to spin through your year" shows once per browser, 1.2 s after a first load.
# Every context of the suite has seen it already, so no test, picture or aria snapshot meets it
# unless it asks: the callout tests remove the key themselves (tests/e2e/test_v51_notes.py).
DIAL_HINT_SEEN = (
    "try { localStorage.setItem('k-dial-hint', '1'); "
    "if (!localStorage.getItem('k-locale-hint-test')) localStorage.setItem('k-locale-hint', '1'); "
    "} catch (e) {}"
)


@pytest.fixture(scope="session", autouse=True)
def _dial_hint_seen():
    """An init script on every context the suite makes, whoever makes it (the `context` fixture or a
    `browser.new_context(...)` in a test): the key is in place before the page's own script runs."""
    new_context = Browser.new_context

    def with_the_key(self, *args, **kwargs):
        context = new_context(self, *args, **kwargs)
        context.add_init_script(DIAL_HINT_SEEN)
        return context

    Browser.new_context = with_the_key
    try:
        yield
    finally:
        Browser.new_context = new_context


# ── server fixture ────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def live_server():
    """Start a real uvicorn process for the full E2E session.

    Yields the base URL (e.g. ``http://127.0.0.1:54321``).
    The server is terminated when the session ends. Each test session picks a
    free port so multiple e2e runs (e.g. parallel local + CI, or two agents
    working on different test files) can run at once without colliding.
    """
    port = _find_free_port()
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_file:
        db_path = db_file.name

    db_url = f"sqlite:///{db_path}"

    env = {
        **os.environ,
        "DATABASE_URL": db_url,
        "PYTHONPATH": str(BACKEND_DIR),
        # never the ECB from a test: GET /api/fx answers "unavailable"
        "KRONOS_FX_URL": "",
    }

    # Run alembic migrations against the temp DB before starting the server
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_DIR.parent),  # project root where alembic.ini lives
        env=env,
        check=True,
        capture_output=True,
    )

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        cwd=str(BACKEND_DIR),
        env=env,
    )

    try:
        _wait_for_server(port)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        Path(db_path).unlink(missing_ok=True)


@pytest.fixture(scope="session")
def base_url(live_server):
    """Alias for live_server — matches the name Playwright's browser fixture expects."""
    return live_server


@pytest.fixture(scope="session")
def demo_url():
    """A Kronos of its own for the tests that need the same page every day: the demo data, with
    "now" frozen on the server (a test freezes the browser's clock with `DEMO_NOW` too)."""
    port = _find_free_port()
    repo_root = BACKEND_DIR.parent
    with tempfile.TemporaryDirectory() as data_dir:
        env = {
            **os.environ,
            "KRONOS_DATA_DIR": data_dir,
            "KRONOS_NOW": DEMO_NOW,
            "KRONOS_FX_URL": "",
            "PYTHONPATH": str(BACKEND_DIR),
            "TZ": "Europe/Madrid",
        }
        env.pop("DATABASE_URL", None)
        run = {"cwd": str(repo_root), "env": env, "check": True, "capture_output": True}
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], **run)
        subprocess.run([sys.executable, "docs/demo/seed_demo.py"], **run)
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1"]
            + ["--port", str(port), "--no-access-log"],
            cwd=str(BACKEND_DIR),
            env=env,
        )
        try:
            _wait_for_server(port)
            yield f"http://127.0.0.1:{port}"
        finally:
            proc.terminate()
            proc.wait(timeout=10)


# ── the number format of a server, for the length of a test ───────────────────────────────────


def _number_format(url: str, tag: str):
    httpx.put(f"{url}/api/config", json={"number_format": tag}).raise_for_status()
    try:
        yield
    finally:
        httpx.put(f"{url}/api/config", json={"number_format": "en-US"}).raise_for_status()


@pytest.fixture
def es_numbers(base_url):
    """The shared server writes numbers the Spanish way (1.234,56) until the test ends. The
    Calculator's Spanish decimals are tested under it."""
    yield from _number_format(base_url, "es-ES")


@pytest.fixture
def es_numbers_demo(demo_url):
    """The same for the demo server."""
    yield from _number_format(demo_url, "es-ES")


# ── Playwright page fixtures ───────────────────────────────────────────────────


@pytest.fixture(scope="session")
def browser_context_args():
    """Default browser context options shared across all E2E tests."""
    return {
        "viewport": {"width": 1280, "height": 800},
        "locale": "en-GB",
    }
