# Kronos UI guide

This guide holds the rules that keep every page of Kronos looking and behaving the same. `DESIGN.md` says how Kronos looks (colours, type, motion); this file says how information is presented, so the pages do not drift apart again. Read it before any UI change, and update it in the same change when a rule moves.

The rules come from the audit of 2026-11-05 (Phase 39) and from well-known usability guidance, cited at the end of each rule. Where a rule is a decision of Miguel's and not a convention, it says so.

# The rules at a glance

1. The same thing looks the same, sits in the same place and uses the same words on every page.
2. Every page starts with one page head: the title on the left, the controls on the right.
3. In the head, the controls go in a fixed order: the page's own buttons, then the Employee/Freelance pill, then the year selector.
4. Exports are small buttons in the head, never a block at the bottom of the page.
5. One primary button per view, and every primary button looks like "+ Add block".
6. Numbers have one format per kind: hours, money, percent, dates.
7. Page titles outside a card all look like "Calculator"; titles inside a card are card titles.
8. Hints are the exception: if a label is clear, nothing explains it.
9. An empty list says what is missing and offers one action.
10. 👔 marks the employee side and ⚡ the freelance side, wherever both appear.

# Words you will meet

These are the terms used in design circles, with what each means in Kronos.

- Design token: a named value that records one design decision, such as `--k-brass` for the accent colour. A component uses the name, never the raw hex.
- Semantic token: a token named by its role (`--k-muted`, `--k-deficit`) and not by its look (`--grey-500`).
- Design system: the standards plus the reusable pieces that make many screens consistent. In Kronos it is `DESIGN.md`, this guide and `styles.css`.
- Style guide: the visual rules (colour, type, tone). Kronos keeps it in `DESIGN.md`.
- Pattern: a solved layout problem that is reused, such as the page head or the "+ Add" opener.
- Page head: the top block of a page, with the title on the left and the controls on the right (`.page-head`).
- Primary action: the one main button of a view, such as "Create entry". Everything else is secondary.
- Secondary button: a lower-weight action, drawn as an outline (`secondary outline`, `.head-btn`).
- Ghost button: a button with no fill at all. Kronos does not use it any more.
- Destructive button: an action that deletes or cannot be undone (`.btn-danger`), always confirmed first.
- Segmented control: a short row of exclusive options that switch the view of the same data. The Employee/Freelance pill is one (`.seg-toggle`).
- Tabs: navigation between separate sections. The top navigation is made of tabs.
- Toggle (switch): one on/off setting that applies at once, such as "Tarifa plana".
- Chip or pill: a small rounded label that states something and can be clicked (`.fl-jump`, `.update-pill`).
- Tabular figures: digits that all have the same width, so columns of numbers line up (`.metric`).
- Empty state: what a list or chart shows when it has no data yet.
- Progressive disclosure: showing the common things first and hiding the rare ones behind one control ("+ Add break", "+ Add note").
- Microcopy: the small texts of the interface, such as button labels, hints and errors.
- Sentence case: only the first word and proper names are capitalised ("Add break", not "Add Break").
- Visual hierarchy: size, weight and colour tell the eye what matters first.
- Interface inventory: every distinct button, tab and table of the app shown side by side, so the differences stand out.

# Page anatomy

Every tab starts with `<header class="page-head">`. The title is on the left. The controls are in `.page-head-controls`, on the right, in this order from left to right:

1. The page's own buttons, all `.head-btn`: a shortcut ("Freelance options"), exports ("CSV", "JSON", "⚡ Freelance CSV", "⚡ Payouts CSV", "PDF") or search.
2. The Employee/Freelance pill, when the page has both sides (Days and Analytics today).
3. The year selector (`.year-step`, plus "All" in Days).

On a phone the controls row spans the whole head and wraps, but the year selector stays at the right edge. After the head come the content blocks, each one a card or a section with a title.

Rule 3 is Miguel's decision (2026-11-05): a user who learned where the pill is on one page must find it in the same place on the others. Nielsen's heuristic "consistency and standards" asks for exactly this, and Jakob's law adds that people expect an app to work like the others they already know. Primer's PageHeader follows the same layout, with the actions at the top right.

# Buttons

- One primary button per view. It uses `button.btn-action` (brass fill, 6px radius, bold). The look of "+ Add block" is the standard for every primary button; the full-width variant is `.btn-action.btn-action--block` (Create entry).
- Secondary buttons are `secondary outline`, and in the head `.head-btn`. An opener such as "+ Add break" is secondary too.
- Labels start with a verb and use sentence case. Use "Add" to put something in a list and "Create" for a new entry of the main ledger; do not mix them for the same action.
- A destructive action uses `.btn-danger` and asks for confirmation.
- Pick the control by what it does: tabs move between sections, a segmented control switches the view of the same data (two to five options), a toggle is for an on/off setting that applies at once.

# Numbers and dates

Kronos has one helper per kind of number in `app.js`. Never format by hand in a template.

- Hours: `fmtHours` for totals (trailing zeros trimmed: 34.5h) and `formatSurplus` for signed deltas (always two decimals: +24.50h). This is Miguel's decision.
- Money: `fmtMoney`, always with cents and a thousands comma: €1,289.71. Inside a chart a label may round (`fmtMoney0`: €1,290) because it has no room for cents.
- Calculator: the Freelance calculator is the one place with Spanish decimals, typed and shown (`calcMoney`: €28.687,41), because its inputs follow the browser's locale. This is Miguel's decision.
- Compact exceptions, on purpose: the weekday averages under the Weekday pattern bars keep one decimal (+0.7h) because the cell is narrow.
- Numbers use the `.metric` class, so the digits are tabular and the columns line up, and numeric columns are right-aligned.
- Dates have two forms, and the form follows what the reader is doing (Miguel, 2026-11-05). Where the reader looks things up, scans a column or sorts (Days, the Records, the exports), the date is exact and sortable: ISO, `2026-11-05`. Where the reader takes in a card or a label in passing (the Dashboard, Plan, Log, chips), the date is short and carries the weekday, which is what places it in the week: "Thu, Nov 5". A table needs a fixed width and an order that sorts, a card is read like a sentence. Never mix the two forms inside one block.

MDN documents tabular figures and `Intl.NumberFormat`, the helper the formatters use.

# Titles, hints and empty states

- A title outside a card is an h2 in `.section-header.an-head`, 1.25rem, like "Calculator". Inside a card it is `.card-title h3`.
- A hint line is the exception. If a label is clear, nothing explains it. When the information is still worth having, it moves to a `title` attribute (a tooltip). Task-critical information never lives only in a tooltip.
- An empty state says "No <things> yet." plus at most one link with a short verb phrase: "No sources yet. Add one". No explanation sentence.
- Optional fields hide behind one opener, at most one level deep.

# The two marks

👔 marks the employee side and ⚡ the freelance side. They go on the pill, on titles and buttons that exist for one side only (the Freelance exports, the Settings navigation, "Balance over time") and on the Dashboard blocks that sit next to each other. They are decoration plus a quick signal, so they are `aria-hidden` and the accessible name stays plain ("Employee", "Freelance"). An icon or emoji is never the only label of a button.

# Decisions log

- 2026-11-05: the Employee/Freelance pill sits in the page head, left of the year, on every page that has it. It replaced the tab strip of Days.
- 2026-11-05: exports are `.head-btn` pills in the head with short names. The bottom "Export" blocks went away.
- 2026-11-05: hours keep trimmed totals and two-decimal deltas; money always has cents; the calculator uses Spanish decimals.
- 2026-11-05: tab counts ("65 days", "4 blocks") were removed; tabs are named, not counted.
- 2026-11-05: five hints were removed by name: "hover a day · click to open it in Log", "for the range shown", "Billed · 2026", the "still to bill over ... weeks" line and the calculator's "hourly, daily, net yearly" sentence.
- 2026-11-05: every primary button takes the look of "+ Add block".
- 2026-11-05: dates keep two forms on purpose, ISO for lookup and short for glancing (see Numbers and dates).
- 2026-11-05: Kronos is dark only: the light theme and its switch were removed.
- 2026-11-05: the "ahead overall" line under the title was removed; the Dashboard hero already says it.

# Look at it

Tests that read the markup cannot see a label that sits off-centre in its button, a name that wraps onto two lines or a line of text that came back. Those were found by eye, after the tests were green. So every UI change is looked at before it is called done, and that is a rule of the workspace (`software/AGENTS.md`, "UI validation"), not a preference.

1. Shoot every screen you touched at 1280px and at 375px (`python bin/kctl.py shot "/#<tab>" --out .artifacts/x.png`, add `--viewport phone`) and open the images. Say what you saw.
2. Run `tests/e2e/test_ui_geometry.py`. It measures every tab at both widths: the text of a control sits in its middle, no label takes two lines, no text is clipped, the page does not scroll sideways. It has a positive control, a test that must report a deliberately broken button, so it cannot pass by measuring nothing.
3. A change adds the assertion for what it touched, and one bad style is planted to see the audit turn red.

A framework's defaults can undo your CSS silently: Pico styles `a[role=button]` with more weight than a plain class, which is how the new export pills ended up off-centre. When a control looks wrong, compare its computed style with what you wrote.

# Before you ship a UI change

Answer yes or no. Any "no" is a reason to stop.

1. Does the page start with the standard page head, with the controls in the fixed order?
2. Is there at most one primary button in view?
3. Does every colour, spacing and size come from a token and not from a raw value?
4. Do all numbers go through the shared helpers, with `.metric`?
5. Are button labels verb-first, in sentence case, and the same verb for the same action as elsewhere?
6. Did you choose tabs, segmented control or toggle by what the control does?
7. Does every list, table and chart have an empty state with at most one action?
8. Is anything important only in a tooltip, or behind more than one opener?
9. Does reduced motion still turn the animation off? (Kronos is dark only: there is no theme to check.)
10. Did you open the screenshots (1280px and 375px) next to the neighbouring page, and does `test_ui_geometry.py` pass?
11. Did you update this guide or `DESIGN.md` if a pattern changed?

# How the guide is enforced

- `tests/e2e/test_ui_pagehead.py` walks every tab and asserts that it has one page head, that the title comes first, that the year selector is the last control, that the pill comes after the page's buttons and just before the year, that the pill keeps its height between Days and Analytics, and that the controls end at the right edge of the head.
- `tests/e2e/test_ui_geometry.py` measures the drawn boxes on every tab at 1280px and 375px: centred text, one line, no clipping, no sideways scroll, no theme switch and no line under the title.
- `tests/e2e/test_ui_consistency.py` asserts the export names in the head, the removed hints and that the primary buttons share one look.
- `tests/unit/test_ui_rules.py` reads the templates and fails on a bottom "Export" block, the old export names, a second primary-button class, a ghost button, money without cents outside a chart, a hand-made number format, an h3 as page-level title and any hint from the removed list.
- To see the app's buttons, tabs and heads side by side, run `python bin/kctl.py up --seed`, then `python bin/kctl.py shot "/#<tab>"` for each tab, and compare them. Do it by hand before each UI phase; a pixel diff in the pipeline would be flaky.

# Sources

- Nielsen Norman Group: ten usability heuristics, consistency and standards, Jakob's law, tabs, toggle switches, tooltips, progressive disclosure, empty states and icon usability (nngroup.com).
- Primer (GitHub): PageHeader and Button components (primer.style).
- GOV.UK Design System: button and table components, and the A-to-Z style guide (design-system.service.gov.uk).
- Atlassian design system: empty states and language (atlassian.design).
- MDN: `font-variant-numeric` and `Intl.NumberFormat`.
