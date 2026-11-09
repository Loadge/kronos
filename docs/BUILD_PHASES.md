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
37 to 50 confirmed and archived. 51 to 56 built and waiting for Miguel's check
(Miguel, 2026-11-07: money first, because PROD reads a euro payout as dollars); 28 after them (Anselmo
logs through the CLI Phase 32 delivered); 29 any time, and before next October; 36 (the tactile pass)
in slices, each one a weekend; 30 only if logging from the phone outside the LAN turns out to be common.

### Phase 56 — Miguel's notes on v55 (built 2026-11-09, awaiting confirmation)

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

### Phase 55 — The edges of a web app (built 2026-11-07, awaiting confirmation)

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

### Phase 54 — The Plan page fills the screen (built 2026-11-07, awaiting confirmation)

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

### Phase 53 — Country and number format (built 2026-11-07, awaiting confirmation)

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

### Phase 52 — Money in any currency (built 2026-11-07, awaiting confirmation)

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

### Phase 51 — Miguel's notes on v50 (built 2026-11-07, awaiting confirmation)

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
