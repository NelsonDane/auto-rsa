import asyncio
import os
import traceback

from dotenv import load_dotenv
from public_invest_api import Public

from helperAPI import (
    Brokerage,
    getOTPCodeDiscord,
    maskString,
    printAndDiscord,
    printHoldings,
    stockOrder,
)


def public_init(PUBLIC_EXTERNAL=None, botObj=None, loop=None):
    # Initialize .env file
    load_dotenv()
    # Import Public account
    public_obj = Brokerage("Public")
    if not os.getenv("PUBLIC_BROKER") and PUBLIC_EXTERNAL is None:
        print("Public not found, skipping...")
        return None
    PUBLIC = (
        os.environ["PUBLIC_BROKER"].strip().split(",")
        if PUBLIC_EXTERNAL is None
        else PUBLIC_EXTERNAL.strip().split(",")
    )
    # Log in to Public account
    print("Logging in to Public...")
    for index, account in enumerate(PUBLIC):
        name = f"Public {index + 1}"
        try:
            account = account.split(":")
            pb = Public(filename=f"public{index + 1}.pkl", path="./creds/")
            try:
                if botObj is None and loop is None:
                    # Login from CLI
                    pb.login(
                        username=account[0],
                        password=account[1],
                        wait_for_2fa=True,
                    )
                else:
                    # Login from Discord and check for 2fa required message
                    pb.login(
                        username=account[0],
                        password=account[1],
                        wait_for_2fa=False,
                    )
            except Exception as e:
                if "2FA" in str(e) and botObj is not None and loop is not None:
                    # Sometimes codes take a long time to arrive
                    timeout = 300  # 5 minutes
                    sms_code = asyncio.run_coroutine_threadsafe(
                        getOTPCodeDiscord(botObj, name, timeout=timeout, loop=loop),
                        loop,
                    ).result()
                    if sms_code is None:
                        raise Exception("No SMS code found")
                    pb.login(
                        username=account[0],
                        password=account[1],
                        wait_for_2fa=False,
                        code=sms_code,
                    )
                else:
                    raise e
            # Public only has one account
            public_obj.set_logged_in_object(name, pb)
            an = pb.get_account_number()
            public_obj.set_account_number(name, an)
            print(f"{name}: Found account {maskString(an)}")
            atype = pb.get_account_type()
            public_obj.set_account_type(name, an, atype)
            cash = pb.get_account_cash()
            public_obj.set_account_totals(name, an, cash)
        except Exception as e:
            print(f"Error logging in to Public: {e}")
            print(traceback.format_exc())
            continue
    print("Logged in to Public!")
    return public_obj


def public_holdings(pbo: Brokerage, loop=None):
    for key in pbo.get_account_numbers():
        for account in pbo.get_account_numbers(key):
            obj: Public = pbo.get_logged_in_objects(key)
            try:
                # Get account holdings
                positions = obj.get_positions()
                if positions != []:
                    for holding in positions:
                        # Get symbol, quantity, and total value
                        sym = holding["instrument"]["symbol"]
                        qty = float(holding["quantity"])
                        try:
                            current_price = obj.get_symbol_price(sym)
                        except Exception:
                            current_price = "N/A"
                        pbo.set_holdings(key, account, sym, qty, current_price)
            except Exception as e:
                printAndDiscord(f"{key}: Error getting account holdings: {e}", loop)
                traceback.format_exc()
                continue
    printHoldings(pbo, loop)


def public_transaction(pbo: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Public")
    print("==============================")
    print()
    for s in orderObj.get_stocks():
        for key in pbo.get_account_numbers():
            printAndDiscord(
                f"{key}: {orderObj.get_action()}ing {orderObj.get_amount()} of {s}",
                loop,
            )
            for account in pbo.get_account_numbers(key):
                obj: Public = pbo.get_logged_in_objects(key)
                print_account = maskString(account)
                try:
                    order = obj.place_order(
                        symbol=s,
                        quantity=orderObj.get_amount(),
                        side=orderObj.get_action(),
                        order_type="market",
                        time_in_force="day",
                        is_dry_run=orderObj.get_dry(),
                    )
                    if order["success"] is True:
                        order = "Success"
                    dry_message = ""
                    if orderObj.get_dry():
                        dry_message = "DRY RUN: "
                    printAndDiscord(
                        f"{dry_message}{orderObj.get_action()} {orderObj.get_amount()} of {s} in {print_account}: {order}",
                        loop,
                    )
                except Exception as e:
                    printAndDiscord(f"{print_account}: Error placing order: {e}", loop)
                    traceback.print_exc()
                    continue
