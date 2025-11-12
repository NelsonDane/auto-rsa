import os
import traceback
from asyncio import AbstractEventLoop
from typing import TYPE_CHECKING, cast

from dotenv import load_dotenv
from email_validator import EmailNotValidError, validate_email
from fennel_invest_api import Fennel

from src.helper_api import Brokerage, StockOrder, print_all_holdings, print_and_discord

if TYPE_CHECKING:
    from fennel_invest_api.models.accounts_pb2 import Account


def fennel_init(loop: AbstractEventLoop | None = None) -> Brokerage | None:
    """Initialize Fennel API."""
    # Initialize .env file
    load_dotenv()
    # Import Fennel account
    fennel_obj = Brokerage("Fennel")
    if not os.getenv("FENNEL"):
        print("Fennel not found, skipping...")
        return None
    big_fennel = os.environ["FENNEL"].strip().split(",")
    # Log in to Fennel account
    print("Logging in to Fennel...")
    for index, account in enumerate(big_fennel):
        name = f"Fennel {index + 1}"
        try:
            # The hold way was with an email. If we detect email, send message to tell them to switch
            try:
                validate_email(account)
                print_and_discord(
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
            for an in account_info:
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


def fennel_holdings(fbo: Brokerage, loop: AbstractEventLoop | None = None) -> None:
    """Retrieve and display all Fennel account holdings."""
    for key in fbo.get_account_numbers():
        obj = cast("Fennel", fbo.get_logged_in_objects(key, "fb"))
        for account in fbo.get_account_numbers(key):
            account_info = cast("Account", fbo.get_logged_in_objects(key, account))
            try:
                # Get account holdings
                positions = obj.get_portfolio_positions(account_id=account_info.id)
                if positions != []:
                    for holding in positions:
                        if int(holding.shares) == 0:
                            continue
                        price = holding.value if holding.value is not None else "N/A"
                        fbo.set_holdings(key, account, holding.symbol, holding.shares, price)
            except Exception as e:
                print_and_discord(f"Error getting Fennel holdings: {e}")
                print(traceback.format_exc())
                continue
    print_all_holdings(fbo, loop, mask_account_number=False)


def fennel_transaction(fbo: Brokerage, order_obj: StockOrder, loop: AbstractEventLoop | None = None) -> None:
    """Handle Fennel API transactions."""
    print()
    print("==============================")
    print("Fennel")
    print("==============================")
    print()
    for s in order_obj.get_stocks():
        for key in fbo.get_account_numbers():
            print_and_discord(
                f"{key}: {order_obj.get_action()}ing {order_obj.get_amount()} of {s}",
                loop,
            )
            for account in fbo.get_account_numbers(key):
                obj = cast("Fennel", fbo.get_logged_in_objects(key, "fb"))
                account_info = cast("Account", fbo.get_logged_in_objects(key, account))
                try:
                    if not order_obj.get_dry():
                        order = obj.place_order(
                            account_id=account_info.id,
                            symbol=s,
                            shares=order_obj.get_amount(),
                            side="BUY" if order_obj.get_action().lower() == "buy" else "SELL",
                        )
                        message = f"Success: {order.success}, Status: {order.status}, ID: {order.id}"
                    else:
                        message = "Dry Run Success"
                    print_and_discord(
                        f"{key}: {order_obj.get_action()} {order_obj.get_amount()} of {s} in {account}: {message}",
                        loop,
                    )
                except Exception as e:
                    print_and_discord(f"{key} {account}: Error placing order: {e}", loop)
                    print(traceback.format_exc())
                    continue
