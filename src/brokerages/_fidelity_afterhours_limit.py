"""Salvage a Fidelity market order that Fidelity rejects after hours.

Outside regular market hours Fidelity refuses *market* orders and
requires a *limit* order (error **146034** / *"does not accept market
orders ... during non market hours"*). The upstream
``FidelityAutomation.transaction`` only switches to a limit order when
the quote is sub-$1 **or** it manages to detect the extended-hours DOM
toggle. That detection is unreliable, so a >$1 stock placed after hours
is sent as a market order and rejected — exactly the failure seen for
LCID (~$6) in live testing.

This wraps ``transaction`` so that, when a market order is rejected for
that specific after-hours reason and the caller did **not** ask for an
explicit limit price, it:

* reads the last price already shown on the order ticket,
* builds a marketable limit one tick away, rounded to Fidelity's tick
  size (whole cents for >=$1, $0.0001 for <$1 — this also fixes the
  separate upstream bug where the auto-derived limit kept 3 decimals
  and was rejected on a decimal error), and
* retries the **same** order once as that limit order.

The rejected market order never filled (146034 is an outright reject),
and the retry passes ``limit_price`` so it cannot market-reject again,
so this can only ever turn a guaranteed failure into a fill — it never
places an extra order. Best-effort, idempotent and reversible: any
unexpected shape change makes it quietly no-op and return the original
result unchanged.
"""

from __future__ import annotations

_applied = False

# Substrings that identify "market order refused because it's after
# hours" (vs. any other failure we must not paper over).
_AFTERHOURS_MARKET_REJECT = (
    "146034",
    "does not accept market orders",
    "change your order to a limit",
)


def _looks_like_afterhours_market_reject(error_message: object) -> bool:
    text = str(error_message or "").lower()
    return any(sig in text for sig in _AFTERHOURS_MARKET_REJECT)


def _scrape_last_price(page: object) -> float | None:
    """Read the order ticket's last price, or None if unavailable."""
    try:
        el = page.query_selector(  # type: ignore[attr-defined]
            "#eq-ticket__last-price > span.last-price",
        )
        if el is None:
            return None
        raw = (el.text_content() or "").replace("$", "").replace(",", "").strip()
        price = float(raw)
    except Exception:
        return None
    return price if price > 0 else None


def _marketable_limit(price: float, action: str) -> float:
    """Return a limit one tick across the spread, at Fidelity's tick size."""
    if price >= 1:
        tick, decimals = 0.01, 2
    else:
        tick, decimals = 0.0001, 4
    wanted = price + tick if action.lower() == "buy" else price - tick
    return round(wanted, decimals)


def _arg(args: tuple, kwargs: dict, index: int, name: str, default: object) -> object:
    if name in kwargs:
        return kwargs[name]
    if len(args) > index:
        return args[index]
    return default


def apply() -> None:
    """Wrap FidelityAutomation.transaction with after-hours salvage. Idempotent."""
    global _applied  # noqa: PLW0603
    if _applied:
        return
    try:
        from fidelity import fidelity as _f  # noqa: PLC0415

        original = _f.FidelityAutomation.transaction

        def _transaction_with_afterhours_limit(
            self: object,
            *args: object,
            **kwargs: object,
        ) -> tuple[bool, str | None]:
            success, error_message = original(self, *args, **kwargs)  # type: ignore[misc]
            if success or not _looks_like_afterhours_market_reject(error_message):
                return success, error_message

            # Caller already chose an explicit limit price -> nothing to
            # salvage here; surface the original outcome untouched.
            explicit_limit = _arg(args, kwargs, 5, "limit_price", None)
            if explicit_limit is not None:
                return success, error_message

            stock = _arg(args, kwargs, 0, "stock", None)
            quantity = _arg(args, kwargs, 1, "quantity", None)
            action = str(_arg(args, kwargs, 2, "action", "") or "")
            account = _arg(args, kwargs, 3, "account", None)
            dry = bool(_arg(args, kwargs, 4, "dry", default=True))
            if not stock or quantity is None or not action or account is None:
                return success, error_message

            price = _scrape_last_price(getattr(self, "page", None))
            if price is None:
                return success, error_message
            limit = _marketable_limit(price, action)
            if limit <= 0:
                return success, error_message

            print(
                f"Fidelity: market order rejected after hours; retrying "
                f"{stock} as a limit order @ {limit}",
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

        _f.FidelityAutomation.transaction = _transaction_with_afterhours_limit  # type: ignore[invalid-assignment]
        _applied = True
        print("Fidelity: after-hours market->limit salvage active")
    except Exception as exc:
        print(f"Fidelity: after-hours limit patch not applied ({exc})")
