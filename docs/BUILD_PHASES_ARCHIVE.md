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

## Phases 34 and 35 — Freelance hours in Kronos (`3baed75`, `9314942`)
Built 2026-11-02, reviewed twice, confirmed by Miguel on 2026-11-04 "as they are".

**Why.** Besides the job Kronos tracks, Miguel works as a freelancer ("autónomo", in Spain), by the
hour, outside his working hours, for clients that may pay in US dollars. A separate rate calculator
did the sums for that side and was retired; Kronos became the one place for both sides. The
question behind it is whether, in a year or two, the freelance work could replace the job. The tax
engine (`services/tax.py` with the 2026 figures in `data/fiscal_es.json`) was moved in beforehand
and stays the only source of every tax figure.

**Process.** The first build had no mockups, because the existing design system fitted every
surface. Two review rounds followed. The first used mockups (`docs/mockups/ux-u{1,2}.html`):
Miguel chose U1's Log, and U2's Days, Analytics and Freelance.

**Decisions on the data.**
- **Blocks are independent of the employee side.** A block has no foreign key to a work entry, so a
  Saturday of freelance work needs no entry, and nothing freelance can reach the target, the
  balance, the streaks or the timesheet. A test pins the dashboard and the timesheet byte for byte
  before and after blocks.
- **A block keeps a snapshot** of the rate, the currency and the exchange rate at the moment it is
  saved. Changing a source's rate later never rewrites old blocks.
- **A source with blocks cannot be deleted (409), only archived.** Archiving hides it from the
  picker and keeps the label of every old block.
- **Tax inputs live per year,** and a year without a row inherits the latest earlier one. The
  gestoría and other expenses were added because the engine needs them, though the spec listed
  neither.
- **Hours are stored as exact minutes.** The API accepts hours or a start and an end.

**FX discipline.**
- A USD block takes the ECB rate of its own date, and a weekend or holiday takes the last published
  day. If no rate is available the block is still saved with no rate: it counts its hours but not
  its money, every sum reports it as missing, and a rate typed by hand repairs it. A silent 1:1 was
  rejected on purpose.
- Rates are fetched only when something asks (saving a USD block, opening Settings, Currency, the
  calculator switching to USD) and at most once an hour. Never on a timer.
- Sums add each block at the cents it shows, so a list and its total always agree.

**The tax maths.**
- The year's tax figures are built on the projected gross (billed so far plus the planned hours to
  Dec 31), because a RETA tramo and an IRPF bracket belong to a year and not to the part of it that
  has passed. The planned hours bill at the €/h realised so far, or at the default source's rate
  before the first block. Days off are spread evenly over the year, since nobody knows when they
  fall.
- The Modelo 130 is 20% of the net yield accumulated since January 1st, minus the earlier
  quarters' payments, never below zero. The start-up reduction does not apply to it, because it
  lowers the Renta instead. The deadlines live in `fiscal_es.json`.
- The calculator is a pure endpoint with every assumption in the body, so the browser keeps no
  formula. The two anchors of `tests/unit/test_tax.py` come out to the cent from the API and from
  the browser.

**Decisions on the screens.**
- The Freelance tab (key F) and the dashboard card appear only once a source exists, so a Kronos
  without freelance keeps its five tabs.
- Settings has two levels (Employee, Freelance, General) and saves by itself: a field after 600 ms,
  a switch at once, with "saved" in the card head. This came from the UX round, where Miguel
  asked for no Save buttons and fewer hints. "Weeks off" became "days off" at the same time.
- The Log tab got a Freelance card of its own that saves a block as soon as it is added, and the
  planner's year strip as the month picker. Removing a block offers Undo for five seconds.
- Days has two sub-tabs, Employee and Freelance, the second with a filter per source. The PDF
  button follows the tab: `/timesheet/freelance` prints one row per block, with no empty days,
  because it goes to a client or the adviser.
- Analytics gets an Employee/Freelance switch on Year at a glance, freelance hours stacked on the
  employee bars, and an Income series. There is no employee income anywhere, because the salary
  is not logged day by day.
- Every tab has one page head, and the year is always the same stepper pill.
- Year at a glance is pinned by a fixed compact bar that appears once the full block has scrolled
  out. The first version, a sticky block that shrank, changed the page height under the scroll and
  made the page bounce to the top. A fixed element takes no room, so nothing moves.

**Backup v3.** It adds the sources, the blocks and the tax years, and versions 1 and 2 still
restore. A file with no freelance section leaves sources and tax years alone but wipes the blocks,
as every restore does. The freelance CSV is a second file, not rows in the entries CSV, because
that format is per date. There is no freelance CSV import: the backup carries the blocks.

**Known limits.**
- The 130's fixed costs are the projected year's RETA spread evenly, not the cuotas actually paid
  month by month.
- Withholdings on the salary and the retenciones a client may apply are not modelled.
- The calendar's billable days count the vacation budget, not the days taken.
- The projection bills a flat rate per week.
- The block editor's start and end are same-day only, like the employee's times.
- The CLI reads the freelance summary in `check` and nothing else.
- Decided not to do: a check that a block overlaps the employee hours of the day.

**Commits.** `3baed75` Freelance hours in Kronos, phases 34-35; `9314942` escape the income source
name in the heatmap tooltip (found in review).

## Phase 37 — Freelance payouts

**Why.** Kronos estimates freelance money as hours times the rate stored on each block. What a
client actually pays differs from that: there are bonuses, and the rate changes from week to week.
A "payout" is what one income source really paid for one ISO week, and wherever it exists it is
the money Kronos uses for that source and week, instead of the estimate.

**Decisions.**
- A payout is per source and ISO week (Monday to Sunday), typed in the source's currency.
- It replaces the estimate in every sum for that source and week, and the blocks stay untouched.
  The hours are still the blocks' hours, so the €/h moves with the money.
- A USD payout takes the ECB rate of the week's Sunday, and it can be edited. With no rate it
  counts as missing, never at 1:1.
- The payout is spread over the week's days pro-rata by each block's estimate, so a week that
  crosses a month or a year edge splits by work date, the 130 and the tax year included.
- A payout without blocks is allowed and counts 0h on the week's Sunday.
- It is entered in Days, in the ⚡ Freelance week headers (one per ISO week, per source). The Log
  tab shows a read-only line when the day's week has one.
- Every total shows the split between paid out and estimated, on the Freelance tab, the dashboard
  card and Analytics.
- The freelance PDF prints a payout line under each paid week, and a payouts CSV joins the export.
- The backup goes to version 4, and versions 1 to 3 still restore.

**How it was built.** Mockups first: Miguel chose P2 (`docs/mockups/payouts-p2.html`), where each
week is one compact line ("estimated", "part paid out" or "paid out", plus a quiet "awaiting
payout") that opens to show the payout of each source. Then five units, each one written by a
Sonnet subagent and reviewed blind before the next: the table and its API, the money rule, the
Days and Log screens, the split on the other screens, and the PDF, CSV and seed. Full spec and
interview: `.agents/changes/backlog/freelance-payouts/`.

**Choices made on the way.**
- One rule computes every euro, `money_lines()` in `services/freelance.py`: the payout's cents are
  split over the week's blocks by largest remainder, so a week always adds up to its payout to the
  cent. The browser follows the same rule through each block's `effective_eur`.
- A payout splits by the blocks' estimates, and by their minutes when one of them has no rate.
- In Days a week is listed under the month of its Monday, but each month's total counts what is
  dated in it, like the Freelance tab, and says "€X of it from W40" when part comes from a week
  listed under the month before.
- A paid week's blocks keep their own estimate, shown muted, in Days and in the Log card.
- The split and the "weeks awaiting a payout" line only appear once at least one payout exists,
  so nothing changes for a year without payouts.
- The freelance PDF without payouts is byte for byte what it was before (a test pins it).

**Review round (2026-11-04, after Miguel tried it on INT).** The blocks of a week hang under its
line, indented, with a thin rail. Paid-out money has its own colour, teal (`--paid`), everywhere it
shows, while estimates keep the brass. The dashboard card shows "Estimated" and "Paid out" side
by side for the week and the month, with the gap against the estimate of the paid part only
("+€40 vs est."). The Log's "in Days" is now a pill button ("W45 in Days").

**Known limits.** A month with freelance money but no week starting in it has no total line in
Days (only a lone block on a Sunday the 1st). Once the first payout is entered, every earlier
week with blocks shows "awaiting payout" until it has one. The heatmap tooltip still shows each
block's estimate.

**Commits.** `e494a3c` Phase 37; `b3bb814` the review round.

## Phase 38 — Quieter Log and live updates

**Why.** After using Phase 37 on PROD, Miguel asked for four things: the work week number on the Log
calendar, a Notes field that does not feel out of place on a big screen, no jump to Days after
logging a day, and a way for Kronos to tell the browser that a newer version is waiting.

**Decisions.**
- The Log calendar has a "Wk" column on its left with the ISO week of each row. Each number is a
  button that opens that week in Days, and a week with no entry and no freelance block is dimmed.
- Days > Employee has a separator row per ISO week while it is sorted by date (W45, its dates, the
  days, net against target and the surplus). The jump lands on it and flashes the week's rows. A week
  with only freelance blocks opens Days > Freelance instead.
- Notes is a "+ Add note" button, like "+ Add break". It opens one textarea in place, stays open when
  the day has a note and folds away when it is left empty.
- From 1100px the right column of the form is a rail with the day's result (net, target, surplus and
  a fill bar) and the Create entry button. Below that the form is one column, as before.
- The two card hints ("the day for the job" and "blocks with their own rate") are gone.
- Saving or deleting a day keeps the user in Log, and the calendar stays on its month. The toast is
  the confirmation.
- The title has a faint "v38" next to it. It is the phase number and is bumped by hand in
  `backend/app/version.py` when a phase lands.
- Every build has an id, a 10-character hash of the static files and the templates. The page carries
  the id it loaded and asks `/api/version` when the tab becomes visible, when the connection comes back
  and every 10 minutes. If the server has another id, a pill says "Update ready — Reload". The page
  never reloads by itself, because the user may be typing.
- The service worker names its cache after the build id, so nobody has to bump it any more. The page
  itself is network-first and `app.js` and `styles.css` carry the id in their URL, so the reload brings
  the new files instead of the cached ones.

**How it was built.** Mockups first for the Notes field (a margin note, a day rail and a full-width
layout). Miguel proposed the "+ Add note" button and kept the rail as the second choice, so the
result is both. Then three units, each one written by a Sonnet subagent and reviewed blind: the week
column and the jump, the Notes button and the rail, and the version, the update check and staying
in Log.

**Known limits.** A week that crosses a month edge gets its separator only above the days of its
later month, with the totals of the whole week. The first time after this deploy, a browser that still
has the old service worker shows the old page once, and the pill needs one more reload to appear,
because that worker serves its cached shell first. The Notes control was not checked in the light
theme.

**Commits.** `7eddb1c` Phase 38; `3fce538` quieter Log, Days and Analytics.

## Phase 39 — One look across pages

**Why.** An audit of the seven pages found the same things drawn differently: the
Employee/Freelance switch sat in two places, exports lived in three, numbers had several formats and
the primary buttons came in four styles. Miguel asked for one rule per thing, and for a guide that
keeps it that way.

**Decisions.**
- The Employee/Freelance switch is the Analytics pill, in the page head, just left of the year selector.
  Days uses it too, and the tab strip with its counts is gone.
- Exports are small pills in the head, named "CSV", "JSON", "⚡ Freelance CSV" and "⚡ Payouts CSV" (Days
  keeps "PDF"). The "Export" blocks at the bottom of Analytics and Freelance are gone.
- Money always shows cents (€1,289.71); charts may round their labels. Hours keep trimmed totals and
  two-decimal deltas. The Freelance calculator speaks Spanish decimals, typed and shown (€28.687,41).
  Dates are still open: Days uses ISO and Plan and the Dashboard use "Thu, Nov 5".
- Five hints were removed by name, and the information they carried moved to tooltips where it was worth
  keeping. The Freelance card no longer says "nothing yet".
- Empty states read "No X yet." with at most one link.
- Page-level titles are all like "Calculator" (Modelo 130 and Upcoming time off included).
- Every primary button has the look of "+ Add block" (`btn-action`); openers such as "+ Add a change" are
  secondary outlines. The year selector stays at the right edge of the head on a phone.
- 👔 marks the employee side next to ⚡ (Dashboard, Settings navigation, Days, Analytics).
- `UI_GUIDE.md` holds these rules with a glossary and a checklist, and three test files enforce what can
  be checked: the page head on every tab, the exports, the hints and the formatters.

**How it was built.** An audit by a read-only subagent, a research agent for the guide, then two Sonnet
subagents on disjoint pages (Analytics, Log, Days and Dashboard; Freelance, Settings and Plan), with the
formatting done by the Advisor because it is money. One red control was missing a first time (the
page-head test read DOM order, so a CSS `order` slipped past); it now compares screen positions.

**Known limits.** The weekday averages keep one decimal on purpose, because the cells are narrow.
Dates keep two forms on purpose (ISO to look things up, short with the weekday to glance at). Follow-up
the same day: the light theme was removed (Kronos is dark only), the line under the title came out, and
the anchor pills and the Settings navigation were fixed (off-centre label, a name on two lines).

**Commits.** `f7f8cd5` Phase 39; `4420f93` the same pill in Days; `2addb57` dark only and a geometry audit.

## Phase 40 — Eyes on the UI

**Why.** Three layout bugs in a row were seen only by Miguel, after the tests were green. He asked for a
practice that looks at the UI, and for the tools to back it.

**Decisions.**
- Ten key screens are compared with approved pictures (`pytest-playwright-visual-snapshot`). The pictures
  are made in the same Linux image as the pipeline, because text renders differently on Windows, and
  `make snapshots` and `make snapshots-update` run from any machine with Docker. They need the same page
  every day, so they use the demo data and a frozen "now": `KRONOS_NOW` is a new setting read by
  `backend/app/services/clock.py`, for disposable instances only. It also replaces the `TZ` trick of the demo GIF.
- Playwright is pinned, because a new Chromium moves pixels; a bump needs new baselines in the same commit.
- Aria snapshots pin the header and the head of every page by role and name, with extra children forbidden.
- axe scans every tab at both widths. Today's serious findings live in an allowlist that can only shrink, and
  `docs/a11y_report.md` explains them.
- A red e2e run keeps its traces, screenshots and picture diffs as job artifacts for two weeks.
- `/ui-review` is a new skill: a fresh reviewer looks at every page against `UI_GUIDE.md` before PROD. It
  advises, it does not gate. No script calling a vision API was built, because that needs an API key and a
  subagent does the same job.
- The scan paid for itself at once: the heatmap cells got a role, the two scrolling areas can take focus, and
  the ⚡ marks are hidden from screen readers on every page, as the guide already said.
- The first `/ui-review` caught a real bug the geometry audit had missed: with a row in its ledger, the Plan
  page scrolled sideways on a phone. The ledger's rows now wrap on a phone, and the audit's data has such a row.

**Known limits.** The contrast findings are recorded, not fixed: the rows of days off in Days are most of
them, and that is a design decision. Baselines are about 1.5 MB, and each approved change adds to the repo's
history. If the snapshot tests flake in two pipelines, they move to a non-blocking job.

**Commits.** `cbd9c68` Phase 40.

## Phase 41 — Kronos on a phone

**Why.** The first `/ui-review` showed that desktop tables were being squeezed onto the phone: Days was 755px
wide inside a 343px space, so Net and the delta needed sideways scrolling, and Notes were hidden altogether.

**Decisions.**
- Up to 640px, each row of Days (Employee and Freelance) is two lines: what the day is and its numbers, then
  times, breaks, the running total and the note. Nothing is dropped and nothing scrolls sideways. The column
  headers go, so sorting by header is a desktop thing, and the pencil goes because the whole row opens the day.
- In Analytics the Range card comes right after the chart on a phone, before Weekday pattern, and the Years
  table fits without scrolling.
- Controls are at least 24px each way on a phone; text links inside a sentence are exempt.
- A label of the Calculator's bar hides when its segment is too narrow for it.
- The geometry audit gained the tap size and the scroll inside Days, and its data now has real rows.

**Known limits.** The Days loading skeleton on a phone was not looked at. The thresholds that hide the
Calculator's labels are estimates from character counts. Desktop did not move: no 1280px baseline changed.

**Commits.** `3808b78` Phase 41; `8be17e5` one arrow on Save as template.

## Phase 42 — One line per week

**Why.** In Days > Freelance the arrow hid the numbers of a week and the days were always there, so seeing the
next week meant scrolling past every block. Miguel asked for the reverse: the hours, the payout and the rest are
always visible, and the arrow only collapses the days, so a collapsed week is one line with the next week
right under it.

**Decisions.**
- From 1280px a one-source week is one line: arrow, week, range, tags, Hours, Estimate, Payout, Gap, € / h and
  the status tag. The source name moves to a tooltip and the week's euro amount to a tooltip on Estimate.
- A week with two or more sources shows its totals on the week line, and one line per source stays under it,
  always visible. The arrow only hides the days.
- The payout field lives on the line, so a payout can be typed in a collapsed week. Clicking anywhere on the
  line toggles the week, except inside the payout cell.
- On load only the current week shows its days. While the notes search has text every week opens, so a hit is
  never hidden; the arrows still work and clearing the search puts each week back as it was.
- The week columns have one header at the top of the table, and each open week has a small header for its
  block columns, so with everything collapsed there is only one header.
- Under 1280px the week is two stacked lines, and on a phone it keeps the labelled blocks with no header rows.
  The plan said 1100px, but a paid USD week with four-figure amounts does not fit on one line below 1280px:
  Pico's root font grows with the screen, and at 1200px the page scrolled sideways.
- From 1280px to 1535px the current week drops its "splits" tag when it has one, because "this week" and
  "splits Oct/Nov" do not fit next to each other. The month row still says what comes from that week.
- The geometry audit now measures the week tags, with every week open and with every week collapsed.

**Known limits.** On a phone a long source name wraps to two lines in a day row, as it did before this phase.
Between 601px and 1279px the source name of a one-source week is only in the tooltip, which a touch screen does
not show. The picture baselines do not cover this table, because they show Days in Employee mode.

**Commits.** `f5faa45` Phase 42; `2e5e539` four-figure amounts stay whole on the week line.

## Phase 43 — One line per week in Employee

**Why.** After Phase 42 Miguel asked for the same behaviour in Days > Employee: the week's numbers always
visible, and the arrow only collapsing the days.

**Decisions.**
- A week is a line with Net, Target, Δ and Σ under the table's own columns, plus the number of days. Σ on the
  week line is new: it is the running total at the last day of that week, because collapsing would hide it.
- Clicking the arrow or anywhere on the line toggles the week. On load only the current week shows its days,
  and Expand all and Collapse all appear above the table.
- Open and closed weeks are shared with Freelance, so a week stays open when the pill changes. Expand all only
  touches the weeks of the side on screen.
- The notes search works as in Freelance: every week opens, the arrows still work, and clearing it puts each
  week back.
- Sorted by Net the table stays a flat list of days, with no weeks and no arrows.
- From 1280px a hidden row in the table's head holds each column at its widest usual value, so opening a week
  does not move the numbers of the others. Below that it would push the table past the page, so the columns
  can still shift.
- The Log calendar's week button opens the week it jumps to. The scroll to today lands on the week line when
  that day is hidden.
- On a phone a week is two lines: arrow, week, range and tag, then days, net / target, Δ and Σ.

**Known limits.** Between 641px and 900px an open table still scrolls inside its own box, as it always did, so
Σ can sit off screen there. A value wider than the hidden row can still widen its column.

**Commits.** `50ec193` Phase 43; `c26a1b5` the Selected card of Days > Freelance holds its line.

## Phase 44 — The bezel

**Why.** Miguel asked for a way to expand or collapse every week that followed Kronos's style instead of two
text links. The options were drawn in `docs/mockups/days-fold.html`, and he chose the bezel.

**Decisions.**
- A strip with one tick per week replaces Expand all and Collapse all, in Employee and in Freelance. Lit ticks
  are open weeks, so the strip is also a map of the year.
- A year has a slot for every Monday from the week holding Jan 1 to the week holding Dec 31. "All" goes from
  the first week with data to the last. A slot with nothing to show is an empty tick.
- In Employee the height is the week's surplus around a centre line. In Freelance it is the week's euros from
  a baseline. An open week is brass, and in Freelance an open week that is paid out is teal.
- A press toggles a week, and when it opens the week it also jumps to it and flashes it. A drag gives every week
  it crosses the state of the first one, even when the hand wanders off the strip.
- A finger waits until it moves sideways or lifts, so a vertical swipe that starts on the strip scrolls the
  page and touches no week.
- The chip at the right end reads `- 2 of 45 open +`. Its two buttons keep the old test ids, and when one has
  nothing to do it is dim and marked `aria-disabled`, not `disabled`.
- From 901px the strip sticks to the top of the screen, with the table's headers just under it.
- The strip is one tab stop, and the arrows, Home and End move between the weeks with data.

**Known limits.** In "All", when the data starts in the last weeks of December, the first two year labels can
sit very close on a phone. Playwright refuses to click an `aria-disabled` button, so a test that presses `+` or
`-` with nothing to do must force the click.

**Commits.** `319455e` Phase 44; `97aa5eb` the gap under the sticky strip and the flash on a phone; `f5fc1ac` the flash shows through the day cells; `b059006` the wave test reads its state in one turn.

## Phase 45 — Leaving a day in Log

**Why.** Miguel wanted to get out of editing a day by clicking on the calendar, without the ← button, and no
longer needed to read "New entry" or "Edit 2026-11-06" next to the title.

**Decisions.**
- A click on the day being edited leaves it, as Escape does: the form goes back to a new entry for today and the
  calendar stays on its month.
- A click on another day leaves the edit and selects that day. A day with an entry opens for editing, an empty
  day starts a fresh form, and a drafted day starts from its draft. Nothing of the day just left carries over.
- Unsaved changes are discarded with no prompt. Miguel chose this, and ← and Escape already did it.
- During an edit the other days are neither dimmed nor disabled.
- The ← button and the subtitle are gone, so the title reads "Log". Escape keeps working.
- When two days are clicked quickly, only the answer for the newest click counts.

**Commits.** `9ea495f` Phase 45.

## Phase 46 — The day ribbon

**Why.** This is slice 1 of Phase 36, the one that replaces typing for the common case. Miguel left a free
evening to the Advisor with "implement something fun", and this was first in the plan he had already written.

**Decisions.**
- The day is a strip from 06:00 to midnight above the time fields, and it opens earlier when the day does. The
  fields stay as the precise editor, and a drag only writes into them.
- The grips at the ends change the times and dragging the bar moves the whole day with its breaks. Breaks are
  notches that can be moved and resized, a double press on the bar adds one, and pulling one off the lane
  removes it. A break that is only minutes has no place in the day, so it is drawn dashed until it is dragged.
- Everything snaps to 15 minutes. A floating tag shows the time, the net and the delta while dragging.
- A flag marks the moment the day reaches its target, and the bar is lit after it. A day under target shows
  the missing stretch as a dashed outline.
- Timed freelance blocks have their own lane. A click opens a block in the editor and a drag on the empty
  lane fills the editor. Blocks are not moved on the ribbon, because that would write money.
- A drag never saves. A finger on the bar waits until it moves sideways, so a vertical swipe scrolls the page.
- Every handle is a slider for the keyboard and for screen readers.

**Known limits.** An end cannot go past 23:45, because a time field has no 24:00. A grip stops at a break
instead of pushing it along. On a phone a 30-minute notch is about 7px wide, so it takes care to hit.

**Commits.** `86101eb` Phase 46; `ff74b17` no error in the console after a drag, when Log is left.

## Phase 47 — The year dial

**Why.** Miguel asked for something fun and said the bezel was the coolest of the options, so this is its big
brother. A working prototype came first (`docs/mockups/year-dial.html`), then the real thing.

**Decisions.**
- Pressing the logo, the key Y or the palette opens a full-screen dialog: the year as a chronograph. The outer
  ring turns under a fixed index, one day per detent, and the day under the index is read out in the middle.
- Each day is a tick: outward for surplus, inward for deficit, a fixed bar for leave, dashed for a draft. An
  inner ring marks freelance days, teal when they are paid out. A brass pip marks today.
- The ring can be dragged and flicked, turned by the wheel or the keys, and a press on the ring turns to that
  day. The crown goes back to today by the short way. Enter or "Open in Log" opens the day.
- The balance sub-dial counts as the Dashboard does, with "Cumulative since" and "Reset on January 1st"
  respected, so on today it says the same figure.
- Sound is a click made on the spot with Web Audio. It is off by default and kept in the browser.
- The little second hand is the one thing in Kronos that moves with nobody touching it, because it is a clock.
  Everything stops when the dial closes.
- `dial.js` is its own file, so the physics stay out of `app.js`.

**Known limits.** On a phone the figures of the sub-dials move to the panel under the dial, because they would
be 5px text on the face. The opening turn is 150 days whatever the date.

**Commits.** `402d0d6` Phase 47; `673854d` two dial tests no longer depend on the runner.

## Phase 48 — Kronos in the hand

**Why.** An independent review of every page found the phone's Create entry 1,800px down the page, tabs too
small to tap, and the palette cut at the bottom. Miguel left the UI pass to the Advisor.

**Decisions.**
- Up to 640px the tabs are a bar fixed to the bottom of the screen, with a hand-drawn icon over each label.
- In Log on a phone the rail becomes a dock above that bar: net, delta and the form's own submit button. It is
  the same button at every width, so Delete moved to the end of the form, also on a desktop.
- The bar and the dock step aside while the keyboard is up. They stay for a time or date field, because those
  open the phone's own picker and keep the focus after it closes.
- In Log on a phone the twelve mini months are twelve letters, and the legend folds. That saves about 400px.
- One brass line marks the active tab at every width and slides between tabs with a spring.
- A page fades in over 160ms when the tab changes, never on load.
- The palette lost its empty key chips and the blank band, scrolls inside the screen, and a brass tick slides
  between its rows.
- "+ Add break" and "+ Add note" sit side by side from 641px, and "Log multiple days…" is a small button.

**Known limits.** Not tried on a real iPhone: the safe area and the keyboard are from the rules, not from a
device. A phone user has to tap away from a text field to reach Create entry.

**Commits.** `31922d2` Phase 48; `ff74b17` the Dashboard fits a phone with real figures.

## Phase 49 — Every page at its best

**Why.** An independent review of all seven pages found the dull spots and the small breaks of the guide, and
Miguel left the choices to the Advisor, including the ones that were waiting for him.

**Decisions.**
- Log's two brass buttons: "+ Add block" is an outline now, so "Create entry" is the one primary of the view.
  "Save block" stays filled while a block is being edited. "Commit" in Plan is an outline too.
- Days-off rows stay quieter than work days, but their text reaches 4.5:1. That took the accessibility list
  from 53 entries to 36.
- Pico's blue-grey is gone from every page: its secondary and link colours map to brass and muted once.
- Plan's three figures are cards in a row, each with a small drawing of a figure it already has: the balance
  as a line to Dec 31, one pip per vacation day, one pip per drafted day. The calendar column got narrower.
- Hints moved to tooltips or to a small "?" chip that also opens on touch.
- On a phone the heatmap opens on today's month and fades at its right edge while there is more.
- The Calculator's fields sit on one shared grid. Its money fields are text fields now, so they can show
  `28.960,03` like the results, and they read `28960,03`, `28960.03`, `28.960,03` and `55.000` the Spanish way.
- Settings uses the whole width, every value control ends on the card's edge, the links have a brass tick that
  slides, and "General" got a mark of its own.

**Known limits.** The source name of a block row on a phone can still end in an ellipsis. In the Calculator
"95.125" reads as ninety-five thousand, because a dot before three digits is a thousands mark.

**Commits.** `e29ca8c` Phase 49.

## Phase 50 — Small brass surprises

**Why.** Miguel asked for something fun with room for whimsy, and the moments that matter in a day of logging
had no reaction of their own.

**Decisions.**
- The big balance and the Freelance hero roll digit by digit like an odometer, on first view and on a change.
  The real text stays in the element for screen readers and tests.
- A day saved in Log takes a brass stamp on its calendar cell.
- The save that completes a week puts a brass seal in the toast ("W45 sealed +4.75h"). It only counts the work
  days of the current or the previous week, and each week seals once per browser.
- A payout saved in Days > Freelance sends coins to the Selected card: five above the estimate, one otherwise.
- A bead on the header's hairline shows the hour of the day, from 06:00 to 24:00. It needs that hairline, so it
  is hidden below 720px.
- Typing "kronos" also winds the logo one full turn.

**Known limits.** The vibrations are written but were not tried on a real phone.

**Commits.** `54e88e2` Phase 50.

---

## Phase 51 — Miguel's notes on v50

**Why.** Miguel tried v50 and loved the dial, the ribbon and the coins, but could not find the dial's crown,
said people would miss the dial itself, asked for an explanation of the ribbon in his own words, asked what
the golden dot was for, and wanted the coins to follow the amount.

**Decisions.**
- The tab title is just "Kronos".
- The dial's crown is bigger, and while the ring is away from today an engraved "Today" label sits next to
  it and the crown glows once. Both bring the ring back.
- The logo says "Your year as a dial (Y)" and winds a little under the pointer. Once per browser a brass
  callout under it says "New: press the logo to spin through your year", and it never comes back after it
  is closed or the dial is opened.
- A "?" chip next to "Employee" in Log explains the day bar in plain words.
- One coin per €100 of the payout, between 1 and 40, all landed within 1.6s, with a glint when the payout
  beats the estimate.
- The bead on the header's hairline still shows the hour, and once today has a start the line is lit from
  the start to the bead, with a tick at the time the day reaches its target. Its title says it all: "Now
  13:00 · in since 08:30 · target at 17:00".
- Found in the review: the app started twice on every load (Alpine calls `init()` by itself, and the page
  called it again), so every request of the first load went out twice. It now starts once: 14 requests
  instead of 27.

**Known limits.** On a phone the dial keeps its width, so "Today" runs vertically beside the crown. The
tabs that don't show days now load them quietly, so the bead knows today's start on every page.

**Commits.** `9044af0`, `f7c8ef8`

## Phase 52 — Money in any currency

**Why.** Miguel bills a client in dollars, $95/h, but the money lands in his Spanish bank in euros. He typed
the €877.94 that arrived for W44, Kronos read it as dollars and showed €785.84. He also expects accounts in
other currencies, such as a dollar account or a crypto wallet, and wants Kronos to stop being Spain-only.

**Decisions (Miguel, 2026-11-07).**
- Accounts are "where the money lands": a name, a currency and a kind (bank, wallet, cash, other). A payout
  says which account received it, in that account's currency. A source can say which account it is paid into
  ("Paid into"), and the payout row picks that account by default.
- Any currency the ECB publishes (about 30) plus five coins: BTC, ETH, USDC, USDT and SOL. Coin prices come
  from CoinGecko's free API, which has no key and only goes back 365 days; for an older payout, or when a rate
  can't be had, the row asks what it was worth in euros.
- Euros stay the pivot: every stored rate is "units per 1 EUR", so every old USD row keeps its meaning and
  nothing was rewritten. A base currency other than EUR is a later phase.
- A payout in another currency than its source tells the story behind a small "FX" chip: what was billed, the
  ECB rate of the day, what arrived, what the exchange and the fees cost, and the rate he really got. The
  Freelance tab adds "Lost to exchange and fees" for the year and "Where it landed", per account.
- A payout from before accounts reads exactly as before, in its source's currency. Pointing it at an account
  in the row's select re-reads the same number in that account's currency.
- The backup stays version 4, with accounts as optional keys: an old file restores as before.

**How Miguel fixes W44 on PROD.** Settings > Freelance > Accounts: add "Deutsche Bank" in EUR. Then Days >
Freelance, W44: switch the payout's select from "As billed (USD)" to "Deutsche Bank". The row then reads
€877.94, and the FX chip says the exchange cost €70.19.

**Known limits.** CoinGecko's free API answers only the last 365 days. An account's currency is locked once
a payout uses it. The Accounts card sits inside the Sources section of Settings, with no index entry of its
own.

**Commits.** `0bbaace`

## Phase 53 — Country and number format

**Why.** Miguel wants Kronos to stop assuming its user lives in Spain, now that it is becoming a
production-grade app. The app stays in English; what changes is where the user lives and how they write
numbers.

**Decisions (Miguel, 2026-11-07: "Country + locale").**
- Settings > General has a new "Country and format" card with two settings. Country picks the holidays'
  default and the tax module. Number format is one of `1,234.56` (the default, what Kronos always printed),
  `1.234,56`, `1 234,56` and `1'234.56`. The few long dates follow it ("Nov 7" in the default, "7 Nov" in
  the others), still in English.
- An existing database is Spain with the default format, so PROD looks and adds up exactly as before.
- Every number the app prints goes through one set of formatters, and every number typed into a text field
  (the Calculator, a payout, an exchange rate, "worth €") goes through one parser that reads the chosen
  format. The server has the same rules for the printed timesheets, and both copies are tested against one
  table of cases, so they cannot drift apart.
- Spain keeps its own tax module (the "autónomo" quota, IRPF, the modelo 130 and the "gestoría" fee), shown
  only when the country is ES. Any other country gets the Simple module: a share of every payment set aside
  for the tax office (30% unless he writes another), and the Freelance tab reads "Set aside: €X of €Y
  received this year" instead of the 130 rail.
- A new, empty database whose browser speaks another country's language (German, French) gets a one-time
  suggestion in Settings to use that country's holidays and format. Nothing changes by itself.

**What Miguel will notice.** With the default format, the Calculator now reads "55.000" as 55, the English
way. Before, it read it the Spanish way, as 55000. If he types numbers the Spanish way, he picks `1.234,56` in
Settings > General, and then the whole app prints them that way too.

**Known limits.** The plain number boxes (rates, tax inputs, hours) are the browser's own number fields, so
they keep the browser's decimal mark instead of the chosen one. The Simple module knows no brackets and no
social security: it is a share, and the screen says to check with an adviser.

**Commits.** `52485f1`

## Phase 54 — The Plan page fills the screen

**Why.** Miguel marked the empty space on Plan at 1280: three figure cards about 360px tall for 150px of
content, with the calendar pushed below the fold.

**What changed.**
- The year strip gets a line under the twelve mini months: the real balance day by day up to today, solid
  brass, and from today to Dec 31 the projection of the mode he picked (On target or At my pace), dashed,
  with the other one faint. Each month of the line sits under its mini. It has a pip on today, a dot and a
  label on Dec 31, a small diamond for each drafted day, and the date and balance on hover or tap. The
  balance comes from the same function the dial uses, so today's pip reads what the Dashboard reads.
- A past year shows only its real line, and a future year only its projection.
- The three cards are now one compact row, about 130px tall instead of 358px. Balance has its caption to
  the right of the figure; Vacation and Drafted have their pips beside the figure. The little line drawing
  of the Balance card is gone, because the year line replaces it.
- At 1280 x 900 the calendar starts 205px higher than before.
- The line draws itself once, left to right, and the tail fades in after it. Switching the mode crossfades
  the two tails. With reduced motion everything is instant.
- On a phone the line runs the full width under the 4 x 3 minis, with J F M ... under it.

**Known limits.** The projection tail is a straight run from today to Dec 31, not day by day. The touch
tooltip (tap, then it hides after 2.5 seconds) is only tested with a mouse.

**Commits.** `a360928`

## Phase 55 — The edges of a web app

**Why.** Miguel asked what a pasted Kronos link should look like in WhatsApp or Telegram (a link preview,
built from "Open Graph" tags), and what else a web app has that Kronos never had.

**What changed.**
- Link previews: the page carries Open Graph tags with the title "Kronos", the line "Your hours, your
  balance and your year, at a glance." and a 1200 x 630 picture (`og.png`, the logo, the name and a slice of
  the dial's ring). The picture's address is built from the address the browser used, so no host name is
  written in the repo. WhatsApp builds the preview on the phone that sends the link, so it works on the
  home network. Telegram fetches it through its own servers, which cannot reach Kronos, so it shows no
  preview.
- Icons: the 814 KB `icon.png`, used for everything, is replaced by real sizes (32, 96, 180, 192, 512 and a
  maskable 512), made by `bin/icons.py`. The header logo is now the disc without its square tile.
- Install dialog: the manifest has the real icons, the colours, shortcuts to Log, Plan, Days and the year
  dial, and two screenshots of the Dashboard (wide and narrow), made by `bin/og_image.py`. The address
  `/#dial` opens the year dial.
- Not for search engines: `robots.txt` says no, and the pages say `noindex`. The preview crawlers of
  Facebook, Telegram, WhatsApp and Twitter are allowed by name.
- A wrong address gets a Kronos page ("This page isn't on the dial") with a button back home. A wrong
  `/api/` address still answers JSON.
- When the browser goes offline, or the server does not answer, a banner under the header says Kronos
  can't reach the server, with "Try again". It goes away by itself when the server answers again.
- Security headers on every answer, including a Content Security Policy. To make it work, the printed
  timesheets moved their small scripts into `timesheet.js`.
- Browser details: dark form controls and scrollbars, brass text selection, no grey flash on tap, and a
  line for browsers without JavaScript.

**Lighthouse (before, after).** Phone: performance 62, 86; accessibility 96, 96; best practices 100, 100;
SEO 91, 66. Desktop: performance 94, 97; accessibility 96, 96; best practices 100, 100; SEO 91, 66. SEO drops
on purpose, because of `noindex`. Performance rose mostly because the 814 KB icon is gone.

**Known limits.** Lighthouse still flags three muted colours under 4.5:1 contrast (the version label, the
weekday initials of the Log calendar and the holiday dots), and the Log calendar's day buttons, whose
spoken name differs from their visible text.

**Commits.** `c06e1d7`, `0b91450`

## Phase 56 — Miguel's notes on v55

**Why.** Miguel validated 51 to 55 on INT and sent notes before pressing PROD: tooltips nobody would read, tab names that did not match what the pages do, and a year dial that people will miss. He picked each solution from mockups.

**What changed.**
- Interface text: a tooltip lists what you can do, one short line each, and a status chip says only its conclusion. The "?" of the day bar is four lines with gesture icons. A test now fails on any tooltip line over 90 characters.
- Tabs: Log is now Days, Days is now Weeks and Analytics is now Year. The addresses are `#days`, `#weeks` and `#year`, and `#log` and `#analytics` still work. An old `#days` link opens the new Days page, on purpose. Keys: D, W, Y, and K for the year dial. L and A are gone.
- The header line has a notch and a time at the two default hours (Settings > Employee), and a fainter one at 12:00. It is dropped when a default hour is within 90 minutes of it.
- The FX chip tells the percentage ("FX -7.4%"), and its tooltip is one sentence ("Exchange and fees cost you €70.19").
- "Payouts waiting" in the Freelance card of the Days page: a chip per week that is over and has blocks but no payout, then the amount, the account and Save. It saves through the same code as the Weeks page.
- Calculator: each parameter has its label right beside its value, in three columns. The block is 69px shorter at 1280.
- The year dial is harder to miss: the logo wears a ring of the year with today lit, and the Dashboard has a tile, "Day 313 of 365", that opens the dial.

**Known limits.** The header line, and so its marks, only exist from 720px wide. The current week never appears in "Payouts waiting", the same rule as the Freelance tab's "awaiting a payout" count. On the plain number boxes the decimal mark is still the browser's own (see Phase 53).

**Commits.** `bce7201`, `4d1c828`

## Phase 57 — Sent and arrived

**Superseded.** Miguel validated it on INT on 2026-11-09 and replaced it the same day with the chain of accounts of Phase 58, which removes "As billed", bare currencies and the "Use" roles.

**Why.** Miguel wants to say, for each payout, what was sent and what reached his account, because they are different things: a client pays $999 through Stripe and €894.76 lands in Deutsche Bank. He confirmed the layout on a mockup of his own W45 row.

**Decisions (Miguel, 2026-11-09).**
- The payout cell has two lines in the space of the old one. Line 1 is what was sent: an amount and "As billed", an account that sends, or any of the 35 currencies. Line 2 is what arrived: an amount and an account that receives. When the destination is not in euros, a third line keeps "= €X set the € value".
- Each account says in Settings how it is used: "Paid from", "Paid into" or "Both". Accounts created before this phase are "Both". Each source gets a "Paid from" default beside "Paid into".
- The arrived amount comes pre-filled at the day's rate, and it follows line 1 until it is overwritten. With the same currency on both sides it copies the sent amount.
- Emptying the arrived amount brings the suggestion back, and emptying the sent amount deletes the payout.
- The red gap compares what was sent with what was billed.
- FX is renamed DIFF. It keeps measuring what was billed, at the day's rate, against what arrived, so it also counts what the client did not pay. The Freelance tab says "Difference from billed".
- A payout from before this phase has no sent side: "sent" counts as billed, and it reads and adds up as before until it is edited.

**Known limits.** Euros stay the pivot, so totals still come from what arrived. Without any account the cell stays a single line. The rate is the one of the week's Sunday.

**Commits.** `1303288`, `f356a6d`

## Archiving a phase
When Miguel confirms a phase is live: replace its block in `BUILD_PHASES.md` with one row in the
"Done" table there, and add a summary here in the same docs commit (what was decided, what shipped,
what was left undone and why, the commit shas). Keep what a future session cannot get from the code:
decisions and their reasons, rejected options, known limits. Drop what the code and tests say better
(endpoint lists, test counts). Open phases and anything awaiting confirmation stay in
`BUILD_PHASES.md`.
