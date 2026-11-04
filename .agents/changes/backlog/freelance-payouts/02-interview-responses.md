# Interview

Grill-me session, 2026-11-04. Every answer was the recommended one, so there are no accepted risks.

| # | Question | Answer | Recommended? |
|---|---|---|---|
| Q1 | What period does one payout cover? | ISO week, Monday to Sunday. A monthly client's money goes in the month's last week | Yes |
| Q2 | Per income source, or one total? | Per source, in that source's currency. Other sources of the same week keep their estimate | Yes |
| Q3 | What does a payout do to the numbers? | It replaces the source's estimated money for that week in every sum. The blocks keep their own estimate, the hours stay, the €/h moves and the gap is shown | Yes |
| Q4 | Name | "Payout" ("estimated $2,640, payout $3,000") | Yes |
| Q5 | Currency and exchange rate | The source's currency. A USD payout takes the ECB rate of the week's Sunday (in practice the last published day, a Friday), editable by hand. No rate means missing, never 1:1. Bank fees go to "other expenses" in Taxes | Yes |
| Q6 | Where is it typed? | In a header per ISO week inside Days, ⚡ Freelance: per source, the estimate and the payout. The Log's ⚡ card shows the week's payout read-only | Yes |
| Q7 | A week across two months or two years | Spread pro-rata over the week's days by each day's block estimate, because the IRPF counts income by when it is earned ("devengo") | Yes |
| Q8 | Payout in a week with no blocks of that source | Allowed: the money counts with 0h, dated on the week's Sunday, and flagged "payout with no hours" | Yes |
| Q9 | Stop? | No | |
| Q10 | Editing blocks of a week that already has a payout | The payout wins, silently: hours, €/h and the gap update. Deleting the payout goes back to the estimate, with Undo in the ribbon | Yes |
| Q11 | Paid and estimated on the screens | Every freelance total shows the split ("€9,200, €7,400 paid out, €1,800 estimated"): Freelance hero and monthly bars (lighter shade for the estimated part), dashboard card, Analytics ledger. Past weeks with blocks and no payout get a quiet "awaiting payout" in Days. No nagging | Yes |
| Q12 | PDF and CSV | The freelance PDF keeps its block rows and adds a payout line under each week that has one ("W44 payout $3,000, +$360 over the estimate"), and its totals use the payouts. The CSV export gets the payouts as their own file | Yes |
| Q13 | Which phase | Confirm and archive Phases 34 and 35 as they are. Payouts become Phase 37, built before Phase 36 (Tactile Kronos) | Yes |
| Q14 | Mockups first? | Yes, one round: the Days week header and the Freelance hero and bars. The PDF line follows the header | Yes |
| Q15 | Stop? | Yes | |
| Q16 | Handoff | C: save and start here. Claude orchestrates and reviews, the code is written by cheaper subagents (not the local model) | |

# Accepted risks

None.

# Unresolved

None. Two points were not asked because they are not a choice: the backup carries the payouts (version 4, with the fidelity test), and a source with payouts cannot be deleted, only archived (the same rule as blocks).
