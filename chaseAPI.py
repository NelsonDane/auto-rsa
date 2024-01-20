# Donald Ryan Gullett(MaxxRK)
# Chase API

import asyncio
import os
import pprint
import queue as q
import traceback
from threading import Thread
from time import sleep

from chase import account as ch_account
from chase import order, session, symbols
from dotenv import load_dotenv

from helperAPI import (Brokerage, maskString, printAndDiscord, printHoldings,
                       stockOrder)


def monitor(queue, loop):
    # Monitor Login thread
    need_code = queue.get()
    if need_code == (True, "code"):
        printAndDiscord("Chase login code required please input through @code command. You have ~2 min.", loop)
        for i in range(0, 121):
            if not queue.empty():
                logged_in = queue.get()
                break
            elif queue.empty() and (i+1)%20 == 0:
                printAndDiscord(f"Waiting for code... You have ~{119 - i} seconds left.", loop)
                sleep(1)
            sleep(1)
        if logged_in == (True, "logged_in"):
           printAndDiscord("Code received!", loop)
        elif logged_in == (False, "logged_in"):
            printAndDiscord("Code not received in time...", loop)
        return logged_in
    return need_code

def chase_init(CHASE_EXTERNAL=None, DOCKER=False, EXTERNAL_CODE=False, loop=None):
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
    # Log in to Chase account
    print("Logging in to Chase...")
    queue= q.Queue()
    chase_obj = Brokerage("Chase")
    for account in accounts:
        index = accounts.index(account) + 1
        name = f"Chase {index}"
        try:
            account = account.split(":")
            ch_session = session.ChaseSession(title=f"chase_{index}", headless=True, docker=DOCKER, external_code=EXTERNAL_CODE)
            t = Thread(
                target=ch_session.login,
                args=(account[0], account[1], account[2], queue)
                                        )
            t.daemon = True
            t.start()
            logged_in = monitor(queue, loop)
            t.join()
            if logged_in == (False, "logged_in"):
                return None
            all_accounts = ch_account.AllAccount(ch_session)
            account_ids = list(all_accounts.account_connectors.keys())
            print("Logged in to Chase!")
            chase_obj.set_logged_in_object(name, ch_session)
            for account in account_ids:
                account = ch_account.AccountDetails(account, all_accounts)
                chase_obj.set_account_number(name, account.account_id)
                chase_obj.set_account_totals(
                    name, account.account_id, account.account_value
                )
            print_accounts = [
                maskString(a)
                for a in account_ids
            ]
            print(f"The following Chase accounts were found: {print_accounts}")
        except Exception as e:
            print(f"Error logging in to Chase: {e}")
            print(traceback.format_exc())
            return None
    return chase_obj


def chase_holdings(chase_o: Brokerage, loop=None):
    # Get holdings on each account
    for key in chase_o.get_account_numbers():
        for account in chase_o.get_account_numbers(key):
            obj: ch_session.ChaseSession = chase_o.get_logged_in_objects(key)
            try:
                data = symbols.SymbolHoldings(account, obj)
                success = data.get_holdings()
                if success:
                    for i, _ in enumerate(data.positions):
                        if data.positions[i]["instrumentLongName"] == "Cash and Sweep Funds":
                            sym = data.positions[i]["instrumentLongName"]
                            current_price = data.positions[i]["marketValue"]["baseValueAmount"]
                            qty = "1"
                        elif data.positions[i]["assetCategoryName"] == "EQUITY":
                            try:
                                sym = data.positions[i]["positionComponents"][0][
                                    "securityIdDetail"
                                ][0]["symbolSecurityIdentifier"]
                                current_price = data.positions[i]["marketValue"]["baseValueAmount"]
                                qty = data.positions[i]["tradedUnitQuantity"]
                            except KeyError:
                                sym = data.positions[i]["securityIdDetail"]["cusipIdentifier"]
                                current_price = data.positions[i]["marketValue"]["baseValueAmount"]
                                qty = data.positions[i]["tradedUnitQuantity"]
                        chase_o.set_holdings(key, account, sym, qty, current_price)
            except Exception as e:
                printAndDiscord(f"{key} {account}: Error getting holdings: {e}", loop)
                print(traceback.format_exc())
                continue
        printHoldings(chase_o, loop)


def chase_transaction(chase_o: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Chase")
    print("==============================")
    print()
    # Buy on each account
    for s in orderObj.get_stocks():
        for key in chase_o.get_account_numbers():
            printAndDiscord(
                f"{key} {orderObj.get_action()}ing {orderObj.get_amount()} {s} @ {orderObj.get_price()}",
                loop,
            )
            for account in chase_o.get_account_numbers(key):
                obj: ch_session.ChaseSession = chase_o.get_logged_in_objects(key)
                print_account = maskString(account)
                # If DRY is True, don't actually make the transaction
                if orderObj.get_dry():
                    printAndDiscord(
                        "Running in DRY mode. No transactions will be made.", loop
                    )
                try:
                    price_type = order.PriceType.MARKET
                    if orderObj.get_action().capitalize() == "Buy":
                        order_type = order.OrderType.BUY
                    else:
                        order_type = order.OrderType.SELL
                    chase_order = order.Order(obj)
                    messages = chase_order.place_order(
                        account_id=account,
                        quantity=int(orderObj.get_amount()),
                        price_type=price_type,
                        symbol=s,
                        duration=order.Duration.DAY,
                        order_type=order_type,
                        dry_run=orderObj.get_dry(),
                    )
                    print("The order verification produced the following messages: ")
                    pprint.pprint(messages['ORDER CONFIRMATION'])
                    printAndDiscord(
                        f"{key} account {print_account}: The order verification was "
                        + "successful"
                        if messages["ORDER CONFIRMATION"] not in  ["", "No order confirmation page found. Order Failed."]
                        else "unsuccessful",
                        loop,
                    )
                    if not messages["ORDER INVALID"] == "No invalid order message found.":
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
                sleep(1)
                print()