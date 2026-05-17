"""Retry Chase holdings fetch on the upstream library's silent timeout.

After the slow mobile-app-approval login, the zendriver session is
degraded and ``chase.symbols.SymbolHoldings.get_holdings`` frequently
hits its internal 10s ``asyncio.wait_for`` timeout on the holdings XHR
and returns False, printing an empty ``Error getting holdings:`` (an
``asyncio.TimeoutError`` stringifies to ""). The navigation + JSON read
is idempotent, so retrying it a couple of times clears a transient
first-load miss.

Best-effort and reversible: if the upstream shape ever changes the
patch simply isn't applied and behaviour is unchanged.
"""

from __future__ import annotations

import time

_applied = False
_RETRIES = 3
_DELAY_S = 2.0


def apply() -> None:
    """Wrap SymbolHoldings.get_holdings with a small retry. Idempotent."""
    global _applied  # noqa: PLW0603
    if _applied:
        return
    try:
        from chase import symbols as _sym  # noqa: PLC0415

        original = _sym.SymbolHoldings.get_holdings

        def _retrying_get_holdings(self: object) -> bool:
            for attempt in range(_RETRIES):
                if original(self):  # type: ignore[invalid-argument-type]
                    return True
                if attempt < _RETRIES - 1:
                    time.sleep(_DELAY_S)
            return False

        _sym.SymbolHoldings.get_holdings = _retrying_get_holdings  # type: ignore[invalid-assignment]
        _applied = True
    except Exception as exc:
        print(f"Chase: holdings-retry patch not applied ({exc})")
