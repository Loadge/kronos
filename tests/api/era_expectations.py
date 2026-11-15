"""What the era fixtures hold and what must come out of them, written by hand.

``tests/fixtures/eras`` holds databases, API answers and backups written by the real code of
past versions (see its ``build_eras.py``). The migration to a chain of accounts and the
restore of an old backup must both give these chains: the figures here were read off the
fixtures and added up by hand, never produced by the code under test.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ERAS = REPO / "tests" / "fixtures" / "eras"
TODAY = "2026-11-11"

# What a payout is worth and what it is measured against: none of these may move.
MONEY = (
    "source_id",
    "week_start",
    "amount",
    "currency",
    "fx_rate",
    "amount_eur",
    "rate_source",
    "rate_date",
    "note",
    "blocks",
    "minutes",
    "estimate_amount",
    "estimate_eur",
    "billed_amount",
    "billed_currency",
    "billed_eur",
    "fx_cost_eur",
    "effective_rate",
)

# payout id -> its chain after the migration: (account, amount) from first to last.
LEGS_V56 = {
    1: [("USD account", 750.0)],  # before accounts, and without a rate
    2: [("USD account", 1800.0)],
    3: [("EUR account", 480.0)],
    4: [("USD account", 2000.0)],
    5: [("USD account", 700.0)],
    6: [("Main bank", 1650.0)],  # dollars billed, euros landed
    7: [("Dollar account", 1900.0)],
    8: [("Cold wallet", 0.021)],
    9: [("Cold wallet", 0.022)],
    10: [("EUR account", 600.0)],  # the accounts era, still without one
    11: [("Dollar account", 700.0)],
    12: [("Closed bank", 500.0)],  # an account archived since
}
LEGS_V57 = LEGS_V56 | {
    13: [("Stripe", 999.0), ("Main bank", 894.76)],
    14: [("USD account", 1500.0), ("Dollar account", 1480.0)],  # sent in a bare currency
    15: [("USD account", 1200.0), ("Dollar account", 1190.0)],  # sent from where it arrived
    16: [("Main bank", 1500.0)],  # as billed
    17: [("EUR account 2", 500.0), ("EUR account", 495.0)],  # no account on either side
    18: [("Wise", 300.0), ("EUR account", 300.0)],
}
LEGS = {"v56": LEGS_V56, "v57": LEGS_V57}
# The accounts the migration makes, in the order it makes them.
MADE = {
    "v56": [("USD account", "USD"), ("EUR account", "EUR")],
    "v57": [("USD account", "USD"), ("EUR account", "EUR"), ("EUR account 2", "EUR")],
}

# The sum of what arrived, per currency, added up by hand from the fixtures' payouts.
ARRIVED = {
    "v56": {"USD": 7850.0, "EUR": 3230.0, "BTC": 0.043},
    "v57": {"USD": 10520.0, "EUR": 6419.76, "BTC": 0.043},
}
CHAINS = {
    "v56": {"Northwind Labs": ["Main bank"], "Local consulting": [], "Old client": []},
    # Paid from, then paid into; the same account twice is one; an archived one is left out.
    "v57": {
        "Northwind Labs": ["Stripe", "Main bank"],
        "Local consulting": ["Wise"],
        "Old client": [],
    },
}
ACCOUNT_ORDER = {
    "v56": [
        "Main bank",
        "Dollar account",
        "Cold wallet",
        "Closed bank",
        "USD account",
        "EUR account",
    ],
    "v57": [
        "Main bank",
        "Dollar account",
        "Cold wallet",
        "Closed bank",
        "Stripe",
        "Wise",
        "USD account",
        "EUR account",
        "EUR account 2",
    ],
}
