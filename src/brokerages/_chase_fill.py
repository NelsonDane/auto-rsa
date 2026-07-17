"""Classify a Chase execute response into a FillState (pure).

Chase's ``/buy-orders`` (and sell) endpoint can return a
confirmation-shaped 2xx body that is NOT a fill — the
``orderQueueAvailabilityIndicator=true`` after-hours case, confirmed in
the field to never reach the account. This module encodes the rule in
one testable place so ``chase_api._order_succeeded`` and any future
caller agree on what counts as a fill.

Behavior-preserving: ``classify_chase_execute(...) is FillState.FILLED``
returns exactly what the previous inline ``_order_succeeded`` logic
returned. Queue-eligible maps to REJECTED (not PENDING) on purpose:
the order never reached the account, so it must stay retryable in
market hours — mapping it to PENDING would wrongly block the retry.

Pure — no I/O, no broker libs. See ``docs/FILL_VERIFICATION_DESIGN.md``.
"""

from __future__ import annotations

from src.brokerages.fill_result import FillState

# Keys Chase uses to echo a rejection inside a 2xx body.
_REJECT_KEYS = ("tradeErrorMessages", "errors", "errorMessages")
# Recognized order-id keys — presence is the strongest fill signal.
_ID_KEYS = (
    "orderIdentifier",
    "orderId",
    "financialInformationExchangeSystemOrderIdentifier",
)


def classify_chase_execute(
    confirmation: object,
    *,
    dry: bool = False,
    validation: object = None,
) -> FillState:
    """Return the :class:`FillState` for a Chase order response.

    * dry run: FILLED if the validation body is truthy (a dry run has
      only ORDER VALIDATION and no execute), else UNKNOWN.
    * live: REJECTED for an empty/degenerate body, an explicit reject
      marker, or a queue-eligible-only response; otherwise FILLED.
    """
    if dry:
        return FillState.FILLED if validation else FillState.UNKNOWN
    if not isinstance(confirmation, dict) or not confirmation:
        return FillState.REJECTED
    if any(confirmation.get(k) for k in _REJECT_KEYS):
        return FillState.REJECTED
    if confirmation.get("orderQueueAvailabilityIndicator"):
        # Queue-eligible only — never reached the account. Safe to retry
        # in market hours, so REJECTED (retryable), NOT PENDING.
        return FillState.REJECTED
    return FillState.FILLED


def chase_order_ref(confirmation: object) -> str:
    """Best-effort broker order id from a Chase confirmation body."""
    if not isinstance(confirmation, dict):
        return ""
    for k in _ID_KEYS:
        val = confirmation.get(k)
        if val:
            return str(val)
    return ""


def has_recognized_id(confirmation: object) -> bool:
    """True if the confirmation carries a known order-id key."""
    return bool(chase_order_ref(confirmation))
