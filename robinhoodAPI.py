# Nelson Dane
# Robinhood API

import os
import sys
import robin_stocks.robinhood as rh
from dotenv import load_dotenv

def robinhood_init():
    # Initialize .env file
    load_dotenv()
    # Import Robinhood account
    if not os.environ["ROBINHOOD_USERNAME"] or not os.environ["ROBINHOOD_PASSWORD"]:
        print("Error: Missing Robinhood credentials")
        sys.exit(1)
    RH_USERNAME = os.environ["ROBINHOOD_USERNAME"]
    RH_PASSWORD = os.environ["ROBINHOOD_PASSWORD"]
    # Log in to Robinhood account
    print("Logging in to Robinhood...")
    rh.login(RH_USERNAME, RH_PASSWORD)
    print("Logged in to Robinhood!")
    return rh

def robinhood_transaction(rh, action, stock, amount, price, time, DRY):
    print()
    print("==============================")
    print("Robinhood")
    print("==============================")
    print()
    if not DRY:
        try:
            # Buy Market order
            if action.lower == "buy":
                rh.order_buy_market(stock, amount)
                print(f"Bought {amount} of {stock} on Robinhood")
            # Sell Market order
            elif action.lower == "sell":
                rh.order_sell_market(stock, amount)
                print(f"Sold {amount} of {stock} on Robinhood")
            else:
                print("Error: Invalid action")
                sys.exit(1)
        except Exception as e:
            print(f'Error submitting order on Robinhood: {e}')
            #sys.exit(1)
    else:
        print(f"Running in DRY mode. Trasaction would've been: {action} {amount} of {stock} on Robinhood")