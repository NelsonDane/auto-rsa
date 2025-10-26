import os
import traceback

from dotenv import load_dotenv
from fennel_invest_api import Fennel, models
from email_validator import validate_email, EmailNotValidError
from helperAPI import (
    Brokerage,
    printAndDiscord,
    printHoldings,
    stockOrder
)


def fennel_init(FENNEL_EXTERNAL: str | None = None, botObj=None, loop=None):
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
            # The hold way was with an email. If we detect email, send message to tell them to switch
            try:
                validate_email(account)
                printAndDiscord(
                    f"{name}: Fennel no longer supports email login. Please switch to PAT tokens. See README for more info.",
                    loop,
                )
                continue
            except EmailNotValidError:
                pass
            # Login with PAT. If not error then we succeeded
            fb = Fennel(pat_token=account)
            fennel_obj.set_logged_in_object(name, fb, "fb")
            account_info = fb.get_account_info()
            for i, an in enumerate(account_info):
                b = fb.get_portfolio_cash_summary(account_id=an.id)
                fennel_obj.set_account_number(name, an.name)
                fennel_obj.set_account_totals(
                    name,
                    an.name,
                    b.cash_available,
                )
                fennel_obj.set_logged_in_object(name, an, an.name)
                print(f"Found {an.name}")
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
            obj: Fennel = fbo.get_logged_in_objects(key, "fb") # pyright: ignore[reportAssignmentType]
            account_info: models.accounts_pb2.Account = fbo.get_logged_in_objects(key, account)
            try:
                # Get account holdings
                positions = obj.get_portfolio_positions(account_id=account_info.id)
                if positions != []:
                    for holding in positions:
                        if int(holding.shares) == 0:
                            continue
                        price = holding.value
                        if price is None:
                            price = "N/A"
                        fbo.set_holdings(key, account, holding.symbol, holding.shares, price)
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
                obj: Fennel = fbo.get_logged_in_objects(key, "fb") # pyright: ignore[reportAssignmentType]
                account_info: models.accounts_pb2.Account = fbo.get_logged_in_objects(key, account)
                try:
                    if not orderObj.get_dry():
                        order = obj.place_order(
                            account_id=account_info.id,
                            symbol=s,
                            shares=orderObj.get_amount(),
                            side="BUY" if orderObj.get_action().lower() == "buy" else "SELL"
                        )
                        message = f"Success: {order.success}, Status: {order.status}, ID: {order.id}"
                    else:
                        message = "Dry Run Success"
                    printAndDiscord(
                        f"{key}: {orderObj.get_action()} {orderObj.get_amount()} of {s} in {account}: {message}",
                        loop,
                    )
                except Exception as e:
                    printAndDiscord(f"{key} {account}: Error placing order: {e}", loop)
                    print(traceback.format_exc())
                    continue
