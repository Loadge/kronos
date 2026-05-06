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

## Phase 10 — Shortcut Discoverability & Date UX fixes (next)

### 10a — Keyboard shortcut hint button
- Add a `⌨` button next to the theme toggle that opens the command palette on click.
- On hover: custom styled tooltip listing all active shortcuts.
- No permanent space used; zero intrusion on existing layout.

### 10b — Date probe on blur, not change
- Change `@change="onDateChange()"` → `@blur="onDateChange()"` on the Log tab date input.
- Fixes premature edit-mode trigger when typing a day like "21" (the partial "02" was
  being probed before the user finished typing).

---

## Phase 11 — Bulk Date Logging

Log multiple days in one action — motivated by vacation/holiday blocks.
**Decided: Option C — Calendar overlay (Lorca-inspired).**

- "Log multiple days" button on the Log tab opens a modal calendar (1–2 months visible).
- Click selects a single day; click+drag selects a range.
- Floating action pill: `[Vacation] [Sick] [Holiday] [Flex] [✕]`.
- Confirming posts to a new `POST /api/entries/batch` endpoint.
- Skips existing entries (or warns). Weekends visually distinct / skippable.
- No external JS dependencies — pure Alpine.js + CSS calendar component.

---

## Architecture Notes

- All DB writes via `entries.py` router. Single `Entry` row per date (date is PK).
- Frontend: Alpine.js reactive, no build step. CSS: Pico CSS + custom variables.
- Templates: `index.html` + one partial per tab (`_tab_*.html`).
- Tests: pytest, e2e via `tests/e2e/`.
