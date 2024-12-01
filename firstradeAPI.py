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
from firstrade.exceptions import QuoteRequestError

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
                    symbol = item["symbol"]
                    try:
                        quote = symbols.SymbolQuote(obj, account, symbol)
                        price = quote.last
                    except QuoteRequestError:
                        price = 0
                    firstrade_o.set_holdings(
                        key,
                        account,
                        symbol,
                        item["quantity"],
                        price,
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
            for account in firstrade_o.get_account_numbers(key):
                obj: ft_account.FTSession = firstrade_o.get_logged_in_objects(key)
                print_account = maskString(account)
                # If DRY is True, don't actually make the transaction
                if orderObj.get_dry():
                    printAndDiscord(
                        "Running in DRY mode. No transactions will be made.", loop
                    )
                old_amount = orderObj.get_amount()
                original_action = orderObj.get_action()
                try:
                    should_dance = False
                    symbol_data = symbols.SymbolQuote(obj, account, s)
                    if symbol_data.last < 1.00:
                        if int(orderObj.get_amount()) < 100:
                            should_dance = True
                        price_type = order.PriceType.LIMIT
                        orderObj.set_price("limit")
                        if orderObj.get_action().capitalize() == "Buy":
                            price = symbol_data.last + 0.01
                        else:
                            price = symbol_data.last - 0.01
                    else:
                        price_type = order.PriceType.MARKET
                        orderObj.set_price("market")
                        price = 0.00
                    if orderObj.get_action().capitalize() == "Buy":
                        order_type = order.OrderType.BUY
                    else:
                        order_type = order.OrderType.SELL
                    printAndDiscord(
                        f"{key} {orderObj.get_action()}ing {orderObj.get_amount()} {s} @ {orderObj.get_price()}",
                        loop,
                    )
                    if should_dance and orderObj.get_action() == "buy":
                        # Do the dance
                        quantity = 100
                        printAndDiscord(
                            f"Buying {quantity} then selling {quantity - orderObj.get_amount()} of {s}",
                            loop,
                        )
                        orderObj.set_amount(quantity)
                        ft_order = order.Order(obj)
                        order_conf = ft_order.place_order(
                            account=account,
                            symbol=s,
                            price_type=price_type,
                            order_type=order_type,
                            quantity=orderObj.get_amount(),
                            duration=order.Duration.DAY,
                            price=price,
                            dry_run=orderObj.get_dry(),
                        )
                        print(
                            "The buy order verification produced the following messages: "
                        )
                        pprint.pprint(order_conf)
                        buy_success = order_conf["error"] == ""
                        printAndDiscord(
                            (
                                f"{key} account {print_account}: The buy order verification was "
                                + "successful"
                                if buy_success
                                else f"{key} account {print_account}: The sell order verification was unsuccessful"
                            ),
                            loop,
                        )
                        if not buy_success:
                            printAndDiscord(
                                f"{key} account {print_account}: The order verification produced the following messages: {order_conf}",
                                loop,
                            )
                            raise Exception(f"Error buying {quantity} of {s}")
                        orderObj.set_amount(quantity - old_amount)
                        # Rest before selling
                        sleep(1)
                        symbol_data = symbols.SymbolQuote(obj, account, s)
                        price = symbol_data.last - 0.01
                        ft_order = order.Order(obj)
                        order_conf = ft_order.place_order(
                            account=account,
                            symbol=s,
                            price_type=price_type,
                            order_type=order.OrderType.SELL,
                            quantity=orderObj.get_amount(),
                            duration=order.Duration.DAY,
                            price=price,
                            dry_run=orderObj.get_dry(),
                        )
                        print(
                            "The sell order verification produced the following messages: "
                        )
                        pprint.pprint(order_conf)
                        sell_success = order_conf["error"] == ""
                        printAndDiscord(
                            (
                                f"{key} account {print_account}: The sell order verification was "
                                + "successful"
                                if sell_success
                                else f"{key} account {print_account}: The sell order verification was unsuccessful"
                            ),
                            loop,
                        )
                        if not sell_success:
                            printAndDiscord(
                                f"{key} account {print_account}: The order verification produced the following messages: {order_conf}",
                                loop,
                            )
                            raise Exception(
                                f"Error selling {quantity - old_amount} of {s}"
                            )
                    else:
                        # Normal buy/sell
                        ft_order = order.Order(obj)
                        order_conf = ft_order.place_order(
                            account=account,
                            symbol=s,
                            price_type=price_type,
                            order_type=order_type,
                            quantity=orderObj.get_amount(),
                            duration=order.Duration.DAY,
                            price=price,
                            dry_run=orderObj.get_dry(),
                        )
                        print(
                            "The order verification produced the following messages: "
                        )
                        pprint.pprint(order_conf)
                        order_success = order_conf["error"] == ""
                        printAndDiscord(
                            (
                                f"{key} account {print_account}: The order verification was "
                                + "successful"
                                if order_success
                                else f"{key} account {print_account}: The sell order verification was unsuccessful"
                            ),
                            loop,
                        )
                        if not order_success:
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

                finally:
                    # Restore orderObj
                    orderObj.set_amount(old_amount)
                    orderObj.set_action(original_action)
                sleep(1)
                print()
