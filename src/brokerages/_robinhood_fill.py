"""Classify a Robinhood order dict into a FillState (pure).

`robin_stocks` returns an order dict on placement (with an ``id`` and an
initial ``state`` that is usually *not yet* "filled") and a richer dict
from ``get_stock_order_info(id)`` once polled. This maps either dict's
``state`` to a :class:`FillState`, so a merely-*submitted* order is
never recorded as a fill — the Robinhood analog of the Chase
queue-eligible bug (an accepted order is not a filled order).

Pure — no I/O, no robin_stocks import. See
``docs/FILL_VERIFICATION_DESIGN.md`` §3.2.
"""

from __future__ import annotations

import contextlib

from src.brokerages.fill_result import FillState

# Robinhood order-state vocabulary → FillState.
_FILLED = {"filled"}
# Working/accepted but not yet filled. partially_filled is still an open
# order, so it stays PENDING (blocking) until it completes — layer 2
# (quantity-aware reconcile) reports the partial shortfall.
_PENDING = {
    "queued",
    "unconfirmed",
    "confirmed",
    "new",
    "pending",
    "partially_filled",
    "partial",
}
_REJECTED = {"rejected", "canceled", "cancelled", "failed", "voided"}


def robinhood_order_ref(order: object) -> str:
    """Best-effort order id from a robin_stocks order dict."""
    if isinstance(order, dict):
        val = order.get("id")
        if val:
            return str(val)
    return ""


def robinhood_filled_qty(order: object) -> float | None:
    """Filled share count from ``cumulative_quantity``, if present."""
    if not isinstance(order, dict):
        return None
    raw = order.get("cumulative_quantity")
    if raw in (None, ""):
        return None
    with contextlib.suppress(TypeError, ValueError):
        return float(raw)
    return None


def classify_robinhood_order(order: object) -> FillState:
    """Return the :class:`FillState` for a robin_stocks order dict.

    * an explicit ``non_field_errors`` (a rejected submission) → REJECTED
    * ``state`` in the filled/working/rejected vocabularies as mapped
    * an unrecognized or missing state → UNKNOWN (routed to review; a
      missed buy beats a double-buy)
    """
    if not isinstance(order, dict) or not order:
        return FillState.UNKNOWN
    if order.get("non_field_errors"):
        return FillState.REJECTED
    state = str(order.get("state", "") or "").strip().lower()
    if not state:
        return FillState.UNKNOWN
    if state in _FILLED:
        return FillState.FILLED
    if state in _REJECTED:
        return FillState.REJECTED
    if state in _PENDING:
        return FillState.PENDING
    return FillState.UNKNOWN
