# Nelson Dane
# Schwab API

import os
import pprint
from time import sleep

from dotenv import load_dotenv
from schwab_api import Schwab

from helperAPI import Brokerage, printAndDiscord, printHoldings, stockOrder


def schwab_init(SCHWAB_EXTERNAL=None):
    # Initialize .env file
    load_dotenv()
    # Import Schwab account
    if not os.getenv("SCHWAB") and SCHWAB_EXTERNAL is None:
        print("Schwab not found, skipping...")
        return None
    accounts = (
        os.environ["SCHWAB"].strip().split(",")
        if SCHWAB_EXTERNAL is None
        else SCHWAB_EXTERNAL.strip().split(",")
    )
    # Log in to Schwab account
    print("Logging in to Schwab...")
    schwab_obj = Brokerage("Schwab")
    for account in accounts:
        index = accounts.index(account) + 1
        name = f"Schwab {index}"
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
            schwab_obj.set_logged_in_object(name, schwab)
            for account in account_list:
                schwab_obj.set_account_number(name, account)
                schwab_obj.set_account_totals(
                    name, account, account_info[account]["account_value"]
                )
        except Exception as e:
            print(f"Error logging in to Schwab: {e}")
            return None
    return schwab_obj


def schwab_holdings(schwab_o: Brokerage, loop=None):
    # Get holdings on each account
    for key in schwab_o.get_account_numbers():
        for account in schwab_o.get_account_numbers(key):
            obj: Schwab = schwab_o.get_logged_in_objects(key)
            try:
                holdings = obj.get_account_info()[account]["positions"]
                for item in holdings:
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
                    schwab_o.set_holdings(key, account, sym, qty, current_price)
            except Exception as e:
                printAndDiscord(f"{key} {account}: Error getting holdings: {e}", loop)
                continue
        printHoldings(schwab_o, loop)


def schwab_transaction(schwab_o: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Schwab")
    print("==============================")
    print()
    # Buy on each account
    for s in orderObj.get_stocks():
        for key in schwab_o.get_account_numbers():
            printAndDiscord(
                f"{key} {orderObj.get_action()}ing {orderObj.get_amount()} {s} @ {orderObj.get_price()}",
                loop,
            )
            for account in schwab_o.get_account_numbers(key):
                obj: Schwab = schwab_o.get_logged_in_objects(key)
                print(f"{key} Account: {account}")
                # If DRY is True, don't actually make the transaction
                if orderObj.get_dry():
                    printAndDiscord(
                        "Running in DRY mode. No transactions will be made.", loop
                    )
                try:
                    messages, success = obj.trade(
                        ticker=s,
                        side=orderObj.get_action().capitalize(),
                        qty=orderObj.get_amount(),
                        account_id=account,
                        dry_run=orderObj.get_dry(),
                    )
                    print("The order verification produced the following messages: ")
                    pprint.pprint(messages)
                    printAndDiscord(
                        f"{key} account {account}: The order verification was "
                        + "successful"
                        if success
                        else "unsuccessful",
                        loop,
                    )
                    if not success:
                        printAndDiscord(
                            f"{key} account {account}: The order verification produced the following messages: {messages}",
                            loop,
                        )
                except Exception as e:
                    printAndDiscord(
                        f"{key} {account}: Error submitting order: {e}", loop
                    )
                    continue
                sleep(1)
                print()
