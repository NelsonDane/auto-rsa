"""Make Chase order placement account-scoped (skip "Choose an account").

Root cause of the multi-account Chase order hang: the vendored
``chase.order._async_place_order`` navigates to ``order_page()`` which
is the **generic** equity-entry URL
(``…/dashboard/oi-trade/equity/entry``). With 8 accounts Chase serves a
"Choose an account" chooser and never establishes order context, so
the validate/execute POSTs stall (then time out via the request guard).

Chase's other working routes are account-scoped with a ``;ai=`` matrix
param (``account_holdings`` → ``…/positions/render;ai={id}``,
``order_status`` → ``…/order/status;ai={id};…``). This patch applies
the same convention to the order page: a context var holds the
account_id of the in-flight ``Order.place_order`` call, and a patched
``chase.order.order_page`` appends ``;ai={account_id}`` so the SPA
opens directly in that account's order ticket — no chooser, no DOM
scraping, no payload/logic change (navigation only).

Best-effort, idempotent, reversible; if ``;ai=`` is ignored on the
entry route it is no worse than today (still the chooser).
"""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_applied = False
_CURRENT_ACCOUNT_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "rsa_chase_order_account_id", default=None,
)


def apply() -> None:
    """Patch chase.order so place_order navigates account-scoped. Idempotent."""
    global _applied  # noqa: PLW0603
    if _applied:
        return
    try:
        from chase import order as _co  # noqa: PLC0415

        orig_order_page: Callable[[], str] = _co.order_page

        def _scoped_order_page() -> str:
            base = orig_order_page()
            acct = _CURRENT_ACCOUNT_ID.get()
            if not acct or ";ai=" in base:
                return base
            return f"{base};ai={acct}"

        orig_place_order = _co.Order.place_order

        def _place_order_scoped(self: object, *args: object, **kwargs: object) -> object:
            acct = kwargs.get("account_id")
            if acct is None and args:
                acct = args[0]
            token = _CURRENT_ACCOUNT_ID.set(str(acct) if acct is not None else None)
            try:
                return orig_place_order(self, *args, **kwargs)  # type: ignore[misc]
            finally:
                _CURRENT_ACCOUNT_ID.reset(token)

        _co.order_page = _scoped_order_page  # type: ignore[assignment]
        _co.Order.place_order = _place_order_scoped  # type: ignore[assignment]
        _applied = True
        print("Chase: account-scoped order page active")
    except Exception as exc:
        print(f"Chase: account-scoped order patch not applied ({exc})")
