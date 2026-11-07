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
| 31 | Visual redesign: 5 tabs + gear, dashboard hero with trajectory and week strip, Settings cards, dense Days | `35ad663` |
| 33 | Interactive Analytics: zoomable SVG chart whose range drives the page, heatmap tooltip + click | `35ad663` |
| 34–35 | Freelance hours: income sources, blocks with a rate snapshot, ECB rate, Freelance tab, 130, calculator, Days / Analytics / PDF | `3baed75`, `9314942` |
| 37 | Freelance payouts: what a source really paid for a week replaces the estimate everywhere | `e494a3c`, `b3bb814` |
| 38 | Quieter Log and live updates: Wk column, + Add note, the result rail, version label and Update ready pill | `7eddb1c`, `3fce538` |
| 39 | One look across pages: one switch, one place for exports, one number format, `UI_GUIDE.md` | `f7f8cd5`, `4420f93`, `2addb57` |
| 40 | Eyes on the UI: screenshot baselines, aria snapshots, axe scan, `/ui-review` | `cbd9c68` |
| 41 | Kronos on a phone: two-line rows in Days, tap sizes of 24px, Analytics in phone order | `3808b78`, `8be17e5` |
| 42 | One line per week in Days > Freelance: the numbers always on screen, the arrow only hides the days | `f5faa45`, `2e5e539` |
| 43 | One line per week in Days > Employee, with Σ on the week line | `50ec193`, `c26a1b5` |
| 44 | The bezel: one tick per week over the Days table, in place of Expand all and Collapse all | `319455e`, `97aa5eb`, `f5fc1ac`, `b059006` |
| 45 | Leaving a day in Log by clicking the calendar; the ← button and the subtitle are gone | `9ea495f` |
| 46 | The day ribbon in Log: drag the day, its breaks and its blocks; the fields stay the precise editor | `86101eb`, `ff74b17` |
| 47 | The year dial: the year as a chronograph, opened from the logo, Y or the palette | `402d0d6`, `673854d` |
| 48 | Kronos in the hand: tab bar at the bottom, Log's dock, letters for months, a sliding brass line | `31922d2`, `ff74b17` |
| 49 | Every page at its best: Pico's blue gone, Plan cards with drawings, calculator fields, Settings | `e29ca8c` |
| 50 | Small brass surprises: rolling numbers, the stamp, the week's seal, coins, the hour bead | `54e88e2` |

---

## Open phases

Suggested order (2026-11-04; 31, 32, 33, 34 and 35 built, 34 and 35 confirmed and archived):
37 to 50 confirmed and archived; 28 next (Anselmo logs
through the CLI Phase 32 delivered); 29 any time, and before next October; 36 (the tactile pass)
in slices, each one a weekend, the day ribbon first; 30 only if logging from the phone outside
the LAN turns out to be common.

### Phase 36 — Tactile Kronos (idea, written 2026-11-02 at the end of the 34–35 review)

**Why.** Kronos already has a few things you *handle* rather than fill in: the rectangle you draw on
the Analytics chart, the click-and-drag that drafts time off, the leave slider, the quarter-hour
stepper. Everywhere else a number is still typed into a box. The question behind the freelance
work — *should I bill more, work less, is it worth it?* — is best answered by pulling on something
and watching the rest move. This phase turns the numbers that people explore (not the ones they
record) into things that can be dragged, and gives the recording surfaces one gesture where a
gesture is faster than a keyboard.

**Rules for every slice.** A drag is never the only way: the field stays, the keyboard works on the
handle (arrows step, shift+arrows step ×4, Home/End), and a screen reader gets the same value.
`prefers-reduced-motion` switches the springs off, never the feature. A drag that *records* (times,
blocks, drafts) snaps to the app's grain — 15 minutes, a whole day — and confirms with the ribbon
and its Undo; a drag that *explores* (rates, hours a week) changes nothing until it is released,
and says what it would change. Touch first: 44px handles, one finger drags, two fingers are the
page's. Nothing here moves the employee's numbers or the timesheet by itself.

**Slices, most valuable first.**

1. **The day ribbon (Log).** Built as Phase 46. Under the Employee card, the day as a strip from 06:00 to 24:00: the
   employee span as a brass bar, breaks as notches cut out of it, the freelance blocks as coin bars
   in their source colours, now as a hairline. Drag a bar's end to change the time, drag the bar to
   move it, drag a notch to move a break, drag in an empty stretch to add a block (the source
   picker pops under the finger). Snap to 15 min with a soft tick (`navigator.vibrate(8)` on the
   phone). The numbers in the form follow live; Save stays Save. This is the one slice that
   replaces typing for the common case — "I worked 9 to 18:45 with lunch at 14" is three gestures.
2. **Pull the calculator.** A slider under each of the three linked fields (hourly, daily, net)
   and under hours a day and billable days; dragging one reflows the other two with the same
   debounce and sequence guard the fields use. The waterfall bar becomes the handle: drag the edge
   of the *net* segment to a width and the hourly rate that gets there is written back — "to keep
   €40,000 net I'd need €112/h". A ghost of the year's real figures stays under the bar so the
   what-if is always compared with what is.
3. **Drag the plan (Freelance).** In the months chart the dashed planned bars have a handle: drag
   up or down and `hours a week` follows (the strip's input updates, saves on release). On the 130
   rail, drag the running quarter's payment up to see what gross the rest of the quarter needs.
4. **Drag the forecast (Dashboard).** The trajectory's Dec-31 point gets a handle: pull it to a
   balance and the dashed tail bends to it, the caption says the surplus per work day that lands
   there ("+0.35h a day from here"); release and it snaps back — exploring, not recording. The
   week strip's bars scrub: press and slide across the seven days to read each in the tooltip.
5. **Brush the year (Analytics).** Drag across the heatmap's cells to select a run of days: the
   chart below zooms to that range (the preset clears), the ledger follows. The same brush on the
   pinned copy. Shift+drag extends.
6. **Swipe the rows (Days, phone).** Swipe a day or a block left to reveal ✎ and ✕ (✕ with the
   ribbon's Undo), right to open it in Log. On the freelance side, long-press a row and drag it
   onto a source chip to re-bill it to that source (rate snapshot offered: keep the old rate, or
   take the new source's).
7. **Move a draft (Plan).** Drag a drafted block to other dates (the ledger row or the calendar
   cells), resize it by its ends; the projection card's number ticks while dragging.
8. **Paint the settings.** The work-week picker paints on drag (press Mon, slide to Fri). The
   target timeline becomes a stepped bar chart of hours over time: drag a step's height for the
   hours, its left edge for the date it started — the rows below stay the precise editor.
9. **The small stuff, everywhere.** Handles with a spring on release (`cubic-bezier(.34,1.56,.64,1)`,
   the app's existing curve), the number under a finger shown large in a floating tag while
   dragging, a tick at every snap, a longer haptic at the end of a range. The coin float and the
   bump already exist on the Log panel; the ribbon's Undo is the safety net for every recording
   gesture.

**What each slice needs.** 1, 5, 6 and 7 are frontend only (pointer events on the existing data,
the APIs already take everything). 2 needs nothing new from the API but one more field in the
answer of `POST /api/freelance/calc` for the inverse from a *net share*; 3 and 4 are frontend only
(the projection maths is already server-side; 4 computes its caption from the series it has). 8
touches no endpoint. Every slice gets Playwright tests driving the pointer (the chart's rectangle
test is the model) and a keyboard-parity test on the handle.

**Not in this phase.** Drag-to-reorder of anything (there is no order a user owns), gestures on
the timesheet pages (they are documents), and a canvas/WebGL anything — the hand-drawn SVG stays.

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

### Phase 32 — `kronos` CLI for Agents (built 2026-10-31, awaiting confirmation)

Kronos had no CLI: `bin/kctl.py` only starts disposable instances for verification. An agent (an
agentic coder, Anselmo) that wanted to read or log days had to click the web UI or touch the
database. Spec: one script, subcommands, `--json`; HTTP API only; `--target local|int|prod` with
URLs from env or a git-ignored file; every write with `--dry-run`; a write to PROD takes a backup
first; gaps in the API get filled in the API, never with a side door. Prerequisite of Phase 28.

**Process.** Interview first (four rounds, 19 questions; record in `docs/interview_spec.md`),
then one implementation pass, done in a Code Behaviors task and brought back on branch `phase32`
(2026-11-01). Not yet confirmed by Miguel or deployed; the archive
gets its summary when it is.

**What shipped.**
- `bin/kronos.py` (stdlib only, no packaging): reads `today` (the day + the three balances + the
  streaks), `balance`, `days --month|--from/--to`, `plan --year`, `config`, `targets`, `check`;
  writes `log` (work days; leave with `--hours`; `A..B` ranges and repeated dates for one leave
  type through the batch endpoint; `--replace` to overwrite, otherwise a logged date is an
  error), `clock in|out`, `plan add|rm|commit`, `holidays import`, `backup`, `restore --yes`.
  `--target`, `--json`, `--dry-run` before or after the command. Exit codes 0 / 1 API / 2 usage /
  3 unreachable or backup failed; `--json` errors as `{"error", "exit", "status"}`.
- **Targets:** `KRONOS_{LOCAL,INT,PROD}_URL` in the environment or `kronos.env` (git-ignored,
  `kronos.env.example` committed); env wins; `local` defaults to `http://localhost:8765`,
  `int`/`prod` have no default. Decided against a console entry point / `pip install` for now.
- **The PROD rule:** before a write to `prod` the CLI saves `GET /api/backup` to
  `backups/prod/kronos_backup_<UTC>.json` (`KRONOS_BACKUP_DIR` to move it), fails closed, keeps
  the newest 50 (only files of that exact name shape are pruned; a same-second write gets `-2`),
  skips under `--dry-run`, and has no `--no-backup`. `int` takes none. `restore` wipes first, so it
  backs up on every target and needs `--yes`. Rejected: a `--yes` on ordinary prod writes (an
  unattended bot would pass it always, so it would protect nothing).
- **API additions** (the UI can use them too): `POST /api/clock/in` and `/out` stamp the server's
  wall clock in `TZ` (one definition of "now" for a bot in a UTC container; a `date` other than
  today needs `at` — the first review found `clock out --date <future>` stamping 22:41 onto that
  day, and the CLI now refuses before any request too); `POST
  /api/entries/preview` validates and computes a day without writing it, with `exists`;
  `leave_hours` as the alternative to `fraction` on entries, batch, preview and plans, converted
  server-side against the target in force on each date (hours equal to the target are a whole
  day, more is a 422); `notes` on batch logging; `dry_run` on the clock endpoints.
- **Optimisations** (all seven agreed in the interview): the per-row `session.get` loops became
  one `IN` query or an anti-join (dashboard drafts, `list_plans`, `draft_plans`, `commit_plans`,
  batch, holiday import/preview, CSV import); `_whole_history` filters in SQL; `projection` reads
  the entries and the drafts once; `DailyTargetSchedule.for_date` is a binary search and
  `entry_to_out` resolves it once per day; `GZipMiddleware` and a one-year `Cache-Control` on
  `/static/vendor/*` (linked with a content-hash `?v=`, so a library bump is never served stale;
  service-worker cache bumped to v30); the dashboard's first paint fetches entries, drafts and
  streaks in parallel with the numbers; the migrations-vs-models test runs Alembic in-process on
  an in-memory database (`config.attributes["connection"]`) instead of spawning an interpreter.
- `deploy.sh` / `deploy-staging.sh` run `kronos check` after `smoke.py` and exclude `kronos.env`
  and `backups/` from the sync.

**Tests.** 35 unit (target resolution, env file, arguments, the `log` body, retention, the
fail-closed backup, formatting), 41 API (clock, preview, `leave_hours`, batch notes, gzip and
cache headers), 25 e2e running the CLI as a subprocess against the live server — the prod rule is
proven by aiming `KRONOS_PROD_URL` at that server: the snapshot exists, is version 2 and predates
the write; a dead port exits 3 with nothing written; `int` takes no backup; retention keeps 50.

**Known limits.** `int`/`prod` cannot be reached from the sandbox; the proof is by URL. The
holiday import needs the network the sandbox lacks (the CLI relays the API's 502). `plan rm` and
`plan commit` over many dates are one request per date / one request, respectively; `log` over a
range goes through `/batch` and so cannot carry times.

## Small items

- **Wrap-up after Phase 26 (2026-10-27):** `tests/unit/test_repo_hygiene.py` now enforces three
  rules by test — models ⇔ migrations (autogenerate diff empty after `upgrade head`), no "Phase N"
  in code, no mixed line endings; `tests/integration/test_backup_fidelity.py` proves backup → wipe →
  restore → backup is identical, which found that break time ranges were dropped by the backup
  (fixed, old files still load); `bin/smoke.py` checks the planner and the timesheet too.
- **PROD data from the Phase 27 check (2026-10-16):** 1-may is stored as `vacation`, and 12-jun /
  19-jun as holidays without a note. Left for Miguel to decide.
- **`IMPROVEMENTS.md`** (git-ignored, local only) is a superseded backlog (see its banner); delete
  it or fold what's left in here.

---

## Architecture Notes

- All DB writes via `entries.py` router. Single `Entry` row per date (date is PK).
- Frontend: Alpine.js reactive, no build step. CSS: Pico CSS + custom variables.
- Templates: `index.html` + one partial per tab (`_tab_*.html`).
- Tests: pytest, e2e via `tests/e2e/`.
