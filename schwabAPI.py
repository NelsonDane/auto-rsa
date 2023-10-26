# Nelson Dane
# Schwab API

import os
import psutil
from time import sleep

from dotenv import load_dotenv
from helperAPI import Brokerage, printAndDiscord, printHoldings, stockOrder


# Check for Schwab Beta
load_dotenv()
if os.getenv("SCHWAB_BETA", "").lower() == "true":
    from schwab_api2 import Schwab
    print("Using Schwab Beta API")
    SCHWAB_BETA = True
else:
    from schwab_api import Schwab
    SCHWAB_BETA = False


def check_playwright():
    processes = psutil.process_iter()
    for process in processes:
        try:
            # Get the process name and command line arguments
            name = process.name()
            cmdline = process.cmdline()

            # Check if the process is a Playwright process
            if "playwright" in name or "playwright" in cmdline:
                print("Terminating Playwright process:", name, cmdline)
                process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass


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
        obj: Schwab = schwab_o.get_logged_in_objects(key)
        for account in schwab_o.get_account_numbers(key):
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
        printHoldings(schwab_o, loop)
        if SCHWAB_BETA:
            print(f"Closing session for {key}")
            obj.close_session()
            check_playwright()


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
            obj: Schwab = schwab_o.get_logged_in_objects(key)
            for account in schwab_o.get_account_numbers(key):
                print(f"{key} Account: {account}")
                # If DRY is True, don't actually make the transaction
                if orderObj.get_dry():
                    printAndDiscord(
                        "Running in DRY mode. No transactions will be made.", loop
                    )
                try:
                    if SCHWAB_BETA:
                        # Schwab Beta has different parameters
                        messages, success = obj.trade(
                            ticker=s,
                            action=orderObj.get_action().capitalize(),
                            qty=orderObj.get_amount(),
                            order_type="Market",
                            account_id=str(account),
                            dry_run=orderObj.get_dry(),
                        )
                    else:
                        messages, success = obj.trade(
                        ticker=s,
                        side=orderObj.get_action().capitalize(),
                        qty=orderObj.get_amount(),
                        account_id=account,
                        dry_run=orderObj.get_dry(),
                    )
                    printAndDiscord(
                        f"{key} account {account}: The order verification was "
                        + "successful"
                        if success
                        else "unsuccessful",
                        loop,
                    )
                    if not success:
                        if SCHWAB_BETA:
                            messages = messages["order_messages"]
                        else:
                            if len(messages) > 1 and "security is deficient" in messages[1]:
                                printAndDiscord(
                                    f"Error: {messages[1]}. If this persists, please run with SCHWAB_BETA=True in .env",
                                    loop,
                                )
                                continue
                        printAndDiscord(
                            f"{key} account {account}: The order verification produced the following messages: {messages}",
                            loop,
                        )
                except Exception as e:
                    printAndDiscord(
                        f"{key} {account}: Error submitting order: {e}", loop
                    )
                sleep(1)
            if SCHWAB_BETA:
                print(f"Closing session for {key}")
                obj.close_session()
                check_playwright()
