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

# Reason codes classify_outcome returns for a NON-fill outcome. A line that
# trips the fill regex but ALSO classifies as one of these is not a genuine
# fill (see _is_genuine_fill).
_NONFILL_CODES = frozenset(_MESSAGES)


def _is_genuine_fill(line: str) -> bool:
    """Report whether a fill-looking line is a real fill, not a non-fill.

    ``is_fill_line`` matches "buy N of X", but a broker can print the
    rejection reason on that SAME line — Robinhood appends its raw
    ``non_field_errors`` ("You do not have enough buying power", "not
    available for trading", "not permitted to trade this security"), which
    carries no failure keyword for the fill regex's negative gate to catch.
    The outcome classifier DOES recognize those (NO_FUNDS / STOCK_UNAVAILABLE
    / RESTRICTED / …), so it vetoes the line — the ledger already records it
    REJECTED, and the friendly icon must not claim ✅.
    """
    if not is_fill_line(line):
        return False
    return classify_outcome(line, success=False) not in _NONFILL_CODES


def friendly_summary(lines: list[str]) -> tuple[str, str]:
    """Return (icon, one-line plain message) for a broker's status lines.

    A broker's grouped lines can span MANY tickers/accounts, so we can't
    just classify the joined blob — a rejection or "not available" for one
    ticker must not hide a genuine fill for another. The rule that matches
    the UI's own contract ("✅ = at least one order placed"):

    1. If any line is a GENUINE fill (_is_genuine_fill: the fill regex matches
       AND the line doesn't ALSO classify as a known non-fill like NO_FUNDS /
       STOCK_UNAVAILABLE / RESTRICTED — Robinhood prints the rejection reason
       on the same "buy N of X" line) or a broker's explicit placed/verified
       confirmation, AND no pending signal says an accepted order isn't
       confirmed → ✅. A fill on ticker A wins over an error/reject on ticker B
       (both still visible in the details expander).
    2. Else if a queued/pending signal is present (and no genuine fill) → ⏳.
    3. Else classify the failure/benign outcome (session, unavailable,
       rejected, error, …), or "ran clean, nothing placed".
    """
    if not lines:
        return _EMPTY
    text = "\n".join(lines)
    low = text.lower()

    has_fill = any(_is_genuine_fill(ln) for ln in lines) or any(
        m in low for m in _POSITIVE_FILL_MARKERS
    )
    has_pending = any(m in low for m in _PENDING_MARKERS)

    # 1) A genuine fill wins — unless a pending marker says it's not confirmed.
    if has_fill and not has_pending:
        return _FILLED
    # 2) Accepted-but-not-yet-filled.
    if has_pending:
        return _PENDING
    # 3) No genuine fill → classify the failure / benign outcome.
    code = classify_outcome(text, success=False)
    if code in _MESSAGES:
        return _MESSAGES[code]
    if any(m in low for m in _REJECT_MARKERS) or any(m in low for m in _ERROR_MARKERS):
        return _ERROR
    return _CLEAN
