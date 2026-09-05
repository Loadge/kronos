#!/usr/bin/env bash
# deploy-staging.sh — build + run Kronos locally on this workstation's own
# Docker Desktop engine, as a staging/integration environment separate from
# the production deployment on DockerusMaximus (see deploy.sh).
#
# No SSH, no remote sync — everything happens against the local Docker
# engine, in the current working tree. Isolated from prod by container name
# (kronos-staging) and volume (kronos-staging-data); see
# docker-compose.staging.yml.
#
# Usage (from project root, in Git Bash):
#   bash deploy-staging.sh

set -euo pipefail

CONTAINER="kronos-staging"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.staging.yml)

# ── guards ────────────────────────────────────────────────────────────────────
if [[ ! -f "Dockerfile" ]]; then
  echo "✗  Run this script from the project root (where Dockerfile lives)." >&2
  exit 1
fi

# ── 1. local tests (non-fatal — warn and continue if pytest is unavailable) ───
echo "▸ Running tests…"
if ! command -v python &>/dev/null; then
  echo "⚠  python is not on PATH — tests were SKIPPED, not run. Deploying unverified."
else
  rc=0
  python -m pytest tests/ -q --tb=short || rc=$?
  case $rc in
    0) echo "✓ Tests passed" ;;
    5) echo "⚠  pytest collected NO tests — that is not a pass. Deploying unverified." ;;
    *) echo "⚠  Tests FAILED (pytest exit $rc) — deploying anyway (staging is where you're supposed to catch this)" ;;
  esac
fi

# ── 2. build + (re)create the staging container ────────────────────────────────
echo "▸ Building image and recreating the staging container…"
"${COMPOSE[@]}" up -d --build --force-recreate
docker image prune -f > /dev/null
echo "✓ Container recreated"

# ── 3. verify the new container is healthy ────────────────────────────────────
echo "▸ Waiting for health check…"
for i in $(seq 1 12); do
  STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo 'starting')
  if [[ "$STATUS" == "healthy" ]]; then
    echo "✓ Container is healthy"
    break
  fi
  if [[ "$i" -eq 12 ]]; then
    echo "⚠  Container did not reach healthy state after 60 s — check: docker logs $CONTAINER"
  fi
  sleep 5
done

# ── done ──────────────────────────────────────────────────────────────────────
echo ""
echo "🚀  http://localhost:${APP_PORT:-8765}  (staging — separate volume from prod, local to this workstation)"
