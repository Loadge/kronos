#!/usr/bin/env bash
# Review a Kronos checkout from inside the Taiga sandbox (no Docker, no network).
#
#   bash review_sandbox.sh [<kronos_coding_behaviors folder>] [--e2e] [--serve] [--quick]
#
# The sandbox twin of review_turn.sh: same checks, same flags, same exit code, but it takes a
# plain project folder instead of an archive (default: ./kronos_coding_behaviors if there is
# one, else the checkout this script lives in) and runs with the sandbox's own Python and its
# pre-installed Chromium (PLAYWRIGHT_BROWSERS_PATH, or /opt/pw-browsers). Never touches data/:
# every database it creates lives in a temp dir that is removed at the end.
# Runs: ruff (check + format), pytest (unit/api/integration), an Alembic upgrade/downgrade
# round trip.
#   --e2e    also run tests/e2e with Playwright + Chromium
#   --serve  afterwards, seed a demo DB and serve the app on http://localhost:${REVIEW_PORT:-8799}
#            (Ctrl+C stops it and the temp DB is removed)
#   --quick  skip the checks and only --serve
# Exit code: 0 if every check passed, 1 otherwise.

set -uo pipefail

usage() { sed -n 4,17p "$0"; exit 2; }

E2E=0
SERVE=0
QUICK=0
ROOT=""
for arg in "$@"; do
  case "$arg" in
    --e2e) E2E=1 ;;
    --serve) SERVE=1 ;;
    --quick) QUICK=1; SERVE=1 ;;
    -h|--help) usage ;;
    -*) usage ;;
    *) [ -z "$ROOT" ] && ROOT="$arg" || usage ;;
  esac
done

if [ -z "$ROOT" ]; then
  if [ -f kronos_coding_behaviors/alembic.ini ]; then ROOT=kronos_coding_behaviors
  else ROOT=$(cd "$(dirname "$0")/.." && pwd); fi
fi
[ -d "$ROOT" ] || { echo "!! $ROOT is not a folder"; usage; }
cd "$ROOT" || exit 1
[ -f alembic.ini ] || { echo "!! $PWD has no alembic.ini: is this a kronos_coding_behaviors folder?"; exit 1; }
echo "== Project root: $PWD"

# ── environment ────────────────────────────────────────────────────────────────
export PATH="$HOME/.local/bin:$PATH"
export PYTHONPATH="$PWD/backend"
export PYTHONDONTWRITEBYTECODE=1
export TZ="${TZ:-Europe/Madrid}"
if [ -z "${PLAYWRIGHT_BROWSERS_PATH:-}" ] && [ -d /opt/pw-browsers ]; then
  export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
fi
PY=${PY:-python3}

TMP=$(mktemp -d -t kronos-review-XXXXXX)
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# Dependencies: install only what is missing (the sandbox has no network once it is up).
if ! "$PY" -c "import fastapi, sqlalchemy, alembic, pytest, httpx, ruff" 2>/dev/null; then
  echo "== pip install -r requirements-dev.txt"
  "$PY" -m pip install -q --break-system-packages -r requirements-dev.txt \
    || { echo "!! dependency install failed"; exit 1; }
fi
if [ "$E2E" = 1 ] && ! "$PY" -c "import playwright" 2>/dev/null; then
  echo "!! --e2e needs pytest-playwright and a Chromium: pip install pytest-playwright && playwright install chromium"
  exit 1
fi

declare -A RESULT
run() { local name=$1; shift; echo; echo "== $name: $*"; if "$@"; then RESULT[$name]=PASS; else RESULT[$name]=FAIL; fi; }

migrations() {
  local db="$TMP/migrations.db"
  rm -f "$db"
  DATABASE_URL="sqlite:///$db" bash -c \
    'alembic upgrade head && alembic current && alembic downgrade -1 && alembic upgrade head && alembic current'
}

FAILED=0
if [ "$QUICK" = 0 ]; then
  run ruff ruff check .
  run format ruff format --check .
  run pytest "$PY" -m pytest -q tests/unit tests/api tests/integration
  run migrations migrations
  if [ "$E2E" = 1 ]; then
    run e2e "$PY" -m pytest -q -p no:cacheprovider tests/e2e
  fi

  echo
  echo "== Summary"
  for name in ruff format pytest migrations e2e; do
    [ -n "${RESULT[$name]:-}" ] || continue
    printf '   %-11s %s\n' "$name" "${RESULT[$name]}"
    [ "${RESULT[$name]}" = PASS ] || FAILED=1
  done
fi

if [ "$SERVE" = 1 ]; then
  PORT=${REVIEW_PORT:-8799}
  export KRONOS_DATA_DIR="$TMP/data"
  mkdir -p "$KRONOS_DATA_DIR"
  echo
  echo "== Seeding a demo DB in $KRONOS_DATA_DIR and serving on http://localhost:$PORT (Ctrl+C to stop)"
  alembic upgrade head >/dev/null && "$PY" backend/seed.py >/dev/null \
    || { echo "!! could not prepare the demo DB"; exit 1; }
  "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --app-dir backend
fi
exit $FAILED
