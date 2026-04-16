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
E2E_PORT = 8998


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

    Yields the base URL (e.g. ``http://127.0.0.1:8998``).
    The server is terminated when the session ends.
    """
    port = E2E_PORT
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = db_file.name
    db_file.close()

    db_url = f"sqlite:///{db_path}"

    env = {
        **os.environ,
        "DATABASE_URL": db_url,
        "PYTHONPATH": str(BACKEND_DIR),
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
            sys.executable, "-m", "uvicorn",
            "app.main:app",
            "--host", "127.0.0.1",
            "--port", str(port),
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


# ── Playwright page fixtures ───────────────────────────────────────────────────


@pytest.fixture(scope="session")
def browser_context_args():
    """Default browser context options shared across all E2E tests."""
    return {
        "viewport": {"width": 1280, "height": 800},
        "locale": "en-GB",
    }
