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

Suggested order (2026-11-01, 31, 32 and 33 built): 34 then 35 (freelance hours, then what they
add up to); 28 after them (Anselmo logs through the CLI Phase 32 delivered); 29 any time, and
before next October; 30 only if logging from the phone outside the LAN turns out to be common.

### Phases 34 and 35 — Freelance hours in Kronos (planned, 2026-11-01)

**Why.** Besides the job Kronos tracks, Miguel now also works as a freelancer (autónomo), by the
hour and outside his working hours, for clients that may pay in US dollars. A separate app (not in
this repository) did the sums for that side: a rate calculator with the Spanish taxes of a
freelancer. That app is being retired, and Kronos becomes
the one place for both: what he worked, as an employee and as a freelancer, and what the freelance
part is really worth after Social Security and income tax. The decision this serves is a real one:
whether, in a year or two, the freelance work could replace the job.

**What already exists for this.** The tax engine was moved in before these phases and is the single
source of every tax figure: `backend/app/services/tax.py` with the 2026 figures in
`backend/app/data/fiscal_es.json` (RETA cuota by tramos or the tarifa plana; IRPF by the state +
Andalusian scales; with a salary, the freelance income is taxed at the marginal rate on top of it;
the 130 apart from what is left for the Renta; the pluriactividad refund; a year without its own
block uses the latest earlier one), and `GET /api/fx` (`backend/app/services/fx.py`), the ECB's
EUR/USD reference rate, fetched only when asked and at most once an hour. `tests/unit/test_tax.py`
works two reference cases by hand (a few hours a day on top of a salary, and full time with no
salary); read it, and the module docstring for what is not modelled.

**How to approach it.** These two phases describe outcomes and the decisions Miguel already took;
the shape of the screens, the names, the data model and the order of the work are the
implementer's to design, and a better idea than the one written here is welcome, said out loud
before it is built. Where this text is silent, make a choice and say why; where a choice would
change what Miguel sees or stores, ask first.

#### Phase 34 — Freelance hours next to the working day

A day can be mixed: 4 h worked as an employee, half a day of paid vacation, and 3 h of freelance
work in the evening. Kronos must log that day easily and show it truthfully.

- **Freelance hours are blocks of their own**, several per day if need be, each with hours (or a
  start and an end) and a note. They never count towards the employee's daily target, balance,
  streaks or the printable timesheet: that sheet goes to the employer and must not change.
- **Every block has a rate.** Settings hold income sources (name, hourly rate, currency EUR or USD;
  one is the default). A block takes the rate and currency of its source when it is saved, so a new
  rate never rewrites the past. A USD block also keeps the ECB rate of its own date, taken once when
  it is saved (a weekend or holiday takes the last published day) and editable by hand; it is never
  fetched again. Today's `/api/fx` only knows the latest rate: extending it to the rate of a date
  is part of this phase, with the same discipline (fetched on demand, never on a timer).
- **The Log tab is where this must feel good.** Adding, adjusting and removing a block on a day
  that already has employee hours should be quick on a phone too. How it looks is open.
- **Settings get a first level.** Today the gear opens one list (Work, Leave, Holidays, Profile,
  Templates, Data) beside the content. It becomes three groups: **Employee** (Work, Leave, Holidays,
  Profile, Templates), **Freelance** (income sources and rates, taxes, currency) and **General**
  (Data). On a phone the two levels must still fit (Miguel suggested two dropdowns above the
  content).
- **Taxes are per year** (Freelance → taxes): the gross salary of the job held at the same time,
  the tarifa plana, the 20 % start-up reduction and the share of each payment set aside for the
  tax office (40 % by default). A year without values of its own uses the latest earlier year's.
  The region is Andalucía, the only one in `fiscal_es.json`.
- Backups, restore and the CSV export carry everything new (the backup fidelity test must keep
  passing with freelance data in it).
- Decided not to do: no check that a freelance block overlaps the employee hours of that day.

#### Phase 35 — What the freelance hours add up to

- **A Freelance tab.** Two parts:
  - *This year, for real*: gross income in euros, hours, average EUR/h, and, quarter by quarter,
    the 130 to pay (20 % of the net yield accumulated since 1 January, less what earlier quarters
    already paid) with its deadline; a projection to the end of the year from planned freelance
    hours per week and weeks off (two settings).
  - *Calculator*: hourly ⇄ daily ⇄ net yearly, three linked fields that drive each other; rates in
    EUR or USD with the rate on view (the ECB's, or one typed by hand); every assumption on view
    and editable (billable days, 220 by default, or the calendar's; hours per day; salary; the
    switches), starting from the year's real values; how the IRPF is paid ("the 20 % goes every
    quarter, the rest in the Renta"); "estimate: check with an adviser". The two reference cases
    of `tests/unit/test_tax.py` must come out to the cent.
- **The Dashboard** gets a freelance card, only when an income source exists: hours and gross
  income this week and this month, and how much to set aside. The employee hero stays as it is.
- **Analytics** separates the hours (employee and freelance stacked in the chart, a switch on the
  heatmap) and adds freelance income per month and the effective EUR/h before and after tax. The
  salary is not logged day by day, so there is no employee income here.
- The `/api/fx` discipline holds everywhere: the page asks when the user navigates to a view that
  needs a rate or changes a currency option; never on a timer.

**Constraints (both phases).**
- One source of tax maths: `tax.py` and `fiscal_es.json`. The browser shows what the API computes
  and keeps no copy of the formulas; a tax figure in a test is worked out by hand in a comment.
- The printable timesheet and the employee balance must not move because of freelance data.
- The repository is publicly mirrored: no personal data, salaries, clients or schedules in code,
  fixtures or docs.
- Existing tests are updated when behaviour changes on purpose, never weakened; the hygiene tests
  (models ⇔ migrations, no phase numbers in code, one line ending per file) keep passing; new
  behaviour gets tests that fail without it.

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
