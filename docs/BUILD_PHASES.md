# Kronos — Build Phases

Personal work-hours tracker. Single-user, no auth — trusted network only.
Stack: FastAPI + SQLite + Alpine.js + Pico CSS. Mirrors Lorca's structural patterns.

**Completed phases live in `BUILD_PHASES_ARCHIVE.md`** (decisions, what shipped, known limits; read
it for the history of a decision, not by default). This file keeps only open and unconfirmed work.

---

## Done (archived in `BUILD_PHASES_ARCHIVE.md`)

| Phase | What | Landed |
|---|---|---|
| 1–10 | Base app: scaffolding, entry CRUD, Log / Dashboard / Days / Analytics / Settings tabs, backup and CSV export, UX polish, calendar picker | before git history |
| 11 | Bulk date logging | `ac562e1` |
| 12 | Server-side templates | `5409030` |
| 13 | Clock in / clock out | `e514613` |
| 14 | Public holidays from Nager.Date (+ preview) | `0679290`, `cee88f8` |
| 16 | Notes search | `d688dea` |
| 17 | Week view | no commit of its own |
| 18 | Streaks & milestones | `8248dd5` |
| 19 | CSV import | `01f4de5` |
| 22 | Log tab UI overhaul | `0e9d347` |
| 23 | Date-effective daily target | `31bd9ba` |
| 24 | Partial-day leave (any hours, not just half days) | `17c2cdb` |
| 25 | Time-off planner (Plan tab, projection, ghost days) | `17c2cdb` |
| 26 | Printable timesheet (Days → PDF, profile settings) | `17c2cdb` |
| 27 | Spanish holidays from the BOE (+ list under the preview) | `bfdffe1`, `a1c8bff` |

---

## Open phases

Suggested order (2026-10-27, 24–26 done): 31 → 33 (Analytics inherits the redesign's visual
language); 32 in parallel with either, since it lives in `bin/` and the API, not the frontend; 28
after 32 (Anselmo would log through the CLI); 29 any time; 30 only if logging from the phone
outside the LAN turns out to be common.

### Phase 28 — Log Without Typing (idea, spike first)

Kronos proposes the day from signals that already exist and Miguel only confirms it: the work PC's
power-on / power-off events, presence in Home Assistant, and optionally Anselmo over Telegram ("hoy
entré a las 8:30, comí 45 min"), with the local LLM extracting the times from the text.

- **Spike first, before any build:** do the signals give reliable start/end times or just noise?
  Compare a few weeks of signals against the logged days.
- A proposal is never an entry until confirmed; nothing overwrites a logged day.
- Boundary with **jornada**: Kronos is publicly mirrored and nothing from jornada may go into it.
  An idea of Kronos' own is fine; copying jornada's design is not.

### Phase 29 — BOE Resolution Discovery (planned)

Phase 27 left a yearly chore: add next year's BOE id to `BOE_RESOLUTIONS` each October. Find it
instead: search the BOE summary for the "relación de fiestas laborales para el año N" resolution,
check it parses like the fixtures, keep the hand-written table as the fallback.

- While there: Canarias' island holidays and Arán's substitution, which live in the table's
  footnotes and are not imported today.

### Phase 30 — Offline PWA (idea)

The service worker caches only the app shell. Queue writes made offline on the phone (clock in/out,
save a day) and sync them on reconnect, resolving conflicts per date. Serious frontend and e2e work;
worth it only if logging from the phone outside the LAN is common.

### Phase 31 — Visual Redesign: Navigation, Dashboard + Week, Settings, Days (planned)

One phase on purpose: the four parts share one visual language and the navigation, so redesigning
them separately would mean deciding it four times. **Starts with an interview with Miguel** (when the
phase begins, not before) and mockups to choose from, like Phases 25–26. What follows is the
starting proposal for that interview, not a decision.

- **Navigation: 7 entries → 5.** Week disappears into the Dashboard; Settings becomes a gear icon
  next to the theme toggle. Since Plan arrived the menu is crowded enough that it is unclear what to
  press. Option for the interview: Log as a slide-over panel opened from anywhere (key **L**) instead
  of a tab, leaving Dashboard · Plan · Days · Analytics.
- **Dashboard, "less is more".** Today it shows three large cards, two streak tiles, the forecast,
  the "Log a day" button and four quick-log pills, and the milestone toast overlaps the first line.
  Proposal: one hero number (the cumulative balance), the week's seven days as a compact strip
  underneath (what the Week tab shows today, including clicking a day to open it in Log) and a
  one-line forecast. The month, the streaks and quick-log become secondary (smaller, or on demand).
  The draggable layout (dashboard_layout) has to survive or be retired explicitly.
- **Settings.** Today one 1280 px column: fields of inconsistent widths (the daily target full
  width, start/end time half), Pico's default blue "Save settings" button outside the palette, one
  save button for everything, and a "Fun zone" mixing wipe with backup/restore. Proposal: a section
  index on the left (Work · Leave · Holidays · Profile · Templates · Data), content at ~720 px, save
  per section, and everything destructive grouped under Data.
- **Days.** The misalignment in the table (2026-10-27 screenshot) comes from the note icon sharing
  the action cell with **Edit**: rows with a note push the button, rows without do not. Proposal: a
  dense table with a fixed-width action column, the whole row clickable to edit, sticky header,
  a separator per month with its subtotal, and "N entries / PDF" in the top bar instead of floating
  under the search box.
- Must not break: keyboard shortcuts and the command palette (W goes away or is remapped), the e2e
  suite (it asserts the tabs), the phone layout, dark and light themes.

### Phase 32 — `kronos` CLI for Agents (planned)

Kronos has no CLI: `bin/kctl.py` only starts disposable instances for verification. An agent (an
agentic coder, Anselmo) that wants to read or log days today must click the web UI or touch the
database. Model it on lorca's `bin/lorca.py`.

- Talks **only to the HTTP API**, never to SQLite. `--target local|int|prod` (URLs from env or a
  git-ignored file, never the repo: it is publicly mirrored), `--json` on every command.
- Reads: `today`, `balance` (week / month / cumulative), `days --month 2026-10`, `plan`, `config`.
- Writes: `log 2026-10-27 --start 8:30 --end 16:45 --break 45`, `log 2026-10-28 --type vacation
  [--hours 4]`, `clock in|out`, `plan add|rm`, `holidays import`, `backup` / `restore`. Every write
  has `--dry-run` (prints the request and the resulting day without sending it), and a write to
  PROD takes a backup first, as lorca's does.
- Wherever the API lacks an endpoint a command needs, add it to the API (the UI then gets it too)
  rather than giving the CLI a side door.
- It is the prerequisite of Phase 28: Anselmo logging from Telegram would call this CLI.

### Phase 33 — Interactive Analytics (planned)

Analytics is hand-drawn SVG: the cumulative trend is a thin line with one point per month, the
monthly bars are fixed, and nothing responds to the pointer. Chart.js is already vendored
(`static/vendor/chart.umd.js`, ~200 KB) and used nowhere; Pi-hole's zoomable graphs are Chart.js
with its zoom plugin.

- Cumulative balance **per day**, with wheel and drag zoom, pan, and a reset; a range selector
  that filters the whole page (monthly breakdown, weekday pattern, records).
- Year-at-a-glance heatmap with a tooltip per cell (hours, Δ, note) and click → that day in Log.
- New views: start and end times per weekday (when do I really arrive and leave?), distribution of
  daily surplus/deficit, this month against the same month last year.
- Keeps working in both themes and on the phone (touch pinch-zoom), and the e2e suite covers at
  least the zoom/reset and the range filter.

---

## Small items

- **Wrap-up after Phase 26 (2026-10-27):** `tests/unit/test_repo_hygiene.py` now enforces three
  rules by test — models ⇔ migrations (autogenerate diff empty after `upgrade head`), no "Phase N"
  in code, no mixed line endings; `tests/integration/test_backup_fidelity.py` proves backup → wipe →
  restore → backup is identical, which found that break time ranges were dropped by the backup
  (fixed, old files still load); `bin/smoke.py` checks the planner and the timesheet too.
- **Demo GIF** (`docs/demo/`) predates the planner, partial days and the timesheet; re-record it
  when convenient (`docs/demo/README.md`).

- **PROD data from the Phase 27 check (2026-10-16):** 1-may is stored as `vacation`, and 12-jun /
  19-jun as holidays without a note. Left for Miguel to decide.
- **`IMPROVEMENTS.md`** (git-ignored, local only) is a superseded backlog (see its banner); delete
  it or fold what's left in here.
- **Old mockups are served in PROD:** `backend/static/mockups/` (10 files: dashboard directions,
  plan and timesheet mockups) ships in the image under `/static/mockups/` and goes out with the
  public mirror. Move them to `docs/mockups/`.
- **Chart.js** (`static/vendor/chart.umd.js`) is vendored but loaded nowhere. Phase 33 should use
  it; if it does not, remove it.

---

## Architecture Notes

- All DB writes via `entries.py` router. Single `Entry` row per date (date is PK).
- Frontend: Alpine.js reactive, no build step. CSS: Pico CSS + custom variables.
- Templates: `index.html` + one partial per tab (`_tab_*.html`).
- Tests: pytest, e2e via `tests/e2e/`.
