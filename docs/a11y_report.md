# Accessibility report

This report records what axe found on every tab of Kronos, at 1280 px and at 375 px. Axe is a tool that inspects a page in the browser and flags what makes it hard to use with a screen reader, with the keyboard alone or with poor eyesight. The scan runs against the demo server, which has the same data and the same frozen date every day, so the result does not move with the calendar. This unit only measures: nothing has been fixed.

# Summary

Axe reports 184 elements with serious impact, all of them for low colour contrast, and 2 elements with minor impact for an empty table header. There are no critical or moderate findings. The counts are per tab and per width, so an element that fails at both widths counts twice. The serious ones are recorded in `tests/e2e/a11y_known.json` as 53 distinct entries, and any new serious or critical finding now fails the e2e suite.

Two rules that showed up in an earlier scan are gone. The heatmap cells now have a role, and the scrollable heatmap and the Years table can take focus, so `aria-prohibited-attr` and `scrollable-region-focusable` no longer appear.

# Colour contrast (color-contrast)

This rule asks that text stand out from its background by at least 4.5 to 1. It is the only serious finding left, and it breaks down like this:

- Version label (`.brand-ver`), 14 elements, one per tab at each width. It is faint on purpose, because Miguel asked for a discreet version number. It stays in the list as a known, accepted finding. If it should ever stop being reported, the only honest way is to exempt it in the scan with a comment saying why.
- Days, 97 elements at 1280 px and about half that at 375 px, all in the rows of days without work (weekend, holiday, sick, vacation, flex): the weekday name, the day pill and the numbers. Proposal: raise the text colour of the `.non-work` row from the dim tone to one that meets 4.5 to 1, and keep the row dimmed through its background instead.
- Dashboard, 8 elements at each width: the holiday note in the quick log (`.ql-holiday`) and the weekday names of the empty, weekend and current days in the week strip. Proposal: use the normal muted text tone for `.wd-dow` in those states, and darken the holiday note.
- Plan, 3 elements at each width besides the version: the flex and holiday text and the dial label (`.subdial-label`). Proposal: lighten those three tones until they pass.
- Freelance, 3 elements at each width besides the version: the labels inside the tax split bar (`.calc-seg-lbl`). Proposal: pick the label colour per segment, dark text on light segments and light text on dark ones.

# Empty table header (empty-table-header)

This rule, of minor impact, warns that a column header has no text, so a screen reader announces nothing for it. It affects 2 elements, the second column header of the table in Days, once at each width. It is not in the known list, because that list only holds serious and critical findings. Proposal: put a visually hidden text in that `th` that says what the column holds.

# How the scan works

Each test opens a tab in a fresh browser context with the language, the time zone, the dark scheme and the reduced motion setting of the snapshot tests, and with the clock fixed to the demo date. It waits for the network to be idle, for the fonts and then 300 ms more, so entry animations cannot change the contrast it measures. Before storing a finding, the test removes attribute values such as `[title="..."]` from its selector, so a change of wording or of an amount does not alter the list. Each entry is otherwise exact: a new element on a rule that is already allowed still fails, and an entry that axe no longer finds also fails, with a message asking to delete it, so the list can only shrink.

To regenerate the list after fixing something, run `KRONOS_A11Y_UPDATE=1 pytest tests/e2e/test_ui_a11y.py`. A separate test injects a button without a label and checks that axe reports it, so the scan cannot pass by scanning nothing.

# Where it was run

The scan gives the same result on Windows and in the Linux image of the pipeline, so the list holds in both.
