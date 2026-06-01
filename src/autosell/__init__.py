"""Auto-sell queue: surface positions whose hold_until has passed.

Phase 8 is intentionally **operator-in-the-loop**: a daily CLI lists
positions that are due for sell (Spin-off ≥ 5 days post record date,
Special-div ≥ 1 day post ex-date) and the GUI surfaces them in a
review pane. The operator clicks "Sell now" per row, which routes
through the existing trade runner — same dry-run gate and
typed-LIVE confirm as a manual sell.

Why not fully unattended: actually placing sells requires the
vault master password to decrypt broker credentials. Storing that
unattended either (a) defeats the vault's purpose or (b) requires a
separate kill switch + credential-vending design that's bigger than
this feature's value. The operator-in-loop pattern keeps the same
nightly-launchd cadence (the CLI sends a Discord webhook if there's
work to do) without the credential-exposure cost.
"""

from src.autosell.finder import DueSell, find_due_sells

__all__ = ["DueSell", "find_due_sells"]
