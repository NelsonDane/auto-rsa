"""friendly_summary: raw broker status lines -> one plain sentence."""

from src.gui.core.friendly_errors import friendly_summary


def test_fill_reads_as_placed():
    icon, msg = friendly_summary(["Robinhood: buy 1 of FOMO in ****1234: Success"])
    assert icon == "✅"
    assert "placed" in msg.lower()


def test_session_error_is_actionable():
    icon, msg = friendly_summary(["Error logging in to Fidelity: got error page"])
    assert icon == "⚠️"
    assert "sign in" in msg.lower()
    assert "admin" in msg.lower()  # tells the friend what to do


def test_stock_unavailable_is_benign():
    icon, msg = friendly_summary(["BBAE: FOMO is not available to trade"])
    assert icon == "🟡"
    assert "available" in msg.lower()


def test_market_closed():
    icon, msg = friendly_summary(["Chase: does not accept market orders outside market hours"])
    assert icon == "🟡"
    assert "market" in msg.lower()


def test_generic_error():
    icon, msg = friendly_summary(["Webull: unexpected exception in order flow"])
    assert icon == "❌"
    assert "admin" in msg.lower()


def test_clean_no_order_is_not_an_error():
    icon, msg = friendly_summary(["Public: logged in", "Public: Total value $100"])
    assert icon == "🟡"
    assert "no order" in msg.lower()


def test_empty():
    assert friendly_summary([])[0] == "⚪"


def test_ledger_skip():
    icon, _ = friendly_summary(["Fennel: skipped FOMO — already executed (no double-buy)"])
    assert icon == "⚪"


def test_rejected_order_is_not_shown_as_placed():
    # Fennel-style: the submission line literally says "Success: False, REJECTED".
    icon, msg = friendly_summary(
        ["Fennel: buy 1 of AAPL in acct: Success: False, Status: REJECTED, ID: abc"],
    )
    assert icon == "❌", (icon, msg)


def test_queued_order_is_pending_not_placed():
    lines = [
        "Robinhood: buy 1 of AAPL in xxxx1234: Success",
        "Robinhood: AAPL in xxxx1234 — order state 'queued' "
        "(recorded PENDING, not a confirmed fill)",
    ]
    icon, msg = friendly_summary(lines)
    assert icon == "⏳", (icon, msg)


def test_chase_placed_confirmation_is_a_fill():
    icon, _ = friendly_summary(["Chase account 1234: ✅ Order placed (Chase order id 55)"])
    assert icon == "✅"


def test_chase_unsuccessful_is_error():
    icon, _ = friendly_summary(["Chase account 1234: ❌ The order was unsuccessful"])
    assert icon == "❌"


def test_schwab_verification_success_is_a_fill():
    icon, _ = friendly_summary(["Schwab account xxxx: The order verification was successful"])
    assert icon == "✅"


def test_real_robinhood_fill_still_reads_placed():
    icon, _ = friendly_summary(["Robinhood: buy 1 of AAPL in xxxx1234: Success"])
    assert icon == "✅"


def test_robinhood_market_to_limit_fallback_is_a_fill():
    # RH prints a benign "Error … trying Limit Order" notice, then the fill.
    # The fill must win over the notice's "error" word (REG-1).
    lines = [
        "Robinhood 1: Error buying 1 of LCID in xxxx1234, trying Limit Order",
        "Robinhood 1: buy 1 of LCID in xxxx1234 @ 0.56: Success",
    ]
    assert friendly_summary(lines)[0] == "✅"


def test_multi_ticker_fill_not_masked_by_another_unavailable():
    lines = [
        "Webull 1: buy 1 of AAPL in xxxx1234: Success",
        "Webull 1 xxxx1234: Error placing order: LCID is not available for trading",
    ]
    assert friendly_summary(lines)[0] == "✅"  # at least one order placed


def test_multi_ticker_fill_not_masked_by_another_rejection():
    lines = [
        "Public 1: buy 1 of AAPL in xxxx: Success (FILLED)",
        "Public 1: buy 1 of LCID in xxxx: Rejected (REJECTED)",
    ]
    assert friendly_summary(lines)[0] == "✅"
