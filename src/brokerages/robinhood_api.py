# Nelson Dane
# Robinhood API

import contextlib
import os
import traceback
from asyncio import AbstractEventLoop
from typing import Any, cast

from dotenv import load_dotenv

from src.helper_api import Brokerage, StockOrder, mask_string, print_all_holdings, print_and_discord
from src.vendors.robin_stocks.robin_stocks import robinhood as rh


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
            rh_obj.set_logged_in_object(name, rh)
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
        obj = cast("rh", rho.get_logged_in_objects(key))
        for account in rho.get_account_numbers(key):
            login_with_cache(pickle_path="./creds/", pickle_name=key)
            try:
                # Get account holdings
                positions = cast("list[dict[str, str]]", obj.get_open_stock_positions(account_number=account))
                if positions:
                    for item in positions:
                        # Get symbol, quantity, price, and total value
                        sym = item["symbol"] = cast("str", obj.get_symbol_by_url(item["instrument"]))
                        qty = float(item["quantity"])
                        current_price: float | str = "N/A"
                        with contextlib.suppress(Exception):
                            current_price = round(float(obj.stocks.get_latest_price(sym)[0]), 2)
                        rho.set_holdings(key, account, sym, qty, current_price)
            except Exception as e:
                print_and_discord(f"{key}: Error getting account holdings: {e}", loop)
                print(traceback.format_exc())
                continue
    print_all_holdings(rho, loop)


def robinhood_transaction(rho: Brokerage, order_obj: StockOrder, loop: AbstractEventLoop | None = None) -> None:  # noqa: C901, PLR0912
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
                obj = cast("rh", rho.get_logged_in_objects(key))
                login_with_cache(pickle_path="./creds/", pickle_name=key)
                print_account = mask_string(account)
                if not order_obj.get_dry():
                    try:
                        # Market order
                        market_order = obj.order(
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
                            ask = obj.get_latest_price(s, priceType="ask_price")[0]
                            bid = obj.get_latest_price(s, priceType="bid_price")[0]
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
                                continue
                            limit_order = obj.order(
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
                                continue
                            message = "Success"
                            limit_order = cast("dict[str, str]", limit_order)
                            if limit_order.get("non_field_errors") is not None:
                                message = limit_order["non_field_errors"]
                            print_and_discord(
                                f"{key}: {order_obj.get_action()} {order_obj.get_amount()} of {s} in {print_account} @ {price}: {message}",
                                loop,
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
                    except Exception as e:
                        print_and_discord(f"{key} Error submitting order: {e}", loop)
                        print(traceback.format_exc())
                else:
                    print_and_discord(
                        f"{key} {print_account} Running in DRY mode. Transaction would've been: {order_obj.get_action()} {order_obj.get_amount()} of {s}",
                        loop,
                    )
