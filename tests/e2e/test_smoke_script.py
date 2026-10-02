"""E2E: the smoke script itself (bin/smoke.py).

Why this exists
---------------
deploy.sh runs `python bin/smoke.py <url>` after every deploy and trusts its
exit code: non-zero means the deploy is bad. That contract only means anything
if the script can actually go *red* — a smoke test that could never fail is
indistinguishable from no check at all. These tests pin both directions:

  * against the live server fixture, every check passes and the exit code is 0;
  * against a free port with nothing listening, the exit code is 1 and the
    output contains FAIL lines.
"""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 120  # seconds


def _free_port() -> int:
    """Same trick as conftest._find_free_port(): bind port 0, ask the kernel."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_smoke_passes_against_live_server(base_url: str) -> None:
    result = subprocess.run(
        [sys.executable, "bin/smoke.py", base_url],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 0, (
        f"smoke exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "checks passed" in result.stdout
    assert "FAIL" not in result.stdout


def test_smoke_fails_against_dead_port() -> None:
    port = _free_port()
    result = subprocess.run(
        [sys.executable, "bin/smoke.py", f"http://127.0.0.1:{port}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    assert result.returncode == 1, (
        f"smoke exited {result.returncode}, expected 1\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert "FAIL" in result.stdout
