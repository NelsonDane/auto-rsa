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

import asyncio
import datetime
import os
import time

_applied = False
_DIRECT_MARKER = "_rsa_chase_direct"

# Per-call HTTP timeouts. The vendored lib's curl_cffi calls have
# none, which is the *root cause* of the intermittent multi-account
# hang: when an endpoint stalls there's nothing to break the wait,
# and the 120s outer coroutine bound only fires per-account so 8
# accounts x 120s easily blows past the 600s broker watchdog.
#
# Tunable via env (operators don't have to edit code to soften them).
_VALIDATE_TIMEOUT = 45
_EXECUTE_TIMEOUT = 45
_QUOTE_TIMEOUT = 20
# Quote GETs are idempotent and read-only — retrying is safe and
# pulls intermittent transient stalls out of the hot path. Order
# POSTs stay single-shot (retrying execute could double-fill).
_QUOTE_RETRIES = 3
_QUOTE_BACKOFF_S = (0.5, 1.5, 3.0)


def _envint(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _validate_timeout() -> int:
    return _envint("RSA_CHASE_DIRECT_VALIDATE_TIMEOUT", _VALIDATE_TIMEOUT)


def _execute_timeout() -> int:
    return _envint("RSA_CHASE_DIRECT_EXECUTE_TIMEOUT", _EXECUTE_TIMEOUT)


def _quote_timeout() -> int:
    return _envint("RSA_CHASE_DIRECT_QUOTE_TIMEOUT", _QUOTE_TIMEOUT)


def _classify_chase_exc(exc: BaseException) -> str:
    """Map a Chase POST exception to one of the project's reason codes.

    The direct path catches `Exception` around every curl_cffi call;
    without classification the GUI just sees opaque "Validation
    Exception: ..." text and can't distinguish a session-expired
    failure from a timeout from a 4xx rejection. Surface the code
    in the ORDER INVALID text so the per-broker icon (SESSION_ERROR
    -> red) and the ledger reason field both reflect reality.

    Lazy import of src.outcomes so this patch module stays
    self-contained and doesn't fail-fast on import-time circulars.
    """
    try:
        from src.outcomes import classify_outcome  # noqa: PLC0415

        return classify_outcome(repr(exc))
    except Exception:
        return "OTHER"


def _log(label: str, t0: float, extra: str = "") -> None:
    """Stamp a chase-direct step with elapsed seconds since this call started.

    Cheap diagnostic for the *next* hang report: 'we got to validate
    POST at T+12.4s and never reached execute' is actionable; 'it
    hung' is not.
    """
    elapsed = time.monotonic() - t0
    suffix = f" {extra}" if extra else ""
    print(f"[chase-direct] T+{elapsed:5.2f}s {label}{suffix}")


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

    async def _direct_place_order_async(  # noqa: C901, PLR0911, PLR0912, PLR0915, PLR0917
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
        t0 = time.monotonic()
        _log("order start", t0, f"acct={account_id} {order_type} {symbol}")
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
        _log("cookies fetched", t0, f"n={len(cookies_dict)}")

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
            _log("validate POST →", t0, f"timeout={_validate_timeout()}s")
            resp_val = _cc_requests.post(
                validate_order(order_type=order_type),
                headers=headers,
                cookies=cookies_dict,
                json=payload,
                impersonate="chrome",
                timeout=_validate_timeout(),
            )
            _log("validate POST ←", t0, f"http={resp_val.status_code}")
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
                _log("dry-run done", t0)
                return order_messages
            if not exchange_id:
                order_messages["ORDER INVALID"] = (
                    "Validation returned no exchange id; not executing."
                )
                return order_messages
        except Exception as exc:
            order_messages["ORDER INVALID"] = (
                f"Validation Exception [{_classify_chase_exc(exc)}]: {exc}"
            )
            _log("validate FAIL", t0, repr(exc))
            return order_messages

        try:
            exec_payload = dict(payload)
            exec_payload[
                "financialInformationExchangeSystemOrderIdentifier"
            ] = exchange_id
            _log("execute POST →", t0, f"timeout={_execute_timeout()}s")
            resp_exec = _cc_requests.post(
                execute_order(order_type=order_type),
                headers=headers,
                cookies=cookies_dict,
                json=exec_payload,
                impersonate="chrome",
                timeout=_execute_timeout(),
            )
            _log("execute POST ←", t0, f"http={resp_exec.status_code}")
            if resp_exec.status_code != 200:  # noqa: PLR2004
                order_messages["ORDER INVALID"] = (
                    f"Execution Failed ({resp_exec.status_code}): "
                    f"{resp_exec.text}"
                )
                return order_messages
            order_messages["ORDER CONFIRMATION"] = resp_exec.json()
        except Exception as exc:
            order_messages["ORDER INVALID"] = (
                f"Execution Exception [{_classify_chase_exc(exc)}]: {exc}"
            )
            _log("execute FAIL", t0, repr(exc))
        return order_messages

    _direct_place_order_async._rsa_chase_direct = True  # type: ignore[attr-defined]  # noqa: SLF001
    _co.Order._place_order_async = _direct_place_order_async  # type: ignore[assignment]  # noqa: SLF001

    # --- SymbolQuote.get_symbol_quote: same page-nav hang, same fix ---
    orig_quote = _cs.SymbolQuote.get_symbol_quote
    if not getattr(orig_quote, _DIRECT_MARKER, False):

        async def _direct_get_symbol_quote(self: object) -> None:  # noqa: C901, PLR0915
            t0 = time.monotonic()
            _log(
                "quote start", t0,
                f"symbol={self.symbol}",  # type: ignore[attr-defined]
            )
            try:
                cookies = await self.session.browser.cookies.get_all()  # type: ignore[attr-defined]
            except Exception as exc:
                _log("quote cookies FAIL", t0, repr(exc))
                return
            cookies_dict = {c.name: c.value for c in cookies}
            url = (
                f"{quote_url()}?security-symbol-code={self.symbol}"  # type: ignore[attr-defined]
                "&security-validate-indicator=true"
                "&dollar-based-trading-include-indicator=true"
            )
            # Retry the GET because it's idempotent and read-only —
            # turning an intermittent transient stall into a deferred
            # success is the load-bearing part of this whole fix.
            q: dict | None = None
            last_exc: Exception | None = None
            for attempt in range(1, _QUOTE_RETRIES + 1):
                _log(
                    "quote GET →", t0,
                    f"attempt={attempt}/{_QUOTE_RETRIES} "
                    f"timeout={_quote_timeout()}s",
                )
                try:
                    resp = _cc_requests.get(
                        url,
                        headers=get_headers(),
                        cookies=cookies_dict,
                        impersonate="chrome",
                        timeout=_quote_timeout(),
                    )
                    _log("quote GET ←", t0, f"http={resp.status_code}")
                    if resp.status_code == 200:  # noqa: PLR2004
                        q = resp.json()
                        break
                    last_exc = RuntimeError(
                        f"http {resp.status_code}: {resp.text[:200]}",
                    )
                except Exception as exc:
                    last_exc = exc
                    _log("quote GET FAIL", t0, repr(exc))
                # Backoff before the next attempt (no sleep after last).
                if attempt < _QUOTE_RETRIES:
                    delay = _QUOTE_BACKOFF_S[
                        min(attempt - 1, len(_QUOTE_BACKOFF_S) - 1)
                    ]
                    await asyncio.sleep(delay)
            if q is None:
                _log(
                    "quote gave up", t0,
                    f"after {_QUOTE_RETRIES} attempts: {last_exc!r}",
                )
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
            _log(
                "quote done", t0,
                f"last={self.last_trade_price_amount}",  # type: ignore[attr-defined]
            )

        _direct_get_symbol_quote._rsa_chase_direct = True  # type: ignore[attr-defined]  # noqa: SLF001
        _cs.SymbolQuote.get_symbol_quote = _direct_get_symbol_quote  # type: ignore[assignment]

    _applied = True
    print(
        "Chase: direct-order path active "
        "(RSA_CHASE_DIRECT_ORDER=1; order + quote page nav skipped)",
    )
