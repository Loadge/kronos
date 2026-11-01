"""Alembic runtime environment.

Imports `app.database.Base` and `app.models` to register ORM metadata for autogenerate,
and pulls the database URL from `app.config.DATABASE_URL` so env vars win over alembic.ini.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app import models  # noqa: E402, F401 — register models on Base.metadata
from app.config import DATABASE_URL  # noqa: E402
from app.database import Base  # noqa: E402

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# A caller that already holds a connection (the test that diffs the migrations against
# the models runs Alembic in-process) hands it over in ``config.attributes`` — the
# documented way — and keeps its own logging; the CLI configures logging from the ini.
_shared_connection = config.attributes.get("connection")

if config.config_file_name is not None and _shared_connection is None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _migrate(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # SQLite-safe ALTERs
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if _shared_connection is not None:
        _migrate(_shared_connection)
        return
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _migrate(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
