import asyncio
import os
import traceback

from dotenv import load_dotenv
from fennel_invest_api import Fennel

from helperAPI import (
    Brokerage,
    getSMSCodeDiscord,
    maskString,
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
                    sms_code = asyncio.run_coroutine_threadsafe(
                        getSMSCodeDiscord(botObj, name, timeout=timeout, loop=loop),
                        loop,
                    ).result()
                    if sms_code is None:
                        raise Exception("No 2FA code found")
                    fb.login(
                        email=account,
                        wait_for_code=False,
                        code=sms_code,
                    )
                else:
                    raise e
            # Fenneldoesn't expose the account number
            an = "00000000"
            fennel_obj.set_logged_in_object(name, fb)
            fennel_obj.set_account_number(name, an)
            total_cash = fb.get_portfolio_summary()
            fennel_obj.set_account_totals(name, an, total_cash["cash"]["balance"]["canTrade"])
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
            obj: Fennel = fbo.get_logged_in_objects(key)
            try:
                # Get account holdings
                positions = obj.get_stock_holdings()
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
    printHoldings(fbo, loop)


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
                obj: Fennel = fbo.get_logged_in_objects(key)
                print_account = maskString(account)
                try:
                    order = obj.place_order(
                        ticker=s,
                        quantity=orderObj.get_amount(),
                        side=orderObj.get_action(),
                        dry_run=orderObj.get_dry(),
                    )
                    print(f"{key}: {order}")
                    printAndDiscord(
                        f"{key}: {orderObj.get_action()} {orderObj.get_amount()} of {s} in {print_account}: {order}",
                        loop,
                    )
                except Exception as e:
                    printAndDiscord(f"{key}: Error placing order: {e}", loop)
                    print(traceback.format_exc())
                    continue
