import asyncio
import os
import traceback

from dotenv import load_dotenv
from fennel_invest_api import Fennel

from helperAPI import (
    Brokerage,
    getOTPCodeDiscord,
    printAndDiscord,
    printHoldings,
    stockOrder,
)


def fennel_init(FENNEL_EXTERNAL=None, botObj=None, loop=None):
    # Initialize .env file
    load_dotenv()
    # Import Fennel account
    fennel_obj = Brokerage("Fennel")
    if not os.getenv("FENNEL") and FENNEL_EXTERNAL is None:
        print("Fennel not found, skipping...")
        return None
    FENNEL = (
        os.environ["FENNEL"].strip().split(",")
        if FENNEL_EXTERNAL is None
        else FENNEL_EXTERNAL.strip().split(",")
    )
    # Log in to Fennel account
    print("Logging in to Fennel...")
    for index, account in enumerate(FENNEL):
        name = f"Fennel {index + 1}"
        try:
            fb = Fennel(filename=f"fennel{index + 1}.pkl", path="./creds/")
            try:
                if botObj is None and loop is None:
                    # Login from CLI
                    fb.login(
                        email=account,
                        wait_for_code=True,
                    )
                else:
                    # Login from Discord and check for 2fa required message
                    fb.login(
                        email=account,
                        wait_for_code=False,
                    )
            except Exception as e:
                if "2FA" in str(e) and botObj is not None and loop is not None:
                    # Sometimes codes take a long time to arrive
                    timeout = 300  # 5 minutes
                    otp_code = asyncio.run_coroutine_threadsafe(
                        getOTPCodeDiscord(botObj, name, timeout=timeout, loop=loop),
                        loop,
                    ).result()
                    if otp_code is None:
                        raise Exception("No 2FA code found")
                    fb.login(
                        email=account,
                        wait_for_code=False,
                        code=otp_code,
                    )
                else:
                    raise e
            fennel_obj.set_logged_in_object(name, fb, "fb")
            account_ids = fb.get_account_ids()
            for i, an in enumerate(account_ids):
                account_name = f"Account {i + 1}"
                b = fb.get_portfolio_summary(an)
                fennel_obj.set_account_number(name, account_name)
                fennel_obj.set_account_totals(
                    name,
                    account_name,
                    b["cash"]["balance"]["canTrade"],
                )
                fennel_obj.set_logged_in_object(name, an, account_name)
                print(f"Found {account_name}")
            print(f"{name}: Logged in")
        except Exception as e:
            print(f"Error logging into Fennel: {e}")
            print(traceback.format_exc())
            continue
    print("Logged into Fennel!")
    return fennel_obj


def fennel_holdings(fbo: Brokerage, loop=None):
    for key in fbo.get_account_numbers():
        for account in fbo.get_account_numbers(key):
            obj: Fennel = fbo.get_logged_in_objects(key, "fb")
            account_id = fbo.get_logged_in_objects(key, account)
            try:
                # Get account holdings
                positions = obj.get_stock_holdings(account_id)
                if positions != []:
                    for holding in positions:
                        qty = holding["investment"]["ownedShares"]
                        if float(qty) == 0:
                            continue
                        sym = holding["security"]["ticker"]
                        cp = holding["security"]["currentStockPrice"]
                        if cp is None:
                            cp = "N/A"
                        fbo.set_holdings(key, account, sym, qty, cp)
            except Exception as e:
                printAndDiscord(f"Error getting Fennel holdings: {e}")
                print(traceback.format_exc())
                continue
    printHoldings(fbo, loop, False)


def fennel_transaction(fbo: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Fennel")
    print("==============================")
    print()
    for s in orderObj.get_stocks():
        for key in fbo.get_account_numbers():
            printAndDiscord(
                f"{key}: {orderObj.get_action()}ing {orderObj.get_amount()} of {s}",
                loop,
            )
            for account in fbo.get_account_numbers(key):
                obj: Fennel = fbo.get_logged_in_objects(key, "fb")
                account_id = fbo.get_logged_in_objects(key, account)
                try:
                    order = obj.place_order(
                        account_id=account_id,
                        ticker=s,
                        quantity=orderObj.get_amount(),
                        side=orderObj.get_action(),
                        dry_run=orderObj.get_dry(),
                    )
                    if orderObj.get_dry():
                        message = "Dry Run Success"
                        if not order.get("dry_run_success", False):
                            message = "Dry Run Failed"
                    else:
                        message = "Success"
                        if order.get("data", {}).get("createOrder") != "pending":
                            message = order.get("data", {}).get("createOrder")
                    printAndDiscord(
                        f"{key}: {orderObj.get_action()} {orderObj.get_amount()} of {s} in {account}: {message}",
                        loop,
                    )
                except Exception as e:
                    printAndDiscord(f"{key} {account}: Error placing order: {e}", loop)
                    print(traceback.format_exc())
                    continue
