# Mockups

Static HTML, one file per direction, hand-written with the tokens from `backend/static/styles.css`.
They are design artefacts, not the app: open them straight from disk. They used to ship in the
Docker image under `/static/mockups/`; moved here so the public mirror and PROD stop serving them.

| Phase | Files | Chosen |
|---|---|---|
| Dashboard redesign (pre-24) | `d1.html`, `d2.html`, `d2-whimsy.html`, `d3.html` | D2 ("Chronograph"), the current design system |
| 25 — Time-off planner | `plan-p1.html`, `plan-p2.html`, `plan-p3.html` | P2 + P3's year strip |
| 26 — Timesheet | `timesheet-t1.html`, `timesheet-t2.html`, `timesheet-t3.html` | T2's detail + T3's month sections |
| 31 — Visual redesign | `redesign-r1.html`, `redesign-r2.html`, `redesign-r3.html` | R2 throughout, with R3's card-per-section Settings |
| 33 — Interactive analytics | `analytics-a1.html`, `analytics-a2.html` | A2 entirely |
| UX round after 34–35 | `ux-u1.html`, `ux-u2.html` (+ `_ux_base.css`) | U1's Log; U2's Days, Analytics and Freelance; the shared Settings and timesheet |
| 37 — Freelance payouts | `payouts-p1.html`, `payouts-p2.html` (+ `_ux_base.css`) | Open |
| 44 — Folding the weeks | `days-fold.html` | The bezel |

## Phase 31 — `redesign-r{1,2,3}.html`

Each file contains the three redesigned screens (Dashboard with the week strip, Settings, Days)
behind a working nav — click **Dashboard / Days** or the settings icon — plus a working theme
toggle; resize the window for the phone layout. Plan · Log · Analytics are inert. Numbers are
invented for Tue 2026-10-27. Shared by all three: five tabs + a settings icon next to the theme
toggle, no "Today is … target … since …" line, no draggable layout, quick-log only while today is
empty, a section index on the left of Settings with a save button per section, Days as a dense
table (row click edits, ✎ in a fixed column, sticky header, a separator per month with its
subtotal, notes as the last column, count + PDF in the top bar).

| | R1 — Chronograph | R2 — Trajectory | R3 — Ledger |
|---|---|---|---|
| Hero | A 240° dial: the cumulative balance filled from zero, a brass marker at its tip, the year-end forecast as a dashed arc ahead of it; a watch-style date window at 6 o'clock | The number left; right, a sparkline of the cumulative balance per day this year drawing itself, then a dashed projection to Dec 31 | The number alone, very large, over a hairline |
| Week · month · vs last year | Three chronograph subdials | Three stat chips with a bullet bar | Three typographic columns |
| Forecast | The dashed arc + label on the dial | The projection line's end label | A "runway" bar for the year: elapsed, today, planned ticks, the projected value at the end |
| Week strip | Compact cards (as the Week tab) | Cards with a tiny bar chart per day, the target as a rule | A flat row with hairlines |
| Vacation | "Power reserve" gauge with a notch per day | 22 notches: filled / dashed / hollow | Glyphs: ● used · ◌ planned · ○ left |
| Settings icon | Watch crown (pulls out on hover, turns while open) | 8-tooth gear (quarter-turn on hover, spins while open) | Cog inside an engraved ring |
| Settings fields | Short fields in a 2–3 column grid, label above | Rows: label + hint left, sized control right | Same rows, one card per section, save in the card header |
| Days notes | One line, ellipsis, 📝 prefix, italic | Wrapped in full | One line, ellipsis, unfolds when the row is hovered |

## Phase 33 — `analytics-a{1,2}.html`

Both have the same content and the same **working** chart — hand-drawn SVG like the dashboard's
trajectory: drag a rectangle to zoom into that range (y rescales to what is visible), wheel to
zoom at the cursor, shift+drag to pan, drag the strip under it, double-click or *Reset* to go
back; presets This month · 3 months · This year · 12 months · All; a Balance / Per day / Per
month switch. Whatever range the chart shows drives the summary, the weekday pattern (Δ plus
average start → end), the daily-surplus histogram and the records. Year at a glance stays whole
year, with a tooltip per day (hours, Δ, note) and a click that opens the day in Log. Monthly
breakdown is gone; Years and Export stay. Invented data, 2025-01-01 → 2026-10-28.

| | A1 — Chart first | A2 — Chart + ledger |
|---|---|---|
| Layout | The chart spans the page; presets in its header; the range summary as five chips under it | The chart with a ledger beside it: presets as a list, the range's numbers as rows |
| Records | A dense 4-column grid of label · value · when | Two columns of one-line rows |

## UX round after Phases 34–35 — `ux-u{1,2}.html`

Miguel's review of the freelance build (2026-11-02): no save buttons in Settings, fewer hints,
plainer words, days off instead of weeks off, the year strip on the Log page, an "Employee" title on
the Log form, ← keeping the month, a Days switch with source filters and a freelance PDF, the Year
at a glance pinned in Analytics, and the empty space on the Freelance page. Both files have the five
screens behind a working nav (Log · Days · Analytics · Freelance · ⚡ Timesheet · ⚙), a theme toggle,
and a working autosave demo in Settings (type in a field: the card head says *saved ✓*). Invented
numbers for Mon 2026-11-02. The Settings screen and the freelance timesheet page are the same in
both; the two directions differ where the layout had a real choice:

| | U1 — "Strip on top" | U2 — "Side by side" |
|---|---|---|
| Log | Plan's year strip across the top (twelve mini months in a row; a click picks the month on the left); the form card titled **Employee** with the notes beside it; the **⚡ Freelance** card under it, same shape | The year as a 3×4 grid of mini months *inside* the left column, above the month; **Employee** and **⚡ Freelance** side by side from 1100px (stacked below), notes under the form |
| Days | An *Employee · ⚡ Freelance* switch next to the title; in Freelance a row of source **chips** (toggle each; *all · none*), the count and totals in the header follow; **⚡ PDF** | Two **sub-tabs** under the title with counts; a filter **bar** with a row per source (checkbox, blocks · hours · €, *all · none*) and a totals tile for what is ticked; the PDF button follows the tab |
| Analytics | The **whole** Year-at-a-glance block stays pinned (title, switch, year, heatmap; ~190px); on the phone only the controls row | The block **shrinks** when scrolled: small title, no hint, 4px cells, the switch and year kept — a 90px toolbar that still shows the year's shape |
| Freelance | The 130 as a **vertical list** of four rows beside the year ledger: both columns end together | **No right column**: the year as a strip under the hero (inputs · waterfall · eight tiles), the 130's four cards in a row, then the Calculator |
| Shared | Settings: autosave (*saved ✓* in the card head, no buttons), hints removed, the timeline explained in two short sentences, "This asks the Banco Central Europeo", **Days off a year**; the freelance timesheet page with the sources as checkboxes in its toolbar | |

## Payouts round (Phase 37), 2026-11-04 — `payouts-p{1,2}.html`

A payout is what one income source actually paid for one ISO week, in the source's currency; it replaces
the estimate (hours x rate of the blocks) wherever it exists. Both files show the same four pieces with
invented numbers (today = Wed 2026-11-04; Northwind Labs at $60/h and Local consulting at EUR 50/h), the
Days part once as desktop and once as a 380px phone, side by side (stacked on a narrow window):
the Days ⚡ Freelance list for October and November with a header per ISO week on top of the block rows, which stay as in U2 (a click opens the day in Log; in a paid week their amounts are the estimate, muted); the Freelance tab hero
("EUR 9,200 this year · EUR 7,400 paid out · EUR 1,800 estimated") with the twelve monthly bars (paid out
solid, estimated in a lighter shade of the same colour, planned after today dashed); the dashboard card as
one line; and one week of the freelance PDF with its payout line under the blocks. They link `_ux_base.css`
and keep everything else inline. Working bits: type in a payout (the week shows *saved ✓*), empty a filled
one (Undo in the ribbon), click ✎ next to a rate to edit it, theme toggle.

The weeks cover every state of the brief: W45 the current week (no payout, not flagged); W44 a USD payout
above the estimate ($2,100 against $1,800, rate shown with its pencil, +$300) that is also the week
crossing Oct/Nov (it appears once, under October, with a note that its money is split by day worked);
W43 a past week with blocks and no payout ("awaiting payout", quiet); W42 a EUR payout below the estimate;
W41 a payout with no hours.

| | P1 — "Week headers, always open" | P2 — "Compact header, payout on demand" |
|---|---|---|
| Week header | A small header per week ("W44 · Oct 26 – Nov 1") that only names the week; the split note and *saved ✓* sit in it | One line per week: week, dates, hours, money and a tag (*paid out* solid, *estimated* dashed, like the bars); "awaiting payout" next to the tag on past weeks |
| Per source | Line(s) always visible under the header: hours, estimate, payout field, gap, EUR/h; the block rows follow | The same line(s), only after clicking the header (W44 starts open; Expand all / Collapse all); the block rows are visible either way |
| Payout field | Always on screen, empty means "use the estimate" | Appears when the week is opened |
| Cost | Taller list (every source of every week), the whole state readable at a glance | Short list, one scan of the money; typing a payout takes a click more |
| Shared | Freelance tab hero and bars, dashboard line, PDF week | Same |

Not shown: the Log ⚡ card line ("W44 payout $2,100" with its link), the Analytics ledger split, the CSV
button, a USD payout without an exchange rate (counted as missing), and the gap and EUR/h updating live
while you type.
