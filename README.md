# Kronos ⏱️

> A self-hosted work-hours tracker for people who don't want to open a spreadsheet every morning.

Single-user. No auth. SQLite-backed. Runs as a Docker container behind your own reverse proxy.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)

---

## What it does

Log your working days in seconds. Kronos keeps a running tab of where you stand — this week,
this month, all time — against a configurable daily target, and gets out of your way otherwise.

- **One row per day** — `work` / `vacation` / `sick` / `holiday` / `flex`
- **Work days** have start/end times and any number of break entries (time-range or manual minutes)
- **Weekly, monthly, cumulative, and year-over-year surplus/deficit**, computed against your target
- **Non-work days** zero out that day's target — period totals adjust automatically; `flex` days
  still drain the target (paid time off charged against the surplus pool)
- **Draggable dashboard** — reorder the summary cards, streak tiles, and forecast/quick-log blocks
  to your liking; the layout persists server-side
- **Logging & on-target streaks**, with milestone toasts at 30/100/365 days logged
- **A live Week view**, a calendar-driven Log tab, bulk date logging, and server-side day templates
  for one-click entry of recurring shifts
- **Clock in / clock out** stamps for zero-friction daily logging
- **Public holiday auto-import** (country + region) with a preview before committing
- **CSV import/export** and a full JSON backup/restore
- **Command palette, keyboard shortcuts, dark/light themes, PWA-installable**

---

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI + SQLAlchemy 2 + Alembic |
| Frontend | Jinja2 + Alpine.js + Pico CSS + Chart.js + SortableJS |
| Storage | Single SQLite file (WAL mode) in a Docker volume |
| Vendored | All JS/CSS bundled under `backend/static/vendor/` — **zero build step, zero CDN calls** |

---

## Quick start

### Docker (recommended)

```sh
git clone https://github.com/Loadge/kronos.git
cd kronos
docker compose up -d
```

Open **http://localhost:8765**.

First boot runs `alembic upgrade head` automatically and seeds default settings.

#### Reverse proxy

Point your reverse proxy at `http://<host>:8765`. Example Nginx snippet:

```nginx
location / {
    proxy_pass         http://127.0.0.1:8765;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
}
```

Works with NGINX Proxy Manager, Caddy, Traefik, etc.

#### Port & timezone

```env
# .env next to docker-compose.yml
APP_PORT=8765          # host port
TZ=Europe/Madrid        # drives what "today" means everywhere in the app
```

### Local development

Requires Python 3.12+.

```sh
make install          # pip install -r requirements-dev.txt
make migrate          # alembic upgrade head
make seed             # ~3 months of realistic sample data
make run              # uvicorn on :8765 with --reload
```

---

## Configuration

| Env var | Default | Notes |
|---|---|---|
| `APP_PORT` | `8765` | Internal + published port |
| `TZ` | `Europe/Madrid` | Drives what "today" means throughout the app |
| `KRONOS_DATA_DIR` | `/app/data` (container) / `./data` (local) | Where `kronos.db` lives |
| `DATABASE_URL` | derived from `KRONOS_DATA_DIR` | Full override for the SQLAlchemy URL |

Runtime-editable settings (Settings tab, or `GET`/`PUT /api/config`):

| Setting | Default | Notes |
|---|---|---|
| `daily_target_hours` | `8.0` | Contracted hours per work day |
| `cumulative_start_date` | `2025-01-01` | Start of the all-time running total |
| `reset_annually` | `false` | Auto-advance the cumulative start to Jan 1 each year |
| `work_week_days` | Mon–Fri | Which weekdays count toward the schedule |
| `vacation_budget_days` | `0` | Annual vacation allowance shown on the dashboard |
| `default_start_time` / `default_end_time` | `09:00` / `17:00` | Pre-filled values on the Log tab |
| `holiday_country` / `holiday_region` | *(none)* | Selected country/subdivision for holiday auto-import |
| `dashboard_layout` | see below | Card/tile/block order for the dashboard's drag-to-reorder groups |

Dashboard layout defaults to:
```json
{
  "hero": ["week", "month", "cumulative"],
  "tiles": ["yoy", "logging_streak", "on_target_streak"],
  "aux": ["forecast", "quick_log", "vacation"]
}
```

These all live in the `settings` key-value table; migrations seed sensible defaults on first boot.

---

## Data & backups

The SQLite file lives at **`/app/data/kronos.db`** inside the container, bound to the
**`kronos-data`** named Docker volume.

**Export from the UI** — Settings tab → *Download backup* — produces a portable JSON file that can
be imported back with *Restore from file*. CSV import/export lives right next to it.

**One-shot host-side copy:**
```sh
docker run --rm -v kronos-data:/data -v "$PWD":/out alpine \
  sh -c 'cp /data/kronos.db /out/kronos-$(date +%F).db'
```

> WAL is checkpointed by SQLite on connection close. For a tighter guarantee, stop the container
> before copying.

---

## API

Interactive docs at `/docs` (FastAPI Swagger UI) once the container is running.

| Method & path | Purpose |
|---|---|
| `POST /api/entries` | Create a day entry (with breaks) |
| `POST /api/entries/batch` | Bulk-log the same non-work day type across multiple dates |
| `GET /api/entries` | List entries, optional date range |
| `GET /api/entries/{date}` | Single entry |
| `PUT /api/entries/{date}` | Full replace (atomic break-set replace) |
| `DELETE /api/entries/{date}` | Delete entry (cascades breaks) |
| `GET /api/dashboard?today=` | Week + month + cumulative summary |
| `GET /api/streaks?today=` | Logging streak, on-target streak, all-time days logged |
| `GET /api/analytics/cumulative?as_of=` | Point-in-time surplus/deficit |
| `GET /api/analytics/monthly` / `/yearly` | One row per calendar month / year |
| `GET /api/analytics/records` | Longest day, most surplus month, longest streak, best/worst year |
| `GET /api/analytics/yoy?today=` | This year vs. same period last year |
| `GET /api/export.csv` / `/export.json` | Download entries |
| `POST /api/import/csv` | Bulk-import entries from a Kronos-format CSV |
| `GET /api/config` / `PUT /api/config` | Read/write all app-level settings |
| `GET /api/config/dashboard-layout` / `PUT ...` | Read/write the dashboard's card/tile/block order |
| `GET /api/holidays/countries` / `/subdivisions` | Country + region lookups (proxies Nager.Date) |
| `GET /api/holidays/preview` / `POST /api/holidays/import` | Preview, then import public holidays |
| `GET /api/templates` / `POST` / `DELETE /{id}` | Server-side day templates (start/end/breaks) |
| `GET /api/backup` | Download full JSON backup (entries + settings) |
| `POST /api/restore` | Restore from JSON backup (wipes existing data first) |
| `DELETE /api/data` | Wipe all entries (admin / testing) |
| `POST /api/data/seed` | Populate with sample data (admin / testing) |
| `GET /healthz` | Container healthcheck |

---

## Tests

```sh
make test             # pytest — in-memory SQLite, no container needed
make lint             # ruff check + format check
```

302 tests across four suites:

| Suite | Coverage |
|---|---|
| **Unit** | Net-hours math, break-calc conversions, ISO-week/month boundaries, `DayType` enum, `WorkEntry` properties, settings service |
| **API** | Every router — happy path + validation errors (duplicate date, end ≤ start, break > span, day-type transitions, invalid config) |
| **Integration** | Full CRUD flows, dashboard recalculation after state changes, cross-month weeks, export/import round-trips |
| **Regression** | Cumulative start-date boundary, `as_of` inclusive semantics, float precision, backup field fidelity, orphaned-break FK fix, non-work day zero-target invariant, CSV quoting |

### E2E — Playwright

End-to-end tests spin up a real uvicorn server and drive a real browser. Excluded from the default
`make test` run.

```sh
pip install pytest-playwright
playwright install chromium

pytest tests/e2e -v            # headless
pytest tests/e2e -v --headed   # visible browser
```

---

## Security posture

Kronos is designed for a **trusted internal network** (behind a VPN or a private reverse proxy):

- **No auth layer** — access control is the network itself
- **No cookies** — no CSRF surface to defend
- **JSON-only mutation API** with Pydantic strict validation on every field
- Container runs as a **non-root user** (`kronos`, uid 1000)
- Uvicorn runs with `--proxy-headers` so the real client IP surfaces in logs behind a proxy

> ⚠️ If you ever expose this to the open internet, add an auth layer (e.g. Cloudflare Access,
> Authelia, or Basic Auth in your reverse proxy) — the app itself has no authentication.

---

## Migrations

```sh
make migrate                           # apply pending migrations
make revision MSG="add new column"     # generate a new autogenerated migration
```

Alembic runs with `render_as_batch=True` so SQLite-unfriendly `ALTER TABLE` operations (drop
column, alter type) work correctly.

---

## Layout

```
kronos/
├── backend/
│   ├── app/
│   │   ├── routers/      # entries, analytics, export, config, backup, admin, holidays, templates
│   │   ├── services/     # computations, settings, views
│   │   └── templates/    # Jinja2 shell + tab partials (dashboard/week/log/days/analytics/settings)
│   ├── static/           # app.js, styles.css, sw.js, manifest.json, icon.png, vendor/*
│   └── seed.py           # realistic sample-data generator
├── alembic/              # migrations + env.py
├── tests/
│   ├── unit/             # pure-function tests (no DB)
│   ├── api/               # per-router HTTP tests (in-memory SQLite)
│   ├── integration/       # cross-endpoint flows + regression suite
│   └── e2e/               # Playwright browser tests
├── deploy.sh             # one-command deploy to a remote Docker host via SSH
├── Dockerfile            # multi-stage: base → test (runs pytest at build time) → runtime
├── docker-compose.yml
├── entrypoint.sh         # alembic upgrade head + uvicorn
├── Makefile
├── kronos_plan.md        # phase-by-phase project history/roadmap
└── pyproject.toml        # ruff + pytest config
```

---

## Roadmap

See [`kronos_plan.md`](kronos_plan.md) for the full phase-by-phase history. Planned next:
end-of-day reminders, overtime alerts, and a live active-timer mode.

---

## License

[MIT](LICENSE)
