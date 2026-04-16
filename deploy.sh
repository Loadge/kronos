#!/usr/bin/env bash
# deploy.sh — sync + rebuild Kronos on Dockerusmaximus
#
# Usage (from project root, in Git Bash or WSL):
#   bash deploy.sh
#
# Requirements: ssh, rsync (both ship with Git for Windows / WSL)

set -euo pipefail

HOST="root@dockerusmaximus.nutello.cc"
REMOTE="/opt/kronos"
IMAGE="kronos:latest"

# ── guards ────────────────────────────────────────────────────────────────────
if [[ ! -f "Dockerfile" ]]; then
  echo "✗  Run this script from the project root (where Dockerfile lives)." >&2
  exit 1
fi

# ── 1. local tests ────────────────────────────────────────────────────────────
echo "▸ Running tests…"
python -m pytest tests/ -q --tb=short
echo "✓ Tests passed"

# ── 2. sync files ─────────────────────────────────────────────────────────────
echo "▸ Syncing files to $HOST:$REMOTE…"
tar czf - \
  --exclude='./.git' \
  --exclude='./__pycache__' \
  --exclude='./.pytest_cache' \
  --exclude='./data' \
  --exclude='./*.db' \
  --exclude='./*.db-wal' \
  --exclude='./*.db-shm' \
  --exclude='*/__pycache__' \
  --exclude='*/*.pyc' \
  . \
| ssh "$HOST" "mkdir -p $REMOTE && tar xzf - -C $REMOTE"
echo "✓ Files synced"

# ── 3. rebuild image + restart container ─────────────────────────────────────
echo "▸ Rebuilding image on remote…"
ssh "$HOST" bash <<REMOTE
  set -euo pipefail
  cd "$REMOTE"
  docker build -t $IMAGE --target runtime . --quiet
  docker compose up -d
  docker image prune -f --filter "label!=keep" > /dev/null
REMOTE
echo "✓ Container restarted"

# ── done ──────────────────────────────────────────────────────────────────────
echo ""
echo "🚀  https://kronos.nutello.cc"
