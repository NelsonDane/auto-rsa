"""Normalize a broker order result into a reason code.

Domain reality (from operator experience): the low-float reverse-split
tickers are frequently *unavailable or restricted* on a given broker
even when the session is perfectly healthy. So "nothing was bought"
must be explainable — a stock-unavailable outcome is benign and must
not be treated as a tool/session failure.

``classify_outcome`` maps the free-text result/skip/error a broker
produced into a stable code. Two predicates drive policy:

* :func:`is_session_problem` — genuine auth/session breakage; the
  auto-executor should skip the broker and alert, and the session
  panel should draw attention.
* :func:`is_benign_no_trade` — connection was fine, the order just
  couldn't/shouldn't happen here (filtered, already done, stock
  unavailable/restricted, market closed). Expected; never an alarm.
"""

from __future__ import annotations

import re

OK = "OK"  # order placed/verified
FILTERED = "FILTERED"  # our own per-account allow-list skip
LEDGER_SKIP = "LEDGER_SKIP"  # ledger idempotency / economic dedupe
STOCK_UNAVAILABLE = "STOCK_UNAVAILABLE"  # symbol not tradable here
RESTRICTED = "RESTRICTED"  # restricted/halted/not permitted
NO_FUNDS = "NO_FUNDS"  # insufficient buying power
MARKET_CLOSED = "MARKET_CLOSED"  # market order rejected off-hours
PRICE_REJECTED = "PRICE_REJECTED"  # limit collar / decimal reject
SESSION_ERROR = "SESSION_ERROR"  # login/2FA/auth/closed browser
OTHER = "OTHER"  # unclassified failure

_SESSION = frozenset({SESSION_ERROR})
_BENIGN = frozenset(
    {FILTERED, LEDGER_SKIP, STOCK_UNAVAILABLE, RESTRICTED, MARKET_CLOSED},
)

# Ordered: the first matching pattern wins. Specific/clear signals
# (our skips, broker error codes, auth breakage) are checked before
# broad "unavailable" wording so a precise cause isn't shadowed.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (FILTERED, re.compile(r"not in account filter", re.IGNORECASE)),
    (LEDGER_SKIP, re.compile(r"ledger:|already executed|in-flight|no double-buy", re.IGNORECASE)),
    (SESSION_ERROR, re.compile(
        r"login failed|got error page|target (?:page|closed)|"
        r"browser has been closed|targetclosederror|sign\s?-?in|"
        r"\b2fa\b|otp|captcha|not logged in|authentication|unauthorized|"
        r"invalid (?:credentials|password)|session expired",
        re.IGNORECASE,
    )),
    (MARKET_CLOSED, re.compile(
        r"146034|non[\s-]?market hours|market orders? for securities|"
        r"does not accept market orders|outside (?:of )?market hours",
        re.IGNORECASE,
    )),
    (PRICE_REJECTED, re.compile(
        r"ma5010|limit price entered is too far|too far away from the last|"
        r"decimal|price is not valid|invalid (?:limit )?price",
        re.IGNORECASE,
    )),
    (NO_FUNDS, re.compile(
        r"insufficient|buying power|not enough (?:cash|funds|money)|"
        r"exceeds.*(?:cash|balance)",
        re.IGNORECASE,
    )),
    (RESTRICTED, re.compile(
        r"restricted|halted|not permitted|not allowed|prohibited|"
        r"closed to new positions|cannot be (?:traded|purchased)|"
        r"trading (?:is )?(?:disabled|suspended)",
        re.IGNORECASE,
    )),
    (STOCK_UNAVAILABLE, re.compile(
        r"not available|unavailable|no longer available|"
        r"symbol not found|ticker not found|security not found|"
        r"not found|no such (?:symbol|security)|cannot find|"
        r"not tradable|not eligible|no quote",
        re.IGNORECASE,
    )),
)


# Positive/negative regexes for live-progress fill detection. A line
# is counted as a fill only when the positive pattern matches AND no
# failure marker is present on the same line. Wells Fargo emits both
# "Buy 1 shares of FOO" and "FAILED!" in the same print on rejection,
# so the negative gate is load-bearing.
_FILL_POS_RX = re.compile(
    r"(?:Bought|Sold)\s+\d|"
    r"(?:buy|sell)\s+\d+(?:\.\d+)?\s+(?:shares?\s+)?of\s+\S+|"
    r":\s*(?:Dry\s+Run\s+)?Success(?!\w)",
    re.IGNORECASE,
)
_FILL_NEG_RX = re.compile(
    r"\bfailed\b|\berror\b|\bskipped\b|\bcancel(?:l?ed)?\b|"
    r"\bunable\b|\bvalidation failed\b|\bnot in account filter\b|"
    r"\bno double-?buy\b|\balready (?:executed|in-?flight)\b",
    re.IGNORECASE,
)


def is_fill_line(text: str) -> bool:
    """Heuristic: True if this stdout line is a confirmed buy/sell.

    Conservative — designed to undercount rather than over-count so a
    green icon really means "the broker placed at least one order".
    Dry-run success lines also count, matching the UX intent.
    """
    s = text or ""
    return bool(_FILL_POS_RX.search(s)) and not _FILL_NEG_RX.search(s)


def classify_outcome(text: str, *, success: bool = False) -> str:
    """Return the reason code for a broker result.

    ``success=True`` short-circuits to OK. Otherwise the message text
    is matched against the ordered rule set; unmatched -> OTHER.
    """
    if success:
        return OK
    s = str(text or "")
    if not s.strip():
        return OTHER
    for code, rx in _RULES:
        if rx.search(s):
            return code
    return OTHER


def is_session_problem(code: str) -> bool:
    """Return True if the code is real session/auth breakage (alarm)."""
    return code in _SESSION


def is_benign_no_trade(code: str) -> bool:
    """Return True if no trade happened but the connection was fine."""
    return code in _BENIGN


# --- per-play availability matrix (read-only ledger analytics) --------

BOUGHT = "BOUGHT"
UNAVAILABLE = "UNAVAILABLE"
SESSION = "SESSION"
REJECTED = "REJECTED"
PENDING = "PENDING"
SKIPPED = "SKIPPED"
NONE = "NONE"

# Most-informative-wins precedence when a (ticker, broker) pair has
# several ledger rows: a success beats everything; an unavailable/
# session problem is the next most useful to surface.
_CELL_ORDER = (
    BOUGHT,
    UNAVAILABLE,
    SESSION,
    REJECTED,
    PENDING,
    SKIPPED,
    NONE,
)


def _row_cell(status: str, reason: str) -> str:  # noqa: PLR0911
    if status == "EXECUTED":
        return BOUGHT
    if reason in {STOCK_UNAVAILABLE, RESTRICTED}:
        return UNAVAILABLE
    if reason == SESSION_ERROR:
        return SESSION
    if reason in {MARKET_CLOSED, PRICE_REJECTED, NO_FUNDS}:
        return REJECTED
    # A working-but-not-yet-filled order (fill verification) and a
    # mid-flight INTENDED row both read as PENDING in the matrix.
    if status in {"INTENDED", "PENDING"}:
        return PENDING
    if reason in {FILTERED, LEDGER_SKIP}:
        return SKIPPED
    return NONE


def availability_matrix(
    rows: list[dict[str, object]],
) -> dict[str, dict[str, str]]:
    """Collapse ledger rows into ``{ticker: {broker: cell_code}}``.

    Read-only analytics over ``ledger.list_executions()`` — answers
    "for each play, what happened at each broker" (bought vs. just
    unavailable/restricted there vs. a real session problem).
    """
    rank = {c: i for i, c in enumerate(_CELL_ORDER)}
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        ticker = str(r.get("ticker", "")).upper()
        broker = str(r.get("broker", "")).lower()
        if not ticker or not broker:
            continue
        cell = _row_cell(
            str(r.get("status", "")), str(r.get("reason", "")),
        )
        cur = out.setdefault(ticker, {}).get(broker)
        if cur is None or rank[cell] < rank[cur]:
            out[ticker][broker] = cell
    return out
