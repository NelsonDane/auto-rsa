# Nelson Dane
# Schwab API

import asyncio
import os
import pprint
from time import sleep

from dotenv import load_dotenv
from schwab_api import Schwab


def schwab_init():
    # Initialize .env file
    load_dotenv()
    # Import Schwab account
    if not os.getenv("SCHWAB_USERNAME") or not os.getenv("SCHWAB_PASSWORD"):
        print("Schwab not found, skipping...")
        return None
    SCHWAB_USERNAME = os.environ["SCHWAB_USERNAME"]
    SCHWAB_PASSWORD = os.environ["SCHWAB_PASSWORD"]
    SCHWAB_TOTP_SECRET = os.environ.get("SCHWAB_TOTP_SECRET")
    # Log in to Schwab account
    print("Logging in to Schwab...")
    try:
        schwab = Schwab()
        schwab.login(
            username=SCHWAB_USERNAME,
            password=SCHWAB_PASSWORD,
            totp_secret=SCHWAB_TOTP_SECRET,
        )
        account_info = schwab.get_account_info()
        print(f"The following Schwab accounts were found: {list(account_info.keys())}")
        print("Logged in to Schwab!")
        return schwab
    except Exception as e:
        print(f"Error logging in to Schwab: {e}")
        return None


def schwab_holdings(schwab, ctx=None, loop=None):
    # Make sure init didn't return None
    if schwab is None:
        print()
        print("Error: No Schwab account")
        return None
    print()
    print("==============================")
    print("Schwab Holdings")
    print("==============================")
    print()
    # Get holdings on each account
    try:
        for account in list(schwab.get_account_info().keys()):
            print(f"Holdings in Schwab Account: {account}")
            if ctx and loop:
                asyncio.ensure_future(
                    ctx.send(f"Holdings in Schwab: {account}"), loop=loop
                )
            holdings = schwab.get_account_info()[account]["positions"]
            for item in holdings:
                # Get symbol, market value, quantity, current price, and total holdings
                sym = item["symbol"]
                if sym == "":
                    sym = "Unknown"
                mv = round(float(item["market_value"]), 2)
                qty = float(item["quantity"])
                # Schwab doesn't return current price, so we have to calculate it
                if qty == 0:
                    current_price = 0
                else:
                    current_price = round(mv / qty, 2)
                message = f"{sym}: {qty} @ ${current_price} = ${mv}"
                print(message)
                if ctx and loop:
                    asyncio.ensure_future(ctx.send(message), loop=loop)
    except Exception as e:
        print(f"Schwab {account}: Error getting holdings: {e}")
        if ctx and loop:
            asyncio.ensure_future(
                ctx.send(f"Schwab {account}: Error getting holdings: {e}"), loop=loop
            )


def schwab_transaction(
    schwab, action, stock, amount, price, time, DRY=True, ctx=None, loop=None
):
    # Make sure init didn't return None
    if schwab is None:
        print("Error: No Schwab account")
        return None
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
    # Buy on each account
    for account in list(schwab.get_account_info().keys()):
        print(f"Schwab Account: {account}")
        # If DRY is True, don't actually make the transaction
        if DRY:
            print("Running in DRY mode. No transactions will be made.")
            if ctx and loop:
                asyncio.ensure_future(
                    ctx.send("Running in DRY mode. No transactions will be made."),
                    loop=loop,
                )
        try:
            messages, success = schwab.trade(
                ticker=stock,
                side=action,
                qty=amount,
                account_id=account,  # Replace with your account number
                dry_run=DRY,  # If dry_run=True, we won't place the order, we'll just verify it.
            )
            print(
                "The order verification was " + "successful"
                if success
                else "unsuccessful"
            )
            print("The order verification produced the following messages: ")
            pprint.pprint(messages)
            if ctx and loop:
                asyncio.ensure_future(
                    ctx.send(
                        f"Schwab account {account}: The order verification was "
                        + "successful"
                        if success
                        else "unsuccessful"
                    ),
                    loop=loop,
                )
                if not success:
                    asyncio.ensure_future(
                        ctx.send(
                            f"Schwab account {account}: The order verification produced the following messages: "
                        ),
                        loop=loop,
                    )
                    asyncio.ensure_future(ctx.send(f"{messages}"), loop=loop)
        except Exception as e:
            print(f"Schwab {account}: Error submitting order: {e}")
            if ctx and loop:
                asyncio.ensure_future(
                    ctx.send(f"Schwab {account}: Error submitting order: {e}"),
                    loop=loop,
                )
            return None
        sleep(1)
        print()
