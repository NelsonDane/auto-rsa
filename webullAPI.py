# Nelson Dane
# Webull API

import os
import sys
from time import sleep
from webull import webull
from dotenv import load_dotenv

def webull_init():
    # Initialize .env file
    load_dotenv()
    # Import Webull account
    if not os.environ["WEBULL_USERNAME"] or not os.environ["WEBULL_PASSWORD"]:
        print("Error: Missing Webull credentials")
        sys.exit(1)
    WEBULL_USERNAME = os.environ["WEBULL_USERNAME"]
    WEBULL_PASSWORD = os.environ["WEBULL_PASSWORD"]
    # Log in to Webull account
    print("Logging in to Webull...")
    wb = webull()
    try:
        wb.login(WEBULL_USERNAME, WEBULL_PASSWORD)
    except Exception as e:
        print(f'Error logging in to Webull: {e}')
        sys.exit(1)
    print("Logged in to Webull!")
    return wb

def webull_transaction(webull, action, stock, amount, price, time, DRY):
    print()
    print("==============================")
    print("Webull")
    print("==============================")
    print()
    # Get the trade PIN
    if not os.environ["WEBULL_TRADE_PIN"]:
        print("Error: Missing Webull trade PIN")
        sys.exit(1)
    WEBULL_TRADE_PIN = os.environ["WEBULL_TRADE_PIN"]
    webull.get_trade_token(WEBULL_TRADE_PIN)
    if amount == 1 and action.upper() == "BUY":
        buy100 = True
    else:
        buy100 = False
    if not DRY:
        # Because webull doesn't let you buy 1 share of a stock, we need to buy multiple shares and then sell them all but one
        if buy100:
            try:
                # Buy 100 shares
                webull.place_order(stock=stock, action="BUY", quant=100)
                print(f"Bought {amount} of {stock} on Webull")
            except Exception as e:
                print(f'Error buying 100 shares of {stock} order on Webull: {e}')
                sys.exit(1)
            # Sell 99 shares
            try:
                webull.place_order(stock=stock, action="SELL", quant=99)
                print(f"Sold 99 shares of {stock} on Webull")
            except Exception as e:
                print(f'Error selling 99 shares of {stock} order on Webull: {e}')
                sys.exit(1)
        try:
            # Buy Market order
            if action.upper() == "BUY":
                webull.place_order(stock=stock, action=action.upper(), quant=amount)
                print(f"Bought {amount} of {stock} on Webull")
            # Sell Market order
            elif action.upper() == "SELL":
                webull.place_order(stock=stock, action=action.upper(), quant=amount)
                print(f"Sold {amount} of {stock} on Webull")
            else:
                print("Error: Invalid action")
                sys.exit(1)
        except Exception as e:
            print(f'Error submitting order on Webull: {e}')
            #sys.exit(1)
    else:
        if buy100:
            print(f"Running in DRY mode. Trasaction would've been: Buy 100 of {stock} on Webull, then Sell 99 of {stock} on Webull")
        else:
            print(f"Running in DRY mode. Trasaction would've been: {action} {amount} of {stock} on Webull")