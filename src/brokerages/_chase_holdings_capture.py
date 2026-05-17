"""Make Chase holdings capture survive the degraded post-login session.

After the slow mobile-app-approval login the zendriver session is
sluggish and the upstream ``chase.symbols.SymbolHoldings`` holdings
fetch frequently fails *silently*: ``_get_holdings_async`` does

    async with self.session.page.expect_response(holdings_json()):
        await self.session.page.reload()
        await asyncio.wait_for(response_info.value, timeout=10)

and a single 10s ceiling on the *first* holdings XHR -- right after a
heavyweight push-approval login -- routinely expires. The bare
``except Exception`` then prints ``Error getting holdings:`` (an
``asyncio.TimeoutError`` stringifies to "") and returns False, so
every account shows "No holdings in Account" even though the balances
loaded fine via a different path.

Simply retrying the *same* 10s exact capture fails the same way, so
this replaces ``_get_holdings_async`` with a version that keeps the
identical browser-driven request and identical JSON parsing but makes
the *capture* robust:

* a generous per-attempt timeout (default 30s) instead of 10s;
* a full re-navigation to the holdings page on each attempt (not just
  a reload) so a missed XHR is genuinely re-triggered;
* a few attempts with a short back-off;
* a *non-empty* diagnostic on final failure (exception type + page
  URL) so a future failure is actionable instead of an empty string.

Best-effort, idempotent and reversible: if the upstream shape ever
changes the patch isn't applied and behaviour is unchanged. The
network request and the parsed fields are byte-for-byte what upstream
produced when it worked -- only the capture's resilience changes.
"""

from __future__ import annotations

import asyncio
import datetime
import json

_applied = False
_ATTEMPTS = 3
_TIMEOUT_S = 30.0
_BACKOFF_S = 2.0


def apply() -> None:
    """Replace SymbolHoldings._get_holdings_async with a robust capture. Idempotent."""
    global _applied  # noqa: PLW0603
    if _applied:
        return
    try:
        from chase import symbols as _sym  # noqa: PLC0415
        from chase.urls import account_holdings, holdings_json  # noqa: PLC0415

        async def _robust_get_holdings_async(self: object) -> bool:
            last_error = "no attempts ran"
            for attempt in range(_ATTEMPTS):
                try:
                    await self.session.page.get(account_holdings(self.account_id))  # type: ignore[attr-defined]
                    await self.session.page.sleep(2)  # type: ignore[attr-defined]

                    async with self.session.page.expect_response(  # type: ignore[attr-defined]
                        holdings_json(),
                    ) as response_info:
                        await self.session.page.reload()  # type: ignore[attr-defined]
                        await asyncio.wait_for(
                            response_info.value, timeout=_TIMEOUT_S,
                        )
                        body_str, _ = await response_info.response_body
                        body = json.loads(body_str)

                    # Identical parsing to upstream so downstream code
                    # (data.positions, etc.) sees exactly what it always did.
                    self.raw_json = body  # type: ignore[attr-defined]
                    self.as_of_time = datetime.datetime.strptime(  # type: ignore[attr-defined]
                        self.raw_json["asOfTimestamp"],  # type: ignore[attr-defined]
                        "%Y-%m-%dT%H:%M:%S.%fZ",
                    ).replace(tzinfo=self.local_tz)  # type: ignore[attr-defined]
                    self.asset_allocation_tool_eligible_indicator = bool(  # type: ignore[attr-defined]
                        self.raw_json["assetAllocationToolEligibleIndicator"],  # type: ignore[attr-defined]
                    )
                    self.cash_sweep_position_summary = self.raw_json[  # type: ignore[attr-defined]
                        "cashSweepPositionSummary"
                    ]
                    self.custom_position_allowed_indicator = bool(  # type: ignore[attr-defined]
                        self.raw_json["customPositionAllowedIndicator"],  # type: ignore[attr-defined]
                    )
                    self.error_responses = self.raw_json["errorResponses"]  # type: ignore[attr-defined]
                    self.performance_allowed_indicator = bool(  # type: ignore[attr-defined]
                        self.raw_json["performanceAllowedIndicator"],  # type: ignore[attr-defined]
                    )
                    self.positions = self.raw_json["positions"]  # type: ignore[attr-defined]
                    self.positions_summary = self.raw_json["positionsSummary"]  # type: ignore[attr-defined]
                except Exception as exc:
                    page = getattr(self.session, "page", None)  # type: ignore[attr-defined]
                    url = getattr(page, "url", "?")
                    last_error = f"{type(exc).__name__}: {exc!r} (url={url})"
                    if attempt < _ATTEMPTS - 1:
                        await asyncio.sleep(_BACKOFF_S)
                    continue
                else:
                    return True

            print(
                f"Error getting holdings: capture failed after "
                f"{_ATTEMPTS} attempts -- {last_error}",
            )
            return False

        _sym.SymbolHoldings._get_holdings_async = _robust_get_holdings_async  # type: ignore[invalid-assignment]  # noqa: SLF001
        _applied = True
        print("Chase: robust holdings capture active")
    except Exception as exc:
        print(f"Chase: holdings-capture patch not applied ({exc})")
