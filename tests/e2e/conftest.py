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
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

# ── helpers ───────────────────────────────────────────────────────────────────

BACKEND_DIR = Path(__file__).parent.parent.parent / "backend"
DEMO_NOW = "2026-11-04T10:12:00+01:00"  # the day docs/demo/seed_demo.py was made for


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


# ── Playwright page fixtures ───────────────────────────────────────────────────


@pytest.fixture(scope="session")
def browser_context_args():
    """Default browser context options shared across all E2E tests."""
    return {
        "viewport": {"width": 1280, "height": 800},
        "locale": "en-GB",
    }
