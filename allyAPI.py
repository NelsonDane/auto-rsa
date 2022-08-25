# Nelson Dane
# Ally API

import os
import sys
import ally
from dotenv import load_dotenv

# Initialize Ally
def ally_init():
    # Initialize .env file
    load_dotenv()
    # Import Ally account
    if not os.getenv("ALLY_CONSUMER_KEY") or not os.getenv("ALLY_CONSUMER_SECRET") or not os.getenv("ALLY_OAUTH_TOKEN") or not os.getenv("ALLY_OAUTH_SECRET") or not os.getenv("ALLY_ACCOUNT_NBR"):
        print("Ally not found, skipping...")
        return None
    ALLY_CONSUMER_KEY = os.environ["ALLY_CONSUMER_KEY"]
    ALLY_CONSUMER_SECRET = os.environ["ALLY_CONSUMER_SECRET"]
    ALLY_OAUTH_TOKEN = os.environ["ALLY_OAUTH_TOKEN"]
    ALLY_OAUTH_SECRET = os.environ["ALLY_OAUTH_SECRET"]
    ALLY_ACCOUNT_NBR = os.environ["ALLY_ACCOUNT_NBR"]

    # Initialize Ally account
    try:
        a = ally.Ally()
        print("Logging in to Ally...")
        an = a.balances()
        account_numbers = an['account'].values
        print(f"Ally account numbers: {account_numbers}")
    except Exception as e:
        print(f'Error logging in to Ally: {e}')
        return None
    print("Logged in to Ally!")
    return a

# Function to get the current account holdings
async def ally_holdings(a, ctx=None):
    print("==============================")
    print("Ally Holdings")
    print("==============================")
    print()
    # Make sure init didn't return None
    if a is None:
        print("Error: No Ally account")
        return None
    try:
        # Get account holdings
        ab = a.balances()
        a_value = ab['accountvalue'].values
        for value in a_value:
            print(f"Ally account value: ${value}")
            if ctx:
                await ctx.send(f"Ally account value: ${value}")
        # Print account stock holdings
        ah = a.holdings()
        account_symbols = (ah['sym'].values).tolist()
        qty = (ah['qty'].values).tolist()
        current_price = (ah['marketvalue'].values).tolist()
        print("Ally account symbols:")
        if ctx:
            await ctx.send("Ally account symbols:")
        for symbol in account_symbols:
            # Set index for easy use
            i = account_symbols.index(symbol)
            print(f"{symbol}: {float(qty[i])} @ ${round(float(current_price[i]), 2)} = ${round(float(qty[i]) * float(current_price[i]), 2)}")
            if ctx:
                await ctx.send(f"{symbol}: {float(qty[i])} @ ${round(float(current_price[i]), 2)} = ${round(float(qty[i]) * float(current_price[i]), 2)}")
    except Exception as e:
        print(f'Error getting account holdings on Ally: {e}')
        if ctx:
            await ctx.send(f'Error getting account holdings on Ally: {e}')

# Function to buy/sell stock on Ally
async def ally_transaction(a, action, stock, amount, price, time, DRY=True, ctx=None):
    print()
    print("==============================")
    print("Ally")
    print("==============================")
    print()
    action = action.lower()
    stock = stock.upper()
    amount = int(amount)
    # Make sure init didn't return None
    if a is None:
        print("Error: No Ally account")
        return None
    # Set the action
    if type(price) is str and price.lower() == "market":
        price = ally.Order.Market()
    elif type(price) is float or type(price) is int:
        price = ally.Order.Limit(limpx=float(price))
    try:
        # Create order
        o = ally.Order.Order(
            buysell = action,
            symbol = stock,
            price = price,
            time = time,
            qty = amount
        )
        # Print order preview
        print(str(o))
        # Submit order
        o.orderid
        if not DRY:
            a.submit(o, preview=False)
        else:
            print(f"Running in DRY mode. Trasaction would've been: {action} {amount} of {stock} on Ally")
            if ctx:
                await ctx.send(f"Running in DRY mode. Trasaction would've been: {action} {amount} of {stock} on Ally")
        if o.orderid:
            print(f"Order {o.orderid} submitted on Ally")
            if ctx:
                await ctx.send(f"Order {o.orderid} submitted on Ally")
        else:
            print(f"Order not submitted on Ally")
            if ctx:
                await ctx.send(f"Order not submitted on Ally")
    except Exception as e:
        ally_call_error = "Error: For your security, certain symbols may only be traded by speaking to an Ally Invest registered representative. Please call 1-855-880-2559 if you need further assistance with this order."
        if "500 server error: internal server error for url:" in str(e).lower():
            # If selling too soon, then an error is thrown
            if action == "sell":
                print(ally_call_error)
                if ctx:
                    await ctx.send(ally_call_error)
            # If the message comes up while buying, then try again with a limmit order
            elif action == "buy":
                print(f"Error placing market buy on Ally, trying again with limit order...")
                if ctx:
                    await ctx.send(f"Error placing market buy on Ally, trying again with limit order...")
                # Need to get stock price (compare bid, ask, and last)
                try:
                    # Get stock values
                    quotes = a.quote(
                    stock,
                    fields=['bid','ask','last'],
                    )
                    # Add 1 cent to the highest value of the 3 above
                    new_price = (max([float(quotes['last']), float(quotes['bid']), float(quotes['ask'])])) + 0.01
                    # Run function again with limit order
                    await ally_transaction(a, action, stock, amount, new_price, time, DRY, ctx)
                except Exception as e:
                    print(f"Failed to place limit order on Ally: {e}")
                    if ctx:
                        await ctx.send(f"Failed to place limit order on Ally: {e}")
        elif type(price) is not str:
            print(f"Error placing limit order on Ally: {e}")
            if ctx:
                await ctx.send(f"Error placing limit order on Ally: {e}")
        else:
            print(f'Error submitting order on Ally: {e}')
            if ctx:
                await ctx.send(f'Error submitting order on Ally: {e}')