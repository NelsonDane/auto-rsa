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
        sys.exit(1)
    ALLY_CONSUMER_KEY = os.environ["ALLY_CONSUMER_KEY"]
    ALLY_CONSUMER_SECRET = os.environ["ALLY_CONSUMER_SECRET"]
    ALLY_OAUTH_TOKEN = os.environ["ALLY_OAUTH_TOKEN"]
    ALLY_OAUTH_SECRET = os.environ["ALLY_OAUTH_SECRET"]
    ALLY_ACCOUNT_NBR = os.environ["ALLY_ACCOUNT_NBR"]

    # Initialize Ally account
    a = ally.Ally()
    try:
        print("Logging in to Ally...")
        an = a.balances()
        account_numbers = an['account'].values
        print(f"Ally account numbers: {account_numbers}")
    except Exception as e:
        print(f'Error logging in to Ally: {e}')
        sys.exit(1)
    print("Logged in to Ally!")
    return a

# Function to buy/sell stock on Ally
def ally_transaction(a, action, stock, amount, price, time, DRY):
    print()
    print("==============================")
    print("Ally")
    print("==============================")
    print()
    try:
        # # Initialize Ally account
        # a = ally.Ally()
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
            a.submit(o)
        else:
            print(f"Running in DRY mode. Trasaction would've been: {action} {amount} of {stock} on Ally")
        if o.orderid:
            print(f"Order {o.orderid} submitted on Ally")
        else:
            print(f"Order {o.orderid} not submitted on Ally")
    except Exception as e:
        print(f'Error submitting order on Ally: {e}')
        #sys.exit(1)