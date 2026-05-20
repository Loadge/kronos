# Kronos — Implementation Plan

Personal work-hours tracker. Single-user, no auth — trusted network only.
Stack: FastAPI + SQLite + Alpine.js + Pico CSS. Mirrors Lorca's structural patterns.

---

## Phase 1 — Core Scaffolding ✅ DONE

Directory structure, FastAPI app, Alpine.js + Pico CSS frontend, Docker + `deploy.sh`.
Health check at `/healthz`. Static files from `backend/static/`.

---

## Phase 2 — Database & Entry CRUD ✅ DONE

ORM model: `Entry` (date PK, day_type, start_time, end_time, breaks JSON, notes).
Alembic migrations. `GET/POST/PUT/DELETE /api/entries/{date}`.
SQLite WAL mode.

---

## Phase 3 — Log Tab ✅ DONE

Daily entry form: date picker, day type (work/vacation/sick/holiday/flex),
start/end time, break management (time ranges or manual minutes), notes.
Template save/apply (named entry presets). `@change` date probe auto-loads existing
entry into edit mode.

---

## Phase 4 — Dashboard Tab ✅ DONE

Summary cards: hours today, week surplus/deficit, cumulative surplus/deficit,
days breakdown by type. Skeleton loading state while fetching.

---

## Phase 5 — Days Tab ✅ DONE

Paginated table of all logged entries. Year filter. Inline edit/delete.
`scrollToToday()` on tab open.

---

## Phase 6 — Analytics Tab ✅ DONE

Year filter + "as of date" cumulative view. Charts and breakdowns by day type.

---

## Phase 7 — Settings Tab ✅ DONE

Daily target hours, cumulative start date, annual reset toggle, work-week picker
(Mon–Sun toggles). `GET/PUT /api/config`.

---

## Phase 8 — Backup / Export ✅ DONE

`GET /api/backup` / `POST /api/restore` — full DB download/upload.
`GET /api/export` — CSV/PDF export via dedicated router.
Admin router for maintenance ops.

---

## Phase 9 — UX Polish ✅ DONE

Command palette (`.` key), keyboard shortcuts (l/a/s/Ctrl+Enter/Esc),
theme toggle (dark/light, persisted in localStorage), save-confirmation ribbon,
skeleton loading states, PWA manifest.

---

## Phase 10 — Shortcut Discoverability & Date UX fixes ✅ DONE

### 10a — Keyboard shortcut hint button ✅ DONE
- `⌨` button added next to the theme toggle; grouped in `.header-controls` div.
- Click opens the command palette.
- Hover shows a CSS tooltip listing all active shortcuts (L, A, S, ., Ctrl+↵, Esc)
  with styled `kbd` chips in brass.
- Tooltip overflow fix: moved `overflow:hidden` from `.app-header` to a new
  `.egg-clip` overlay so the egg animation still clips without cutting the tooltip.

### 10b — Replace date input with calendar picker ✅ DONE
- Removed `<input type="date">` and `onDateChange()` entirely.
- Full-width month calendar replaces the date field: 7-col grid, Mon-first,
  prev/next month nav (‹ ›), brass ring for today, brass fill for selected day.
- Logged days coloured by type (reuses `hm-*` classes from analytics heatmap).
- Clicking a cell sets `form.date` and calls `probeDate()` — no partial values,
  premature probe issue gone.
- Editing mode: calendar dims all non-selected cells, click is disabled.
- `go('log')` now fire-and-forgets `loadDays()` so entries are available for
  the calendar without requiring a Days tab visit first.

---

## Phase 11 — Bulk Date Logging ✅ DONE

- "Log multiple days…" button on the Log tab opens a modal calendar.
- Calendar reuses `.log-cal-*` styles; entry colours from `hm-*` classes.
- Click to toggle a single day; click+drag selects a range (union with
  existing selection). `@mouseup.window` ends drag anywhere on screen.
- Weekends visually dimmed (`.bulk-weekend`).
- Action pill appears once ≥1 day is selected: Vacation / Sick / Holiday / Flex / clear.
- Confirming a day type POSTs `POST /api/entries/batch` and shows a toast
  with "X logged, Y skipped" feedback.
- Backend skips existing entries silently; work type rejected with 422.
- 6 new API tests (258 total). No external JS dependencies.

---

## Phase 12 — Server-Side Templates ✅ DONE

- `templates` DB table: id, name, start_time, end_time, breaks (JSON).
- `GET /api/templates` · `POST /api/templates` · `DELETE /api/templates/{id}`
- Frontend loads from API on init; save/delete call API directly.
- Silent one-time migration: on first load, if API returns empty and localStorage
  has templates, they are uploaded automatically and localStorage is cleared.
- 10 new API tests (268 total).

---

## Architecture Notes

- All DB writes via `entries.py` router. Single `Entry` row per date (date is PK).
- Frontend: Alpine.js reactive, no build step. CSS: Pico CSS + custom variables.
- Templates: `index.html` + one partial per tab (`_tab_*.html`).
- Tests: pytest, e2e via `tests/e2e/`.
