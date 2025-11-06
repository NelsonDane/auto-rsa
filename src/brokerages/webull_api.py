# Nelson Dane
# Webull API

import os
import traceback
from asyncio import AbstractEventLoop
from time import sleep
from typing import cast

from dotenv import load_dotenv

from src.helper_api import Brokerage, StockOrder, mask_string, print_all_holdings, print_and_discord
from src.vendors.webull.webull import webull

MAX_WB_RETRIES = 3  # Number of times to retry logging in if not successful
MAX_WB_ACCOUNTS = 11  # Different account types


def place_order(obj: webull, account: str, order_obj: StockOrder, s: str) -> bool:
    """Place an order on Webull."""
    obj.set_account_id(account)
    order_type = "MKT" if order_obj.get_price() == "market" else "LMT"
    order = obj.place_order(
        stock=s,
        action=order_obj.get_action().upper(),
        orderType=order_type,
        quant=int(order_obj.get_amount()),
        enforce=order_obj.get_time().upper(),
    )
    if order.get("success") is not None and not order["success"]:
        print(f"{order['msg']} Code {order['code']}")
        return False
    return True


# Initialize Webull
def webull_init() -> Brokerage | None:
    """Initialize Webull API."""
    # Initialize .env file
    load_dotenv()
    # Import Webull account
    wb_obj = Brokerage("Webull")
    if not os.getenv("WEBULL"):
        print("Webull not found, skipping...")
        return None
    accounts = os.environ["WEBULL"].strip().split(",")
    for index, wb_account in enumerate(accounts):
        print("Logging in to Webull...")
        name = f"Webull {index + 1}"
        account = wb_account.split(":")
        if len(account) != 4:  # noqa: PLR2004
            print(f"Invalid number of parameters for {name}, got {len(account)}, expected 4")
            return None
        try:
            wb: webull | None = None
            for _ in range(MAX_WB_RETRIES):
                wb = webull()
                wb.set_did(account[2])
                wb.login(account[0], account[1])
                wb.get_trade_token(account[3])
                id_test = wb.get_account_id(0)
                if id_test is not None:
                    break
            if wb is None:
                msg = f"Unable to log in to {name}. Check credentials."
                raise Exception(msg)
            wb_obj.set_logged_in_object(name, wb, "wb")
            wb_obj.set_logged_in_object(name, account[3], "trading_pin")
            # Get all accounts
            for i in range(MAX_WB_ACCOUNTS):
                account_id = wb.get_account_id(i)
                if account_id is None:
                    break
                # Webull uses a different internal account ID than displayed in app
                ac = wb.get_account(v2=True)["accountSummaryVO"]
                wb_obj.set_account_number(name, ac["accountNumber"])
                print(mask_string(ac["accountNumber"]))
                wb_obj.set_logged_in_object(name, account_id, ac["accountNumber"])
                wb_obj.set_account_type(
                    name,
                    ac["accountNumber"],
                    ac["accountTypeName"],
                )
                wb_obj.set_account_totals(
                    name,
                    ac["accountNumber"],
                    ac["netLiquidationValue"],
                )
        except Exception as e:
            print(traceback.format_exc())
            print(f"Error: Unable to log in to Webull: {e}")
            return None
        print("Logged in to Webull!")
    return wb_obj


def webull_holdings(wbo: Brokerage, loop: AbstractEventLoop | None = None) -> None:
    """Retrieve and display all Webull account holdings."""
    for key in wbo.get_account_numbers():
        for account in wbo.get_account_numbers(key):
            obj = cast("webull", wbo.get_logged_in_objects(key, "wb"))
            internal_account = wbo.get_logged_in_objects(key, account)
            try:
                # Get account holdings
                obj.set_account_id(internal_account)
                positions = obj.get_positions()
                if positions is None:
                    positions = obj.get_positions(v2=True)
                # List of holdings dictionaries
                if positions is not None and positions != []:
                    for item in positions:
                        if item.get("items") is not None:
                            item = item["items"][0]  # noqa: PLW2901
                        sym = item["ticker"]["symbol"]
                        if not sym:
                            sym = "Unknown"
                        qty = item["quantity"] if item.get("quantity") is not None else item["position"]
                        if float(qty) == 0:
                            continue
                        mv = round(float(item["marketValue"]) / float(qty), 2)
                        wbo.set_holdings(key, account, sym, qty, mv)
            except Exception as e:
                print_and_discord(f"{key}: Error getting holdings: {e}", loop)
                traceback.print_exc()
                continue
    print_all_holdings(wbo, loop=loop)


def webull_transaction(wbo: Brokerage, order_obj: StockOrder, loop: AbstractEventLoop | None = None) -> None:  # noqa: C901, PLR0912, PLR0914, PLR0915
    """Handle Webull stock transactions."""
    print()
    print("==============================")
    print("Webull")
    print("==============================")
    print()
    for s in order_obj.get_stocks():
        for key in wbo.get_account_numbers():
            print_and_discord(
                f"{key}: {order_obj.get_action()}ing {order_obj.get_amount()} of {s}",
                loop,
            )
            for account in wbo.get_account_numbers(key):
                print_account = mask_string(account)
                obj = cast("webull", wbo.get_logged_in_objects(key, "wb"))
                internal_account = cast("str", wbo.get_logged_in_objects(key, account))
                if not order_obj.get_dry():
                    old_amount = order_obj.get_amount()
                    original_action = order_obj.get_action()
                    try:
                        # If buy stock price < $1 or $0.10,
                        # buy 100/1000 shares and sell 100/1000 - amount
                        quote = obj.get_quote(s)
                        ask_list = quote.get("askList", [])
                        bid_list = quote.get("bidList", [])
                        if ask_list == [] and bid_list == []:
                            msg = f"{key}: {s} is not available for trading"
                            print_and_discord(msg, loop)
                            raise Exception(msg)
                        ask_price = float(ask_list[0]["price"]) if ask_list != [] else 0
                        bid_price = float(bid_list[0]["price"]) if bid_list != [] else 0
                        should_dance = False
                        # Dance if:
                        # amount < 100 and price < $1
                        dollar_dance_amount = 100
                        # amount < 1000 and price < $0.10
                        dime_amount = 0.10
                        dime_dance_amount = 1000
                        if ((ask_price < 1 or bid_price < 1) and order_obj.get_amount() < dollar_dance_amount) or ((ask_price < dime_amount or bid_price < dime_amount) and order_obj.get_amount() < dime_dance_amount):  # noqa: PLR0916
                            should_dance = True
                        if should_dance and order_obj.get_action() == "buy":
                            # 100 shares if < $1, 1000 shares if < $0.10
                            big_amount = dime_dance_amount if (ask_price < dime_amount or bid_price < dime_amount) else dollar_dance_amount
                            print(
                                f"Buying {big_amount} then selling {big_amount - order_obj.get_amount()} of {s}",
                            )
                            order_obj.set_amount(big_amount)
                            buy_success = place_order(obj, internal_account, order_obj, s)
                            if not buy_success:
                                msg = f"Error buying {big_amount} of {s}"
                                raise Exception(msg)
                            order_obj.set_amount(big_amount - old_amount)
                            order_obj.set_action("sell")
                            sleep(1)
                            order = place_order(obj, internal_account, order_obj, s)
                            if not order:
                                msg = f"Error selling {big_amount - old_amount} of {s}"
                                raise Exception(msg)
                        else:
                            # Place normal order
                            order = place_order(obj, internal_account, order_obj, s)
                        if order:
                            print_and_discord(
                                f"{key}: {order_obj.get_action()} {order_obj.get_amount()} of {s} in {print_account}: Success",
                                loop,
                            )
                    except Exception as e:
                        print_and_discord(
                            f"{key} {print_account}: Error placing order: {e}",
                            loop,
                        )
                        print(traceback.format_exc())
                        continue
                    finally:
                        # Restore orderObj
                        order_obj.set_amount(old_amount)
                        order_obj.set_action("buy" if original_action.lower() == "buy" else "sell")
                else:
                    print_and_discord(
                        f"{key} {print_account}: Running in DRY mode. Transaction would've been: {order_obj.get_action()} {order_obj.get_amount()} of {s}",
                        loop,
                    )
