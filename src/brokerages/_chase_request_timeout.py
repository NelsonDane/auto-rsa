"""Bound the vendored Chase order HTTP calls so a hang can't freeze a run.

`chase.order._async_place_order` does the order **validation** and
**execution** via ``requests.post(... impersonate="chrome")`` with **no
timeout** (curl_cffi has no default). When Chase serves the
multi-account "Choose an account" state (8+ accounts), those POSTs
never return — the run freezes with the browser parked on that page
and zero output (observed on a live market Chase sell).

This wraps the ``requests`` module *inside chase.order only* so its
``post``/``get`` get a default timeout when the caller didn't set one.
A stuck call then raises, which the vendored code already catches
(``order_messages["ORDER INVALID"] = "Execution Exception: ..."``) and
returns cleanly — so the order surfaces an actionable error instead of
hanging. The per-broker watchdog remains the outer backstop.

Same root cause/fix shape as the SoFi curl_cffi timeout patch. Edits
nothing in site-packages; reversible; no-ops if upstream changes.
"""

from __future__ import annotations

import asyncio
import os

_applied = False
_DEFAULT_TIMEOUT = 45
_DEFAULT_ORDER_TIMEOUT = 120


def _timeout() -> int:
    try:
        return max(10, int(os.getenv("RSA_CHASE_HTTP_TIMEOUT", str(_DEFAULT_TIMEOUT))))
    except ValueError:
        return _DEFAULT_TIMEOUT


def _order_timeout() -> int:
    """End-to-end cap (seconds) for one Chase order.

    Covers browser nav + validate + execute. Bounds the pre-POST
    nodriver step the request timeout can't reach, so a stuck order
    fails fast per-account instead of eating the 600s broker watchdog
    with no output.
    """
    try:
        return max(
            30,
            int(os.getenv("RSA_CHASE_ORDER_TIMEOUT", str(_DEFAULT_ORDER_TIMEOUT))),
        )
    except ValueError:
        return _DEFAULT_ORDER_TIMEOUT


class _TimeoutRequests:
    """Proxy for curl_cffi.requests that defaults a timeout on get/post."""

    def __init__(self, real: object) -> None:
        self._real = real

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)

    def post(self, *args: object, **kwargs: object) -> object:
        kwargs.setdefault("timeout", _timeout())
        return self._real.post(*args, **kwargs)  # type: ignore[attr-defined]

    def get(self, *args: object, **kwargs: object) -> object:
        kwargs.setdefault("timeout", _timeout())
        return self._real.get(*args, **kwargs)  # type: ignore[attr-defined]


_ORDER_BOUNDED = "_rsa_order_bounded"


def apply() -> None:
    """Bound Chase order HTTP + the whole order coroutine. Idempotent."""
    global _applied  # noqa: PLW0603
    if _applied:
        return
    try:
        from chase import order as _co  # noqa: PLC0415
        from chase import symbols as _cs  # noqa: PLC0415

        # 1. Default a timeout on the validate/execute POSTs.
        if not isinstance(_co.requests, _TimeoutRequests):
            _co.requests = _TimeoutRequests(_co.requests)  # type: ignore[assignment]
        # 1b. Same for the quote / holdings GETs in chase.symbols —
        # they're hit on every BUY (SymbolQuote) and every holdings
        # refresh, and went unbounded under the original module-only
        # wrap. Defense in depth for the non-direct path.
        if not isinstance(_cs.requests, _TimeoutRequests):
            _cs.requests = _TimeoutRequests(_cs.requests)  # type: ignore[assignment]

        # 2. Bound the entire _place_order_async (browser nav + POSTs)
        #    so a hang in the pre-POST nodriver step fails fast and
        #    per-account, instead of the silent 600s broker watchdog.
        orig_async = _co.Order._place_order_async  # noqa: SLF001
        if not getattr(orig_async, _ORDER_BOUNDED, False):

            async def _bounded(self: object, *args: object, **kwargs: object) -> object:
                return await asyncio.wait_for(
                    orig_async(self, *args, **kwargs),  # type: ignore[misc]
                    timeout=_order_timeout(),
                )

            _bounded._rsa_order_bounded = True  # type: ignore[attr-defined]  # noqa: SLF001
            _co.Order._place_order_async = _bounded  # type: ignore[assignment]  # noqa: SLF001

        # 3. Bound SymbolQuote.get_symbol_quote too. On a BUY the
        #    upstream quote does `await self.session.page.get(order_page())`
        #    (symbols.py) which hangs on a multi-account "Choose an
        #    account" chooser exactly like the order nav — but nothing
        #    bounded it, so a non-direct BUY froze the quote step until
        #    the 600s per-broker watchdog. Wrap it so it fails fast
        #    per-ticker (the caller's quote loop then degrades to
        #    MARKET). No-op when direct mode already replaced this
        #    method (its marker is checked so we don't double-bound).
        orig_quote = _cs.SymbolQuote.get_symbol_quote
        if not getattr(orig_quote, _ORDER_BOUNDED, False):

            async def _bounded_quote(self: object, *args: object, **kwargs: object) -> object:
                return await asyncio.wait_for(
                    orig_quote(self, *args, **kwargs),  # type: ignore[misc]
                    timeout=_order_timeout(),
                )

            _bounded_quote._rsa_order_bounded = True  # type: ignore[attr-defined]  # noqa: SLF001
            _cs.SymbolQuote.get_symbol_quote = _bounded_quote  # type: ignore[assignment]

        _applied = True
        print("Chase: order timeout guards active (HTTP + coroutine)")
    except Exception as exc:
        print(f"Chase: request-timeout patch not applied ({exc})")
