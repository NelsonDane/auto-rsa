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

import os

_applied = False
_DEFAULT_TIMEOUT = 45


def _timeout() -> int:
    try:
        return max(10, int(os.getenv("RSA_CHASE_HTTP_TIMEOUT", str(_DEFAULT_TIMEOUT))))
    except ValueError:
        return _DEFAULT_TIMEOUT


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


def apply() -> None:
    """Wrap chase.order's requests module with a default timeout. Idempotent."""
    global _applied  # noqa: PLW0603
    if _applied:
        return
    try:
        from chase import order as _co  # noqa: PLC0415

        if not isinstance(_co.requests, _TimeoutRequests):
            _co.requests = _TimeoutRequests(_co.requests)  # type: ignore[assignment]
        _applied = True
        print("Chase: order request-timeout guard active")
    except Exception as exc:
        print(f"Chase: request-timeout patch not applied ({exc})")
