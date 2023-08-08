# Nelson Dane
# Ally API

import os
import traceback

import ally
import requests
from dotenv import load_dotenv
from helperAPI import Brokerage, stockOrder, printAndDiscord, printHoldings


# Initialize Ally
def ally_init(ALLY_EXTERNAL=None, ALLY_ACCOUNT_NUMBERS_EXTERNAL=None):
    # Initialize .env file
    load_dotenv()
    # Import Ally account
    if not os.getenv("ALLY") or not os.getenv("ALLY_ACCOUNT_NUMBERS") and ALLY_EXTERNAL is None and ALLY_ACCOUNT_NUMBERS_EXTERNAL is None:
        print("Ally not found, skipping...")
        return None
    accounts = os.environ["ALLY"].strip().split(",") if ALLY_EXTERNAL is None else ALLY_EXTERNAL.strip().split(",")
    account_nbrs_list = os.environ["ALLY_ACCOUNT_NUMBERS"].strip().split(",") if ALLY_ACCOUNT_NUMBERS_EXTERNAL is None else ALLY_ACCOUNT_NUMBERS_EXTERNAL.strip().split(",")
    params_list = []
    for account in accounts:
        account = account.split(":")
        for nbr in account_nbrs_list:
            for num in nbr.split(":"):
                if len(account) != 4:
                    print(f"{name}: Too many parameters for Ally account, please see README.md and .env.example, skipping...")
                    return None
                params = {
                    "ALLY_CONSUMER_KEY": account[0],
                    "ALLY_CONSUMER_SECRET": account[1],
                    "ALLY_OAUTH_TOKEN": account[2],
                    "ALLY_OAUTH_SECRET": account[3],
                    "ALLY_ACCOUNT_NBR": num,
                }
                params_list.append(params)
    # Initialize Ally account
    ally_obj = Brokerage("Ally")
    for account in accounts:
        index = accounts.index(account) + 1
        name = f"Ally {index}"
        print(f"Logging in to {name}...")
        for nbr in account_nbrs_list:
            for index, num in enumerate(nbr.split(":")):
                try:
                    a = ally.Ally(params=params_list[index])
                except requests.exceptions.HTTPError as e:
                    print(f"{name}: Error logging in: {e}")
                    return None
                # Ally needs a different object for each account number
                ally_obj.set_logged_in_object(name, a, num)
                ally_obj.set_account_number(name, num)
        print("Logged in to Ally!")
    return ally_obj


# Function to get the current account holdings
def ally_holdings(ao: Brokerage, ctx=None, loop=None):
    for key in ao.get_account_numbers():
        account_numbers = ao.get_account_numbers(key)
        for account in account_numbers:
            obj: ally.Ally = ao.get_logged_in_objects(key, account)
            try:
                # Get account holdings
                ab = obj.balances()
                a_value = ab["accountvalue"].values
                for value in a_value:
                    ao.set_account_totals(key, account, value)
                # Print account stock holdings
                ah = obj.holdings()
                # Test if holdings is empty
                if len(ah.index) > 0:
                    account_symbols = (ah["sym"].values).tolist()
                    qty = (ah["qty"].values).tolist()
                    current_price = (ah["marketvalue"].values).tolist()
                    for i, symbol in enumerate(account_symbols):
                        ao.set_holdings(key, account, symbol, qty[i], current_price[i])
            except Exception as e:
                printAndDiscord(f"{key}: Error getting account holdings: {e}", ctx, loop)
                print(traceback.format_exc())
                continue
    printHoldings(ao, ctx, loop)


# Function to buy/sell stock on Ally
def ally_transaction(
    ao: Brokerage, orderObj: stockOrder, ctx=None, loop=None, RETRY=False, account_retry=None
):
    print()
    print("==============================")
    print("Ally")
    print("==============================")
    print()
    # Set the action
    price = ally.Order.Market()
    if isinstance(orderObj.get_price(), float) or isinstance(orderObj.get_price(), int):
        print(f"Limit order at: ${float(orderObj.get_price())}")
        price = ally.Order.Limit(limpx=float(orderObj.get_price()))
    for s in orderObj.get_stocks():
        for key in ao.get_account_numbers():
            printAndDiscord(f"{key}: {orderObj.get_action()}ing {orderObj.get_amount} of {s}", ctx, loop)
            for account in ao.get_account_numbers(key):
                if not RETRY:
                    obj: ally.Ally = ao.get_logged_in_objects(key, account)
                else:
                    obj: ally.Ally = ao
                    account = account_retry
                try:
                    # Create order
                    o = ally.Order.Order(
                        buysell=orderObj.get_action(),
                        symbol=s,
                        price=price,
                        time=orderObj.get_time(),
                        qty=orderObj.get_amount(), 
                        #account=account # This fails if account is not an integer
                    )
                    # Print order preview
                    print(f"{key} {account}: {str(o)}")
                    # Submit order
                    o.orderid
                    if not orderObj.get_dry():
                        obj.submit(o, preview=False)
                    else:
                        printAndDiscord(
                            f"{key} {account}: Running in DRY mode. "
                            + f"Trasaction would've been: {orderObj.get_action()} {orderObj.get_amount()} of {s}",
                            ctx,
                            loop,
                        )
                    # Print order status
                    if o.orderid:
                        printAndDiscord(f"{key} {account}: Order {o.orderid} submitted", ctx, loop)
                    else:
                        printAndDiscord(f"{key} {account}: Order not submitted", ctx, loop)
                    if RETRY:
                        return
                except Exception as e:
                    ally_call_error = (
                        "Error: For your security, certain symbols may only be traded "
                        + "by speaking to an Ally Invest registered representative. "
                        + "Please call 1-855-880-2559 if you need further assistance with this order."
                    )
                    if "500 server error: internal server error for url:" in str(e).lower():
                        # If selling too soon, then an error is thrown
                        if orderObj.get_action() == "sell":
                            printAndDiscord(ally_call_error, ctx, loop)
                        # If the message comes up while buying, then
                        # try again with a limit order
                        elif orderObj.get_action() == "buy" and not RETRY:
                            printAndDiscord(
                                f"{key} {account}: Error placing market buy, trying again with limit order...",
                                ctx,
                                loop,
                            )
                            # Need to get stock price (compare bid, ask, and last)
                            try:
                                # Get stock values
                                quotes = obj.quote(
                                    s,
                                    fields=["bid", "ask", "last"],
                                )
                                # Add 1 cent to the highest value of the 3 above
                                new_price = (
                                    max(
                                        [
                                            float(quotes["last"][0]),
                                            float(quotes["bid"][0]),
                                            float(quotes["ask"][0]),
                                        ]
                                    )
                                ) + 0.01
                                # Set new price
                                orderObj.set_price(new_price)
                                # Run function again with limit order
                                ally_transaction(
                                    ao, orderObj, ctx, loop, RETRY=True, account_retry=account
                                )
                            except Exception as ex:
                                printAndDiscord(f"{key} {account}: Failed to place limit order: {ex}", ctx, loop)
                        else:
                            printAndDiscord(f"{key} {account}: Error placing limit order: {e}", ctx, loop)
                    # If price is not a string then it must've failed a limit order
                    elif not isinstance(orderObj.get_price(), str):
                        printAndDiscord(f"{key} {account}: Error placing limit order: {e}", ctx, loop)
                    else:
                        printAndDiscord(f"{key} {account}: Error submitting order: {e}", ctx, loop)
