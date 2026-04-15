"""Runtime configuration. All overrides via env vars."""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
REPO_ROOT = BACKEND_DIR.parent

DATA_DIR = Path(os.getenv("KRONOS_DATA_DIR", str(REPO_ROOT / "data")))
DB_PATH = DATA_DIR / "kronos.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}")

TIMEZONE = os.getenv("TZ", "Europe/Madrid")

STATIC_DIR = BACKEND_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"

# Default fallbacks; real values live in the `settings` table and are editable via API.
DEFAULT_DAILY_TARGET_HOURS = 8.0
DEFAULT_CUMULATIVE_START_DATE = "2025-01-01"
