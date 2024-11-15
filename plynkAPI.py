import asyncio
import math
import os
import traceback

from time import sleep
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
                old_amount = order_obj.get_amount()
                original_action = order_obj.get_action()
                should_dance = False
                stock_price = plynk.get_stock_price(stock)
                if stock_price < 1.00:
                    need_buy = 1.00/stock_price
                    need_buy = math.ceil(need_buy) + 1  # Round up to nearest whole number + 1 to ensure order will be above 1.00
                    should_dance = True
                    print(
                        f"Buying {need_buy} then selling {need_buy - 1} of {stock}"
                    )
                try:
                    if should_dance and order_obj.get_action() == "buy":
                        order_obj.set_amount(need_buy)
                        if not order_obj.get_dry():
                            order = plynk.place_order_quantity(
                                account_number = account,
                                ticker=stock,
                                quantity=order_obj.get_amount(),
                                side=order_obj.get_action(),
                                price="market",
                            )
                            print(order)
                            if order["messages"].get('status', None) == 'SUCCESSFUL':
                                printAndDiscord(
                                    f"{key}: {order_obj.get_action()} {order_obj.get_amount()} of {stock} in {print_account}: Success",
                                    loop,
                                )
                            else:
                                raise Exception(f"Error buying {need_buy} of {stock}")
                        else:
                            printAndDiscord(
                                f"{key} {print_account}: Running in DRY mode. Transaction would've been: {order_obj.get_action()} {order_obj.get_amount()} of {stock}",
                                loop,
                            )
                        order_obj.set_amount(need_buy - 1)
                        order_obj.set_action("sell")
                        if not order_obj.get_dry():
                            sleep(1)
                            order = plynk.place_order_quantity(
                                account_number = account,
                                ticker=stock,
                                quantity=order_obj.get_amount(),
                                side=order_obj.get_action(),
                                price="market",
                            )
                            if order["messages"].get('status', None) == 'SUCCESSFUL':
                                printAndDiscord(
                                    f"{key}: {order_obj.get_action()} {order_obj.get_amount()} of {stock} in {print_account}: Success",
                                    loop,
                                )
                            else:
                                raise Exception(
                                    f"Error selling {need_buy - old_amount} of {stock}"
                                )
                        else:
                            printAndDiscord(
                                f"{key} {print_account}: Running in DRY mode. Transaction would've been: {order_obj.get_action()} {order_obj.get_amount()} of {stock}",
                                loop,
                            )
                               
                    else:
                        if not order_obj.get_dry():  
                            try:
                                order = plynk.place_order_quantity(
                                    account_number = account,
                                    ticker=stock,
                                    quantity=order_obj.get_amount(),
                                    side=order_obj.get_action(),
                                    price="market",
                                )
                                if order["messages"]['status'] == 'SUCCESSFUL':
                                    order = "Success"
                            except RuntimeError as e:
                                printAndDiscord(f"{key}: Error placing order: {e}", loop)
                                continue
                            printAndDiscord(
                                f"{key}: {order_obj.get_action()} {order_obj.get_amount()} of {stock} in {print_account}: {order}",
                                loop,
                            )
                        else:
                            printAndDiscord(
                                f"{key} {print_account}: Running in DRY mode. Transaction would've been: {order_obj.get_action()} {order_obj.get_amount()} of {stock}",
                                loop,
                            )     
                except Exception as e:
                    printAndDiscord(f"{print_account}: Error placing order: {e}", loop)
                    traceback.print_exc()
                finally:
                    # Restore orderObj
                    order_obj.set_amount(old_amount)
                    order_obj.set_action(original_action)     
