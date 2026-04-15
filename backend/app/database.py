"""SQLAlchemy engine + session factory. SQLite is configured with WAL + FK enforcement."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATA_DIR, DATABASE_URL


def _make_engine(url: str) -> Engine:
    is_sqlite = url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(url, connect_args=connect_args, future=True)

    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - thin wiring
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


# Ensure the data directory exists for file-backed SQLite URLs.
if DATABASE_URL.startswith("sqlite") and ":memory:" not in DATABASE_URL:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

engine: Engine = _make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yields a session, closes on request teardown."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
