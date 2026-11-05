# Kronos design

The look Kronos already has, written down so the next session keeps it. Change the CSS and this file
together. How information is presented (page head, buttons, numbers, hints, empty states) is in
`UI_GUIDE.md`: read it before any UI change.

## Look

Dark antique brass, with a parchment light theme. Everything comes from the `--k-*` variables at the
top of `backend/static/styles.css` (`--k-bg`, `--k-surface`, `--k-border`, `--k-text`, `--k-muted`,
`--k-brass`, plus one variable per day type and for surplus and deficit). Never write a raw colour in
a component: the light theme (`[data-theme="light"]`) only works through the variables.

- Headings and labels use small-caps with a little letter spacing, never upper case.
- Numbers (hours, money, dates in tables) use the `.metric` class: monospace with tabular figures.
- Brass is the one accent: the main action, the current thing, a hover. Paid-out freelance money has
  its own teal (`--paid`) and is never brass.
- Weak information is muted, not smaller than 0.68rem.

## Patterns to reuse

- A secondary, optional field is a `+ Add ...` button (`secondary outline`) that opens the field in
  place: breaks, notes. Nothing optional sits open on the page by default.
- A chip that states something and can be clicked is a small rounded outline in brass (`.fl-jump`,
  `.update-pill`). The same shape is used for "W45 in Days".
- A table separator names a period and sums it (`.month-sep`, `.week-sep`).
- From 1100px a form card may have a rail beside it with the result and the main button. Below that
  it is one column.
- Less text: a card title does not need a hint line. If a label is clear, nothing explains it. Tabs
  are named, not counted; charts carry their caption in a `title`, not under them.
- The two lives wear a mark: 👔 for the employee side, ⚡ for freelance (card titles, the Days tabs,
  the Employee/Freelance switches, "Balance over time"). Both are `aria-hidden`.
- Two charts that share a row fill the height the neighbouring column leaves, instead of leaving a
  hole (Analytics: Weekday pattern and Daily surplus under the balance chart).

## Motion

Kronos should feel tactile and alive. Every interaction answers: buttons lift on hover and press on
click, things that open or change animate briefly (about 150-300 ms), a figure that changes pulses
once. Motion that nobody triggered happens at most once. Every animation has a
`prefers-reduced-motion: reduce` override that turns it off.

## Version label and updates

The faint "v39" next to the title is the phase number (`backend/app/version.py`). The "Update ready"
pill is the only way the app tells the user that a newer build exists, and it never reloads the page
by itself.
