"""Plain-language broker status — friendly summaries from raw engine output.

Turns a broker's verbatim status lines into one sentence a non-technical
friend can act on, reusing the outcome classifier (src/outcomes.py) so the
wording stays consistent with the ledger's own reason codes. The raw lines
stay available (a 'details' expander in full mode) — this leads with the
gist, it never hides information from the operator.
"""

from __future__ import annotations

from src.outcomes import (
    FILTERED,
    LEDGER_SKIP,
    MARKET_CLOSED,
    NO_FUNDS,
    PRICE_REJECTED,
    RESTRICTED,
    SESSION_ERROR,
    STOCK_UNAVAILABLE,
    classify_outcome,
    is_fill_line,
)

# code -> (icon, friendly one-liner). Anything unmapped falls through to
# the "real error" or "ran clean" cases below.
_MESSAGES: dict[str, tuple[str, str]] = {
    SESSION_ERROR: (
        "⚠️",
        "Couldn't sign in — the broker asked for verification or the login "
        "didn't go through. Try again; if it keeps happening, alert the admin.",
    ),
    STOCK_UNAVAILABLE: ("🟡", "This stock isn't available to trade at this broker."),
    RESTRICTED: ("🟡", "This stock is restricted or halted at this broker right now."),
    NO_FUNDS: ("🟡", "Not enough buying power in this account for the order."),
    MARKET_CLOSED: (
        "🟡",
        "The market is closed for this kind of order — try during market hours.",
    ),
    PRICE_REJECTED: (
        "🟡", "The broker rejected the order price — try during market hours.",
    ),
    FILTERED: ("⚪", "Skipped — this account is filtered out."),
    LEDGER_SKIP: ("⚪", "Skipped — already recorded (no double-buy)."),
}

_FILLED = ("✅", "Order placed.")
_CLEAN = ("🟡", "Ran, but no order went through here.")
_ERROR = (
    "❌",
    "Something went wrong with this broker. Try again; if it keeps happening, "
    "alert the admin.",
)
_EMPTY = ("⚪", "No status yet.")

# Markers that mean a genuine failure (vs. a clean run that placed nothing).
_ERROR_MARKERS = ("error", "fail", "unsuccessful", "unable", "timed out", "exception")


def friendly_summary(lines: list[str]) -> tuple[str, str]:
    """Return (icon, one-line plain message) for a broker's status lines."""
    if not lines:
        return _EMPTY
    if any(is_fill_line(ln) for ln in lines):
        return _FILLED
    text = "\n".join(lines)
    code = classify_outcome(text, success=False)
    if code in _MESSAGES:
        return _MESSAGES[code]
    # Unclassified: tell a real error apart from a clean no-order run.
    low = text.lower()
    if any(m in low for m in _ERROR_MARKERS):
        return _ERROR
    return _CLEAN
