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
