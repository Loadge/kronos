# Request

Miguel, 2026-11-04, on the Kronos freelance side (Phases 34 and 35):

> The current version of Kronos feels amazing, but there's an issue. For the Freelance parts, one thing is the Options I specify, how much do I expect to earn each day, and the estimations based on that. But another thing is what reality brings: what amount of money do I actually get paid. Reality tends to change: they implement new bonuses, they do different rates each week in the same project...
>
> I think having a default $ rate for a project is fine, defined in Options nowadays, but I think there should be a way to "correct" or "adjust" the actual money I've received. But I don't know what the best way would be to do it.
>
> Should the money adjustment be done per-week? Or per month? For example, having a way to say "in this week, I've earned 3000€" and then the dashboards, graphs and estimations can act accordingly. The "corrections" or "adjustments" or "reality inputs" (please suggest a better name haha) take priority over the estimations or the activity in the Log. In the absence or a "correction" for a particular week, the numbers taken into consideration are then the ones present at the Log/estimations.
>
> If possible it would be a good idea to not have a new Page to navigate to. I believe we can make this work from the Log tab, or maybe from the Days page, since it's already divided into months. Maybe Days could also be divided into Weeks to allow the input of "corrections" from the real world payments.
>
> Let's have a grill-me session maybe?

# What Kronos does today (checked in the code before the interview)

Kronos has no payment concept yet. A freelance block stores its own snapshot when it is saved: the rate and currency of its income source, plus the ECB rate of its date for a USD source. The rate and the exchange rate of a single block can already be edited from the Log tab (the pencil), so a one-off price works today, but only one block at a time and only as a rate, never as "the client paid me this much for the week".

Every sum is built in `backend\app\services\freelance.py` from the blocks' euros (`Sum.add`, `money(amount_eur)`), and `GET /api/freelance/summary` is the one read behind the Freelance tab, the dashboard card and Analytics: totals, this week and month, per month, per source, the four 130s and the projection. The projection bills the planned hours at the €/h realised so far.

Days already has a ⚡ Freelance sub-tab with one row per block, a separator per month, the source filter and the freelance PDF (`GET /timesheet/freelance`).

Phases 34 and 35 are on `master` (`3baed75`, plus the fix `9314942`) and still marked "awaiting confirmation" in `docs\BUILD_PHASES.md`.
