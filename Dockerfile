# syntax=docker/dockerfile:1.7

# ---------- base: runtime deps only -----------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend

# tzdata is needed so zoneinfo ("Europe/Madrid") resolves inside the container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

# ---------- test: runs the full suite at build time -------------------------
FROM base AS test
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY . .
RUN pytest -q

# ---------- runtime: slim final image ---------------------------------------
FROM base AS runtime

# Non-root user for defense-in-depth.
RUN useradd --create-home --uid 1000 --shell /bin/bash kronos

COPY --chown=kronos:kronos backend /app/backend
COPY --chown=kronos:kronos alembic /app/alembic
COPY --chown=kronos:kronos alembic.ini /app/alembic.ini
COPY --chown=kronos:kronos entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /app/data \
    && chown -R kronos:kronos /app/data

ENV KRONOS_DATA_DIR=/app/data \
    TZ=Europe/Madrid \
    APP_PORT=8765

USER kronos

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys,os; \
port=os.environ.get('APP_PORT','8765'); \
sys.exit(0 if urllib.request.urlopen(f'http://localhost:{port}/healthz',timeout=3).status==200 else 1)" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
