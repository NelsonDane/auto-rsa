# Nelson Dane
# Webull API

import os
import traceback
from time import sleep

from dotenv import load_dotenv
from webull import webull

from helperAPI import Brokerage, maskString, printAndDiscord, printHoldings, stockOrder

MAX_WB_RETRIES = 3  # Number of times to retry logging in if not successful
MAX_WB_ACCOUNTS = 11  # Different account types


def place_order(obj: webull, account: str, orderObj: stockOrder, s: str):
    obj.set_account_id(account)
    order = obj.place_order(
        stock=s,
        action=orderObj.get_action().upper(),
        orderType=orderObj.get_price().upper(),
        quant=orderObj.get_amount(),
        enforce=orderObj.get_time().upper(),
    )
    if order.get("success") is not None and not order["success"]:
        print(f"{order['msg']} Code {order['code']}")
        return False
    return True


# Initialize Webull
def webull_init(WEBULL_EXTERNAL=None):
    # Initialize .env file
    load_dotenv()
    # Import Webull account
    wb_obj = Brokerage("Webull")
    if not os.getenv("WEBULL") and WEBULL_EXTERNAL is None:
        print("Webull not found, skipping...")
        return None
    accounts = (
        os.environ["WEBULL"].strip().split(",")
        if WEBULL_EXTERNAL is None
        else WEBULL_EXTERNAL.strip().split(",")
    )
    for index, account in enumerate(accounts):
        print("Logging in to Webull...")
        name = f"Webull {index + 1}"
        account = account.split(":")
        if len(account) != 4:
            print(
                f"Invalid number of parameters for {name}, got {len(account)}, expected 4"
            )
            return None
        try:
            for i in range(MAX_WB_RETRIES):
                wb = webull()
                wb.set_did(account[2])
                wb.login(account[0], account[1])
                wb.get_trade_token(account[3])
                id_test = wb.get_account_id(0)
                if id_test is not None:
                    break
                if i == MAX_WB_RETRIES - 1:
                    raise Exception(
                        f"Unable to log in to {name} after {i+1} tries. Check credentials."
                    )
            wb_obj.set_logged_in_object(name, wb, "wb")
            wb_obj.set_logged_in_object(name, account[3], "trading_pin")
            # Get all accounts
            for i in range(MAX_WB_ACCOUNTS):
                id = wb.get_account_id(i)
                if id is None:
                    break
                # Webull uses a different internal account ID than displayed in app
                ac = wb.get_account(v2=True)["accountSummaryVO"]
                wb_obj.set_account_number(name, ac["accountNumber"])
                print(maskString(ac["accountNumber"]))
                wb_obj.set_logged_in_object(name, id, ac["accountNumber"])
                wb_obj.set_account_type(
                    name, ac["accountNumber"], ac["accountTypeName"]
                )
                wb_obj.set_account_totals(
                    name, ac["accountNumber"], ac["netLiquidationValue"]
                )
        except Exception as e:
            print(traceback.format_exc())
            print(f"Error: Unable to log in to Webull: {e}")
            return None
        print("Logged in to Webull!")
    return wb_obj


def webull_holdings(wbo: Brokerage, loop=None):
    for key in wbo.get_account_numbers():
        for account in wbo.get_account_numbers(key):
            obj: webull = wbo.get_logged_in_objects(key, "wb")
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
                            item = item["items"][0]
                        sym = item["ticker"]["symbol"]
                        if sym == "":
                            sym = "Unknown"
                        if item.get("quantity") is not None:
                            qty = item["quantity"]
                        else:
                            qty = item["position"]
                        if float(qty) == 0:
                            continue
                        mv = round(float(item["marketValue"]) / float(qty), 2)
                        wbo.set_holdings(key, account, sym, qty, mv)
            except Exception as e:
                printAndDiscord(f"{key}: Error getting holdings: {e}", loop)
                traceback.print_exc()
                continue
    printHoldings(wbo, loop=loop)


def webull_transaction(wbo: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Webull")
    print("==============================")
    print()
    for s in orderObj.get_stocks():
        for key in wbo.get_account_numbers():
            printAndDiscord(
                f"{key}: {orderObj.get_action()}ing {orderObj.get_amount()} of {s}",
                loop,
            )
            for account in wbo.get_account_numbers(key):
                print_account = maskString(account)
                obj: webull = wbo.get_logged_in_objects(key, "wb")
                internal_account = wbo.get_logged_in_objects(key, account)
                if not orderObj.get_dry():
                    old_amount = orderObj.get_amount()
                    original_action = orderObj.get_action()
                    try:
                        if orderObj.get_price() == "market":
                            orderObj.set_price("MKT")
                        # If buy stock price < $1 or $0.10,
                        # buy 100/1000 shares and sell 100/1000 - amount
                        quote = obj.get_quote(s)
                        askList = quote.get("askList", [])
                        bidList = quote.get("bidList", [])
                        if askList == [] and bidList == []:
                            printAndDiscord(
                                f"{key}: {s} is not available for trading", loop
                            )
                            raise Exception(f"{s} is not available for trading")
                        askPrice = float(askList[0]["price"]) if askList != [] else 0
                        bidPrice = float(bidList[0]["price"]) if bidList != [] else 0
                        should_dance = False
                        # Dance if:
                        # amount < 100 and price < $1
                        # amount < 1000 and price < $0.10
                        if (
                            (askPrice < 1 or bidPrice < 1)
                            and orderObj.get_amount() < 100
                        ) or (
                            (askPrice < 0.1 or bidPrice < 0.1)
                            and orderObj.get_amount() < 1000
                        ):
                            should_dance = True
                        if should_dance and orderObj.get_action() == "buy":
                            # 100 shares if < $1, 1000 shares if < $0.10
                            big_amount = (
                                1000 if (askPrice < 0.1 or bidPrice < 0.1) else 100
                            )
                            print(
                                f"Buying {big_amount} then selling {big_amount - orderObj.get_amount()} of {s}"
                            )
                            orderObj.set_amount(big_amount)
                            buy_success = place_order(
                                obj, internal_account, orderObj, s
                            )
                            if not buy_success:
                                raise Exception(f"Error buying {big_amount} of {s}")
                            orderObj.set_amount(big_amount - old_amount)
                            orderObj.set_action("sell")
                            sleep(1)
                            order = place_order(obj, internal_account, orderObj, s)
                            if not order:
                                raise Exception(
                                    f"Error selling {big_amount - old_amount} of {s}"
                                )
                        else:
                            # Place normal order
                            order = place_order(obj, internal_account, orderObj, s)
                        if order:
                            printAndDiscord(
                                f"{key}: {orderObj.get_action()} {orderObj.get_amount()} of {s} in {print_account}: Success",
                                loop,
                            )
                    except Exception as e:
                        printAndDiscord(
                            f"{key} {print_account}: Error placing order: {e}", loop
                        )
                        print(traceback.format_exc())
                        continue
                    finally:
                        # Restore orderObj
                        orderObj.set_amount(old_amount)
                        orderObj.set_action(original_action)
                else:
                    printAndDiscord(
                        f"{key} {print_account}: Running in DRY mode. Transaction would've been: {orderObj.get_action()} {orderObj.get_amount()} of {s}",
                        loop,
                    )
