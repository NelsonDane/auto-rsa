# Nelson Dane
# Ally API

import os
import traceback

import ally
import requests
from dotenv import load_dotenv
from helperAPI import Brokerage, printAndDiscord, printHoldings


# Initialize Ally
def ally_init(ALLY_EXTERNAL=None):
    # Initialize .env file
    load_dotenv()
    # Import Ally account
    if not os.getenv("ALLY") and ALLY_EXTERNAL is None:
        print("Ally not found, skipping...")
        return None
    accounts = os.environ["ALLY"].strip().split(",") if ALLY_EXTERNAL is None else ALLY_EXTERNAL.strip().split(",")
    params_list = []
    for account in accounts:
        account = account.split(":")
        params = {
            "ALLY_CONSUMER_KEY": account[0],
            "ALLY_CONSUMER_SECRET": account[1],
            "ALLY_OAUTH_TOKEN": account[2],
            "ALLY_OAUTH_SECRET": account[3],
            "ALLY_ACCOUNT_NBR": account[4],
        }
        params_list.append(params)
    # Initialize Ally account
    ally_obj = Brokerage("Ally")
    for account in accounts:
        index = accounts.index(account) + 1
        name = f"Ally {index}"
        try:
            a = ally.Ally(params_list[index - 1])
            print(f"Logging in to {name}...")
            an = a.balances()
        except requests.exceptions.HTTPError as e:
            print(f"{name}: Error logging in: {e}")
            return None
        account_numbers = an["account"].values
        print(f"{name} account numbers: {account_numbers}")
        ally_obj.set_logged_in_object(name, a)
        for an in account_numbers:
            ally_obj.set_account_number(name, an)
        print("Logged in to Ally!")
    return ally_obj


# Function to get the current account holdings
def ally_holdings(ao: Brokerage, ctx=None, loop=None):
    for key in ao.get_account_numbers():
        account_numbers = ao.get_account_numbers(key)
        for account in account_numbers:
            obj: ally.Ally = ao.get_logged_in_objects(key)
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
    ao: Brokerage, action, stock, amount, price, time, DRY=True, ctx=None, loop=None, RETRY=False, account_retry=None
):
    print()
    print("==============================")
    print("Ally")
    print("==============================")
    print()
    action = action.lower()
    stock = [x.upper() for x in stock]
    amount = int(amount)
    # Set the action
    if type(price) is str and price.lower() == "market":
        price = ally.Order.Market()
    elif type(price) is float or type(price) is int:
        print(f"Limit order at: ${float(price)}")
        price = ally.Order.Limit(limpx=float(price))
    for s in stock:
        for key in ao.get_account_numbers():
            printAndDiscord(f"{key}: {action}ing {amount} of {s}", ctx, loop)
            for account in ao.get_account_numbers(key):
                if not RETRY:
                    obj: ally.Ally = ao.get_logged_in_objects(key)
                else:
                    obj: ally.Ally = ao
                    account = account_retry
                try:
                    # Create order
                    o = ally.Order.Order(
                        buysell=action, symbol=s, price=price, time=time, qty=amount, account=account
                    )
                    # Print order preview
                    print(str(o))
                    # Submit order
                    o.orderid
                    if not DRY:
                        obj.submit(o, preview=False)
                    else:
                        printAndDiscord(
                            f"{key}: Running in DRY mode. "
                            + f"Trasaction would've been: {action} {amount} of {s}",
                            ctx,
                            loop,
                        )
                    # Print order status
                    if o.orderid:
                        printAndDiscord(f"{key}: Order {o.orderid} submitted", ctx, loop)
                    else:
                        printAndDiscord(f"{key}: Order not submitted", ctx, loop)
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
                        if action == "sell":
                            printAndDiscord(ally_call_error, ctx, loop)
                        # If the message comes up while buying, then
                        # try again with a limit order
                        elif action == "buy" and not RETRY:
                            printAndDiscord(
                                f"{key}: Error placing market buy, trying again with limit order...",
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
                                # Run function again with limit order
                                ally_transaction(
                                    ao, action, s, amount, new_price, time, DRY, ctx, loop, True, account
                                )
                            except Exception as ex:
                                printAndDiscord(f"{key}: Failed to place limit order: {ex}", ctx, loop)
                        else:
                            printAndDiscord(f"{key}: Error placing limit order: {e}", ctx, loop)
                    elif type(price) is not str:
                        printAndDiscord(f"{key}: Error placing limit order: {e}", ctx, loop)
                    else:
                        printAndDiscord(f"{key}: Error submitting order: {e}", ctx, loop)
