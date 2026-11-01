# Interview record — `kronos` CLI for agents (`BUILD_PHASES.md`, Phase 32)

Four rounds, 19 questions, 2026-10-30. The answers below are the spec the implementation
follows; anything not listed here is an implementation detail the implementer decides and
documents in `BUILD_PHASES.md` when the phase is marked built.

## Decisions

| # | Question | Answer |
|---|---|---|
| Q1 | Script location / invocation | `bin/kronos.py`, run as `python bin/kronos.py <cmd>`, stdlib only (`urllib`, `argparse`), like `kctl.py` / `smoke.py`. **No** console entry point / packaging for now. |
| Q2 | Target resolution | Env vars `KRONOS_LOCAL_URL`, `KRONOS_INT_URL`, `KRONOS_PROD_URL`; git-ignored `kronos.env` at the repo root (`KEY=value` lines, `kronos.env.example` committed); env wins over file; `local` defaults to `http://localhost:8765`; `int` / `prod` have no default and fail with a hint; `--target` defaults to `local`. |
| Q3 | `log` on an already-logged date | Fail (the API's 409) unless `--replace`, which does a `PUT`. |
| Q4 | PROD backup mechanics | **UNRESOLVED** as asked (Miguel asked for options with pros and cons instead). Reopened as Q6. |
| Q5 | Meaning of "optimisations across the app" | No limits; the implementer's list (Q18) was accepted in full. |
| Q6 | PROD backup mechanics (reopens Q4) | **Option B**: before every write to `prod` (not `int`, not `local`) the CLI saves `GET /api/backup` to `backups/<target>/kronos_backup_<UTC timestamp>.json` (git-ignored); fails closed (no backup → no write); skipped under `--dry-run`; no `--no-backup` flag; `restore` takes the backup on **every** target; retention keeps the newest **50** files per target. |
| Q7 | Who stamps "now" for `clock in|out` | **Option B**: new `POST /api/clock/in` and `POST /api/clock/out` stamp server time in `TZ` (optional `at`, `date`, and `breaks` on clock-out); the CLI calls them. |
| Q8 | `--dry-run` and "the resulting day" | **Option B**: new `POST /api/entries/preview` validates like create/update and returns the `EntryOut` it would produce, writing nothing. Dry-run may do GETs / read-only calls (`/api/holidays/preview` for `holidays import`, local validation for `restore`) but never a write. |
| Q9 | Ranges and `plan commit` | `log` and `plan add` accept a date range `A..B` and repeated dates for non-work types (batch endpoints); `plan commit` exists; `plan` (read) takes `--year`, default current year. |
| Q11 | `--hours N` → `fraction` | **Option B**: the API accepts `leave_hours` as an alternative to `fraction` on `POST/PUT /api/entries`, `/api/entries/batch`, `/api/entries/preview` and `POST /api/plans`; the server resolves the date's target and derives the fraction; both given together, or hours ≥ target, is a 422. |
| Q12 | Guarding `restore` | **Option B**: `--yes` is required for `restore` on every target (on top of the automatic pre-restore backup). Ordinary PROD writes need no flag. |
| Q13 | What `today` prints | **Option B**: today's entry (or "not logged" / "in progress since HH:MM") plus the week / month / cumulative balances and the streaks. `balance` prints only the numbers. |
| Q14 | How the work lands | On `master`, one commit (code + tests + docs); `BUILD_PHASES.md` Phase 32 block becomes "built, awaiting confirmation" with the decisions; the archive is untouched until Miguel confirms; README updated; this file at `docs/interview_spec.md`. |
| Q16 | Proving the PROD path without a network | Accepted: `KRONOS_BACKUP_DIR` env override; e2e tests point `KRONOS_PROD_URL` at the live test server (backup exists, is a valid v2 snapshot, was written before the entry), at a dead port (exit 3, no entry, no file), `int` takes no backup, retention keeps exactly 50; unit tests for target resolution. |
| Q17 | Smoke coverage | **Option B**: `kronos check [--target]` runs the read commands against the target and reports OK/FAIL per command with an exit code (GET-only, safe on prod); e2e tests pin it green against the live server and red against a dead port. `bin/smoke.py` unchanged. |
| Q18 | Optimisation list | All accepted: (1) N+1 `session.get` loops → one `IN` query (dashboard planned days, `list_plans`, `draft_plans`, `commit_plans`, `batch`, holiday import/preview, CSV import); (2) `_whole_history` and the vacation / plan sums filtered in SQL; (3) `projection` reuses the entries it loaded; (4) `summarize` resolves the schedule once per entry; (5) `GZipMiddleware` + `Cache-Control` on `/static/vendor/*`; (6) parallel initial fetches in `app.js`; (7) the migrations-vs-models test runs Alembic in-process. |
| Q10, Q15, Q19 | Stop here? | Continue, continue, **stop**. |

## Details decided by the implementer (stated during the interview, not objected to)

- Time arguments accept `8:30` and `08:30`; stored as `HH:MM`.
- `--break 45` (minutes) or `--break 13:00-13:45` (range), repeatable; `--note` for notes.
- `holidays import` takes `--country`, `--region`, `--year`, defaulting country and region from
  `/api/config` and the year from today.
- Exit codes: 0 ok · 1 API / validation error · 2 usage · 3 target unreachable (or backup failed).
- With `--json`, errors are printed as `{"error": ...}` on stdout; successes are the API payloads.
- `clock in` on a day that already has an entry is a 409; `clock out` without a started day is a
  404; `clock out` on a finished day is a 409.

## Noted during implementation (small departures, all in Miguel's favour)

- Q11 said "hours ≥ target is a 422": implemented as *more* than the target is a 422, while
  hours **equal** to the target resolve to a whole day (fraction 1.0) — `--hours 8` on an 8h day
  is the obvious way to say "the whole day".
- `POST /api/entries/batch` gained `notes` so `log A..B --type vacation --note "trip"` can
  carry the note (the endpoint had none).
- The clock endpoints take `dry_run: true` so the CLI's `--dry-run` shows the stamped day the
  server would write, rather than guessing the server's time client-side.
- A safety backup in the same second as an earlier one gets a `-2` suffix instead of
  overwriting it; retention only ever deletes files of the automatic name shape.
- `kronos targets` (floated in Q16) was added: it prints the resolved URLs and their source.
- The deploy scripts run `kronos check` after `smoke.py`.
- Review finding (2026-10-31): `clock in|out --date <other day>` without `--at` stamped the
  current time onto that day. Fixed at both ends: the API answers 422 when `date` is not the
  server's today and `at` is missing (dry-run included); the CLI exits 2 before any request.

## Out of scope

- A console entry point / `pip install` (Q1).
- Any change to the Phase 28 bot itself; only the CLI it will call.
- Confirmation flags on ordinary PROD writes (rejected in Q6 as noise for an unattended bot).
