"""Repository rules that are cheap to enforce and expensive to forget.

* The code never mentions phase numbers — managerial detail lives in ``docs/``.
* The ORM models and the Alembic migrations describe the same schema: running every
  migration on an empty database must leave nothing for autogenerate to add.
* No file mixes line endings (the repo is CRLF, a few scripts are deliberately LF).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.database import Base
from sqlalchemy import create_engine

REPO = Path(__file__).resolve().parents[2]
CODE_DIRS = ("backend", "alembic", "tests", "bin")
CODE_SUFFIXES = {".py", ".js", ".css", ".html", ".sh", ".toml", ".ini", ".mako"}


def _code_files():
    for d in CODE_DIRS:
        for p in (REPO / d).rglob("*"):
            if (
                p.suffix in CODE_SUFFIXES
                and "vendor" not in p.parts
                and "__pycache__" not in p.parts
            ):
                yield p


class TestPhaseNumbersStayInDocs:
    def test_no_phase_numbers_in_code(self):
        pattern = re.compile(r"\bPhase \d+")
        offenders = []
        for p in _code_files():
            if p == Path(__file__):
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{p.relative_to(REPO)}:{i}: {line.strip()}")
        assert not offenders, "phase numbers belong in docs/, not in code:\n" + "\n".join(offenders)


class TestLineEndings:
    def test_no_file_mixes_line_endings(self):
        mixed = []
        for p in _code_files():
            raw = p.read_bytes()
            crlf = raw.count(b"\r\n")
            lf = raw.count(b"\n") - crlf
            if crlf and lf:
                mixed.append(f"{p.relative_to(REPO)} ({crlf} CRLF, {lf} LF)")
        assert not mixed, "mixed line endings:\n" + "\n".join(mixed)


class TestMigrationsMatchModels:
    def test_upgrade_head_matches_metadata(self):
        """Apply every migration to a fresh file and diff against the models."""
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "kronos.db"
            env = {**os.environ, "DATABASE_URL": f"sqlite:///{db.as_posix()}"}
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=REPO,
                env=env,
                check=True,
                capture_output=True,
            )
            engine = create_engine(f"sqlite:///{db.as_posix()}")
            with engine.connect() as conn:
                ctx = MigrationContext.configure(conn)
                diff = compare_metadata(ctx, Base.metadata)
            engine.dispose()
        assert diff == [], "models and migrations differ — write a migration:\n" + "\n".join(
            str(d) for d in diff
        )
