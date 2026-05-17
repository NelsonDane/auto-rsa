"""Outcome reason-code classification + benign/session predicates."""

from src import outcomes as o


def test_success_is_ok():
    assert o.classify_outcome("anything", success=True) == o.OK


def test_our_skips():
    assert o.classify_outcome(
        "Fidelity 1 account xxxxx7743: skipped LCID (not in account filter)",
    ) == o.FILTERED
    assert o.classify_outcome(
        "skipped LCID (ledger: already executed or in-flight — no double-buy)",
    ) == o.LEDGER_SKIP


def test_session_breakage_is_the_only_alarm():
    for msg in (
        "Login Failed. Got Error Page: Current URL: .../signin/retail",
        "Page.wait_for_timeout: Target page, context or browser has been closed",
        "Enter 2FA code",
        "captcha required",
        "not logged in, skipping...",
    ):
        code = o.classify_outcome(msg)
        assert code == o.SESSION_ERROR, msg
        assert o.is_session_problem(code)
        assert not o.is_benign_no_trade(code)


def test_benign_no_trade_outcomes():
    cases = {
        "(146034) Fidelity does not accept market orders for securities "
        "priced less than $1 during non market hours": o.MARKET_CLOSED,
        "Error! (MA5010) The limit price entered is too far away from "
        "the last trade": o.PRICE_REJECTED,
        "Symbol not found for ABCD": o.STOCK_UNAVAILABLE,
        "This security is restricted and cannot be traded": o.RESTRICTED,
        "Insufficient buying power for this order": o.NO_FUNDS,
    }
    for msg, expected in cases.items():
        assert o.classify_outcome(msg) == expected, msg
    # Stock-unavailable / restricted / market-closed are NOT session
    # problems and ARE benign (the operator's flagged edge case).
    for c in (o.STOCK_UNAVAILABLE, o.RESTRICTED, o.MARKET_CLOSED):
        assert o.is_benign_no_trade(c)
        assert not o.is_session_problem(c)
    # ...but a price/funds reject is neither a session problem nor
    # "benign expected" — it's a real issue to look at, just not auth.
    assert not o.is_session_problem(o.NO_FUNDS)
    assert not o.is_benign_no_trade(o.NO_FUNDS)


def test_unclassified_and_empty():
    assert o.classify_outcome("") == o.OTHER
    assert o.classify_outcome("some totally novel broker burp") == o.OTHER
    assert not o.is_session_problem(o.OTHER)
