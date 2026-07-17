# Nelson Dane
# Robinhood API

import contextlib
import os
import traceback
from asyncio import AbstractEventLoop
from typing import Any, cast

from dotenv import load_dotenv

from src.helper_api import Brokerage, StockOrder, complete_or_fail, mask_string, print_all_holdings, print_and_discord, record_fill, reserve_or_skip
from src.vendors.robin_stocks.robin_stocks import robinhood as rh

def _env_num(name: str, default: float, cast: type) -> float:
    """Parse a numeric env override, falling back to ``default``.

    A bad operator override (e.g. ``RSA_RH_FILL_POLL_TRIES=5s``) must not
    raise at import and take down the whole Robinhood broker — it just
    reverts to the default.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return default


# Bounded fill-verification poll. A just-placed order is usually still
# "queued" for a beat; poll get_stock_order_info a few times so a market
# order has a chance to reach "filled" before we record it. Kept small so
# it never wedges a run; tunable via env for slow accounts.
_RH_FILL_POLL_TRIES = int(_env_num("RSA_RH_FILL_POLL_TRIES", 4, int))
_RH_FILL_POLL_SECONDS = _env_num("RSA_RH_FILL_POLL_SECONDS", 1.5, float)
_RH_TERMINAL_STATES = frozenset(
    {"filled", "rejected", "canceled", "cancelled", "failed", "voided"},
)


def _poll_rh_order(order_ref: str) -> dict | None:
    """Poll get_stock_order_info until terminal or the budget is spent.

    Returns the last order-info dict seen, or ``None`` when verification
    isn't possible (the function is absent, no order id, or every call
    errored) — the caller then falls back to legacy success/fail so
    there is never a regression when the API can't answer.
    """
    import time  # noqa: PLC0415

    getter = getattr(rh, "get_stock_order_info", None)
    if not callable(getter) or not order_ref:
        return None
    last: dict | None = None
    tries = max(1, _RH_FILL_POLL_TRIES)
    for i in range(tries):
        try:
            info = getter(order_ref)
        except Exception:  # noqa: BLE001 -- best-effort; keep the last good read
            return last
        if isinstance(info, dict) and info:
            last = info
            state = str(info.get("state", "") or "").strip().lower()
            if state in _RH_TERMINAL_STATES:
                return info
        if i < tries - 1:
            time.sleep(_RH_FILL_POLL_SECONDS)
    return last


def _record_rh_outcome(  # noqa: PLR0913
    play: object,
    *,
    order_obj: StockOrder,
    order_resp: object,
    message: str,
    action: str,
    ticker: str,
    account: object,
    key: str,
    print_account: str,
    loop: AbstractEventLoop | None = None,
) -> None:
    """Verify a placed Robinhood order and record its true FillState.

    A submitted order is NOT a filled order (the Robinhood analog of the
    Chase queue-eligible bug). When order-status polling is available we
    record the real state (filled → EXECUTED, working → PENDING, rejected
    → FAILED). When it isn't, we fall back to the legacy behavior exactly
    so nothing regresses.
    """
    from src.brokerages._robinhood_fill import (  # noqa: PLC0415
        classify_robinhood_order,
        robinhood_filled_qty,
        robinhood_order_ref,
    )
    from src.brokerages.fill_result import FillResult, FillState  # noqa: PLC0415

    order_ref = robinhood_order_ref(order_resp)
    # A submission that echoed an error is a rejection regardless of poll.
    if isinstance(order_resp, dict) and order_resp.get("non_field_errors"):
        record_fill(
            play, order_obj=order_obj,
            result=FillResult(
                FillState.REJECTED, broker="robinhood", account=str(account),
                ticker=ticker, action=action, order_ref=order_ref,
                detail=str(message),
            ),
        )
        return

    info = _poll_rh_order(order_ref)
    if info is None:
        # Can't verify (no get_stock_order_info, no id, or transient
        # error) — preserve legacy behavior exactly. No regression.
        complete_or_fail(
            play, order_obj=order_obj,
            success=(message == "Success"), detail=message,
        )
        return

    state = classify_robinhood_order(info)
    qty = robinhood_filled_qty(info)
    rh_state = str(info.get("state", "?"))
    detail = (
        message if state is FillState.FILLED
        else f"{message} (order state: {rh_state})"
    )
    status = record_fill(
        play, order_obj=order_obj, source="poll",
        result=FillResult(
            state, broker="robinhood", account=str(account), ticker=ticker,
            action=action, qty=qty, order_ref=order_ref or robinhood_order_ref(info),
            detail=str(detail),
        ),
    )
    if state is not FillState.FILLED:
        # Surface anything that isn't a clean fill so a "pending" or
        # rejected order isn't mistaken for a completed buy.
        print_and_discord(
            f"{key}: {ticker} in {print_account} — order state "
            f"'{rh_state}' (recorded {status}, not a confirmed fill)",
            loop,
        )


def login_with_cache(pickle_path: str, pickle_name: str) -> None:
    """Log in to Robinhood with cached credentials."""
    rh.login(
        expiresIn=86400 * 30,  # 30 days
        pickle_path=pickle_path,
        pickle_name=pickle_name,
    )


def robinhood_init(loop: AbstractEventLoop | None = None) -> Brokerage | None:
    """Initialize Robinhood API."""
    # Initialize .env file
    load_dotenv()
    # Import Robinhood account
    rh_obj = Brokerage("Robinhood")
    if not os.getenv("ROBINHOOD"):
        print("Robinhood not found, skipping...")
        return None
    big_rh = os.environ["ROBINHOOD"].strip().split(",")
    # Log in to Robinhood account
    all_account_numbers = []
    for account in big_rh:
        index = big_rh.index(account) + 1
        name = f"Robinhood {index}"
        print(f"Logging in to {name}...")
        print_and_discord(f"{name}: Check phone app for verification prompt. You have ~60 seconds.", loop)
        try:
            user_pass = account.split(":")
            rh.login(
                username=user_pass[0],
                password=user_pass[1],
                store_session=True,
                expiresIn=86400 * 30,  # 30 days
                pickle_path="./creds/",
                pickle_name=name,
            )
            # Load all accounts
            all_accounts = cast("list[dict[str, Any]]", rh.account.load_account_profile(dataType="results"))
            for a in all_accounts:
                if a["account_number"] in all_account_numbers:
                    continue
                all_account_numbers.append(a["account_number"])
                rh_obj.set_account_number(name, a["account_number"])
                rh_obj.set_account_totals(
                    name,
                    a["account_number"],
                    a["portfolio_cash"],
                )
                rh_obj.set_account_type(
                    name,
                    a["account_number"],
                    a["brokerage_account_type"],
                )
                print(
                    f"Found {a['brokerage_account_type']} account {mask_string(a['account_number'])}",
                )
        except Exception as e:
            print(f"Error: Unable to log in to Robinhood: {e}")
            print(traceback.format_exc())
            return None
        print(f"Logged in to {name}")
    return rh_obj


def robinhood_holdings(rho: Brokerage, loop: AbstractEventLoop | None = None) -> None:
    """Retrieve and display all Robinhood account holdings."""
    for key in rho.get_account_numbers():
        for account in rho.get_account_numbers(key):
            login_with_cache(pickle_path="./creds/", pickle_name=key)
            try:
                # Get account holdings
                positions = cast("list[dict[str, str]]", rh.get_open_stock_positions(account_number=account))
                if positions:
                    for item in positions:
                        # Get symbol, quantity, price, and total value
                        sym = item["symbol"] = cast("str", rh.get_symbol_by_url(item["instrument"]))
                        qty = float(item["quantity"])
                        current_price: float | str = "N/A"
                        with contextlib.suppress(Exception):
                            current_price = round(float(rh.stocks.get_latest_price(sym)[0]), 2)
                        rho.set_holdings(key, account, sym, qty, current_price)
            except Exception as e:
                print_and_discord(f"{key}: Error getting account holdings: {e}", loop)
                print(traceback.format_exc())
                continue
    print_all_holdings(rho, loop)


def robinhood_transaction(rho: Brokerage, order_obj: StockOrder, loop: AbstractEventLoop | None = None) -> None:  # noqa: C901, PLR0912, PLR0915
    """Handle Robinhood API transactions."""
    print()
    print("==============================")
    print("Robinhood")
    print("==============================")
    print()
    for s in order_obj.get_stocks():
        for key in rho.get_account_numbers():
            print_and_discord(
                f"{key}: {order_obj.get_action()}ing {order_obj.get_amount()} of {s}",
                loop,
            )
            for account in rho.get_account_numbers(key):
                login_with_cache(pickle_path="./creds/", pickle_name=key)
                print_account = mask_string(account)
                # C2 + C1-pre: account filter + ledger intent reservation.
                play = reserve_or_skip(
                    broker_key="robinhood", account=account, ticker=s,
                    order_obj=order_obj,
                    display_label=f"{key} {print_account}", loop=loop,
                )
                if play is None:
                    continue
                if not order_obj.get_dry():
                    try:
                        # Market order
                        market_order = rh.order(
                            symbol=s,
                            quantity=order_obj.get_amount(),
                            side=order_obj.get_action(),
                            account_number=account,
                            timeInForce="gfd",
                        )
                        # Limit order fallback
                        if market_order is None:
                            print_and_discord(
                                f"{key}: Error {order_obj.get_action()}ing {order_obj.get_amount()} of {s} in {print_account}, trying Limit Order",
                                loop,
                            )
                            ask = rh.get_latest_price(s, priceType="ask_price")[0]
                            bid = rh.get_latest_price(s, priceType="bid_price")[0]
                            if ask is not None and bid is not None:
                                print(f"Ask: {ask}, Bid: {bid}")
                                # Add or subtract 1 cent to ask or bid
                                if order_obj.get_action() == "buy":
                                    price = max(float(bid), float(ask))
                                    price = round(price + 0.01, 2)
                                else:
                                    price = min(float(bid), float(ask))
                                    price = round(price - 0.01, 2)
                            else:
                                print_and_discord(
                                    f"{key}: Error getting price for {s}",
                                    loop,
                                )
                                complete_or_fail(
                                    play, order_obj=order_obj, success=False,
                                    detail="quote unavailable",
                                )
                                continue
                            limit_order = rh.order(
                                symbol=s,
                                quantity=order_obj.get_amount(),
                                side=order_obj.get_action(),
                                limitPrice=price,
                                account_number=account,
                                timeInForce="gfd",
                            )
                            if limit_order is None:
                                print_and_discord(
                                    f"{key}: Error {order_obj.get_action()}ing {order_obj.get_amount()} of {s} in {print_account}",
                                    loop,
                                )
                                complete_or_fail(
                                    play, order_obj=order_obj, success=False,
                                    detail="limit order returned None",
                                )
                                continue
                            message = "Success"
                            limit_order = cast("dict[str, str]", limit_order)
                            if limit_order.get("non_field_errors") is not None:
                                message = limit_order["non_field_errors"]
                            print_and_discord(
                                f"{key}: {order_obj.get_action()} {order_obj.get_amount()} of {s} in {print_account} @ {price}: {message}",
                                loop,
                            )
                            _record_rh_outcome(
                                play, order_obj=order_obj, order_resp=limit_order,
                                message=message, action=order_obj.get_action(),
                                ticker=s, account=account, key=key,
                                print_account=print_account, loop=loop,
                            )
                        else:
                            message = "Success"
                            market_order = cast("dict[str, str]", market_order)
                            if market_order.get("non_field_errors") is not None:
                                message = market_order["non_field_errors"]
                            print_and_discord(
                                f"{key}: {order_obj.get_action()} {order_obj.get_amount()} of {s} in {print_account}: {message}",
                                loop,
                            )
                            _record_rh_outcome(
                                play, order_obj=order_obj, order_resp=market_order,
                                message=message, action=order_obj.get_action(),
                                ticker=s, account=account, key=key,
                                print_account=print_account, loop=loop,
                            )
                    except Exception as e:
                        print_and_discord(f"{key} Error submitting order: {e}", loop)
                        print(traceback.format_exc())
                        complete_or_fail(
                            play, order_obj=order_obj, success=False, detail=str(e),
                        )
                else:
                    print_and_discord(
                        f"{key} {print_account} Running in DRY mode. Transaction would've been: {order_obj.get_action()} {order_obj.get_amount()} of {s}",
                        loop,
                    )
                    # Dry run: complete_or_fail is a no-op (see helper docs).
                    complete_or_fail(
                        play, order_obj=order_obj, success=True, detail="dry run",
                    )
