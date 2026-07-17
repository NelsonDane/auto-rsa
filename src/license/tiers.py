"""Tier names, per-tier broker caps, and per-broker sub-account caps.

Single source of truth for the gating rule. Any future tier or limit
change happens here, never inline at a call site.

Two axes:
* **broker cap** (``TIER_CAPS``) — how many parent brokerage logins a
  tier may configure. ``None`` = unlimited.
* **sub-account cap** (``SUBACCOUNT_CAPS``) — how many accounts *within*
  each broker may place orders per run. ``None`` = unlimited. The Friend
  tiers cap this at 1 (no multi-account fan-out) — the enforcement point
  that keeps a friend's footprint small and low-troubleshooting.

Friend tiers (the fork the operator ships to friends):
* ``friend_lite`` — 1 broker, 1 account. The trial: sign in to a single
  broker at a time, no multi-account support.
* ``friend_main`` — many brokers, 1 account each.
"""

from __future__ import annotations

from typing import Literal

Tier = Literal[
    "unlicensed",
    "basic",
    "advanced",
    "operator",
    "friend_lite",
    "friend_main",
]

# How many parent brokerage logins a tier permits. ``None`` = unlimited.
TIER_CAPS: dict[Tier, int | None] = {
    "unlicensed": 1,
    "basic": 1,
    "advanced": 5,
    "operator": None,
    "friend_lite": 1,     # trial: one broker at a time
    "friend_main": None,  # many brokers
}

# How many accounts WITHIN each broker may trade per run. ``None`` =
# unlimited (the pro tiers keep multi-account fan-out). Friend tiers = 1.
#
# ``unlicensed`` is None here (pro "try it" state is unchanged), but
# manager.subaccount_cap() tightens it to 1 in a FRIEND build so a lapsed
# offline friend can't trade uncapped — see there.
SUBACCOUNT_CAPS: dict[Tier, int | None] = {
    "unlicensed": None,
    "basic": None,
    "advanced": None,
    "operator": None,
    "friend_lite": 1,
    "friend_main": 1,
}

# Pretty display names for the GUI banner.
TIER_LABEL: dict[Tier, str] = {
    "unlicensed": "Unlicensed",
    "basic": "Basic",
    "advanced": "Advanced",
    "operator": "Operator",
    "friend_lite": "Friend Lite",
    "friend_main": "Friend Main",
}
