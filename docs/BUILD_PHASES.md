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

---

## Open phases

Suggested order (2026-10-31, 31, 32 and 33 built): 28 next (Anselmo logs through the CLI
Phase 32 delivered); 29 any time, and before next October; 30 only if logging from the phone
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
- **Demo GIF** (`docs/demo/`) predates the planner, partial days, the timesheet and the Phase
  31 / 33 redesign — the README's first image shows the old dashboard and analytics. Re-record it
  when convenient (`docs/demo/README.md`; the recorder's scenes already point at the new
  headings).

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
