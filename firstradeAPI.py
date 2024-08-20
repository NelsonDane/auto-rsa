# Donald Ryan Gullett(MaxxRK)
# Firstrade API

import asyncio
import os
import pprint
import traceback
from time import sleep

from dotenv import load_dotenv
from firstrade import account as ft_account
from firstrade import order, symbols

from helperAPI import (
    Brokerage,
    getOTPCodeDiscord,
    maskString,
    printAndDiscord,
    printHoldings,
    stockOrder,
)


def firstrade_init(botObj=None, loop=None):
    # Initialize .env file
    load_dotenv()
    if not os.getenv("FIRSTRADE"):
        print("Firstrade not found, skipping...")
        return None
    accounts = os.environ["FIRSTRADE"].strip().split(",")
    # Log in to Firstrade account
    print("Logging in to Firstrade...")
    firstrade_obj = Brokerage("Firstrade")
    for account in accounts:
        index = accounts.index(account) + 1
        name = f"Firstrade {index}"
        try:
            account = account.split(":")
            firstrade = ft_account.FTSession(
                username=account[0],
                password=account[1],
                pin=(
                    account[2]
                    if len(account[2]) == 4 and account[2].isdigit()
                    else None
                ),
                phone=(
                    account[2][-4:]
                    if len(account[2]) == 10 and account[2].isdigit()
                    else None
                ),
                email=account[2] if "@" in account[2] else None,
                mfa_secret=(
                    account[2]
                    if len(account[2]) > 14 and "@" not in account[2]
                    else None
                ),
                profile_path="./creds/",
            )
            need_code = firstrade.login()
            if need_code:
                if botObj is None and loop is None:
                    firstrade.login_two(input("Enter code: "))
                else:
                    sms_code = asyncio.run_coroutine_threadsafe(
                        getOTPCodeDiscord(botObj, name, timeout=300, loop=loop), loop
                    ).result()
                    if sms_code is None:
                        raise Exception(
                            f"Firstrade {index} code not received in time...", loop
                        )
                    firstrade.login_two(sms_code)
            print("Logged in to Firstrade!")
            account_info = ft_account.FTAccountData(firstrade)
            firstrade_obj.set_logged_in_object(name, firstrade)
            for account in account_info.account_numbers:
                firstrade_obj.set_account_number(name, account)
                firstrade_obj.set_account_totals(
                    name, account, account_info.account_balances[account]
                )
            print_accounts = [maskString(a) for a in account_info.account_numbers]
            print(f"The following Firstrade accounts were found: {print_accounts}")
        except Exception as e:
            print(f"Error logging in to Firstrade: {e}")
            print(traceback.format_exc())
            return None
    return firstrade_obj


def firstrade_holdings(firstrade_o: Brokerage, loop=None):
    # Get holdings on each account
    for key in firstrade_o.get_account_numbers():
        for account in firstrade_o.get_account_numbers(key):
            obj: ft_account.FTSession = firstrade_o.get_logged_in_objects(key)
            try:
                data = ft_account.FTAccountData(obj).get_positions(account=account)
                for item in data["items"]:
                    firstrade_o.set_holdings(
                        key,
                        account,
                        item.get("symbol") or "Unknown",
                        item["quantity"],
                        item["market_value"],
                    )
            except Exception as e:
                printAndDiscord(f"{key} {account}: Error getting holdings: {e}", loop)
                print(traceback.format_exc())
                continue
    printHoldings(firstrade_o, loop)


def firstrade_transaction(firstrade_o: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Firstrade")
    print("==============================")
    print()
    # Buy on each account
    for s in orderObj.get_stocks():
        for key in firstrade_o.get_account_numbers():
            printAndDiscord(
                f"{key} {orderObj.get_action()}ing {orderObj.get_amount()} {s} @ {orderObj.get_price()}",
                loop,
            )
            for account in firstrade_o.get_account_numbers(key):
                obj: ft_account.FTSession = firstrade_o.get_logged_in_objects(key)
                print_account = maskString(account)
                # If DRY is True, don't actually make the transaction
                if orderObj.get_dry():
                    printAndDiscord(
                        "Running in DRY mode. No transactions will be made.", loop
                    )
                try:
                    symbol_data = symbols.SymbolQuote(obj, account, s)
                    if symbol_data.last < 1.00:
                        price_type = order.PriceType.LIMIT
                        if orderObj.get_action().capitalize() == "Buy":
                            price = symbol_data.last + 0.01
                        else:
                            price = symbol_data.last - 0.01
                    else:
                        price_type = order.PriceType.MARKET
                        price = 0.00
                    if orderObj.get_action().capitalize() == "Buy":
                        order_type = order.OrderType.BUY
                    else:
                        order_type = order.OrderType.SELL
                    ft_order = order.Order(obj)
                    order_conf = ft_order.place_order(
                        account=account,
                        symbol=s,
                        price_type=price_type,
                        order_type=order_type,
                        quantity=int(orderObj.get_amount()),
                        duration=order.Duration.DAY,
                        price=price,
                        dry_run=orderObj.get_dry(),
                    )

                    print("The order verification produced the following messages: ")
                    pprint.pprint(order_conf)
                    printAndDiscord(
                        (
                            f"{key} account {print_account}: The order verification was "
                            + "successful"
                            if order_conf["error"] == ""
                            else "unsuccessful"
                        ),
                        loop,
                    )
                    if not order_conf["error"] == "":
                        printAndDiscord(
                            f"{key} account {print_account}: The order verification produced the following messages: {order_conf}",
                            loop,
                        )
                except Exception as e:
                    printAndDiscord(
                        f"{key} {print_account}: Error submitting order: {e}", loop
                    )
                    print(traceback.format_exc())
                    continue
                sleep(1)
                print()
