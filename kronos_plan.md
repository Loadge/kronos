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

## Phase 14 — Public Holidays Auto-Population ✅ DONE

Pick a country (and optional region) in Settings; Kronos pre-populates official public
holidays for the current year as `holiday` entries in one click.

- Backend fetches server-side via stdlib `urllib` (no new dependency) from Nager.Date
  (free, no key). Browser never calls the external API directly.
- `GET /api/holidays/countries` — proxies Nager `AvailableCountries` (sorted by name).
- `GET /api/holidays/subdivisions?country=ES&year=2026` — distinct ISO-3166-2 codes
  derived from the year's holidays (Nager has no subdivisions endpoint); powers the
  region dropdown, showing only regions that actually have a regional holiday.
- `POST /api/holidays/import?country=ES&year=2026&region=ES-MD` — imports national
  (`global`) holidays plus, when a region is given, that subdivision's holidays.
  **Region filter is required for correctness** — without it, importing a country
  would dump every region's holidays. `notes` is set to the holiday's local name.
- Skips existing dates and in-response duplicates (same rule as batch/import).
- Settings: country + optional region selectors + "Import holidays" button, with a note
  that **local/municipal fiestas** (e.g. a town's two local holidays) aren't in the
  dataset and must be logged manually. Year is current-year only (not persisted);
  `holiday_country` + `holiday_region` are persisted in the config KV table.
- Toast: "X holidays imported, Y skipped". Network failure → 502 surfaced in the banner.
- **Mini-calendar preview**: once a country (and optional region) is chosen, per-month
  mini-calendars render the matching holidays before import — filled = will import,
  ring = already logged (will be skipped) — with a summary line
  ("9 national · 3 regional · 2 already logged") and a legend. Powered by a read-only
  `GET /api/holidays/preview` sharing the same filter logic as import. The import button
  reflects the count ("Import 3 holidays") and disables when nothing is left to import.
- 12 new API tests (291 total); fetches are monkeypatched so tests never hit the network.

---

## Phase 16 — Notes Search ✅ DONE

Search field on the Days tab that filters the entry list by note content in real time.

- Pure frontend filter — no API change needed.
- Clears on tab switch.
- Highlights matched text in the results.

---

## Phase 22 — Log Tab UI Overhaul ✅ DONE

Full visual redesign of the Log tab to a modern, cohesive desktop layout.

- **Three-column structure**: sticky calendar / card-surface form / notes panel. Card wraps cols 2+3 with `var(--k-surface)` background + border + border-radius — inspired by Linear/Raycast "tool panel left, card right" pattern.
- **Now pill relocated**: moved from mid-row (colliding with time value) to the label row above each time input, right-aligned as a compact helper affordance.
- **Template bar collapsed**: replaced full-width bar with a dashed ghost trigger button opening an Alpine `x-data` dropdown. Recovers ~60px of vertical prime real estate.
- **Save as template**: replaced with a `<details>` collapsible — collapsed by default, expands inline. Eliminates input truncation.
- **Notes panel**: uppercase section header + live character count; textarea fills the card column height.
- **Create entry CTA**: full-width, solid brass background — sole primary action, pinned to bottom of form column via `margin-top: auto`.
- **Form hierarchy**: thin `border-top` dividers between sections, consistent group spacing.

---

## Phase 17 — Week View ✅ DONE

New "Week" tab showing Mon–Sun at a glance: hours per day, daily surplus/deficit
indicator, and week total. Most-used view in Toggl/Clockify.

- Pure frontend — per-day figures come straight from `/api/entries`; summing the
  week's entries reproduces the backend `summarize()`, so the week total stays in
  lock-step with the Dashboard "This week" card. No new endpoint.
- Navigation arrows (‹ ›) to jump between weeks; "This week" button snaps back
  (shown only when off the current week).
- Click any day cell to open it in the Log tab (edit mode if logged, new otherwise).
- Reuses `hm-*` colour classes for day-type indicators; `day-pill` for non-work days.
- Keyboard shortcut **W**, command-palette entry, and shortcut-tooltip row added.
- Dashboard "This week" card is now clickable → opens the Week tab (brass hover cue,
  keyboard-activatable, no underline).
- Responsive: 7-column grid on desktop, stacked rows under 640px.

---

## Phase 18 — Streaks & Milestones ✅ DONE

Motivational counters displayed on the Dashboard.

- **Logging streak**: consecutive calendar days with any entry logged.
- **On-target streak**: consecutive work days where surplus ≥ 0.
- **Milestones**: toast notification when hitting 30 / 100 / 365 days logged.
- Computed server-side via `GET /api/streaks`; no new DB table needed.

- `GET /api/streaks?today=` — `logging_streak` (consecutive calendar days with any
  entry, ending at `today`; falls back to `today - 1` as anchor if today isn't logged
  yet so the count doesn't drop to 0 mid-day), `on_target_streak` (consecutive most
  recent `work` entries with per-day surplus ≥ 0 — non-work days in between don't
  break it), `total_logged_days` (all-time entry count).
- Dashboard: new summary-card row for the two streaks, styled like the existing cards.
- Milestone toast (30/100/365) is frontend-only: compares `total_logged_days` against
  a `k-milestone-seen` localStorage watermark so it fires once per threshold crossed,
  no backend state needed.
- 7 new API tests (298 total).

---

## Phase 19 — CSV Import ✅ DONE

Companion to the existing CSV export. Upload a CSV file (matching the export format)
to bulk-import historical entries.

- `POST /api/import/csv` — parses the CSV text, validates each row via `EntryIn`,
  inserts entries. Body is `{content: "<csv>"}` (file read client-side, like restore)
  so no `python-multipart` dependency is needed.
- Reuses the `CSV_COLUMNS` contract from export; derived columns (net/target/surplus)
  are ignored, and a work day's `total_break_minutes` is reconstructed as one break.
- Skips dates that already exist **and** dates repeated within the file (same skip
  rule as the batch endpoint). Adds to existing data — nothing is wiped.
- Returns `{ imported: [...], skipped: [...], errors: ["row N: <msg>", ...] }`;
  invalid rows are collected, not fatal.
- UI: "⇪ Import CSV…" button in Settings → Backup & restore, next to Restore.
- 7 new API tests (279 total). The round-trip test clears via the per-entry endpoint
  rather than `DELETE /api/data`: the test engine doesn't install the production
  `PRAGMA foreign_keys=ON` listener, so a bulk wipe orphans breaks there. Production
  enforces FK cascade correctly, so this is a test-harness quirk only, not a bug.

---

## Phase 23 — Date-Effective Daily Target ✅ DONE

`daily_target_hours` was a single global value, so a mid-year contract change (8h → 6h)
silently corrupted every cumulative/surplus number spanning it. The target is now
date-effective and the math is correct across a change.

- **`DailyTargetSchedule`** value object (`computations.py`): sorted `(effective_from,
  hours)` rows; `for_date(d)` returns the most recent row on/before `d`. `summarize()`
  and `daily_target_for()` accept `float | DailyTargetSchedule` — a bare float is coerced
  to a constant schedule, so display-only callers stay simple while the range-summing
  analytics callers resolve the target per entry date.
- **Storage** (`settings.py`): JSON timeline under the `daily_target_timeline` KV key,
  mirroring `dashboard_layout`. No schema migration. Before any timeline exists it
  synthesizes a one-row schedule from the legacy `daily_target_hours` value (anchored at
  the cumulative start), so existing deployments are unchanged.
- **Single-field coexistence**: the familiar "Daily target hours" field reads today's
  effective target and writes the *latest* row non-destructively (never wipes history).
- **API**: `GET`/`PUT /api/config/daily-target-schedule`; the timeline also rides along
  in `ConfigOut` so backup/restore round-trips it (older backups without it fall back to
  the single value).
- **Callers updated** to pass the schedule: dashboard, streaks (on-target compares each
  day to its own target), cumulative/monthly/yearly/records/yoy, entries, export.
- **Settings UI**: an "Advanced: my contracted hours changed over time" `<details>`
  disclosure with an add/remove/save timeline editor (rows keyed by stable client id to
  avoid Alpine `x-for` node-reuse on removal). The common single-target case is untouched.
- 20 new tests (326 total): schedule value object, settings service (fallback,
  non-destructive single-field write), the endpoint, dashboard per-date correctness, and
  a backup round-trip.

---

## Phase 24 — Half-Day Leave (planned)

Vacation / sick / holiday / flex are whole-day only. Real leave is often a half-day
(a morning off, a half-day sick). Add 0.5-day granularity to non-work entries.

- Non-work entries gain a fraction (1.0 / 0.5); a half-day charges half the day's target
  against the surplus pool and counts as 0.5 against the vacation budget.
- Log tab + bulk logging expose the half-day option; Days/Week/dashboard reflect it.
- Vacation-budget math and `summarize()` account for fractional non-work days.

---

## Phase 25 — Time-Off Planner (planned)

Kronos is retrospective — you log what already happened. The planner is forward-looking:
pencil in future vacation/holiday/flex and see the projected cumulative balance and
remaining vacation budget **before** the days arrive. Builds on the existing vacation
budget + forecast, the date-effective target (Phase 23), and half-day leave (Phase 24).

- A planning view where future non-work days can be drafted (not yet real entries).
- Live projection: cumulative balance and vacation budget remaining as-of year end, given
  the drafted days.
- "Commit" turns drafts into real entries via the existing batch endpoint.

---

## Phase 26 — Printable Timesheet / PDF Export (planned)

A cleanly formatted monthly or annual timesheet for records, an employer, or invoicing.
Independent of the other phases — pure output layer, no model changes.

- Print-optimized HTML view (period picker → formatted table + totals) that the browser
  can save to PDF; no server-side PDF dependency required.
- Reuses the existing period/summary computations; shows per-day rows + period totals.

---

## Architecture Notes

- All DB writes via `entries.py` router. Single `Entry` row per date (date is PK).
- Frontend: Alpine.js reactive, no build step. CSS: Pico CSS + custom variables.
- Templates: `index.html` + one partial per tab (`_tab_*.html`).
- Tests: pytest, e2e via `tests/e2e/`.
