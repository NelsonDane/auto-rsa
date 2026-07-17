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
_PENDING = (
    "⏳",
    "Order accepted but not confirmed filled yet — check Balances, or try "
    "again.",
)
_CLEAN = ("🟡", "Ran, but no order went through here.")
_ERROR = (
    "❌",
    "Something went wrong with this broker. Try again; if it keeps happening, "
    "alert the admin.",
)
_EMPTY = ("⚪", "No status yet.")

# Markers that mean a genuine failure (vs. a clean run that placed nothing).
_ERROR_MARKERS = ("error", "fail", "unsuccessful", "unable", "timed out", "exception")
# Explicit rejection wording a broker may print ON a line that ALSO looks
# like a fill (e.g. "buy 1 of X: Success: False, Status: REJECTED").
_REJECT_MARKERS = (
    "rejected", "declined", "denied", "not placed", "not filled",
    "success: false",
)
# Accepted-but-not-yet-filled: a working/queued order is NOT a fill.
_PENDING_MARKERS = ("queued", "unconfirmed", "not a confirmed fill", "pending")
# Broker confirmations that don't match the generic fill regex but DO mean
# a real fill (checked only AFTER the failure/pending markers above).
_POSITIVE_FILL_MARKERS = ("order placed", "verification was successful")


def friendly_summary(lines: list[str]) -> tuple[str, str]:
    """Return (icon, one-line plain message) for a broker's status lines.

    Order matters: a real failure/rejection/pending signal must win over a
    submission line that merely *looks* like a fill — otherwise a rejected
    or queued order gets shown as "Order placed" (the false-success class
    this project has repeatedly fought).
    """
    if not lines:
        return _EMPTY
    text = "\n".join(lines)
    low = text.lower()
    # 1) A recognized outcome code (session error, stock unavailable,
    #    market closed, no funds, restricted, filtered, ledger skip).
    code = classify_outcome(text, success=False)
    if code in _MESSAGES:
        return _MESSAGES[code]
    # 2) An explicit rejection / failure marker → real failure.
    if any(m in low for m in _REJECT_MARKERS) or any(m in low for m in _ERROR_MARKERS):
        return _ERROR
    # 3) Accepted-but-not-filled (queued/pending) → not a fill.
    if any(m in low for m in _PENDING_MARKERS):
        return _PENDING
    # 4) A genuine fill — a fill line, or a broker's explicit placed/verified
    #    confirmation, with NO failure/pending signal (ruled out above).
    if any(is_fill_line(ln) for ln in lines) or any(m in low for m in _POSITIVE_FILL_MARKERS):
        return _FILLED
    # 5) Ran, nothing placed here.
    return _CLEAN
