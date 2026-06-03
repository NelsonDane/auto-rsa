"""License-tier gating: parent brokerage login cap by activation state.

This package implements the design in ``docs/LICENSE_TIERS_DESIGN.md``.

Module layout:

* ``tiers``       — Tier names + per-tier broker caps (single source of truth).
* ``fingerprint`` — Stable per-machine hardware ID (binds a token to a host).
* ``verify``      — Ed25519 signature verification + canonical JSON.
* ``token_store`` — Read/write the cached signed token on disk.
* ``manager``     — The one entry point the rest of the app talks to:
                   ``current_tier()``, ``account_cap()``,
                   ``can_add_broker(current_count)``, ``status_summary()``.

Phase 1 (this slice): core module + vault enforcement + GUI banner. No
server contact yet — tokens must already be on disk (or absent, in
which case the tool runs in **unlicensed** mode: 1 parent broker,
swappable).

Phase 3 will add ``client`` (POST /activate, /refresh) and the GUI
License tab once the Cloudflare Worker is up.
"""

from src.license.manager import (
    account_cap,
    bypass_flag_path,
    can_add_broker,
    current_tier,
    set_bypass_flag,
    status_summary,
)
from src.license.tiers import TIER_CAPS, Tier

__all__ = [
    "TIER_CAPS",
    "Tier",
    "account_cap",
    "bypass_flag_path",
    "can_add_broker",
    "current_tier",
    "set_bypass_flag",
    "status_summary",
]
