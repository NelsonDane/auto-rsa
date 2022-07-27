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
    if not os.environ["ALLY_CONSUMER_KEY"] or not os.environ["ALLY_CONSUMER_SECRET"] or not os.environ["ALLY_OAUTH_TOKEN"] or not os.environ["ALLY_OAUTH_SECRET"] or not os.environ["ALLY_ACCOUNT_NBR"]:
        print("Error: Missing Ally credentials")
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
    try:
        # Create order
        o = ally.Order.Order(
            buysell = action,
            symbol = stock,
            price = ally.Order.Market(),
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
        print(f'Error submitting order on Ally: {e}')
        if ctx:
            await ctx.send(f'Error submitting order on Ally: {e}')