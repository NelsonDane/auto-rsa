# Donald Ryan Gullett(MaxxRK)
# Chase API

import asyncio
import os
import pprint
import traceback

from chase import account as ch_account
from chase import order, session, symbols
from dotenv import load_dotenv

from helperAPI import (
    Brokerage,
    getOTPCodeDiscord,
    printAndDiscord,
    printHoldings,
    stockOrder,
)


def chase_run(
    orderObj: stockOrder, command=None, botObj=None, loop=None, CHASE_EXTERNAL=None
):
    # Initialize .env file
    load_dotenv()
    # Import Chase account
    if not os.getenv("CHASE") and CHASE_EXTERNAL is None:
        print("Chase not found, skipping...")
        return None
    accounts = (
        os.environ["CHASE"].strip().split(",")
        if CHASE_EXTERNAL is None
        else CHASE_EXTERNAL.strip().split(",")
    )
    # Set the functions to be run
    _, second_command = command

    for account in accounts:
        index = accounts.index(account) + 1
        success = chase_init(
            account=account,
            index=index,
            botObj=botObj,
            loop=loop,
        )
        if success is not None:
            orderObj.set_logged_in(success, "chase")
            if second_command == "_holdings":
                chase_holdings(success, loop=loop)
            else:
                chase_transaction(success, orderObj, loop=loop)
    return None


def get_account_id(account_connectors, value):
    for key, val in account_connectors.items():
        if val[0] == value:
            return key
    return None


def chase_init(account, index, botObj=None, loop=None):
    # Log in to Chase account
    print("Logging in to Chase...")
    chase_obj = Brokerage("Chase")
    name = f"Chase {index}"
    try:
        account = account.split(":")
        debug = bool(account[3]) if len(account) == 4 else False
        ch_session = session.ChaseSession(
            title=f"chase_{index}", headless=True, profile_path="./creds", debug=debug
        )
        need_second = ch_session.login(account[0], account[1], account[2])
        if need_second:
            if botObj is None and loop is None:
                ch_session.login_two(input("Enter code: "))
            else:
                sms_code = asyncio.run_coroutine_threadsafe(
                    getOTPCodeDiscord(botObj, name, code_len=8, loop=loop), loop
                ).result()
                if sms_code is None:
                    raise Exception(f"Chase {index} code not received in time...", loop)
                ch_session.login_two(sms_code)
        all_accounts = ch_account.AllAccount(ch_session)
        account_ids = list(all_accounts.account_connectors.keys())
        print("Logged in to Chase!")
        chase_obj.set_logged_in_object(name, ch_session)
        print_accounts = []
        for acct in account_ids:
            account = ch_account.AccountDetails(acct, all_accounts)
            chase_obj.set_account_number(name, account.mask)
            chase_obj.set_account_totals(name, account.mask, account.account_value)
            print_accounts.append(account.mask)
        print(f"The following Chase accounts were found: {print_accounts}")
    except Exception as e:
        ch_session.close_browser()
        print(f"Error logging in to Chase: {e}")
        print(traceback.format_exc())
        return None
    return chase_obj


def chase_holdings(chase_o: Brokerage, loop=None):
    # Get holdings on each account
    for key in chase_o.get_account_numbers():
        try:
            for h, account in enumerate(chase_o.get_account_numbers(key)):
                obj: session.ChaseSession = chase_o.get_logged_in_objects(key)
                if h == 0:
                    all_accounts = ch_account.AllAccount(obj)
                    if all_accounts is None:
                        raise Exception("Error getting account details")
                account_id = get_account_id(all_accounts.account_connectors, account)
                data = symbols.SymbolHoldings(account_id, obj)
                success = data.get_holdings()
                if success:
                    for i, _ in enumerate(data.positions):
                        if (
                            data.positions[i]["instrumentLongName"]
                            == "Cash and Sweep Funds"
                        ):
                            sym = data.positions[i]["instrumentLongName"]
                            current_price = data.positions[i]["marketValue"][
                                "baseValueAmount"
                            ]
                            qty = "1"
                            chase_o.set_holdings(key, account, sym, qty, current_price)
                        elif data.positions[i]["assetCategoryName"] == "EQUITY":
                            try:
                                sym = data.positions[i]["positionComponents"][0][
                                    "securityIdDetail"
                                ][0]["symbolSecurityIdentifier"]
                                current_price = data.positions[i]["marketValue"][
                                    "baseValueAmount"
                                ]
                                qty = data.positions[i]["tradedUnitQuantity"]
                            except KeyError:
                                sym = data.positions[i]["securityIdDetail"][
                                    "cusipIdentifier"
                                ]
                                current_price = data.positions[i]["marketValue"][
                                    "baseValueAmount"
                                ]
                                qty = data.positions[i]["tradedUnitQuantity"]
                            chase_o.set_holdings(key, account, sym, qty, current_price)
        except Exception as e:
            obj.close_browser()
            printAndDiscord(f"{key} {account}: Error getting holdings: {e}", loop)
            print(traceback.format_exc())
            continue
        printHoldings(chase_o, loop)
    obj.close_browser()


def chase_transaction(chase_o: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Chase")
    print("==============================")
    print()
    account_id = None
    # Buy on each account
    for s in orderObj.get_stocks():
        for key in chase_o.get_account_numbers():
            printAndDiscord(
                f"{key} {orderObj.get_action()}ing {orderObj.get_amount()} {s} @ {orderObj.get_price()}",
                loop,
            )
            try:
                print(chase_o.get_account_numbers())
                for account in chase_o.get_account_numbers(key):
                    obj: session.ChaseSession = chase_o.get_logged_in_objects(key)
                    if account_id is None:
                        all_accounts = ch_account.AllAccount(obj)
                        if all_accounts is None:
                            raise Exception("Error getting account details")
                    account_id = get_account_id(
                        all_accounts.account_connectors, account
                    )
                    # If DRY is True, don't actually make the transaction
                    if orderObj.get_dry():
                        printAndDiscord(
                            "Running in DRY mode. No transactions will be made.", loop
                        )
                    price_type = order.PriceType.MARKET
                    if orderObj.get_action().capitalize() == "Buy":
                        order_type = order.OrderSide.BUY
                    else:
                        order_type = order.OrderSide.SELL
                    chase_order = order.Order(obj)
                    messages = chase_order.place_order(
                        account_id=account_id,
                        quantity=int(orderObj.get_amount()),
                        price_type=price_type,
                        symbol=s,
                        duration=order.Duration.DAY,
                        order_type=order_type,
                        dry_run=orderObj.get_dry(),
                    )
                    print("The order verification produced the following messages: ")
                    if orderObj.get_dry():
                        pprint.pprint(messages["ORDER PREVIEW"])
                        printAndDiscord(
                            (
                                f"{key} account {account}: The order verification was "
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
                            not messages["ORDER INVALID"]
                            == "No invalid order message found."
                        ):
                            printAndDiscord(
                                f"{key} account {account}: The order verification produced the following messages: {messages['ORDER INVALID']}",
                                loop,
                            )
                    else:
                        pprint.pprint(messages["ORDER CONFIRMATION"])
                        printAndDiscord(
                            (
                                f"{key} account {account}: The order verification was "
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
                            not messages["ORDER INVALID"]
                            == "No invalid order message found."
                        ):
                            printAndDiscord(
                                f"{key} account {account}: The order verification produced the following messages: {messages['ORDER INVALID']}",
                                loop,
                            )
            except Exception as e:
                printAndDiscord(f"{key} {account}: Error submitting order: {e}", loop)
                print(traceback.format_exc())
                continue
    obj.close_browser()
    printAndDiscord(
        "All Chase transactions complete",
        loop,
    )
