# Nelson Dane
# Ally API

import os
import traceback

import ally
from dotenv import load_dotenv

from helperAPI import Brokerage, printAndDiscord


# Initialize Ally
def ally_init(ALLY_EXTERNAL=None):
    # Initialize .env file
    load_dotenv()
    # Import Ally account
    if not os.getenv("ALLY") and ALLY_EXTERNAL is None:
        print("Ally not found, skipping...")
        return None
    accounts = (
        os.environ["ALLY"].strip().split(",")
        if ALLY_EXTERNAL is None
        else ALLY_EXTERNAL.strip().split(",")
    )
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
        try:
            a = ally.Ally(params_list[index - 1])
            print(f"Logging in to Ally {index}...")
            an = a.balances()
            account_numbers = an["account"].values
            print(f"Ally {index} account numbers: {account_numbers}")
            ally_obj.loggedInObjects.append(a)
            for an in account_numbers:
                ally_obj.add_account_number(f"Ally {index}", an)
        except Exception as e:
            print(f"Ally {index}: Error logging in: {e}")
            traceback.print_exc()
            return None
        print("Logged in to Ally!")
    return ally_obj


# Function to get the current account holdings
def ally_holdings(ao, ctx=None, loop=None):
    print("==============================")
    print("Ally Holdings")
    print("==============================")
    print()
    a = ao.loggedInObjects
    for obj in a:
        index = a.index(obj) + 1
        try:
            # Get account holdings
            ab = obj.balances()
            a_value = ab["accountvalue"].values
            for value in a_value:
                printAndDiscord(f"Ally {index} account value: ${value}", ctx, loop)
            # Print account stock holdings
            ah = obj.holdings()
            # Test if holdings is empty. Supposedly len and index are faster than .empty
            if len(ah.index) == 0:
                printAndDiscord(f"Ally {index}: No holdings found", ctx, loop)
            else:
                account_symbols = (ah["sym"].values).tolist()
                qty = (ah["qty"].values).tolist()
                current_price = (ah["marketvalue"].values).tolist()
                printAndDiscord(f"Ally {index} account symbols:", ctx, loop)
                for symbol in account_symbols:
                    # Set index for easy use
                    i = account_symbols.index(symbol)
                    printAndDiscord(
                        f"{symbol}: {float(qty[i])} @ ${round(float(current_price[i]), 2)} "
                        + f"= ${round(float(qty[i]) * float(current_price[i]), 2)}",
                        ctx,
                        loop,
                    )
        except Exception as e:
            printAndDiscord(f"Ally {index}: Error getting account holdings: {e}", ctx, loop)


# Function to buy/sell stock on Ally
def ally_transaction(
    ao, action, stock, amount, price, time, DRY=True, ctx=None, loop=None, index=None
):
    print()
    print("==============================")
    print("Ally")
    print("==============================")
    print()
    action = action.lower()
    stock = stock.upper()
    amount = int(amount)
    # Set the action
    if type(price) is str and price.lower() == "market":
        price = ally.Order.Market()
    elif type(price) is float or type(price) is int:
        price = ally.Order.Limit(limpx=float(price))
    # If doing a retry, ao is a list
    if type(ao) is not list:
        a = ao.loggedInObjects
    else:
        a = ao
    for obj in a:
        if index is None:
            index = a.index(obj) + 1
        try:
            # Create order
            o = ally.Order.Order(buysell=action, symbol=stock, price=price, time=time, qty=amount)
            # Print order preview
            print(str(o))
            # Submit order
            o.orderid
            if not DRY:
                obj.submit(o, preview=False)
            else:
                printAndDiscord(
                    f"Ally {index}: Running in DRY mode. "
                    + f"Trasaction would've been: {action} {amount} of {stock}",
                    ctx,
                    loop,
                )
            # Print order status
            if o.orderid:
                printAndDiscord(f"Ally {index}: Order {o.orderid} submitted", ctx, loop)
            else:
                printAndDiscord(f"Ally {index}: Order not submitted", ctx, loop)
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
                # If the message comes up while buying, then try again with a limit order
                elif action == "buy":
                    printAndDiscord(
                        f"Ally {index}: Error placing market buy, trying again with limit order...",
                        ctx,
                        loop,
                    )
                    # Need to get stock price (compare bid, ask, and last)
                    try:
                        # Get stock values
                        quotes = obj.quote(
                            stock,
                            fields=["bid", "ask", "last"],
                        )
                        # Add 1 cent to the highest value of the 3 above
                        new_price = (
                            max(
                                [
                                    float(quotes["last"]),
                                    float(quotes["bid"]),
                                    float(quotes["ask"]),
                                ]
                            )
                        ) + 0.01
                        # Run function again with limit order
                        ally_transaction(
                            obj, action, stock, amount, new_price, time, DRY, ctx, loop, index
                        )
                    except Exception as e:
                        printAndDiscord(
                            f"Ally {index}: Failed to place limit order: {e}", ctx, loop
                        )
            elif type(price) is not str:
                printAndDiscord(f"Ally {index}: Error placing limit order: {e}", ctx, loop)
            else:
                printAndDiscord(f"Ally {index}: Error submitting order: {e}", ctx, loop)
