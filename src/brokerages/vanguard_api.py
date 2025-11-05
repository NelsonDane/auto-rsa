# Donald Ryan Gullett(MaxxRK)
# Vanguard API

import asyncio
import os
import pprint
import traceback
from typing import cast

from discord.ext.commands import Bot
from dotenv import load_dotenv
from vanguard import account as vg_account
from vanguard import order, session

from src.helper_api import Brokerage, StockOrder, get_otp_from_discord, mask_string, print_all_holdings, print_and_discord


def vanguard_run(order_obj: StockOrder, bot_obj: Bot | None = None, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Run the Vanguard command in a single thread."""
    # Initialize .env file
    load_dotenv()
    # Import Vanguard account
    if not os.getenv("VANGUARD"):
        print("Vanguard not found, skipping...")
        return
    accounts = os.environ["VANGUARD"].strip().split(",")
    # Get headless flag
    headless = os.getenv("HEADLESS", "true").lower() == "true"

    for account in accounts:
        index = accounts.index(account) + 1
        success = vanguard_init(
            van_account=account,
            index=index,
            headless=headless,
            bot_obj=bot_obj,
            loop=loop,
        )
        if success is not None:
            order_obj.set_logged_in(success, "vanguard")
            if order_obj.get_holdings():
                vanguard_holdings(success, loop=loop)
            else:
                vanguard_transaction(success, order_obj, loop=loop)
    return


def vanguard_init(van_account: str, index: int, *, headless: bool = True, bot_obj: Bot | None = None, loop: asyncio.AbstractEventLoop | None = None) -> Brokerage | None:
    """Initialize the Vanguard API."""
    # Log in to Vanguard account
    print("Logging in to Vanguard...")
    vanguard_obj = Brokerage("VANGUARD")
    name = f"Vanguard {index}"
    try:
        account = van_account.split(":")
        debug = bool(account[3]) if len(account) == 4 else False  # noqa: PLR2004
        vg_session = session.VanguardSession(
            title=f"Vanguard_{index}",
            headless=headless,
            profile_path="./creds",
            debug=debug,
        )
        need_second = vg_session.login(account[0], account[1], account[2])
        if need_second:
            if bot_obj is None and loop is None:
                vg_session.login_two(input("Enter code: "))
            elif bot_obj is not None and loop is not None:
                sms_code = asyncio.run_coroutine_threadsafe(
                    get_otp_from_discord(bot_obj, name, timeout=120, loop=loop),
                    loop,
                ).result()
                if sms_code is None:
                    msg = f"Vanguard {index} code not received in time..."
                    raise Exception(msg, loop)
                vg_session.login_two(sms_code)
        all_accounts = vg_account.AllAccount(vg_session)
        success = all_accounts.get_account_ids()
        if not success:
            msg = "Error getting account details"
            raise Exception(msg, loop)
        print("Logged in to Vanguard!")
        vanguard_obj.set_logged_in_object(name, vg_session)
        print_accounts = []
        for acct in all_accounts.account_totals:
            vanguard_obj.set_account_number(name, acct)
            vanguard_obj.set_account_totals(
                name,
                acct,
                all_accounts.account_totals[acct],
            )
            print_accounts.append(acct)
        print(f"The following Vanguard accounts were found: {print_accounts}")
    except Exception as e:
        vg_session.close_browser()
        print(f"Error logging in to Vanguard: {e}")
        print(traceback.format_exc())
        return None
    return vanguard_obj


def vanguard_holdings(vanguard_o: Brokerage, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Retrieve and display all Vanguard account holdings."""
    # Get holdings on each account
    for key in vanguard_o.get_account_numbers():
        try:
            obj = cast("session.VanguardSession", vanguard_o.get_logged_in_objects(key))
            all_accounts = vg_account.AllAccount(obj)
            if all_accounts is None:
                msg = "Error getting account details"
                raise Exception(msg)
            success = all_accounts.get_holdings()
            if success:
                for account in all_accounts.accounts_positions:
                    for account_type in all_accounts.accounts_positions[account]:
                        for stock in all_accounts.accounts_positions[account][account_type]:
                            if float(stock["quantity"]) != 0 and stock["symbol"] != "—":
                                vanguard_o.set_holdings(
                                    key,
                                    account,
                                    stock["symbol"],
                                    stock["quantity"],
                                    stock["price"],
                                )
            else:
                msg = "Vanguard-api failed to retrieve holdings."
                raise Exception(msg)
        except Exception as e:
            obj.close_browser()
            print_and_discord(f"{key} {account}: Error getting holdings: {e}", loop)
            print(traceback.format_exc())
            continue
        print_all_holdings(vanguard_o, loop)
    obj.close_browser()


def vanguard_transaction(vanguard_o: Brokerage, order_obj: StockOrder, loop: asyncio.AbstractEventLoop | None = None) -> None:  # noqa: C901, PLR0912, PLR0915
    """Handle Vanguard API transactions."""
    print()
    print("==============================")
    print("Vanguard")
    print("==============================")
    print()
    # Use each account (unless specified in .env)
    purchase_accounts = os.getenv("VG_ACCOUNT_NUMBERS", "").strip().split(":")
    for s in order_obj.get_stocks():
        for key in vanguard_o.get_account_numbers():
            print_and_discord(
                f"{key} {order_obj.get_action()}ing {order_obj.get_amount()} {s} @ {order_obj.get_price()}",
                loop,
            )
            try:
                for account in vanguard_o.get_account_numbers(key):
                    print_account = mask_string(account)
                    if purchase_accounts != [""] and order_obj.get_action().lower() != "sell" and str(account) not in purchase_accounts:
                        print(
                            f"Skipping account {print_account}, not in VG_ACCOUNT_NUMBERS",
                        )
                        continue
                    obj = cast("session.VanguardSession", vanguard_o.get_logged_in_objects(key))
                    # If DRY is True, don't actually make the transaction
                    if order_obj.get_dry():
                        print_and_discord(
                            "Running in DRY mode. No transactions will be made.",
                            loop,
                        )
                    vg_order = order.Order(obj)
                    price_type = order.PriceType.MARKET
                    order_type = order.OrderSide.BUY if order_obj.get_action().capitalize() == "Buy" else order.OrderSide.SELL
                    # Check if dance is needed
                    transaction_length = 2 if int(order_obj.get_amount()) == 1 and order_obj.get_action() == "buy" else 1
                    for i in range(transaction_length):
                        if i == 0 and transaction_length == 2:  # noqa: PLR2004
                            print_and_discord(
                                f"{key} account {print_account}: Buying 26 then selling 25 of {s}",
                                loop,
                            )
                            dance_quantity = 26
                        elif i == 0 and transaction_length == 1:
                            dance_quantity = int(order_obj.get_amount())
                        else:
                            dance_quantity = 25
                            order_type = order.OrderSide.SELL
                        messages = vg_order.place_order(
                            account_id=account,
                            quantity=dance_quantity,
                            price_type=price_type,
                            symbol=s,
                            duration=order.Duration.DAY,
                            order_type=order_type,
                            dry_run=order_obj.get_dry(),
                            after_hours=True,
                        )
                        print(
                            "The order verification produced the following messages: ",
                        )
                        if messages["ORDER CONFIRMATION"] == "No order confirmation page found. Order Failed.":
                            print_and_discord(
                                "Market order failed placing limit order.",
                                loop,
                            )
                            price_type = order.PriceType.LIMIT
                            price = vg_order.get_quote(s)
                            if not price:
                                print_and_discord(f"{key} account {print_account}: Error getting quote for {s}", loop)
                                continue
                            price += 0.01
                            messages = vg_order.place_order(
                                account_id=account,
                                quantity=dance_quantity,
                                price_type=price_type,
                                symbol=s,
                                duration=order.Duration.DAY,
                                order_type=order_type,
                                limit_price=price,
                                dry_run=order_obj.get_dry(),
                            )
                        if order_obj.get_dry():
                            if messages["ORDER PREVIEW"]:
                                pprint.pprint(messages["ORDER PREVIEW"])  # noqa: T203
                            print_and_discord(
                                (f"{key} account {print_account}: The order verification was " + ("successful" if messages["ORDER PREVIEW"] not in {"", "No order preview page found."} else "unsuccessful")),
                                loop,
                            )
                            if messages["ORDER INVALID"] != "No invalid order message found.":
                                print_and_discord(
                                    f"{key} account {print_account}: The order verification produced the following messages: {messages['ORDER INVALID']}",
                                    loop,
                                )
                        else:
                            if messages["ORDER CONFIRMATION"]:
                                pprint.pprint(messages["ORDER CONFIRMATION"])  # noqa: T203
                            print_and_discord(
                                (f"{key} account {print_account}: The order verification was " + ("successful" if messages["ORDER CONFIRMATION"] not in {"", "No order confirmation page found. Order Failed."} else "unsuccessful")),
                                loop,
                            )
                            if messages["ORDER INVALID"] != "No invalid order message found.":
                                print_and_discord(
                                    f"{key} account {print_account}: The order verification produced the following messages: {messages['ORDER INVALID']}",
                                    loop,
                                )
            except Exception as e:
                print_and_discord(
                    f"{key} {print_account}: Error submitting order: {e}",
                    loop,
                )
                print(traceback.format_exc())
                continue
    obj.close_browser()
    print_and_discord(
        "All Vanguard transactions complete",
        loop,
    )
