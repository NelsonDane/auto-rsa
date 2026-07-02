"""Place a limit order when Fidelity would reject a market order after hours.

Outside regular market hours Fidelity refuses *market* orders and
requires a *limit* order (error **146034**). Upstream
``FidelityAutomation.transaction`` only switches to a limit order for
sub-$1 quotes or when it detects the extended-hours DOM toggle; that
detection is unreliable, so a >$1 stock after hours is sent as a market
order and rejected.

An earlier version of this patch tried to salvage the *rejected* order
by reading the price off the leftover ticket and retrying — but after a
rejection the ticket no longer shows the right quote, so it produced a
wildly wrong limit (e.g. $0.99 for a $6 stock). Real money: never trust
a post-failure scrape.

Instead this wraps ``transaction`` to act **before** ordering: when the
US market is closed and the caller asked for a plain market buy, it
probes the correct last price from a *fresh* order ticket, builds a
marketable limit one tick away rounded to Fidelity's tick size (whole
cents >=$1, $0.0001 <$1), and calls upstream once with that explicit
``limit_price`` so the order is a valid limit from the start.

Safe in every case: during regular hours (or if the clock can't be
determined, or the probe fails) it does nothing and upstream runs
exactly as before. A marketable limit also fills fine if the market
turns out to be open (e.g. a half-day), so a misjudged clock only ever
swaps an equivalent market fill for a marketable-limit fill — never an
extra order, never a worse price than a rejected-and-retried mess.
Best-effort, idempotent, reversible.
"""

from __future__ import annotations

import contextlib
from datetime import datetime, time
from zoneinfo import ZoneInfo

_applied = False

_ORDER_ENTRY = "https://digital.fidelity.com/ftgw/digital/trade-equity/index/orderEntry"
_MARKET_OPEN = time(9, 30)
_MARKET_CLOSE = time(16, 0)


def _us_market_closed() -> bool | None:
    """Report whether US equities are outside regular hours (None if unknown).

    Holidays/half-days aren't modeled — that's fine: a marketable limit
    still fills if the market is actually open, so the only effect of a
    wrong guess is an equivalent fill, never a worse one.
    """
    try:
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return None
    if now.weekday() >= 5:  # Sat/Sun  # noqa: PLR2004
        return True
    return not (_MARKET_OPEN <= now.time() < _MARKET_CLOSE)


def _probe_last_price(page: object, stock: str) -> float | None:
    """Read ``stock``'s last price from a fresh order ticket, or None.

    Mirrors upstream's own quote read (same selectors) but on a clean
    ticket we navigate ourselves, so the value is trustworthy.
    """
    try:
        page.goto(_ORDER_ENTRY)  # type: ignore[attr-defined]
        page.get_by_label("Symbol", exact=True).click()  # type: ignore[attr-defined]
        page.get_by_label("Symbol", exact=True).fill(stock)  # type: ignore[attr-defined]
        page.get_by_label("Symbol", exact=True).press("Enter")  # type: ignore[attr-defined]
        page.locator("#quote-panel").wait_for(timeout=5000)  # type: ignore[attr-defined]
        el = page.query_selector(  # type: ignore[attr-defined]
            "#eq-ticket__last-price > span.last-price",
        )
        if el is None:
            return None
        raw = (el.text_content() or "").replace("$", "").replace(",", "").strip()
        price = float(raw)
    except Exception:
        return None
    else:
        return price if price > 0 else None
    finally:
        # Reset to a clean ticket so upstream starts from a known state.
        with contextlib.suppress(Exception):
            page.goto(_ORDER_ENTRY)  # type: ignore[attr-defined]


def _marketable_limit(price: float, action: str) -> float:
    """Return a limit one tick across the spread, at Fidelity's tick size."""
    if price >= 1:
        tick, decimals = 0.01, 2
    else:
        tick, decimals = 0.0001, 4
    wanted = price + tick if action.lower() == "buy" else price - tick
    return round(wanted, decimals)


def _arg(args: tuple, kwargs: dict, index: int, name: str, *, default: object) -> object:
    if name in kwargs:
        return kwargs[name]
    if len(args) > index:
        return args[index]
    return default


def apply() -> None:
    """Wrap FidelityAutomation.transaction with after-hours limit logic. Idempotent."""
    global _applied  # noqa: PLW0603
    if _applied:
        return
    try:
        from fidelity import fidelity as _f  # noqa: PLC0415

        original = _f.FidelityAutomation.transaction

        def _transaction_after_hours_aware(
            self: object,
            *args: object,
            **kwargs: object,
        ) -> tuple[bool, str | None]:
            stock = _arg(args, kwargs, 0, "stock", default=None)
            quantity = _arg(args, kwargs, 1, "quantity", default=None)
            action = str(_arg(args, kwargs, 2, "action", default="") or "")
            account = _arg(args, kwargs, 3, "account", default=None)
            dry = bool(_arg(args, kwargs, 4, "dry", default=True))
            explicit_limit = _arg(args, kwargs, 5, "limit_price", default=None)

            # Intervene for a plain market BUY *or* SELL while the
            # market is closed; everything else runs upstream
            # untouched. Sells were previously unprotected, so an
            # after-hours sell went out as a MARKET order (limit_price
            # None) which Fidelity rejects outside RTH — "sell doesn't
            # work" on any overnight/after-hours run.
            # _marketable_limit already prices the sell side (last -
            # tick), so both directions get a marketable limit.
            intervene = (
                explicit_limit is None
                and action.lower() in {"buy", "sell"}
                and bool(stock)
                and quantity is not None
                and account is not None
                and _us_market_closed() is True
            )
            if not intervene:
                return original(self, *args, **kwargs)  # type: ignore[misc]

            price = _probe_last_price(getattr(self, "page", None), str(stock))
            if price is None:
                # Couldn't get a trustworthy quote -> don't guess; let
                # upstream do whatever it would have done.
                return original(self, *args, **kwargs)  # type: ignore[misc]

            limit = _marketable_limit(price, action)
            print(
                f"Fidelity: market closed; placing {stock} as a limit "
                f"order @ {limit} (last {price})",
            )
            return original(  # type: ignore[misc]
                self,
                stock,
                quantity,
                action,
                account,
                dry=dry,
                limit_price=limit,
            )

        _f.FidelityAutomation.transaction = _transaction_after_hours_aware  # type: ignore[invalid-assignment]
        _applied = True
        print("Fidelity: after-hours market->limit salvage active")
    except Exception as exc:
        print(f"Fidelity: after-hours limit patch not applied ({exc})")
