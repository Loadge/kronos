"""Shared test fixtures.

Each test gets a fresh in-memory SQLite (StaticPool so all connections share one DB).
The `get_session` dependency is overridden so the app reads/writes through that engine.
No test touches the real on-disk SQLite file.
"""

from __future__ import annotations

import os

# Force in-memory DB *before* any app import (the module-level engine would otherwise
# try to create data/kronos.db on disk as an import side-effect).
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from collections.abc import Callable, Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_session  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(db_engine) -> Iterator[Session]:
    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_engine) -> Iterator[TestClient]:
    SessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)

    def _override_get_session() -> Iterator[Session]:
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _override_get_session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


# ---------- builders -------------------------------------------------------


@pytest.fixture
def work_body() -> Callable[..., dict]:
    """Factory: returns a valid work-day POST body with sensible defaults."""

    def _build(
        date: str = "2026-04-14",
        start: str = "09:00",
        end: str = "17:00",
        breaks_min: tuple[int, ...] = (60,),
        notes: str | None = None,
    ) -> dict:
        body: dict = {
            "date": date,
            "day_type": "work",
            "start_time": start,
            "end_time": end,
            "breaks": [{"break_minutes": m} for m in breaks_min],
        }
        if notes is not None:
            body["notes"] = notes
        return body

    return _build
