#!/usr/bin/env bash
# deploy.sh — sync + rebuild Kronos on the Docker host
#
# Usage (from project root, in Git Bash or WSL):
#   bash deploy.sh
#
# Where it deploys is NOT in this file (the repo is public). Set these in a
# git-ignored `deploy.env` next to this script (see deploy.env.example), or in
# the environment (CI variables):
#   DEPLOY_HOST        ssh host or ~/.ssh/config alias of the Docker host
#   DEPLOY_PATH        directory on that host holding the compose project
#   DEPLOY_URL         URL the smoke test hits once the container is up
#   DEPLOY_CONTAINER   container name (optional, default: kronos)

set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
[[ -f "$DEPLOY_DIR/deploy.env" ]] && source "$DEPLOY_DIR/deploy.env"
: "${DEPLOY_HOST:?DEPLOY_HOST is not set - put it in deploy.env or the environment}"
: "${DEPLOY_PATH:?DEPLOY_PATH is not set - put it in deploy.env or the environment}"
: "${DEPLOY_URL:?DEPLOY_URL is not set - put it in deploy.env or the environment}"
HOST="$DEPLOY_HOST"
REMOTE="$DEPLOY_PATH"
URL="$DEPLOY_URL"
CONTAINER="${DEPLOY_CONTAINER:-kronos}"

# ── guards ────────────────────────────────────────────────────────────────────
if [[ ! -f "Dockerfile" ]]; then
  echo "✗  Run this script from the project root (where Dockerfile lives)." >&2
  exit 1
fi

# ── 1. local tests (fast pre-check — the real gate is the Dockerfile) ─────────
# The image build runs the same suite and refuses to produce an image on any
# failure, so a red run here can never deploy. Stopping now just fails in
# seconds instead of after syncing a broken tree to $REMOTE.
echo "▸ Running tests…"
if ! command -v python &>/dev/null; then
  echo "⚠  python is not on PATH — local tests SKIPPED. The image build will still run them."
else
  rc=0
  python -m pytest tests/ -q --tb=short || rc=$?
  case $rc in
    0) echo "✓ Tests passed" ;;
    # Exit 5 is "collected nothing". It is the dangerous one: no failures to
    # read, and indistinguishable from a pass unless you say so out loud.
    5) echo "✗  pytest collected NO tests — that is not a pass. Aborting." >&2; exit 1 ;;
    *) echo "✗  Tests FAILED (pytest exit $rc) — aborting, nothing synced." >&2; exit 1 ;;
  esac

  # E2E is NOT covered by the Dockerfile gate (no browser in the image), so this
  # local run is its only gate: red here must stop the deploy, not warn.
  echo "▸ Running E2E (Playwright)…"
  rc=0
  python -m pytest tests/e2e -q --tb=short -p no:cacheprovider || rc=$?
  case $rc in
    0) echo "✓ E2E passed" ;;
    5) echo "✗  E2E collected NO tests — that is not a pass. Aborting." >&2; exit 1 ;;
    *) echo "✗  E2E FAILED (pytest exit $rc) — aborting, nothing synced." >&2; exit 1 ;;
  esac
fi

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

# ── 3. rebuild image + force-recreate container ───────────────────────────────
# --build     : rebuilds the image from the synced source
# --force-recreate : replaces the running container even if the image tag
#               didn't change (fixes the "old version still running" problem)
echo "▸ Rebuilding image and recreating container on remote…"
ssh "$HOST" bash <<REMOTE
  set -euo pipefail
  cd "$REMOTE"
  docker compose up -d --build --force-recreate
  docker image prune -f > /dev/null
REMOTE
echo "✓ Container recreated"

# ── 4. verify the new container is healthy ────────────────────────────────────
echo "▸ Waiting for health check…"
for i in $(seq 1 12); do
  STATUS=$(ssh "$HOST" "docker inspect --format='{{.State.Health.Status}}' $CONTAINER 2>/dev/null || echo 'starting'")
  if [[ "$STATUS" == "healthy" ]]; then
    echo "✓ Container is healthy"
    break
  fi
  if [[ "$i" -eq 12 ]]; then
    # Exit non-zero: a deploy that ends "⚠ … exit 0" reads as a success to
    # anyone (or anything) that only looks at the exit code.
    echo "✗  Container did not reach healthy state after 60 s — check: ssh $HOST docker logs $CONTAINER" >&2
    exit 1
  fi
  sleep 5
done

# ── 5. smoke test the live URL ────────────────────────────────────────────────
# /healthz only proves the process is up. bin/smoke.py GETs the page, the static
# bundle and every read endpoint the UI uses, through NPM — GET-only, so safe on
# real data — and fails if a 404 control route answers anything but 404.
echo "▸ Smoke-testing $URL…"
if ! command -v python &>/dev/null; then
  echo "✗  python is not on PATH — smoke test SKIPPED. Deploy is UNVERIFIED." >&2
  exit 1
fi
if ! python bin/smoke.py "$URL"; then
  echo "✗  Smoke test FAILED — the new container is live but broken. Check: ssh $HOST docker logs $CONTAINER" >&2
  exit 1
fi

# ── done ──────────────────────────────────────────────────────────────────────
echo ""
echo "🚀  $URL"
