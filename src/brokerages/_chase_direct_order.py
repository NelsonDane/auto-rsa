"""Skip the order-page browser navigation that hangs on multi-account.

Root cause: both ``chase.order._place_order_async`` AND
``chase.symbols.SymbolQuote.get_symbol_quote`` start with
``await self.session.page.get(order_page())``. That nodriver call is
where the multi-account run wedges — even with our
:mod:`_chase_account_scoped_order` patch the screenshot shows the
ticket page rendering but the CDP event never resolves and the
coroutine hangs (then bounded out by
:mod:`_chase_request_timeout`).

For BUYs, ``_process_ticker_orders`` constructs a ``SymbolQuote``
**before** calling ``place_order`` so it can pick a limit price; that
quote constructor hits the same hang at the same line. Patching only
``_place_order_async`` (as we originally did) leaves the BUY path
broken — the run wedges at "account view" before any per-account
order is attempted.

But both navigations are **cosmetic**. Look at
``chase.urls.get_headers()``:

* ``x-jpmc-csrf-token: NONE`` — no token dance
* ``referer: https://secure.chase.com/web/auth/dashboard`` — static,
  not the order page

…and the cookies the validate/execute/quote requests use come from
``self.session.browser.cookies.get_all()`` (the browser-level jar set
at login), not from the page. So we can replace both methods with
bodies that skip ``page.get()`` and run the same curl_cffi requests
directly. Same payload, same endpoints, same session cookies — just
no fragile pre-call DOM step.

Opt-in via ``RSA_CHASE_DIRECT_ORDER=1`` because this is real-money
code. Default off keeps today's behavior (validated holdings path
unchanged in either mode — direct mode only replaces order placement
and quote lookup). Layers under :mod:`_chase_request_timeout` so the
per-order watchdog still applies; coexists with
:mod:`_chase_account_scoped_order` (a no-op when no page navigation
happens).
"""

from __future__ import annotations

import datetime
import os

_applied = False
_DIRECT_MARKER = "_rsa_chase_direct"


def _enabled() -> bool:
    # Accept the HEADLESS-style "true"/"false" the GUI vault writes,
    # plus 1/yes/on so a shell-set env var still works.
    val = (os.getenv("RSA_CHASE_DIRECT_ORDER") or "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def apply() -> None:  # noqa: C901, PLR0915
    """Replace _place_order_async with a no-browser-nav direct-POST version.

    Idempotent. No-op when the env flag is off, or if the chase lib
    is missing, or if upstream changed shape enough that the patch
    can't be safely applied.
    """
    global _applied  # noqa: PLW0603
    if _applied or not _enabled():
        return
    try:
        from chase import order as _co  # noqa: PLC0415
        from chase import symbols as _cs  # noqa: PLC0415
        from chase.urls import (  # noqa: PLC0415
            execute_order,
            get_headers,
            quote_url,
            validate_order,
        )
        from curl_cffi import requests as _cc_requests  # noqa: PLC0415
    except Exception as exc:
        print(f"Chase: direct-order patch not applied ({exc})")
        return

    orig = _co.Order._place_order_async  # noqa: SLF001
    if getattr(orig, _DIRECT_MARKER, False):
        _applied = True
        return

    async def _direct_place_order_async(  # noqa: C901, PLR0911, PLR0912, PLR0917
        self: object,
        account_id: str,
        quantity: int,
        price_type: str,
        symbol: str,
        duration: str,
        order_type: str,
        limit_price: float = 0.00,
        stop_price: float = 0.00,
        after_hours: bool = True,  # noqa: ARG001, FBT001, FBT002
        dry_run: bool = True,  # noqa: FBT001, FBT002
    ) -> dict:
        order_messages: dict[str, object] = {
            "ORDER INVALID": "",
            "ORDER VALIDATION": "",
            "ORDER CONFIRMATION": "",
        }

        # Cookies straight from the browser jar — no page navigation
        # needed. Same call the original makes; lifted before the
        # page.get() we removed.
        try:
            cookies = await self.session.browser.cookies.get_all()  # type: ignore[attr-defined]
        except Exception as exc:
            order_messages["ORDER INVALID"] = f"Cookie fetch failed: {exc}"
            return order_messages
        cookies_dict = {c.name: c.value for c in cookies}
        headers = get_headers()

        payload: dict[str, object] = {
            "accountIdentifier": int(account_id),
            "marketPriceAmount": limit_price,
            "orderQuantity": quantity,
            "accountTypeCode": "CASH",
            "timeInForceCode": duration,
            "securitySymbolCode": symbol,
            "tradeChannelName": "DESKTOP",
            "dollarBasedTradingEligibleIndicator": False,
            "orderTypeCode": price_type,
            "tradeActionName": order_type,
        }
        if price_type == "LIMIT":
            payload["limitPriceAmount"] = limit_price
        elif price_type == "MARKET" and duration not in {"DAY", "ON_THE_CLOSE"}:
            order_messages["ORDER INVALID"] = (
                "Market orders must be DAY or ON THE CLOSE."
            )
            return order_messages
        elif price_type in {"STOP", "STOP_LIMIT"}:
            if duration not in {"DAY", "GOOD_TILL_CANCELLED"}:
                order_messages["ORDER INVALID"] = (
                    "Stop orders must be DAY or GOOD TILL CANCELLED."
                )
                return order_messages
            payload["stopPriceAmount"] = stop_price
            if price_type == "STOP_LIMIT":
                payload["limitPriceAmount"] = limit_price

        exchange_id = None
        try:
            resp_val = _cc_requests.post(
                validate_order(order_type=order_type),
                headers=headers,
                cookies=cookies_dict,
                json=payload,
                impersonate="chrome",
            )
            if resp_val.status_code != 200:  # noqa: PLR2004
                order_messages["ORDER INVALID"] = (
                    f"Validation Failed ({resp_val.status_code}): "
                    f"{resp_val.text}"
                )
                return order_messages
            val_data = resp_val.json()
            errs = val_data.get("tradeErrorMessages", [])
            if errs:
                order_messages["ORDER INVALID"] = errs
                return order_messages
            order_messages["ORDER VALIDATION"] = val_data
            exchange_id = val_data.get(
                "financialInformationExchangeSystemOrderIdentifier",
            )
            if dry_run:
                return order_messages
            if not exchange_id:
                order_messages["ORDER INVALID"] = (
                    "Validation returned no exchange id; not executing."
                )
                return order_messages
        except Exception as exc:
            order_messages["ORDER INVALID"] = f"Validation Exception: {exc}"
            return order_messages

        try:
            exec_payload = dict(payload)
            exec_payload[
                "financialInformationExchangeSystemOrderIdentifier"
            ] = exchange_id
            resp_exec = _cc_requests.post(
                execute_order(order_type=order_type),
                headers=headers,
                cookies=cookies_dict,
                json=exec_payload,
                impersonate="chrome",
            )
            if resp_exec.status_code != 200:  # noqa: PLR2004
                order_messages["ORDER INVALID"] = (
                    f"Execution Failed ({resp_exec.status_code}): "
                    f"{resp_exec.text}"
                )
                return order_messages
            order_messages["ORDER CONFIRMATION"] = resp_exec.json()
        except Exception as exc:
            order_messages["ORDER INVALID"] = f"Execution Exception: {exc}"
        return order_messages

    _direct_place_order_async._rsa_chase_direct = True  # type: ignore[attr-defined]  # noqa: SLF001
    _co.Order._place_order_async = _direct_place_order_async  # type: ignore[assignment]  # noqa: SLF001

    # --- SymbolQuote.get_symbol_quote: same page-nav hang, same fix ---
    orig_quote = _cs.SymbolQuote.get_symbol_quote
    if not getattr(orig_quote, _DIRECT_MARKER, False):

        async def _direct_get_symbol_quote(self: object) -> None:
            try:
                cookies = await self.session.browser.cookies.get_all()  # type: ignore[attr-defined]
            except Exception as exc:
                print(f"Quote error: cookie fetch failed: {exc}")
                return
            cookies_dict = {c.name: c.value for c in cookies}
            url = (
                f"{quote_url()}?security-symbol-code={self.symbol}"  # type: ignore[attr-defined]
                "&security-validate-indicator=true"
                "&dollar-based-trading-include-indicator=true"
            )
            try:
                resp = _cc_requests.get(
                    url,
                    headers=get_headers(),
                    cookies=cookies_dict,
                    impersonate="chrome",
                )
                q = resp.json()
            except Exception as exc:
                print(f"Quote error: {exc}")
                return

            # Mirror the upstream field copy, defensively (a missing
            # field shouldn't kill the run — limit_price math falls
            # back to last_trade_price which we set first).
            def _f(k: str, default: float = 0.0) -> float:
                try:
                    return float(q.get(k, default))
                except (TypeError, ValueError):
                    return default

            def _i(k: str, default: int = 0) -> int:
                try:
                    return int(q.get(k, default))
                except (TypeError, ValueError):
                    return default

            self.ask_price = _f("askPriceAmount")  # type: ignore[attr-defined]
            self.ask_exchange_code = str(q.get("askExchangeCode", ""))  # type: ignore[attr-defined]
            self.ask_quantity = _i("askQuantity")  # type: ignore[attr-defined]
            self.bid_price = _f("bidPriceAmount")  # type: ignore[attr-defined]
            self.bid_exchange_code = str(q.get("bidExchangeCode", ""))  # type: ignore[attr-defined]
            self.bid_quantity = _i("bidQuantity")  # type: ignore[attr-defined]
            self.change_amount = _f("changeAmount")  # type: ignore[attr-defined]
            self.last_trade_price_amount = _f("lastTradePriceAmount")  # type: ignore[attr-defined]
            self.last_trade_quantity = _f("lastTradeQuantity")  # type: ignore[attr-defined]
            self.last_trade_exchange_code = str(q.get("lastTradeExchangeCode", ""))  # type: ignore[attr-defined]
            self.change_percent = _f("changePercent")  # type: ignore[attr-defined]
            ts = q.get("asOfTimestamp")
            if ts:
                try:
                    self.as_of_timestamp = datetime.datetime.strptime(  # type: ignore[attr-defined]
                        ts, "%Y-%m-%dT%H:%M:%S.%fZ",
                    ).replace(tzinfo=self.local_tz)  # type: ignore[attr-defined]
                except ValueError:
                    self.as_of_timestamp = None  # type: ignore[attr-defined]
            self.security_description_text = str(q.get("securityDescriptionText", ""))  # type: ignore[attr-defined]
            self.security_symbol_code = str(q.get("securitySymbolCode", self.symbol))  # type: ignore[attr-defined]
            self.dollar_based_trading_eligible_indicator = bool(  # type: ignore[attr-defined]
                q.get("dollarBasedTradingEligibleIndicator", False),
            )
            self.security_status_code = str(q.get("securityStatusCode", ""))  # type: ignore[attr-defined]

        _direct_get_symbol_quote._rsa_chase_direct = True  # type: ignore[attr-defined]  # noqa: SLF001
        _cs.SymbolQuote.get_symbol_quote = _direct_get_symbol_quote  # type: ignore[assignment]

    _applied = True
    print(
        "Chase: direct-order path active "
        "(RSA_CHASE_DIRECT_ORDER=1; order + quote page nav skipped)",
    )
