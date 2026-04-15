#!/bin/sh
# Entrypoint: apply migrations, then start uvicorn.

set -eu

cd /app

# Alembic is idempotent — safe to run on every boot. Adds tables on first launch
# and applies any new migrations on subsequent deploys.
alembic upgrade head

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${APP_PORT:-8765}" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips='*'
