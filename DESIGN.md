# Kronos design

The look Kronos already has, written down so the next session keeps it. Change the CSS and this file
together. How information is presented (page head, buttons, numbers, hints, empty states) is in
`UI_GUIDE.md`: read it before any UI change.

## Look

Dark antique brass, and only dark: Kronos has no light theme (Miguel, 2026-11-05) and no theme
switch; `<html data-theme="dark">` is fixed. The printable timesheet keeps its own light or dark
paper, a separate template. Everything comes from the `--k-*` variables at the top of
`backend/static/styles.css` (`--k-bg`, `--k-surface`, `--k-border`, `--k-text`, `--k-muted`,
`--k-brass`, plus one variable per day type and for surplus and deficit). Never write a raw colour in
a component.

- Headings and labels use small-caps with a little letter spacing, never upper case.
- Numbers (hours, money, dates in tables) use the `.metric` class: monospace with tabular figures.
- Brass is the one accent: the main action, the current thing, a hover. Paid-out freelance money has
  its own teal (`--paid`) and is never brass.
- Weak information is muted, not smaller than 0.68rem. The labels of the phone's tab bar are the one
  exception, at 0.6rem: six of them have to fit a 320px screen, and each sits under its icon.

## Patterns to reuse

- A secondary, optional field is a `+ Add ...` button (`secondary outline`) that opens the field in
  place: breaks, notes. Nothing optional sits open on the page by default.
- A chip that states something and can be clicked is a small rounded outline in brass (`.fl-jump`,
  `.update-pill`). The same shape is used for "W45 in Days".
- A table separator names a period and sums it (`.month-sep`, `.week-sep`).
- The bezel (`.bz`) is a strip with one tick per week over the Days table: a map of the year and the
  way to open, close and reach weeks. Lit brass means open, teal means open and paid out.
- The day ribbon (`.dr`) draws the day in Log: a brass bar you can drag, notches for breaks, a flag where
  the target is reached, and the surplus in lit coin after it. It only writes what the time fields write.
- The year dial (`.yd`, `dial.js`) opens from the logo: the year as a chronograph whose outer ring turns,
  one day per detent. It is the one place with brushed metal: the `--k-metal-*` tokens stay inside it.
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
`prefers-reduced-motion: reduce` override that turns it off. The one exception to the "at most once" is the
small second hand of the year dial, which ticks because it is a clock, and only while the dial is open.

## Version label and updates

The faint "v49" next to the title is the phase number (`backend/app/version.py`). The "Update ready"
pill is the only way the app tells the user that a newer build exists, and it never reloads the page
by itself.
