# Nelson Dane
# Schwab API

import os
import pprint
from time import sleep
from schwab_api import Schwab 
from dotenv import load_dotenv

def schwab_init():
    # Initialize .env file
    load_dotenv()
    # Import Schwab account
    if not os.getenv("SCHWAB_USERNAME") or not os.getenv("SCHWAB_PASSWORD") or not os.getenv("SCHWAB_TOTP_SECRET"):
        print("Schwab not found, skipping...")
        return None
    SCHWAB_USERNAME = os.environ["SCHWAB_USERNAME"]
    SCHWAB_PASSWORD = os.environ["SCHWAB_PASSWORD"]
    SCHWAB_TOTP_SECRET = os.environ["SCHWAB_TOTP_SECRET"]
    # Log in to Schwab account
    print("Logging in to Schwab...")
    try:
        schwab = Schwab()
        schwab.login(username=SCHWAB_USERNAME, password=SCHWAB_PASSWORD, totp_secret=SCHWAB_TOTP_SECRET)
        account_info = schwab.get_account_info()
        print(f"The following Schwab accounts were found: {list(account_info.keys())}")
        print("Logged in to Schwab!")
        return schwab
    except Exception as e:
        print(f'Error logging in to Schwab: {e}')
        return None

async def schwab_holdings(schwab, ctx=None):
    print()
    print("==============================")
    print("Schwab Holdings")
    print("==============================")
    print()
    # Make sure init didn't return None
    if schwab is None:
        print("Error: No Schwab account")
        return None
    # Get holdings on each account
    try:
        for account in list(schwab.get_account_info().keys()):
            print(f"Holdings in Schwab: {account}")
            if ctx:
                await ctx.send(f"Holdings in Schwab: {account}")
            holdings = schwab.get_account_info()[account]['positions']
            for item in holdings:
                sym = item['symbol']
                if sym == "":
                    sym = "Unknown"
                qty = item['quantity']
                print(f"{sym}: {qty}")
                if ctx:
                    await ctx.send(f"{sym}: {qty}")
    except Exception as e:
        print(f'Error getting holdings on Schwab {account}: {e}')
        if ctx:
            await ctx.send(f'Error getting holdings on Schwab {account}: {e}')
    
async def schwab_transaction(schwab, action, stock, amount, price, time, DRY=True, ctx=None):
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
    amount = int(amount)
    # Make sure init didn't return None
    if schwab is None:
        print("Error: No Schwab account")
        return None
    # Buy on each account
    for account in list(schwab.get_account_info().keys()):
        print(f"Schwab Account: {account}")
        # If DRY is True, don't actually make the transaction
        if DRY:
            print("Running in DRY mode. No transactions will be made.")
            if ctx:
                await ctx.send(f"Running in DRY mode. No transactions will be made.")
        try:
            messages, success = schwab.trade(
                ticker=stock, 
                side=action,
                qty=amount,
                account_id=account, # Replace with your account number
                dry_run=DRY # If dry_run=True, we won't place the order, we'll just verify it.
            )
            print("The order verification was " + "successful" if success else "unsuccessful")
            print("The order verification produced the following messages: ")
            pprint.pprint(messages)
            if ctx:
                await ctx.send(f"The order verification was " + "successful" if success else "unsuccessful")
                await ctx.send(f"The order verification produced the following messages: ")
                await ctx.send(f"{messages}")
        except Exception as e:
            print(f'Error submitting order on Schwab: {e}')
            if ctx:
                await ctx.send(f'Error submitting order on Schwab: {e}')
            return None
        sleep(1)
        print()

