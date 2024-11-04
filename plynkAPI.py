import asyncio
import os
import traceback

from dotenv import load_dotenv
from plynk_api import Plynk

from helperAPI import (
    Brokerage,
    getOTPCodeDiscord,
    maskString,
    printAndDiscord,
    printHoldings,
    stockOrder
)


def plynk_init(PLYNK_EXTERNAL=None, botObj=None, loop=None):
    # Initialize .env file
    load_dotenv()
    # Import Plynk account
    plynk_obj = Brokerage("Plynk")
    if not os.getenv("PLYNK") and PLYNK_EXTERNAL is None:
        print("Plynk not found, skipping...")
        return None
    plynk_creds = (
        os.environ["PLYNK"].strip().split(",")
        if PLYNK_EXTERNAL is None
        else PLYNK_EXTERNAL.strip().split(",")
    )

    # This is used by Plynk API get the OTP when needed
    def get_otp():
        if botObj is not None and loop is not None:
            # Sometimes codes take a long time to arrive
            timeout = 300  # 5 minutes
            otp_code = asyncio.run_coroutine_threadsafe(
                getOTPCodeDiscord(botObj, name, timeout=timeout, loop=loop),
                loop,
            ).result()
        else:
            otp_code = input("Please enter the OTP you received: ")
        if otp_code is None:
            raise Exception("No 2FA code found")
        return otp_code

    # Log in to Plynk account
    print("Logging in to Plynk...")
    for index, account in enumerate(plynk_creds):
        name = f"Plynk {index + 1}"
        try:
            account = account.split(":")
            plynk = Plynk(
                username=account[0],
                password=account[1],
                filename=f"{name}.pkl",
                path="./creds/"
            )
            plynk.login(otp_callback=get_otp)
            # Plynk only has one account
            plynk_obj.set_logged_in_object(name, plynk)
            account_number = plynk.get_account_number()
            plynk_obj.set_account_number(name, account_number)
            print(f"{name}: Found account {maskString(account_number)}")
            cash = plynk.get_account_total(account_number)
            plynk_obj.set_account_totals(name, account_number, cash)
        except Exception as e:
            print(f"Error logging in to Plynk: {e}")
            print(traceback.format_exc())
            continue
    print("Logged in to Plynk!")
    return plynk_obj


def plynk_holdings(plynk_obj: Brokerage, loop=None):
    for key in plynk_obj.get_account_numbers():
        for account in plynk_obj.get_account_numbers(key):
            plynk: Plynk = plynk_obj.get_logged_in_objects(key)
            try:
                # Get account holdings
                holdings = plynk.get_account_holdings(account)
                for holding in holdings:
                    symbol = holding['security']['symbol']
                    if symbol is None:
                        symbol = 'None'
                    quantity = holding['securityCount']
                    price = holding['currentValue']
                    if price is not None:
                        stock_details = plynk.get_stock_details(symbol)
                        price = stock_details['securityDetails']['lastPrice']
                    else:
                        price = 0
                    plynk_obj.set_holdings(key, account, symbol, quantity, price)
            except Exception as e:
                printAndDiscord(f"{key} {account}: Error getting holdings: {e}")
                print(traceback.format_exc())
                continue
    printHoldings(plynk_obj, loop)


def plynk_transaction(plynk_obj: Brokerage, order_obj: stockOrder, loop=None):
    raise NotImplementedError("Not implemented yet, ya bloody bloak!")

    print()
    print("==============================")
    print("Plynk")
    print("==============================")
    print()

    for stock in order_obj.get_stocks():
        for key in plynk_obj.get_account_numbers():
            printAndDiscord(
                f"{key}: {order_obj.get_action()}ing {order_obj.get_amount()} of {stock}...",
                loop,
            )
            for account in plynk_obj.get_account_numbers(key):
                plynk: Plynk = plynk_obj.get_logged_in_objects(key)
                print_account = maskString(account)
                try:
                    order = plynk.place_order(
                        symbol=stock,
                        quantity=order_obj.get_amount(),
                        side=order_obj.get_action(),
                        order_type="market",
                        time_in_force="day",
                        is_dry_run=order_obj.get_dry(),
                    )
                    if order["success"] is True:
                        order = "Success"
                    printAndDiscord(
                        f"{key}: {order_obj.get_action()} {order_obj.get_amount()} of {stock} in {print_account}: {order}",
                        loop,
                    )
                except Exception as e:
                    printAndDiscord(f"{print_account}: Error placing order: {e}", loop)
                    traceback.print_exc()
                    continue
