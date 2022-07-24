# Nelson Dane
# Schwab API

import os
import sys
import pprint
from time import sleep
from schwab_api import Schwab 
from dotenv import load_dotenv

def schwab_init():
    # Initialize .env file
    load_dotenv()
    # Import Schwab account
    if not os.environ["SCHWAB_USERNAME"] or not os.environ["SCHWAB_PASSWORD"] or not os.environ["SCHWAB_TOTP_SECRET"]:
        print("Error: Missing Schwab credentials")
        sys.exit(1)
    SCHWAB_USERNAME = os.environ["SCHWAB_USERNAME"]
    SCHWAB_PASSWORD = os.environ["SCHWAB_PASSWORD"]
    SCHWAB_TOTP_SECRET = os.environ["SCHWAB_TOTP_SECRET"]
    # Log in to Schwab account
    print("Logging in to Schwab...")
    schwab = Schwab()
    try:
        schwab.login(username=SCHWAB_USERNAME, password=SCHWAB_PASSWORD, totp_secret=SCHWAB_TOTP_SECRET)
    except Exception as e:
        print(f'Error logging in to Schwab: {e}')
        sys.exit(1)
    account_info = schwab.get_account_info()
    #pprint.pprint(account_info)
    print(f"The following Schwab accounts were found: {list(account_info.keys())}")
    print("Logged in to Schwab!")
    return schwab

def schwab_transaction(schwab, action, stock, amount, price, time, DRY):
    print()
    print("==============================")
    print("Schwab")
    print("==============================")
    print()
    # Get correct capitalization for action
    if action.lower() == "buy":
        action = "Buy"
    elif action.lower() == "sell":
        action = "Sell"
    stock = stock.upper()
    # Buy on each account
    for account in list(schwab.get_account_info().keys()):
        print(f"Schwab Account: {account}")
        # If DRY is True, don't actually make the transaction
        if DRY:
            print("Running in DRY mode. No transactions will be made.")
            try:
                messages, success = schwab.trade(
                    ticker=stock, 
                    side=action,
                    qty=amount,
                    account_id=account, # Replace with your account number
                    dry_run=True # If dry_run=True, we won't place the order, we'll just verify it.
                )
                print("The order verification was " + "successful" if success else "unsuccessful")
                print("The order verification produced the following messages: ")
                pprint.pprint(messages)
            except Exception as e:
                print(f'Error submitting order on Schwab: {e}')
                sys.exit(1)
        # If DRY is False, make the transaction
        else:
            try:
                messages, success = schwab.trade(
                    ticker=stock, 
                    side=action,
                    qty=amount,
                    account_id=account, # Replace with your account number
                    dry_run=False # If dry_run=True, we won't place the order, we'll just verify it.
                )
                print("The order was " + "successful" if success else "unsuccessful")
                print("The order produced the following messages: ")
                pprint.pprint(messages)
            except Exception as e:
                print(f'Error submitting order on Schwab account {account}: {e}')
                #sys.exit(1)
        sleep(1)
        print()

