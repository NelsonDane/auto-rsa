"""Pure per-broker fill classifiers — Chase and Robinhood.

These lock the rule that a *submitted/eligible* order is not a *fill*.
Kept dependency-free (no dotenv / broker libs) so they run anywhere.
"""

from src.brokerages._chase_fill import (
    chase_order_ref,
    classify_chase_execute,
    has_recognized_id,
)
from src.brokerages._robinhood_fill import (
    classify_robinhood_order,
    robinhood_filled_qty,
    robinhood_order_ref,
)
from src.brokerages.fill_result import FillResult, FillState


# --- Chase ------------------------------------------------------------
def test_chase_queue_eligible_is_rejected_not_filled():
    """THE incident: a confirmation-shaped body that never reached the
    account. Must not be a fill; must stay retryable (REJECTED, not
    PENDING — PENDING would wrongly block the in-hours retry)."""
    body = {
        "orderIdentifier": "9",
        "orderDate": "2026-07-17",
        "orderQueueAvailabilityIndicator": True,
    }
    assert classify_chase_execute(body) is FillState.REJECTED


def test_chase_confirmed_fill():
    assert classify_chase_execute({"orderIdentifier": "123"}) is FillState.FILLED


def test_chase_reject_markers_fail():
    for k in ("tradeErrorMessages", "errors", "errorMessages"):
        assert classify_chase_execute({k: ["bad"]}) is FillState.REJECTED


def test_chase_empty_or_missing_body_rejected():
    assert classify_chase_execute({}) is FillState.REJECTED
    assert classify_chase_execute(None) is FillState.REJECTED


def test_chase_2xx_without_recognized_id_still_fills():
    # A non-empty 2xx body with no reject marker is a fill even without a
    # known id key (avoids the double-buy false-negative).
    assert classify_chase_execute({"someKey": 1}) is FillState.FILLED
    assert has_recognized_id({"someKey": 1}) is False
    assert has_recognized_id({"orderId": "5"}) is True


def test_chase_dry_uses_validation():
    assert classify_chase_execute(None, dry=True, validation={"ok": 1}) is FillState.FILLED
    assert classify_chase_execute(None, dry=True, validation=None) is FillState.UNKNOWN


def test_chase_order_ref_extraction():
    assert chase_order_ref({"orderId": "77"}) == "77"
    assert chase_order_ref({"financialInformationExchangeSystemOrderIdentifier": "z"}) == "z"
    assert chase_order_ref({}) == ""


# --- Robinhood --------------------------------------------------------
def test_rh_filled():
    info = {"state": "filled", "cumulative_quantity": "1.0000"}
    assert classify_robinhood_order(info) is FillState.FILLED
    assert robinhood_filled_qty(info) == 1.0


def test_rh_working_states_are_pending():
    for st in ("queued", "confirmed", "unconfirmed", "new", "partially_filled"):
        assert classify_robinhood_order({"state": st}) is FillState.PENDING


def test_rh_rejected_states():
    for st in ("rejected", "canceled", "cancelled", "failed", "voided"):
        assert classify_robinhood_order({"state": st}) is FillState.REJECTED


def test_rh_non_field_errors_is_rejected_even_if_state_queued():
    assert classify_robinhood_order(
        {"non_field_errors": ["nope"], "state": "queued"},
    ) is FillState.REJECTED


def test_rh_unknown_when_state_absent_or_bogus():
    assert classify_robinhood_order({"state": "wat"}) is FillState.UNKNOWN
    assert classify_robinhood_order({}) is FillState.UNKNOWN
    assert classify_robinhood_order(None) is FillState.UNKNOWN


def test_rh_qty_and_ref_helpers():
    assert robinhood_filled_qty({"cumulative_quantity": "2.5"}) == 2.5
    assert robinhood_filled_qty({"cumulative_quantity": ""}) is None
    assert robinhood_filled_qty({}) is None
    assert robinhood_order_ref({"id": "abc"}) == "abc"
    assert robinhood_order_ref({}) == ""


def test_fill_result_is_fill_predicate():
    assert FillResult(FillState.FILLED).is_fill is True
    assert FillResult(FillState.PENDING).is_fill is False
    assert FillResult(FillState.REJECTED).is_fill is False
