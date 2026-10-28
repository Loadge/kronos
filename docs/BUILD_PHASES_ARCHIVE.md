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

## Phase 24 — Partial-Day Leave
Confirmed by Miguel and deployed to PROD 2026-10-27.

**Why.** Vacation / sick / holiday / flex were whole-day only, but real leave is often part of a
day (a morning off, leaving at 15:00 sick). The plan said "half-day (0.5)"; during design Miguel
widened it to **any number of hours** — the 0.5 granularity was an arbitrary limit, and a slider in
hours is how people think about it.

**Decisions.**
- A leave entry carries `fraction`, the share of the day that is leave (`0 < f ≤ 1`, REAL, migration
  `0007`, existing rows backfilled to 1.0). Stored as a fraction rather than hours so a whole day
  stays whole even if the target timeline is edited later; the UI converts with the target in force
  on that date. Work days are always 1.0 (422 otherwise). Rejected: a `half_day` boolean (too
  rigid) and keeping `day_type = work` with a "leave annotation" (bulk logging and the planner
  need leave to be the primary type).
- **The rest of the day is worked, and logged on the same row.** A partial leave entry accepts
  start/end/breaks, optional — without them net is 0, like an in-progress work day. Whole-day leave
  still rejects times. Rejected: time-less partial days (every half vacation would show −4h).
- Maths: vacation / sick / holiday charge `T × (1 − f)`; flex still charges the whole `T` (it rests
  on banked surplus; the hours worked offset it). 3h of vacation on an 8h day with 09:00–14:00 worked
  is neutral; a half flex day with its 4h worked costs −4h.
- `work_days` / `non_work_days` became floats in every summary (a 3h-off day is 0.62 work + 0.38
  off, so a week still adds up). `vacation_days_used` sums fractions; `vacation_budget_days` accepts
  halves (22.5, `multiple_of=0.5`).
- Log tab: a "Time off" slider in hours, quarter-hour steps, top = that date's target = whole day
  (the top rounds up to the next quarter hour so a 7.33h target still has a whole-day position).
  Below the top the time fields appear. The bulk modal and the dashboard quick-log stay whole-day
  on purpose (edit the day afterwards); the batch *API* takes an optional `fraction` for the
  planner.
- Display: calendar / heatmap / week cells split diagonally (leave colour for its share, then the
  worked part's surplus colour; `background-image` longhand with `background-origin: border-box`,
  or the gradient tiles into the cell's transparent border); pills read `vacation · 3h`.
- Backup is version 2 (entries carry `fraction`); restore accepts 1 and 2, so an old Kronos refuses
  a v2 file loudly instead of flattening partial days. CSV gains a `fraction` column after
  `day_type`; a missing or blank cell is a whole day.
- Edge rules: the on-target streak skips partial days like other non-work days; longest/shortest
  work-day records and the weekday-pattern chart consider full work days only.

**Tests.** 24 unit, 45 API, 7 Playwright (414 pytest + 67 e2e). Migration checked up and down on a
real file. The CSV round-trip test deletes through the entries endpoint, not the bulk wipe, because
of the Phase 19 harness quirk (orphaned breaks under the test engine).

**Known limits.** Partial days are whole-hour-agnostic but the slider steps in quarter hours; a
fraction set through the API can be anything in (0, 1]. Holiday import is whole-day only.

**Commits.** `17c2cdb` Phases 24–26 together; pipeline 257 (INT and PROD). Phase numbers were kept out of the code on purpose (Miguel's rule: managerial
detail belongs in `docs/`) — the 13 older "Phase N" comments in `app.js` / `styles.css` /
templates predate that rule.

---

## Phase 25 — Time-Off Planner
Confirmed by Miguel and deployed to PROD 2026-10-27.

**Why.** Kronos was retrospective. The planner pencils in vacation / holiday / flex before the
days arrive and shows where the balance lands at Dec 31 and what the plan leaves of the vacation
budget, then commits drafts into real entries.

**Decisions.**
- Drafts are server-side: a `plans` table (migration `0008`; date PK, type, fraction, notes) and
  `/api/plans`. Rejected: localStorage (templates had already moved off it for surviving a browser
  change) and a `planned` flag on `work_entries` (every computation would have to filter it, and a
  draft would block logging the real day).
- Plannable types: vacation, holiday, flex — not sick, not work. Whole days in the UI; the API and
  the backup carry a `fraction`.
- A draft never blocks a real entry. The entry wins; the draft shows as "already logged" in the
  ledger until dismissed or committed (commit just drops it). Logging a drafted day from the Log tab
  consumes the draft. Commit is per block (consecutive days of one type and note, weekends in
  between allowed), copies the note, and uses the batch skip rule.
- Projection is server-side (`GET /api/plans/projection?year=`), with `project_balance()` as a
  pure function. **On target** is the default — it is how Miguel thinks: only leave moves the
  number, flex drains `T(date)`, vacation / holiday are neutral. A remembered toggle shows **at my
  pace** (open scheduled days add the average surplus per work day so far). Real entries after
  today count as they are and beat drafts. Horizon = Dec 31 of the shown year; with an annual reset
  a next-year projection starts from zero. The planner's "vacation logged" counts the whole year
  (days logged ahead included), unlike the dashboard's "used so far".
- The dashboard forecast subtracts the drafted days (and drafted flex hours) instead of the whole
  remaining vacation budget once anything is drafted, and links to the planner.
- UI chosen from three mockups (`docs/mockups/plan-p{1,2,3}.html`): P2 — stat cards, one
  working month, a ledger interleaving drafts with logged time off, year switcher — plus P3's
  year strip of twelve mini months as the month picker. Drafts are dashed ghost cells on the Log
  calendar (click pre-fills the form), the Week view and the heatmap. A dragged range drafts (and
  highlights) work-week days only; a click takes any day. Bulk modal and quick-log unchanged.
- From Miguel's UX pass: days that can't be drafted (logged, or in the past) open in the Log tab
  with that day selected; logged ledger blocks can be deleted (Log tab's confirm) or opened in Log.
- Pico styles `[role=group]` as a full-width button group: the year switcher is a `nav`, the
  toggle a `radiogroup`.

**Tests.** 15 unit (projection), 35 API, 14 Playwright (464 pytest + 81 e2e). Migration `0008`
checked on a real file.

**Known limits.** Partial drafts only through the API. The ledger merges blocks by type *and* note,
so two notes on adjacent days make two rows. No "commit all" — per block only, by Miguel's choice.

**Commits.** `17c2cdb` Phases 24–26 together; pipeline 257 (INT and PROD).

---

## Phase 26 — Printable Timesheet / PDF Export
Confirmed by Miguel and deployed to PROD 2026-10-27.

**Why.** A clean timesheet for records, an employer, or invoicing, without a PDF library: the
browser's "Save as PDF" is the export.

**Decisions.**
- Audience: records first, so a dual detail switch — *Compact* (date, weekday, type, start, end,
  breaks, net) and *Full* (adds target, Δ, and a running Σ that starts at zero on the sheet's first
  day). Every calendar day is listed; weekends shaded; a past work-week day without an entry is
  flagged "not logged"; future days print empty. Whole-day leave prints its type only — blank net /
  target / Δ, Miguel's choice over `0:00 ±0:00` — partial leave its hours off next to the type.
- Periods: *this month* and *this year* stop at today (an employer doesn't want sixty blank rows),
  *last month* / *last year* are whole, custom ranges print as given; over three years is refused.
  A range spanning months gets a heading and a subtotal row per month. Grand totals (net, target,
  balance, time off by type + not-logged count), a legend, optional signature lines.
- Hours as decimal (default) or h:mm. Notes column and signature lines opt-in. Light (default) or
  dark — dark for people who only want the PDF; `print-color-adjust: exact` keeps it dark when
  saved. The picker remembers every choice except the theme, which always starts Light (light
  prints best).
- Identity: three optional settings (Settings → Profile: name, employer / client, extra line),
  printed top-right only when set, in the backup. Rejected: a single free-text header.
- `GET /timesheet` is a server-rendered Jinja page with its own stylesheet, no Alpine, no app
  chrome; the toolbar is a GET form, so every switch is a query parameter and a URL is a report.
  `services/timesheet.py` builds the rows as data (pure, unit-tested); the template has no
  arithmetic. Entry point: a **PDF** button on the Days tab (Miguel's name for it) with a picker,
  plus a palette command. Rejected: a print stylesheet over the Days tab (a tool, not a document),
  any server-side PDF dependency.
- Mockups first (`docs/mockups/timesheet-t{1,2,3}.html`, rendered from seed data):
  Miguel chose T2's detail with T3's month sections.
- Found in review: the service worker's stale-while-revalidate cached report pages by URL, so
  "last month" could show the previous visit's numbers first. `/timesheet` is network-only now,
  and the shell cache name was bumped (it had not been for phases 24–25).
- From Miguel's UX pass: toolbar reloads keep the scroll position; the two date inputs bound each
  other (`min`/`max`) on the page and in the picker, so an inverted range can't be submitted (the
  server's 422 remains for hand-edited URLs).

**Tests.** 27 unit, 22 API, 12 Playwright (513 pytest + 93 e2e); one e2e test runs Chromium's PDF
printer on the page and checks a real PDF comes out.

**Known limits.** No page numbers in the footer (CSS page counters aren't reliable in Chromium;
the browser's own header/footer option adds them). Notes are printed as-is, one line per day.

**Commits.** `17c2cdb` Phases 24–26 together; pipeline 257 (INT and PROD).

---

## Phase 31 — Visual Redesign: Navigation, Dashboard + Week, Settings, Days
Built 2026-10-28 in one session with Phase 31/33; not yet confirmed by Miguel or deployed.

**Why.** Seven tabs since the planner arrived; a dashboard of three cards, two tiles, a forecast
sentence, a button and four pills, with the milestone toast over its first line; Settings as one
1280 px column where a single number took a whole row; a Days table whose note icon pushed the
Edit button around. One phase on purpose: the four parts share one visual language.

**Process.** Interview first (2026-10-27), then three mockups with all screens in each and a
working theme toggle (`docs/mockups/redesign-r{1,2,3}.html`, index in `docs/mockups/README.md`):
R1 "Chronograph" (a dial with subdials, the forecast as a dashed arc), R2 "Trajectory" (a
sparkline of the balance per day with a dashed projection), R3 "Ledger" (typographic, a year
runway). **Chosen: R2 throughout with R3's card-per-section Settings and R2's gear.**

**Decisions.**
- Navigation 7 → 5: Dashboard · Plan · Log · Days · Analytics. Week folded into the Dashboard;
  Settings behind an eight-tooth gear next to the theme toggle (brass on dark, ink on light,
  quarter-turn on hover, slow turn while open). Log stays a tab — the slide-over idea was dropped
  rather than redo Phase 22's three-column Log. Key **W** and the palette's "Week" went; **S**
  stays. Top bar on the phone, no bottom bar. From the UX pass: the first letter of a tab with a
  shortcut is brass (P · L · D · A), Escape goes back to the Dashboard from any tab (it used to
  from Log only; overlays, fields and edits still dismiss first), the palette's hints stopped
  advertising digit keys that never existed, and clicking a tab no longer leaves a blinking caret
  (`user-select: none` + transparent caret; Chrome on Windows painted the collapsed selection).
- Dashboard: no prose. The cumulative balance is the hero, "since Jan 2025 · 8h a day" captions,
  today + live clock a chip. Next to it the **trajectory** — the balance after each logged day of
  the year, then a dashed line to Dec 31 at the forecast value — from the new
  `GET /api/analytics/cumulative-series?year=` (each point equals the as-of cumulative; entries
  before Jan 1 fold into `opening`; one call, not one per day). Week · month · vs last year as
  chips with a bullet bar centred on zero; the day counts the old cards printed are the chips'
  tooltips; yoy is fetched by the dashboard itself. The week as seven tiny bar charts (hours
  worked plus hours off, target as a dashed rule, drafts as ghost bars), always the current week —
  the Week tab's prev/next went, by Miguel's preference for the simple thing. Quick-log only
  while today is empty. Vacation as notches (used / planned / left, fractions fill part of one).
  Rejected: R1's dial (Miguel liked R2), keeping the week navigation.
- Draggable layout retired end to end: `/api/config/dashboard-layout`, service, schema, tests,
  the vendored SortableJS and its CSS. The backup never carried the key; a `dashboard_layout`
  row may linger in existing `settings` tables, unread.
- The save ribbon / milestone toast is fixed to the bottom of the viewport.
- Settings: one page, a scroll-spied index (IntersectionObserver; chips on the phone), one card
  per section (Work · Leave · Holidays · Profile · Templates · Data), the save in the card header,
  enabled only while that section is dirty, sending only its fields (`PUT /api/config` already
  took partial bodies). Rows: label + hint left, a control sized to its content right — the real
  complaint was "a lonely 8" spanning a 2K screen. Saving stays on the page; Ctrl+Enter saves all.
  "Fun zone" kept its name. `btn-action` became a real brass button (Pico's primary stayed blue
  because only `--pico-primary` was mapped; the focus ring followed later).
- Days: row click edits, a ✎ in a fixed action column (hover/focus; always on the phone), a
  weekday column, sticky header (the wrap no longer scrolls on desktop so the page is the
  scroller), a separator with count · net / target · Δ per month under the date sort only, notes
  always visible in the last column (markdown, search highlights in place; hidden under 640 px),
  "N entries · PDF" in the top bar. The notes toggle went. `editEntry()` mirrors `#log` into the
  hash like `go()`.
- Housekeeping: the ten old mockups moved from `backend/static/mockups/` to `docs/mockups/`, so
  they stopped shipping in the image. Service worker cache v29.

**Tests.** 5 API (the series), 10 Playwright (`tests/e2e/test_redesign.py`) plus the caret and
Escape tests in `test_navigation.py`; the affected e2e tests updated (tab count, table columns,
chips for cards, the strip for the Week tab, the gear for the Settings tab). The tick-up
animation is idempotent — a background refresh with unchanged numbers no longer restarts it,
which the e2e suite caught. The sandbox reviewer (`bin/review_sandbox.sh`) came out of this
phase's review round.

**Known limits.** The trajectory draws logged days only (an unlogged work day is a flat step, as
in the Σ column). Under 640 px the notes column is hidden; the note is reachable through the row.
The series endpoint is the seed of Phase 33's per-day chart.

**Commits.** One commit for Phases 31 and 33 on branch `phases-31-33`.

---

## Phase 33 — Interactive Analytics
Built 2026-10-28 in one session with Phase 31/33; not yet confirmed by Miguel or deployed.

**Why.** Analytics was hand-drawn SVG with nothing interactive — a thin trend line with one
point per month, fixed monthly bars, month cards Miguel called "derpy and useless" — and
after Phase 31 it was the page left behind. Miguel wanted what Pi-hole and Proxmox do: draw a
rectangle on the chart and it becomes the new focus. One rule from the start: Year at a glance
stays, whatever happens.

**Process.** Interview (2026-10-28), then two mockups in which the chart already worked
(`docs/mockups/analytics-a{1,2}.html`): A1 "chart first" (full width, the range's numbers as
chips under it) and A2 "chart + ledger" (the range's numbers in a ledger beside it, presets in
the ledger). **Chosen: A2 entirely.**

**Decisions.**
- **Engine: hand-drawn SVG**, like the dashboard's trajectory — the same look, no new
  dependency. Rejected: Chart.js + its zoom plugin (the plugin and hammer.js for touch were two
  more files to vendor, and the sandbox has no network). Chart.js, vendored since the start and
  loaded nowhere, was removed.
- **Zoom:** drag a rectangle → that x-range is the view and y rescales to what is visible;
  wheel zooms at the cursor; shift+drag and the history strip under the chart pan;
  double-click and Reset go back to *This year*; presets This month · 3 months · This year ·
  12 months · All; never narrower than 7 days. Touch: one finger pans, two pinch
  (`touch-action: pan-y` so the page still scrolls). Pointer events are attached once to the
  wrap; the svg inside is rebuilt as markup on every render, because Alpine's `x-for` cannot
  live inside `<svg>`.
- **The range drives the page:** the ledger (balance, net, target, per work day, work / off
  days, vacation · sick, logged days), the weekday pattern, the histogram and the records are
  computed client-side from `/api/entries` for the visible range. The "All years" page filter
  went; a year select stays on Year at a glance only.
- **Series switch:** Balance (cumulative per day across all years, from the new
  `GET /api/analytics/cumulative-series?all=true`, restarting at zero each January 1st under an
  annual reset) · Per day (net hours + hours off as bars coloured by type, the target dashed) ·
  Per month (net vs target). **Monthly breakdown went** — bars and cards; `/api/analytics/monthly`
  and `/records` stay in the API for the CLI (Phase 32).
- **Weekday pattern** became a bar per weekday above / below zero with the average start → end
  under it ("when do I really arrive and leave?"). **Daily surplus**: a histogram in half-hour
  buckets from −3h to +3h with the share within ±30 min — the one new view Miguel wanted to
  try; the month-vs-same-month-last-year view was dropped to keep the page lean. **Records**
  shrank to two columns of one-line rows (Miguel: "way less space, at least on desktop"), per
  range, plus earliest start and latest end; the 2026-10-02 rule stands (a "worst" only when
  negative). **Years** (carry-in) and **Export** stayed.
- **Year at a glance:** a tooltip per day (weekday and date, hours and Δ or the type, the note,
  a draft as "planned") and click → that day in Log, new entry if empty. The cell's `title`
  became `aria-label` so the native tooltip does not double the custom one.
- Order: Year at a glance · Balance over time · Weekday pattern · Daily surplus · Years ·
  Records · Export.

**Tests.** 1 API, 7 Playwright (`tests/e2e/test_analytics_chart.py`: rectangle and wheel zoom,
reset, presets driving the ledger and the records, the series switch, weekday times and the
histogram, the heatmap tooltip and click); the three older Analytics e2e files updated.

**Known limits.** The hover readout exists on the Balance series only (bars carry native
titles). The histogram clips beyond ±3h and says how many days it clipped. The history strip
shows the balance whatever series the chart shows. The demo GIF predates both redesigns.

**Commits.** One commit for Phases 31 and 33 on branch `phases-31-33`.

---

## Archiving a phase
When Miguel confirms a phase is live: replace its block in `BUILD_PHASES.md` with one row in the
"Done" table there, and add a summary here in the same docs commit (what was decided, what shipped,
what was left undone and why, the commit shas). Keep what a future session cannot get from the code:
decisions and their reasons, rejected options, known limits. Drop what the code and tests say better
(endpoint lists, test counts). Open phases and anything awaiting confirmation stay in
`BUILD_PHASES.md`.
