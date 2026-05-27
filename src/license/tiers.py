"""Tier names and per-tier parent-brokerage caps.

Single source of truth for the gating rule. Any future tier or
limit change happens here, never inline at a call site.
"""

from __future__ import annotations

from typing import Literal

Tier = Literal["unlicensed", "basic", "advanced", "operator"]

# How many parent brokerage logins a tier permits.
# ``None`` = unlimited (Operator).
TIER_CAPS: dict[Tier, int | None] = {
    "unlicensed": 1,
    "basic": 1,
    "advanced": 5,
    "operator": None,
}

# Pretty display names for the GUI banner.
TIER_LABEL: dict[Tier, str] = {
    "unlicensed": "Unlicensed",
    "basic": "Basic",
    "advanced": "Advanced",
    "operator": "Operator",
}
