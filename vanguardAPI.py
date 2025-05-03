# Donald Ryan Gullett(MaxxRK)
# Vanguard API

import asyncio
import os
import pprint
import traceback

from dotenv import load_dotenv
from vanguard import account as vg_account
from vanguard import order, session

from helperAPI import (
    Brokerage,
    getOTPCodeDiscord,
    maskString,
    printAndDiscord,
    printHoldings,
    stockOrder,
)


def vanguard_run(orderObj: stockOrder, command=None, botObj=None, loop=None):
    # Initialize .env file
    load_dotenv()
    # Import Vanguard account
    if not os.getenv("VANGUARD"):
        print("Vanguard not found, skipping...")
        return None
    accounts = os.environ["VANGUARD"].strip().split(",")
    # Get headless flag
    headless = os.getenv("HEADLESS", "true").lower() == "true"
    # Set the functions to be run
    _, second_command = command

    for account in accounts:
        index = accounts.index(account) + 1
        success = vanguard_init(
            account=account,
            index=index,
            headless=headless,
            botObj=botObj,
            loop=loop,
        )
        if success is not None:
            orderObj.set_logged_in(success, "vanguard")
            if second_command == "_holdings":
                vanguard_holdings(success, loop=loop)
            else:
                vanguard_transaction(success, orderObj, loop=loop)
    return None


def vanguard_init(account, index, headless=True, botObj=None, loop=None):
    # Log in to Vanguard account
    print("Logging in to Vanguard...")
    vanguard_obj = Brokerage("VANGUARD")
    name = f"Vanguard {index}"
    try:
        account = account.split(":")
        debug = bool(account[3]) if len(account) == 4 else False
        vg_session = session.VanguardSession(
            title=f"Vanguard_{index}",
            headless=headless,
            profile_path="./creds",
            debug=debug,
        )
        need_second = vg_session.login(account[0], account[1], account[2])
        if need_second:
            if botObj is None and loop is None:
                vg_session.login_two(input("Enter code: "))
            else:
                sms_code = asyncio.run_coroutine_threadsafe(
                    getOTPCodeDiscord(botObj, name, timeout=120, loop=loop), loop
                ).result()
                if sms_code is None:
                    raise Exception(
                        f"Vanguard {index} code not received in time...", loop
                    )
                vg_session.login_two(sms_code)
        all_accounts = vg_account.AllAccount(vg_session)
        success = all_accounts.get_account_ids()
        if not success:
            raise Exception("Error getting account details")
        print("Logged in to Vanguard!")
        vanguard_obj.set_logged_in_object(name, vg_session)
        print_accounts = []
        for acct in all_accounts.account_totals:
            vanguard_obj.set_account_number(name, acct)
            vanguard_obj.set_account_totals(
                name, acct, all_accounts.account_totals[acct]
            )
            print_accounts.append(acct)
        print(f"The following Vanguard accounts were found: {print_accounts}")
    except Exception as e:
        vg_session.close_browser()
        print(f"Error logging in to Vanguard: {e}")
        print(traceback.format_exc())
        return None
    return vanguard_obj


def vanguard_holdings(vanguard_o: Brokerage, loop=None):
    # Get holdings on each account
    for key in vanguard_o.get_account_numbers():
        try:
            obj: session.VanguardSession = vanguard_o.get_logged_in_objects(key)
            all_accounts = vg_account.AllAccount(obj)
            if all_accounts is None:
                raise Exception("Error getting account details")
            success = all_accounts.get_holdings()
            if success:
                for account in all_accounts.accounts_positions:
                    for account_type in all_accounts.accounts_positions[account].keys():
                        for stock in all_accounts.accounts_positions[account][
                            account_type
                        ]:
                            if float(stock["quantity"]) != 0 and stock["symbol"] != "—":
                                vanguard_o.set_holdings(
                                    key,
                                    account,
                                    stock["symbol"],
                                    stock["quantity"],
                                    stock["price"],
                                )
            else:
                raise Exception("Vanguard-api failed to retrieve holdings.")
        except Exception as e:
            obj.close_browser()
            printAndDiscord(f"{key} {account}: Error getting holdings: {e}", loop)
            print(traceback.format_exc())
            continue
        printHoldings(vanguard_o, loop)
    obj.close_browser()


def vanguard_transaction(vanguard_o: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Vanguard")
    print("==============================")
    print()
    # Use each account (unless specified in .env)
    purchase_accounts = os.getenv("VG_ACCOUNT_NUMBERS", "").strip().split(":")
    for s in orderObj.get_stocks():
        for key in vanguard_o.get_account_numbers():
            printAndDiscord(
                f"{key} {orderObj.get_action()}ing {orderObj.get_amount()} {s} @ {orderObj.get_price()}",
                loop,
            )
            try:
                for account in vanguard_o.get_account_numbers(key):
                    print_account = maskString(account)
                    if (
                        purchase_accounts != [""]
                        and orderObj.get_action().lower() != "sell"
                        and str(account) not in purchase_accounts
                    ):
                        print(
                            f"Skipping account {print_account}, not in VG_ACCOUNT_NUMBERS"
                        )
                        continue
                    obj: session.VanguardSession = vanguard_o.get_logged_in_objects(key)
                    # If DRY is True, don't actually make the transaction
                    if orderObj.get_dry():
                        printAndDiscord(
                            "Running in DRY mode. No transactions will be made.", loop
                        )
                    vg_order = order.Order(obj)
                    price_type = order.PriceType.MARKET
                    if orderObj.get_action().capitalize() == "Buy":
                        order_type = order.OrderSide.BUY
                    else:
                        order_type = order.OrderSide.SELL
                    # Check if dance is needed
                    if (
                        int(orderObj.get_amount()) == 1
                        and orderObj.get_action() == "buy"
                    ):
                        transaction_length = 2
                    else:
                        transaction_length = 1
                    for i in range(transaction_length):
                        if i == 0 and transaction_length == 2:
                            printAndDiscord(
                                f"{key} account {print_account}: Buying 26 then selling 25 of {s}",
                                loop,
                            )
                            dance_quantity = 26
                        elif i == 0 and transaction_length == 1:
                            dance_quantity = int(orderObj.get_amount())
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
                            dry_run=orderObj.get_dry(),
                            after_hours=True,
                        )
                        print(
                            "The order verification produced the following messages: "
                        )
                        if (
                            messages["ORDER CONFIRMATION"]
                            == "No order confirmation page found. Order Failed."
                        ):
                            printAndDiscord(
                                "Market order failed placing limit order.", loop
                            )
                            price_type = order.PriceType.LIMIT
                            price = vg_order.get_quote(s) + 0.01
                            messages = vg_order.place_order(
                                account_id=account,
                                quantity=dance_quantity,
                                price_type=price_type,
                                symbol=s,
                                duration=order.Duration.DAY,
                                order_type=order_type,
                                limit_price=price,
                                dry_run=orderObj.get_dry(),
                            )
                        if orderObj.get_dry():
                            if messages["ORDER PREVIEW"] != "":
                                pprint.pprint(messages["ORDER PREVIEW"])
                            printAndDiscord(
                                (
                                    f"{key} account {print_account}: The order verification was "
                                    + (
                                        "successful"
                                        if messages["ORDER PREVIEW"]
                                        not in ["", "No order preview page found."]
                                        else "unsuccessful"
                                    )
                                ),
                                loop,
                            )
                            if (
                                messages["ORDER INVALID"]
                                != "No invalid order message found."
                            ):
                                printAndDiscord(
                                    f"{key} account {print_account}: The order verification produced the following messages: {messages['ORDER INVALID']}",
                                    loop,
                                )
                        else:
                            if messages["ORDER CONFIRMATION"] != "":
                                pprint.pprint(messages["ORDER CONFIRMATION"])
                            printAndDiscord(
                                (
                                    f"{key} account {print_account}: The order verification was "
                                    + (
                                        "successful"
                                        if messages["ORDER CONFIRMATION"]
                                        not in [
                                            "",
                                            "No order confirmation page found. Order Failed.",
                                        ]
                                        else "unsuccessful"
                                    )
                                ),
                                loop,
                            )
                            if (
                                messages["ORDER INVALID"]
                                != "No invalid order message found."
                            ):
                                printAndDiscord(
                                    f"{key} account {print_account}: The order verification produced the following messages: {messages['ORDER INVALID']}",
                                    loop,
                                )
            except Exception as e:
                printAndDiscord(
                    f"{key} {print_account}: Error submitting order: {e}", loop
                )
                print(traceback.format_exc())
                continue
    obj.close_browser()
    printAndDiscord(
        "All Vanguard transactions complete",
        loop,
    )
