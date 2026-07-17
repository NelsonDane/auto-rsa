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


def test_is_fill_line_recognises_real_broker_success_lines():
    # Patterns observed across BBAE/Public/Robinhood/Fidelity/Chase/WF.
    yes = [
        "Bought 1.0 ADTX @ MARKET",
        "Chase 1 1234: Bought 1 of ADTX in account 1234: Success",
        "Robinhood 1: buy 1 of LCID in xxxxx7743: Success",
        "BBAE 1: Buy 1 of LCID in xxxxx7743: Success",
        "Fidelity 1 account xxxxx7743: buy 1 shares of LCID",
        "DRY: Fidelity 1 account xxxxx7743: buy 1 shares of LCID",
        "Public 1: buy 1 of LCID in xxxxx7743: Success",
        "WF 1 ...7743: Buy 1 shares of LCID",
        "BBAE 1: Buy 1 of LCID in xxxxx7743: Dry Run Success",
    ]
    for line in yes:
        assert o.is_fill_line(line), line


def test_is_fill_line_rejects_failures_and_noise():
    no = [
        # Wells Fargo emits the buy line AND "FAILED!" in one print.
        "WF 1 ...7743: Buy 1 shares of LCID. FAILED! \nLimit too far",
        "Chase 1 1234: Error submitting order: Timeout",
        "Fidelity 1 account xxxxx7743: Error: 146034 market closed",
        "BBAE 1 7743: Validation failed for buying 1 of LCID: Not available",
        "Robinhood 1 Error submitting order: ServerError",
        "Fidelity 1 account xxxxx7743: skipped LCID (not in account filter)",
        "skipped LCID (ledger: already executed — no double-buy)",
        "Logging into WELLS FARGO...",
        "Got Cookie file does not exist.",
        "",
    ]
    for line in no:
        assert not o.is_fill_line(line), line


def test_is_fill_line_rejects_rejection_and_pending_lines():
    # A submission line that ALSO carries a rejection verdict, or a
    # queued/pending order, must NOT count as a fill.
    no = [
        "Fennel 1: buy 1 of LCID in xxxx: Success: False, Status: REJECTED, ID: 5",
        "Public 1: buy 1 of LCID in xxxx: Rejected (REJECTED)",
        "BBAE 1: Buy 1 of LCID in xxxx: Order declined",
    ]
    for line in no:
        assert not o.is_fill_line(line), line


def test_availability_matrix_precedence():
    rows = [
        # ACME: unavailable at fidelity, but later bought there -> BOUGHT wins
        {"ticker": "acme", "broker": "fidelity", "status": "FAILED",
         "reason": o.STOCK_UNAVAILABLE},
        {"ticker": "ACME", "broker": "fidelity", "status": "EXECUTED",
         "reason": o.OK},
        # ACME at chase: only restricted -> UNAVAILABLE
        {"ticker": "ACME", "broker": "chase", "status": "FAILED",
         "reason": o.RESTRICTED},
        # BETA at fidelity: session error -> SESSION
        {"ticker": "BETA", "broker": "fidelity", "status": "FAILED",
         "reason": o.SESSION_ERROR},
        # BETA at robinhood: filtered out -> SKIPPED
        {"ticker": "BETA", "broker": "robinhood", "status": "FAILED",
         "reason": o.FILTERED},
        {"ticker": "", "broker": "x", "status": "EXECUTED"},  # ignored
    ]
    m = o.availability_matrix(rows)
    assert m["ACME"]["fidelity"] == o.BOUGHT       # success trumps prior fail
    assert m["ACME"]["chase"] == o.UNAVAILABLE
    assert m["BETA"]["fidelity"] == o.SESSION
    assert m["BETA"]["robinhood"] == o.SKIPPED
    assert "" not in m
