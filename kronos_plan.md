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

## Phase 13 — Clock In / Clock Out ✅ DONE

One-tap stamp buttons on the Log tab and Dashboard. "Clock in" sets `start_time = now`;
"Clock out" sets `end_time = now` and saves the entry. Eliminates the main friction point
for daily use — no need to remember what time you started.

- Clock-in button visible when today has no entry yet (or entry has no start_time).
- Clock-out button visible when today has a start_time but no end_time.
- Both buttons disappear once the day is fully logged.
- Tapping either pre-selects today in the Log tab so the full form is accessible for edits.

---

## Phase 14 — Public Holidays Auto-Population (planned)

Pick a country and year in Settings; Kronos pre-populates all official public holidays
as `holiday` entries in one click.

- Settings: country selector (ISO 3166-1) + year. Stored in config table.
- `POST /api/holidays/import?country=ES&year=2026` — hits a public holidays API
  (e.g. Nager.Date, which is free and requires no key) and batch-creates entries.
- Skips dates that already have an entry (same logic as bulk logging).
- Shows toast: "X holidays imported, Y skipped".
- No external JS dependency — purely backend fetch.

---

## Phase 15 — End-of-Day Reminder (planned)

Browser push notification (Web Push API) if no entry has been logged by a configurable
time (default 18:00 local).

- Settings: enable/disable toggle + reminder time picker.
- Service worker handles the scheduled check and notification dispatch.
- Notification taps open the Log tab directly.
- Permission prompt shown only when the user enables the feature.

---

## Phase 16 — Notes Search ✅ DONE

Search field on the Days tab that filters the entry list by note content in real time.

- Pure frontend filter — no API change needed.
- Clears on tab switch.
- Highlights matched text in the results.

---

## Phase 17 — Week View (planned)

New "Week" sub-view (or tab) showing Mon–Sun at a glance: hours per day, daily surplus/
deficit indicator, and week total. Most-used view in Toggl/Clockify.

- Navigation arrows to jump between weeks; "This week" button snaps back.
- Click any day cell to open it in the Log tab for editing.
- Reuses `hm-*` colour classes for day-type indicators.

---

## Phase 18 — Streaks & Milestones (planned)

Motivational counters displayed on the Dashboard.

- **Logging streak**: consecutive calendar days with any entry logged.
- **On-target streak**: consecutive work days where surplus ≥ 0.
- **Milestones**: toast notification when hitting 30 / 100 / 365 days logged.
- Computed server-side via `GET /api/streaks`; no new DB table needed.

---

## Phase 19 — CSV Import (planned)

Companion to the existing CSV export. Upload a CSV file (matching the export format)
to bulk-import historical entries.

- `POST /api/import/csv` — parses uploaded file, validates each row, inserts entries.
- Skips rows for dates that already exist (same skip logic as batch endpoint).
- Returns `{ imported: N, skipped: M, errors: [...] }`.
- UI: file picker in the Settings / Backup section, same area as restore.

---

## Phase 20 — Overtime Alerts (planned)

Warn when weekly hours are heading toward or have exceeded a configurable threshold
(e.g. 45 h/week).

- Settings: weekly overtime threshold (default off).
- Dashboard warning banner when current-week net hours exceed threshold.
- Colour-coded: yellow = approaching (>90% of threshold), red = exceeded.

---

## Phase 21 — Active Timer (planned)

A live running clock for users who prefer to track time in real time rather than logging
after the fact. Bigger lift than the clock-in stamp (Phase 13) — this one ticks.

- "Start timer" button → records `start_time`, begins a seconds-level counter visible
  in the header or Dashboard.
- "Stop timer" → fills `end_time`, prompts for breaks, saves entry.
- Timer state persisted in `localStorage` so it survives page refreshes.
- Conflicts gracefully with manual entries (timer disabled if today already logged).

---

## Architecture Notes

- All DB writes via `entries.py` router. Single `Entry` row per date (date is PK).
- Frontend: Alpine.js reactive, no build step. CSS: Pico CSS + custom variables.
- Templates: `index.html` + one partial per tab (`_tab_*.html`).
- Tests: pytest, e2e via `tests/e2e/`.
