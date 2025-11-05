# Donald Ryan Gullett(MaxxRK)
# Firstrade API

import asyncio
import os
import pprint
import traceback
from time import sleep
from typing import cast

from discord.ext.commands import Bot
from dotenv import load_dotenv
from firstrade import account as ft_account
from firstrade import order, symbols
from firstrade.exceptions import QuoteRequestError

from src.helper_api import Brokerage, StockOrder, get_otp_from_discord, mask_string, print_all_holdings, print_and_discord


def firstrade_init(bot_obj: Bot | None = None, loop: asyncio.AbstractEventLoop | None = None) -> Brokerage | None:
    """Initialize Firstrade API."""
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
            account_creds = account.split(":")
            firstrade = ft_account.FTSession(
                username=account_creds[0],
                password=account_creds[1],
                pin=(account_creds[2] if len(account_creds[2]) == 4 and account_creds[2].isdigit() else None),  # noqa: PLR2004
                phone=(account_creds[2][-4:] if len(account_creds[2]) == 10 and account_creds[2].isdigit() else None),  # noqa: PLR2004
                email=account_creds[2] if "@" in account_creds[2] else None,
                mfa_secret=(account_creds[2] if len(account_creds[2]) > 14 and "@" not in account_creds[2] else None),  # noqa: PLR2004
                profile_path="./creds/",
            )
            need_code = firstrade.login()
            if need_code:
                if bot_obj is None and loop is None:
                    firstrade.login_two(input("Enter code: "))
                elif bot_obj is not None and loop is not None:
                    sms_code = asyncio.run_coroutine_threadsafe(
                        get_otp_from_discord(bot_obj, name, timeout=300, loop=loop),
                        loop,
                    ).result()
                    if sms_code is None:
                        msg = f"Firstrade {index} code not received in time..."
                        raise Exception(msg, loop)
                    firstrade.login_two(sms_code)
            print("Logged in to Firstrade!")
            account_info = ft_account.FTAccountData(firstrade)
            firstrade_obj.set_logged_in_object(name, firstrade)
            for account_number in account_info.account_numbers:
                firstrade_obj.set_account_number(name, account_number)
                firstrade_obj.set_account_totals(name, account_number, account_info.account_balances[account_number])
            print_accounts = [mask_string(a) for a in account_info.account_numbers]
            print(f"The following Firstrade accounts were found: {print_accounts}")
        except Exception as e:
            print(f"Error logging in to Firstrade: {e}")
            print(traceback.format_exc())
            return None
    return firstrade_obj


def firstrade_holdings(firstrade_o: Brokerage, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Retrieve and display all Firstrade account holdings."""
    # Get holdings on each account
    for key in firstrade_o.get_account_numbers():
        for account in firstrade_o.get_account_numbers(key):
            obj = cast("ft_account.FTSession", firstrade_o.get_logged_in_objects(key))
            try:
                data = ft_account.FTAccountData(obj).get_positions(account=account)
                for item in data["items"]:
                    symbol = item["symbol"]
                    try:
                        quote = symbols.SymbolQuote(obj, account, symbol)
                        price = quote.last
                    except QuoteRequestError:
                        price = 0
                    firstrade_o.set_holdings(key, account, symbol, item["quantity"], price)
            except Exception as e:
                print_and_discord(f"{key} {account}: Error getting holdings: {e}", loop)
                print(traceback.format_exc())
                continue
    print_all_holdings(firstrade_o, loop)


def firstrade_transaction(firstrade_o: Brokerage, order_obj: StockOrder, loop: asyncio.AbstractEventLoop | None = None) -> None:  # noqa: C901, PLR0912, PLR0914, PLR0915
    """Handle Firstrade API transactions."""
    print()
    print("==============================")
    print("Firstrade")
    print("==============================")
    print()
    # Buy on each account
    for s in order_obj.get_stocks():
        for key in firstrade_o.get_account_numbers():
            for account in firstrade_o.get_account_numbers(key):
                obj = cast("ft_account.FTSession", firstrade_o.get_logged_in_objects(key))
                print_account = mask_string(account)
                # If DRY is True, don't actually make the transaction
                if order_obj.get_dry():
                    print_and_discord(
                        "Running in DRY mode. No transactions will be made.",
                        loop,
                    )
                old_amount = order_obj.get_amount()
                original_action = order_obj.get_action()
                try:
                    should_dance = False
                    symbol_data = symbols.SymbolQuote(obj, account, s)
                    if symbol_data.last < 1.00:
                        under_one_buy_amount = 100
                        if int(order_obj.get_amount()) < under_one_buy_amount:
                            should_dance = True
                        price_type = order.PriceType.LIMIT
                        order_obj.set_price("limit")
                        price = symbol_data.last + 0.01 if order_obj.get_action().capitalize() == "Buy" else symbol_data.last - 0.01
                    else:
                        price_type = order.PriceType.MARKET
                        order_obj.set_price("market")
                        price = 0.00
                    order_type = order.OrderType.BUY if order_obj.get_action().capitalize() == "Buy" else order.OrderType.SELL
                    print_and_discord(
                        f"{key} {order_obj.get_action()}ing {order_obj.get_amount()} {s} @ {order_obj.get_price()}",
                        loop,
                    )
                    if should_dance and order_obj.get_action() == "buy":
                        # Do the dance
                        quantity = 100
                        print_and_discord(
                            f"Buying {quantity} then selling {quantity - order_obj.get_amount()} of {s}",
                            loop,
                        )
                        order_obj.set_amount(quantity)
                        ft_order = order.Order(obj)
                        order_conf = ft_order.place_order(
                            account=account,
                            symbol=s,
                            price_type=price_type,
                            order_type=order_type,
                            quantity=int(order_obj.get_amount()),
                            duration=order.Duration.DAY,
                            price=price,
                            dry_run=order_obj.get_dry(),
                        )
                        print(
                            "The buy order verification produced the following messages: ",
                        )
                        pprint.pprint(order_conf)  # noqa: T203
                        buy_success = not order_conf["error"]
                        print_and_discord(
                            (f"{key} account {print_account}: The buy order verification was successful" if buy_success else f"{key} account {print_account}: The sell order verification was unsuccessful"),
                            loop,
                        )
                        if not buy_success:
                            print_and_discord(
                                f"{key} account {print_account}: The order verification produced the following messages: {order_conf}",
                                loop,
                            )
                            msg = f"Error buying {quantity} of {s}"
                            raise Exception(msg)
                        order_obj.set_amount(quantity - old_amount)
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
                            quantity=int(order_obj.get_amount()),
                            duration=order.Duration.DAY,
                            price=price,
                            dry_run=order_obj.get_dry(),
                        )
                        print(
                            "The sell order verification produced the following messages: ",
                        )
                        pprint.pprint(order_conf)  # noqa: T203
                        sell_success = not order_conf["error"]
                        print_and_discord(
                            (f"{key} account {print_account}: The sell order verification was successful" if sell_success else f"{key} account {print_account}: The sell order verification was unsuccessful"),
                            loop,
                        )
                        if not sell_success:
                            print_and_discord(
                                f"{key} account {print_account}: The order verification produced the following messages: {order_conf}",
                                loop,
                            )
                            msg = f"Error selling {quantity - old_amount} of {s}"
                            raise Exception(msg)
                    else:
                        # Normal buy/sell
                        ft_order = order.Order(obj)
                        order_conf = ft_order.place_order(
                            account=account,
                            symbol=s,
                            price_type=price_type,
                            order_type=order_type,
                            quantity=int(order_obj.get_amount()),
                            duration=order.Duration.DAY,
                            price=price,
                            dry_run=order_obj.get_dry(),
                        )
                        print(
                            "The order verification produced the following messages: ",
                        )
                        pprint.pprint(order_conf)  # noqa: T203
                        order_success = not order_conf["error"]
                        print_and_discord(
                            (f"{key} account {print_account}: The order verification was successful" if order_success else f"{key} account {print_account}: The sell order verification was unsuccessful"),
                            loop,
                        )
                        if not order_success:
                            print_and_discord(
                                f"{key} account {print_account}: The order verification produced the following messages: {order_conf}",
                                loop,
                            )
                except Exception as e:
                    print_and_discord(
                        f"{key} {print_account}: Error submitting order: {e}",
                        loop,
                    )
                    print(traceback.format_exc())
                    continue

                finally:
                    # Restore orderObj
                    order_obj.set_amount(old_amount)
                    order_obj.set_action("buy" if original_action.lower() == "buy" else "sell")
                sleep(1)
                print()
