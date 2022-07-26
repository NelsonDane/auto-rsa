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
        return None
    WEBULL_USERNAME = os.environ["WEBULL_USERNAME"]
    WEBULL_PASSWORD = os.environ["WEBULL_PASSWORD"]
    # Log in to Webull account
    print("Logging in to Webull...")
    wb = webull()
    try:
        wb.login(WEBULL_USERNAME, WEBULL_PASSWORD)
    except Exception as e:
        print(f'Error logging in to Webull: {e}')
        return None
    print("Logged in to Webull!")
    return wb

def webull_transaction(webull, action, stock, amount, price, time, DRY):
    print()
    print("==============================")
    print("Webull")
    print("==============================")
    print()
    action = action.upper()
    stock = stock.upper()
    # Get the trade PIN
    if not os.environ["WEBULL_TRADE_PIN"]:
        print("Error: Missing Webull trade PIN")
        return None
    WEBULL_TRADE_PIN = os.environ["WEBULL_TRADE_PIN"]
    webull.get_trade_token(WEBULL_TRADE_PIN)
    if amount == 1 and action == "BUY":
        buy100 = True
    else:
        buy100 = False
    if not DRY:
        # Because webull doesn't let you buy 1 share of a stock, we need to buy multiple shares and then sell them all but one
        if buy100:
            # Buy 100 shares
            try:
                webull.place_order(stock=stock, action="BUY", quant=100)
                print(f"Bought {amount} of {stock} on Webull")
            except Exception as e:
                print(f'Error buying 100 shares of {stock} order on Webull: {e}')
                return None
            # Sell 99 shares
            sleep(5)
            try:
                webull.place_order(stock=stock, action="SELL", quant=99)
                print(f"Sold 99 shares of {stock} on Webull")
            except Exception as e:
                print(f'Error selling 99 shares of {stock} order on Webull: {e}')
                return None
        try:
            # Buy Market order
            if action == "BUY":
                webull.place_order(stock=stock, action=action.upper(), quant=amount)
                print(f"Bought {amount} of {stock} on Webull")
            # Sell Market order
            elif action == "SELL":
                webull.place_order(stock=stock, action=action.upper(), quant=amount)
                print(f"Sold {amount} of {stock} on Webull")
            else:
                print("Error: Invalid action")
                return None
        except Exception as e:
            print(f'Error submitting order on Webull: {e}')
            return None
    else:
        if buy100:
            print(f"Running in DRY mode. Trasaction would've been: Buy 100 of {stock} on Webull, then Sell 99 of {stock} on Webull")
        else:
            print(f"Running in DRY mode. Trasaction would've been: {action} {amount} of {stock} on Webull")