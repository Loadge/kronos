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

Suggested order (2026-11-02; 31, 32, 33, 34 and 35 built): 28 next (Anselmo logs through the
CLI Phase 32 delivered); 29 any time, and before next October; 36 (the tactile pass) in slices,
each one a weekend, the day ribbon first; 30 only if logging from the phone outside the LAN turns
out to be common.

### Phases 34 and 35 — Freelance hours in Kronos (built 2026-11-02, awaiting confirmation)

**Why.** Besides the job Kronos tracks, Miguel now also works as a freelancer (autónomo), by the
hour and outside his working hours, for clients that may pay in US dollars. A separate app (not in
this repository) did the sums for that side: a rate calculator with the Spanish taxes of a
freelancer. That app is being retired, and Kronos becomes
the one place for both: what he worked, as an employee and as a freelancer, and what the freelance
part is really worth after Social Security and income tax. The decision this serves is a real one:
whether, in a year or two, the freelance work could replace the job.

**What already existed.** The tax engine was moved in before these phases and is the single
source of every tax figure: `backend/app/services/tax.py` with the 2026 figures in
`backend/app/data/fiscal_es.json`, and `GET /api/fx` (`backend/app/services/fx.py`), the ECB's
EUR/USD reference rate, fetched only when asked and at most once an hour.

**Process.** The first build (2026-11-02) had no mockup round: the spec left the shape of
the screens to the implementer, and the existing design system (brass, hand-drawn SVG, cards
with a save per section) fitted every surface. Two review rounds followed, the first with mockups
(see "The UX round" and "The second review round" below). Built 2026-11-02 on branch
`phases34-35`; not yet confirmed by Miguel or deployed; the archive gets its summary when it is.
Where the spec was silent the choices below were made and are said here; the ones that change
what Miguel sees or stores are marked **(decision)** for review.

#### Phase 34 — Freelance hours next to the working day

**Data model** (migration `0009`, three tables; models ⇔ migrations test green):
- `income_sources` — name, hourly rate, currency (EUR | USD), `is_default`, `archived`. The first
  source is the default whatever the body says. **(decision)** A source with blocks cannot be
  deleted (409) — it is *archived*, which hides it from the picker and keeps every old block's
  label; a source without blocks can be deleted.
- `freelance_blocks` — date, source, `minutes` (exact; the API speaks `hours` or a start and an
  end, which also fix the hours), optional start/end, note, and the snapshot: `rate`, `currency`,
  `fx_rate`. **(decision)** Blocks are independent of `work_entries` — no FK, no entry required —
  so a Saturday of freelance work needs no employee entry and nothing freelance can reach the
  target, the balance, the streaks or the timesheet (`test_blocks_never_touch_the_employee_side`
  pins the dashboard and the timesheet byte-for-byte before and after blocks).
- `freelance_tax_years` — per year: salary of the job, tarifa plana, start-up reduction, the
  share set aside (0.40), gestoría and other deductible expenses. A year without a row uses the
  latest earlier one, with no rows the defaults; `GET /api/freelance/tax-years/{year}` says which
  (`inherited_from`, `is_default`) and which `fiscal_es.json` block applies. **(decision)** The
  two expense fields were added because `tax.TaxParams` needs them; the spec listed neither.
- The projection's two numbers (`freelance_hours_per_week`, `freelance_weeks_off`) are plain
  settings in `/api/config`, so they ride in the backup's `settings` like everything else.

**Rates and the ECB.** A block takes its source's rate and currency when saved (`rate` in the body
overrides, for a one-off price). A USD block takes the ECB rate of its own date — `fx.for_date()`
is new: the daily document for a date within the week, the ECB's 90-day document otherwise, the
full history only for an older date, each fetched at most once an hour and only by that call; a
weekend or holiday takes the last published day. `fx_rate` in the body overrides and is editable
from the Log tab (✎). **(decision)** When no rate is available the block is still saved, with
`fx_rate = null`: it counts its hours but not its money, every sum reports it as `missing_fx`, the
page says so, and a hand-set rate repairs it — never a silent 1:1. Editing a block keeps its
stored rate and exchange rate unless the body gives them or the source changes (then the new
source's rate; a changed date re-asks the ECB). `GET /api/fx?date=` exposes the lookup. Sums add
each block at the cents it shows (`money(amount_eur)`), so a list and its total agree everywhere.

**The Log tab.** A card under the employee form, "⚡ Freelance · Thu, Oct 29": the day's blocks
(source dot, hours or start–end, amount — `$190.00 → €170.07` for USD — note, ✎ ✕), a total, and
an editor that saves a block the moment *Add block* is pressed (its own request; the employee form
is untouched). Hours by a quarter-hour stepper or by start–end (a toggle); a live "≈ €90.00 at
€60.00/h" preview; editing shows the block's rate and, for USD, its exchange rate. Removing
offers **Undo** in the ribbon for five seconds (the ribbon gained an optional action). A chip in
the Log header ("⚡ add freelance" / "⚡ 1.5h · €90.00") jumps to the panel with the hours field
focused — one tap from the top of the page on a phone. Calendar cells with blocks get a coin dot;
the dashboard's week strip and the Days table a "⚡2h" per day (Days stays the employee's
history: a freelance-only day has no row there, the Freelance tab and Analytics have it). Whimsy: the saved amount floats up off the button
(`+€170.07`), the day's total bumps, the first source's toast says the tab is yours.

**Settings, two levels.** Groups **Employee** (Work · Leave · Holidays · Profile · Templates),
**Freelance** (Sources · Taxes · Projection · Currency) and **General** (Data). Desktop: the index
on the left lists the three groups, the open group's sections under it (scroll-spied as before);
only the open group's cards are on the page, the choice is remembered. Phone: two dropdowns above
the content, as Miguel suggested. Freelance cards: *Sources* (list with default / archived tags,
add / edit / make default / archive / delete), *Taxes* (a year switcher; the origin of the shown
values; a save per year; "drop this year's own values"), *Projection* (hours a week, weeks off),
*Currency* (the ECB rate, asked for when this view opens, with its date and staleness, and the
rules in words).

**Backup v3.** Adds `income_sources` (with ids, which the blocks reference), `freelance_blocks`
(with their snapshot) and `freelance_tax_years`; the settings carry the projection's two numbers.
Versions 1 and 2 still restore. **(decision)** A file with a freelance section replaces the sources
and tax years; a file without one (an older backup) leaves them alone but, like every restore,
wipes the blocks (data). `DELETE /api/data` wipes blocks too; sources and tax years are settings
and stay. The fidelity test now populates two sources, three blocks and two tax years and proves
backup → wipe → restore → backup identical. `GET /api/freelance/export.csv` is the freelance side
of the CSV export, one row per block (**decision**: a second file rather than rows in the entries
CSV, whose import format is per date); no freelance CSV import — the backup carries the blocks.

**Also.** The seed creates two sample sources (USD and EUR) when there are none and two or three
evenings a week of blocks with a fixed exchange rate, so `kctl up --seed` shows the whole side
without the network. `smoke.py` and `kronos check` read the freelance endpoints. Service worker
cache v31. Decided not to do (as the spec said): no check that a block overlaps the employee
hours of the day.

#### Phase 35 — What the freelance hours add up to

**`GET /api/freelance/summary?year=`** is the one read behind the tab, the card and Analytics:
totals (hours, gross €, €/h, blocks, `missing_fx`), this week and month, per month, per source,
the four 130s, the tax inputs in force, and the projection. **(decision)** The year's tax figures
are built on the *projected* gross — billed so far plus the planned hours to Dec 31 — because a
RETA tramo and an IRPF bracket belong to a year, not to the part of it that has passed. The planned
hours bill at the €/h realised so far this year (the mix of sources, in euros, no exchange rate
needed), or at the default source's rate before the first block (a USD default asks `fx.latest()`
then — the only fetch this endpoint can make). Weeks off are spread over the year (nobody knows
when they fall): `weeks_left = days_left / 7 − weeks_off × days_left / days_in_year`.

**The 130.** `tax.quarter_payments()` (new, pure, in `tax.py` next to the rest of the maths): 20 %
of the net yield accumulated since 1 January — the quarter's income so far less the year's fixed
costs (expenses + RETA) accrued a twelfth a month, less the 5 % hard-to-justify expenses (capped)
— minus the earlier quarters' payments, never below zero; the start-up reduction does not apply
(it lowers the Renta, as `figures()` already had it). Deadlines moved into `fiscal_es.json`
(`pago_fraccionado_deadlines`: 20 Apr · 20 Jul · 20 Oct · 30 Jan of the next year). Each quarter
has a status: filed (deadline passed) · due · running · ahead.

**The Freelance tab** (key **F**; the palette has *Freelance* and *Rate calculator*). Appears once
a source exists — **(decision)** like the dashboard card, so a Kronos without freelance keeps its
five tabs; `#freelance` without a source shows an empty state that opens Settings → Sources.
Year switcher. *This year, for real*: the gross billed as the hero (count-up), hours, €/h gross and
≈ €/h net, the set-aside chip, a chip per source, and the twelve months as bars (billed solid,
the planned share after today dashed, the current month lit). The **Modelo 130 rail**: four
stations on a line (the running one pulsing), each with its hours, gross, payment and deadline,
and the footer "X through the 130 · the rest in the Renta (returned)". *The year to Dec 31*: the
two projection inputs inline (saved on change), the basis ("168.96h still to bill over 24 weeks at
€80.00/h realised"), and the ledger gross → expenses → RETA (tramo, €/month) → IRPF (effective %)
→ pluriactividad refund → net, net €/h, "keeps of each euro"; the inputs' origin and the fiscal
rules in a footnote with "estimate: check with an adviser".

**The Calculator** (`POST /api/freelance/calc`, pure — every assumption in the body, the browser
keeps no formula): hourly ⇄ daily ⇄ net yearly, the field typed in drives the other two (the
"follows" fields flash; a debounce and a sequence number so the last answer wins); EUR or USD with
the rate on view — the ECB's with its date when the currency switches, the last dollar block's if
the ECB is unreachable, or one typed by hand ("typed by hand"); billable days 220 or *the
calendar's* (the year's work-week days less the holidays logged and the vacation budget) or any
number; hours a day, salary, gestoría, other expenses, the two switches; *Start from this year*
fills it from the year's real values (realised €/h, hours per billed day, the tax inputs, the
default source's currency). The output: a waterfall bar gross → expenses → RETA → IRPF → net,
the breakdown (RETA tramo and base, hard-to-justify, start-up reduction, the taxable yield, IRPF
with its effective rate "on top of the salary", of which the 130 four times and the Renta's
rest or refund, the pluriactividad refund, net a year / a month / per hour), and how the IRPF is
paid in words. The two anchors of `tests/unit/test_tax.py` come out to the cent from the API
(`TestCalculator`) and from the browser (`test_year_quarters_projection_and_the_calculator_anchor`
types them in).

**The Dashboard** gets the card only with a source: this week and this month (hours and gross,
from the blocks already loaded, as the week strip does), set aside (the month's gross × the
year's share), and the last eight weeks of freelance hours as a sparkline; a click opens the tab.
The employee hero is unchanged (pinned by the e2e test: ±0.00h with blocks on the week).

**Analytics.** Year at a glance gets an *Employee | ⚡ Freelance* switch (four shades by hours;
the tooltip lists the day's blocks in either mode, so a mixed day is shown whole). The chart
stacks freelance hours on the employee's bars per day and per month (a freelance-only day gets its
own bar), and a fourth series, *⚡ Income*, shows the gross per month in euros. The range ledger
gains a Freelance block: billed, hours, blocks, €/h gross and ≈ €/h after tax (the year's
`net / gross` share applied). Export gains the freelance CSV. No employee income anywhere: the
salary is not logged day by day.

**FX discipline.** The browser asks `/api/fx` when Settings → Currency opens, when the calculator
switches to USD, and never on a timer; the server asks the ECB when a USD block is saved (its
date), when the calculator or Currency asks (latest), or when a USD default source projects a
year with no blocks yet — each at most once an hour.

**Tests.** 4 unit (the 130), 7 unit (`fx.for_date`, the history parser, disabled, dead network),
7 unit (weeks left, sums), 29 API (`tests/api/test_freelance.py`: sources, blocks with the
snapshot rules and the missing-rate path, tax years and inheritance, the summary by hand — a
round 40,000 € year —, the calculator's two anchors to the cent, the CSV, the config bounds), the
fidelity test extended, 8 e2e (`tests/e2e/test_freelance.py`) plus the Settings index test
rewritten for the two levels; `kronos check` counts 8. After the review rounds: 707 pytest, 163 e2e.

#### The UX round (2026-11-02, after Miguel's review of the build)

Mockups first (`docs/mockups/ux-u{1,2}.html`, `docs/mockups/README.md`): Miguel chose U1's Log,
U2's Days, Analytics and Freelance. What changed:

- **Settings save themselves.** No Save buttons: a field saves 600 ms after the last keystroke, a
  switch or a picker at once; the card head shows `saved ✓` (fades), `check the value` for an
  invalid field (nothing sent), `not saved` on an error. Each section still sends only its
  fields; the target timeline saves through its own endpoint once every row has a date and hours
  (the current target follows the latest row without re-keying the rows under the cursor); the
  Taxes card saves its year (switching the year flushes first); leaving Settings or switching
  the group flushes every pending save. Ctrl+Enter still saves everything with a toast. Action
  buttons stay (Import holidays, Add / Edit a source). Hints removed as listed by Miguel, the
  group hints too; the timeline explained in two sentences; "This asks the European Central Bank."
- **Days off** replace weeks off: `freelance_days_off` (0–366) in the config and the backup,
  spread over the year like before (`weeks_left = (days_left − days_off × days_left /
  days_in_year) / 7`). The v3 backup key changed before any deployment, so no compatibility
  shim.
- **Log.** The planner's year strip sits under the header: a click makes that month the
  calendar's; the calendar lost its arrows and its title (the lit mini month is the title); the
  year switches in the header next to the ⚡ chip. The form card is titled **👔 Employee**, the
  freelance card **⚡ Freelance** in the same style. ← and Escape after editing a day keep the
  calendar in that month (the form goes back to a new entry for today).
- **Days.** With a source, two sub-tabs under the title with their counts: **Employee** (the
  table as before) and **⚡ Freelance** — a filter bar with a row per source (checkbox, blocks ·
  hours · €, *all · none*), a "selected" tile (€, blocks, hours, €/h, blocks without a rate),
  the blocks one row each with a separator per month; the year filter and the note search apply;
  a row opens its day in Log with the block in the editor. The PDF button follows the tab:
  **⚡ PDF** opens the picker with the sources ticked as in the filter (*all · none* there too).
- **`GET /timesheet/freelance?from&to&sources=1,2&hours&notes&sign&theme`** — the freelance
  sheet, a sibling of `/timesheet`: one row per block (no empty days — it goes to a client or
  the adviser), the sources as checkboxes in its toolbar (an empty selection prints an empty
  sheet, not every source), month sections with subtotals, amounts in the source's currency and
  in euros (a block saved without a rate prints "no rate" and is left out of the euros), totals,
  optional notes and signature lines. `build_freelance_timesheet()` in `services/timesheet.py`,
  pure and unit-tested; the employee sheet is byte-for-byte unchanged by blocks.
- **Analytics.** Year at a glance is pinned: a sentinel above the block and an
  IntersectionObserver; once stuck the block shrinks to a ~100px toolbar — small title, no hint /
  legend / labels, 4px cells (the grid's columns are CSS variables now), the switch and the year
  kept; a click on the mini heatmap scrolls back up instead of opening a day; the tooltip is off
  while stuck. Same on the phone.
- **Freelance.** No right column: "The year to Dec 31" is a strip under the hero — the two
  inputs, the basis, the gross → expenses → RETA → IRPF → net waterfall, eight tiles, the
  footnote — and the 130's four cards span the width; the Calculator follows with no hole.

Tests: 4 API (the freelance sheet: rows and totals, the sources filter and the empty
selection, h:mm and a missing rate, the employee sheet untouched), 2 unit (`fmt_money`, the
rows / totals / months), 3 e2e (the Log strip and ←, Days · ⚡ Freelance with the filter, the
totals, the picker opening the sheet in a new tab and a row opening the block; the Analytics
pin), the Settings e2e rewritten for autosave (sections, the timeline), `smoke.py` reads the
freelance sheet.

#### The second review round (2026-11-02)

- **One page head on every tab**: the page's name on the left (Dashboard · Plan · Log · Days ·
  Analytics · ⚡ Freelance · Settings; Log and Settings carry their state as a muted subtitle —
  "· Edit 2026-10-29", "· Freelance"), the controls on the right. **One year stepper**
  everywhere — a pill `‹ 2026 ›` with the year centred between the arrows — replacing the wide
  switch (whose year sat off-centre) and the two dropdowns: Analytics steps through any year,
  Days has an **All** pill beside it. The dashboard's today chip moved into its head; the Days
  head lost its "N entries" (the sub-tabs carry the counts).
- **The Analytics pin, redone.** The sticky block that shrank once stuck changed the page's
  height under the scroll, which unstuck it, which grew it back: at a normal scrolling speed the
  page bounced to the top. Now the year stays in the flow at full size, and once it has scrolled
  out a **fixed** compact bar appears (4px days, the switch, the year; a click goes back up).
  Fixed elements take no room, so nothing moves under the scroll; the e2e test scrolls a notch at
  a time and requires the position to only ever go down.
- **Calculator ⇄ options.** "⚙ Freelance options" in the Freelance page head and the Calculator
  head opens Settings → Freelance at Taxes; "⚡ Open the calculator" in the Settings head (while
  in the Freelance group) and a link in the Taxes card come back — flushing pending autosaves,
  reloading the year and starting the calculator from the inputs just changed.
- **Found on the way:** after visiting the Freelance tab, resetting the year's summary to `null`
  (any block added, any tax input saved) made Alpine re-run effects of the torn-down tab and
  log expression errors. The summary is no longer nulled once loaded; a `_flStale` flag makes
  the next view reload it.

Tests: the page heads (a title on every tab, one stepper where there is a year, the year centred
in it, no count in Days), the pin (slow scroll, the fixed copy, the year from it, the click back),
the two shortcuts; three older Analytics e2e tests adapted (the page title first in the headings,
the stepper instead of the select, the chart scrolled into view before the wheel).

**Known limits.** The 130's fixed costs are the projected year's RETA accrued evenly, not the
cuotas actually paid month by month; a salary's withholdings and the retenciones a client may
apply are not modelled (the engine's docstring lists what else is not). The calendar's billable
days count the vacation *budget*, not the days taken. The projection's planned hours are a flat
rate per week. The block editor's *Start – end* is same-day only (as the employee's times). No
freelance commands in the CLI yet (`check` reads the summary only). The demo GIF predates it all.

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

1. **The day ribbon (Log).** Under the Employee card, the day as a strip from 06:00 to 24:00: the
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
