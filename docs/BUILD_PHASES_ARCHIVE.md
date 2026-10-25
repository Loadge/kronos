# Kronos — Build Phases Archive

Completed and confirmed phases of `BUILD_PHASES.md`, summarised: what each one decided and shipped,
what it left undone, and where the detail is. **Not loaded by default**: read it when you need the
history of a decision. The code and the tests are the current truth; this file is the "why". The
phase blocks as they stood before archiving are in git: `git show 04f0ec1:kronos_plan.md` (the plan
was `kronos_plan.md` at the root until 2026-10-25). Git history starts at Phase 11: Phases 1–10 have
no commits of their own.

How a phase gets here: see "Archiving a phase" at the end.

---

## Phases 1–10 — The base app
- **1 Scaffolding.** FastAPI + Alpine.js + Pico CSS, no build step; Docker + `deploy.sh`;
  `/healthz`; static files from `backend/static/`. Lorca later copied this layout.
- **2 Database.** One `Entry` row per date (date is the primary key), so a day can never be logged
  twice; breaks as JSON; Alembic; SQLite in WAL mode. All writes go through the `entries` router.
- **3 Log tab.** Day types work / vacation / sick / holiday / flex; breaks as time ranges or raw
  minutes; choosing a date that is already logged opens it in edit mode.
- **4 Dashboard**, **5 Days tab** (paginated, year filter, inline edit), **6 Analytics** (year
  filter, "as of date" cumulative view), **7 Settings** (daily target, cumulative start date, annual
  reset, work-week picker).
- **8 Backup / export.** `GET /api/backup` / `POST /api/restore` swap the whole DB; CSV export.
- **9 UX polish.** Command palette (`.`), keyboard shortcuts, dark/light theme in localStorage,
  PWA manifest.
- **10 Shortcut hint and calendar picker.** A `⌨` button shows the shortcuts. The date input was
  replaced by a month calendar because `<input type="date">` fired its change event on partial
  values and probed half-typed dates; clicking a cell sets a whole date. Logged days use the
  heatmap's `hm-*` colours.

## Phase 11 — Bulk date logging (`ac562e1`)
A modal calendar where click toggles a day and click+drag selects a range, then one non-work type
is applied through `POST /api/entries/batch`. Existing entries are skipped silently, never
overwritten; `work` is rejected (422), since a work day needs times.

## Phase 12 — Server-side templates (`5409030`)
Day templates moved from localStorage to a `templates` table so they survive a browser change. The
first load after the upgrade uploaded the localStorage templates once and cleared them.

## Phase 13 — Clock in / clock out (`e514613`)
One-tap buttons on the Log tab and the Dashboard stamp now as start or end time. They show only
while today is incomplete, so a finished day is never stamped over.

## Phase 14 — Public holidays auto-population (`0679290`, preview `cee88f8`)
Country + optional region in Settings import that year's holidays as `holiday` entries, fetched
server-side from Nager.Date with stdlib `urllib` (no new dependency, the browser never calls it).
The region filter is required for correctness: without it a country imports every region's
holidays. A read-only preview shares the import's filter logic and shows what will be imported
and what is already logged. Local/municipal fiestas are not in the data and are logged by hand.
Superseded for Spain by Phase 27.

## Phase 16 — Notes search (`d688dea`)
Filter on the Days tab by note text, pure frontend, highlights the match, clears on tab switch.

## Phase 17 — Week view (no commit of its own)
Mon–Sun with hours and surplus per day and the week total. Pure frontend: summing the week's
entries reproduces the backend `summarize()`, so the total stays equal to the Dashboard's "This
week" card, which now opens the Week tab. Shortcut **W**.

## Phase 18 — Streaks & milestones (`8248dd5`)
`GET /api/streaks`: logging streak (consecutive calendar days with any entry; anchored at yesterday
while today is still empty, so it doesn't drop to 0 mid-day) and on-target streak (consecutive work
entries with surplus ≥ 0; non-work days in between don't break it). The 30 / 100 / 365 milestone
toast is frontend-only, with a localStorage watermark so it fires once.

## Phase 19 — CSV import (`01f4de5`)
Imports the export's own CSV format. The file is read client-side and posted as text so
`python-multipart` is not needed. Same skip rule as batch (existing dates and repeated dates in the
file); bad rows are collected as errors, not fatal; a work day's total break becomes one break.
Test-harness quirk: the test engine does not set `PRAGMA foreign_keys=ON`, so a bulk wipe orphans
breaks there; production enforces the cascade.

## Phase 22 — Log tab UI overhaul (`0e9d347`)
Three columns: sticky calendar / form card / notes panel. The "Now" pill moved to the label row,
the template bar became a dropdown, "Save as template" a collapsed `<details>`, and "Create entry"
the only solid primary button.

## Phase 23 — Date-effective daily target (`31bd9ba`)
A single global target silently corrupted every cumulative number spanning a contract change
(8h → 6h). The target is now a timeline (`DailyTargetSchedule`, most recent row on/before each
date), stored as JSON in the KV table, so no schema migration. Before a timeline exists it is
synthesised from the old single value, so existing deployments read unchanged. The plain "Daily
target hours" field writes only the latest row and never wipes history. The timeline rides in the
config, so backup/restore carries it; older backups fall back to the single value.

---

## Phase 27 — Spanish Holidays from the BOE
Confirmed by Miguel and deployed to PROD 2026-10-19.

**Why.** Phase 14 took Spain from Nager.Date, which is wrong for every Spanish region: it leaves
national holidays that fall on a Sunday on the Sunday (1-nov and 6-dic 2026, 15-ago 2027) instead
of the Monday the regions move them to, and it misses each region's own choices (San José, Easter
Monday, substitutions). Against the official list it differed in all 19 regions (76 differences in
2026, 46 in 2027). Madrid 2027: the BOE has 19-mar and 16-ago, Nager 2-may and 15-ago.

**What shipped.**
- Spain comes from the yearly resolution of the Dirección General de Trabajo ("relación de fiestas
  laborales"), fetched as XML from `boe.es/diario_boe/xml.php?id=<id>`. `services/boe_holidays.py`
  parses its table (one row per date, one column per region; `*`/`**` national, `***` the region's
  own, so only `***` shows as "regional"; a mark with a footnote call still counts). Header texts
  drift between years, so columns map to ISO codes by keyword; an unreadable table raises (→ 502)
  rather than returning partial data.
- `BOE_RESOLUTIONS` maps year → BOE id (2026: `BOE-A-2025-21667`, 2027: `BOE-A-2026-21254`).
  **Add the next year's id each October.** A Spanish year without one is a 404 that says so, never a
  fallback to Nager; the Settings preview shows that error instead of an empty calendar.
- Without a region, Spain imports only the holidays all 19 regions share. Subdivisions for ES are the
  19 BOE columns. Every other country still uses Nager.Date.
- Settings lists the previewed holidays one per line under the legend ("Thu, Jan 1 — Año Nuevo",
  "regional" tag, "already logged" note), asked for by Miguel while checking INT.

**Tests.** The two real XML files are fixtures (`tests/fixtures/boe/`, kept byte-for-byte by
`.gitattributes`). ES-MD 2027 imports exactly its 12 official dates; the Spain API tests make Nager
raise, so routing Spain back to Nager fails 7 of them (checked by planting it). 19 new tests (345
total). The holiday list has no automated test: the preview depends on the live BOE fetch.

**Known limits.** Canarias' island holidays and Arán's substitution live in the table's footnotes and
are not imported (log them by hand, like local fiestas).

**PROD data at the time** (read-only check, 2026-10-16): the 2026 holidays already matched the BOE
for ES-MD (fixed by hand earlier); 1-may was stored as `vacation` and 12-jun / 19-jun as holidays
without a note — left for Miguel.

**Commits.** `bfdffe1` Phase 27 — Spanish Holidays from the BOE; `a1c8bff` the holiday list.
Pipelines 218 and 233 (PROD from 233).

---

## Archiving a phase
When Miguel confirms a phase is live: replace its block in `BUILD_PHASES.md` with one row in the
"Done" table there, and add a summary here in the same docs commit (what was decided, what shipped,
what was left undone and why, the commit shas). Keep what a future session cannot get from the code:
decisions and their reasons, rejected options, known limits. Drop what the code and tests say better
(endpoint lists, test counts). Open phases and anything awaiting confirmation stay in
`BUILD_PHASES.md`.
