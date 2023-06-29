# Nelson Dane
# Schwab API

import asyncio
import os
import pprint
from time import sleep

from dotenv import load_dotenv
from schwab_api import Schwab
from helperAPI import Brokerage


def schwab_init(SCHWAB_EXTERNAL=None):
    # Initialize .env file
    load_dotenv()
    # Import Schwab account
    if not os.getenv("SCHWAB") and SCHWAB_EXTERNAL is None:
        print("Schwab not found, skipping...")
        return None
    accounts = os.environ["SCHWAB"].strip().split(",") if SCHWAB_EXTERNAL is None else SCHWAB_EXTERNAL.strip().split(",")
    # Log in to Schwab account
    print("Logging in to Schwab...")
    schwab_obj = Brokerage("Schwab")
    for account in accounts:
        index = accounts.index(account) + 1
        try:
            account = account.split(":")
            schwab = Schwab()
            schwab.login(
                username=account[0],
                password=account[1],
                totp_secret=None if account[2] == "NA" else account[2],
            )
            account_info = schwab.get_account_info()
            account_list = list(account_info.keys())
            print(f"The following Schwab accounts were found: {account_list}")
            print("Logged in to Schwab!")
            schwab_obj.loggedInObjects.append(schwab)
            for account in account_list:
                schwab_obj.add_account_number(f"Schwab {index}", account)
        except Exception as e:
            print(f"Error logging in to Schwab: {e}")
            return None
    return schwab_obj


def schwab_holdings(schwab_o, ctx=None, loop=None):
    print()
    print("==============================")
    print("Schwab Holdings")
    print("==============================")
    print()
    # Get holdings on each account
    schwab = schwab_o.loggedInObjects
    for obj in schwab:
        index = schwab.index(obj) + 1
        try:
            for account in list(obj.get_account_info().keys()):
                print(f"Holdings in Schwab {index} Account: {account}")
                if ctx and loop:
                    asyncio.ensure_future(
                        ctx.send(f"Holdings in Schwab {index}: {account}"), loop=loop
                    )
                holdings = obj.get_account_info()[account]["positions"]
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
            print(f"Schwab {index} {account}: Error getting holdings: {e}")
            if ctx and loop:
                asyncio.ensure_future(
                    ctx.send(f"Schwab {index} {account}: Error getting holdings: {e}"), loop=loop
                )


def schwab_transaction(
    schwab_o, action, stock, amount, price, time, DRY=True, ctx=None, loop=None
):
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
    schwab = schwab_o.loggedInObjects
    for obj in schwab:
        index = schwab.index(obj) + 1
        for account in list(obj.get_account_info().keys()):
            print(f"Schwab {index} Account: {account}")
            # If DRY is True, don't actually make the transaction
            if DRY:
                print("Running in DRY mode. No transactions will be made.")
                if ctx and loop:
                    asyncio.ensure_future(
                        ctx.send("Running in DRY mode. No transactions will be made."),
                        loop=loop,
                    )
            try:
                messages, success = obj.trade(
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
                            f"Schwab {index} account {account}: The order verification was "
                            + "successful"
                            if success
                            else "unsuccessful"
                        ),
                        loop=loop,
                    )
                    if not success:
                        asyncio.ensure_future(
                            ctx.send(
                                f"Schwab {index} account {account}: The order verification produced the following messages: "
                            ),
                            loop=loop,
                        )
                        asyncio.ensure_future(ctx.send(f"{messages}"), loop=loop)
            except Exception as e:
                print(f"Schwab {index} {account}: Error submitting order: {e}")
                if ctx and loop:
                    asyncio.ensure_future(
                        ctx.send(f"Schwab {index} {account}: Error submitting order: {e}"),
                        loop=loop,
                    )
                return None
            sleep(1)
            print()
