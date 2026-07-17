"""Structured fill outcome — the answer to "did the order ACTUALLY fill?"

Motivated by the Chase queue-eligible incident: the engine reported
orders "placed" that never reached the account because a non-empty
broker response was read as a fill. This module makes the three
distinct states a broker order can be in first-class, so an
accepted-but-not-yet-filled order can never masquerade as a fill.

Pure and dependency-free (no ledger, no broker libs, no I/O) so both
the broker modules and the ledger can import it without a cycle. The
mapping from a :class:`FillState` to a ledger status lives in
``ledger.mark_fill`` — this module only defines the vocabulary.

Design: ``docs/FILL_VERIFICATION_DESIGN.md`` §3.
"""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple


class FillState(str, Enum):
    """The authoritative state of a placed order.

    The whole point is that only :attr:`FILLED` means the shares/cash
    actually moved. Everything else is explicitly *not a fill*:

    * :attr:`FILLED`   — executed; shares/cash moved. The only state
      that may mark a ledger row EXECUTED.
    * :attr:`PENDING`  — accepted and working (queued/confirmed) but
      not yet filled. MIGHT still fill, so re-firing risks a
      double-buy → treated as blocking, like NEEDS_REVIEW.
    * :attr:`REJECTED` — the broker refused it, or it never reached the
      account (e.g. Chase queue-eligible after-hours). No order is
      live, so it is safe to retry later.
    * :attr:`UNKNOWN`  — no authoritative signal. Treated as NOT filled
      and routed to human review (a missed buy beats a double-buy).
    """

    FILLED = "filled"
    PENDING = "pending"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class FillResult(NamedTuple):
    """One order's verified outcome, attachable to a ledger row.

    ``qty`` is the filled quantity when the broker reports it (used by
    the quantity-aware reconcile in a later slice); ``order_ref`` is
    the broker order id, kept for later status polling / audit. Both
    are optional — a broker that can't answer returns
    :attr:`FillState.UNKNOWN` with them as ``None``.
    """

    state: FillState
    broker: str = ""
    account: str = ""
    ticker: str = ""
    action: str = ""
    qty: float | None = None
    order_ref: str | None = None
    detail: str = ""

    @property
    def is_fill(self) -> bool:
        """True only for a genuine fill — the safe headline predicate."""
        return self.state is FillState.FILLED
