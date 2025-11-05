# Kenneth Tang
# API to Interface with Fidelity
# Uses headless Playwright
# 2024/09/19
# Adapted from Nelson Dane's Selenium based code and created with the help of playwright codegen

import asyncio
import os
import traceback
from typing import cast

from discord.ext.commands import Bot
from dotenv import load_dotenv
from fidelity import fidelity

from src.helper_api import Brokerage, StockOrder, get_otp_from_discord, mask_string, print_all_holdings, print_and_discord


def fidelity_run(
    order_obj: StockOrder,
    bot_obj: Bot | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Entry point from main function. Gathers credentials and go through commands for each set of credentials found in the FIDELITY env variable."""
    # Initialize .env file
    load_dotenv()
    # Import Chase account
    if not os.getenv("FIDELITY"):
        print("Fidelity not found, skipping...")
        return
    accounts = os.environ["FIDELITY"].strip().split(",")
    # Get headless flag
    headless = os.getenv("HEADLESS", "true").lower() == "true"

    # For each set of login info, i.e. separate chase accounts
    for account in accounts:
        # Start at index 1 and go to how many logins we have
        index = accounts.index(account) + 1
        name = f"Fidelity {index}"
        # Receive the chase broker class object and the AllAccount object related to it
        fidelityobj = fidelity_init(
            account=account,
            name=name,
            headless=headless,
            bot_obj=bot_obj,
            loop=loop,
        )
        if fidelityobj is not None:
            # Store the Brokerage object for fidelity under 'fidelity' in the orderObj
            order_obj.set_logged_in(fidelityobj, "fidelity")
            if order_obj.get_holdings():
                fidelity_holdings(fidelityobj, name, loop=loop)
            # Only other option is _transaction
            else:
                fidelity_transaction(fidelityobj, name, order_obj, loop=loop)
    return


def fidelity_init(account: str, name: str, *, headless: bool = True, bot_obj: Bot | None = None, loop: asyncio.AbstractEventLoop | None = None) -> Brokerage | None:
    """Log into fidelity. Creates a fidelity brokerage object and a FidelityAutomation object.

    The FidelityAutomation object is stored within the brokerage object and some account information
    is gathered.
    """
    # Log into Fidelity account
    print("Logging into Fidelity...")

    # Create brokerage class object and call it Fidelity
    fidelity_obj = Brokerage("Fidelity")

    try:
        # Split the login into into separate items
        account_creds = account.split(":")
        # Create a Fidelity browser object
        fidelity_browser = fidelity.FidelityAutomation(
            headless=headless,
            title=name,
            profile_path="./creds",
        )

        # Log into fidelity
        step_1, step_2 = cast(
            "tuple[bool, bool]",
            fidelity_browser.login(
                account_creds[0],
                account_creds[1],
                account_creds[2] if len(account_creds) > 2 else "NA",  # noqa: PLR2004
            ),
        )
        # If 2FA is present, ask for code
        if step_1 and not step_2:
            if bot_obj is None and loop is None:
                fidelity_browser.login_2FA(input("Enter code: "))
            elif bot_obj is not None and loop is not None:
                # Should wait for 60 seconds before timeout
                sms_code = asyncio.run_coroutine_threadsafe(
                    get_otp_from_discord(bot_obj, name, code_len=6, loop=loop),
                    loop,
                ).result()
                if sms_code is None:
                    msg = f"{name}: No SMS code found"
                    raise Exception(msg, loop)
                fidelity_browser.login_2FA(sms_code)
        elif not step_1:
            msg = f"{name}: Login Failed. Got Error Page: Current URL: {fidelity_browser.page.url}"
            raise Exception(msg, loop)

        # By this point, we should be logged in so save the driver
        fidelity_obj.set_logged_in_object(name, fidelity_browser)

        # Getting account numbers, names, and balances
        account_dict = fidelity_browser.getAccountInfo()

        if account_dict is None:
            msg = f"{name}: Error getting account info"
            raise Exception(msg, loop)
        # Set info into fidelity brokerage object
        for acct in account_dict:
            fidelity_obj.set_account_number(name, acct)
            fidelity_obj.set_account_type(name, acct, account_dict[acct]["nickname"])
            fidelity_obj.set_account_totals(name, acct, account_dict[acct]["balance"])
        print(f"Logged in to {name}!")

    except Exception as e:
        print(f"Error logging in to Fidelity: {e}")
        print(traceback.format_exc())
        return None
    else:
        return fidelity_obj


def fidelity_holdings(fidelity_o: Brokerage, name: str, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Get the holdings per account by reading from the previously downloaded positions csv file.

    Prints holdings for each account and provides a summary if the user has more than 5 accounts.
    """
    # Get the browser back from the fidelity object
    fidelity_browser = cast("fidelity.FidelityAutomation", fidelity_o.get_logged_in_objects(name))
    account_dict = fidelity_browser.account_dict
    for account_number in account_dict:
        for d in account_dict[account_number]["stocks"]:
            # Append the ticker to the appropriate account
            fidelity_o.set_holdings(
                parent_name=name,
                account_name=account_number,
                stock=d["ticker"],
                quantity=d["quantity"],
                price=d["last_price"],
            )

    # Print to console and to discord
    print_all_holdings(fidelity_o, loop)

    # Close browser
    fidelity_browser.close_browser()


def fidelity_transaction(
    fidelity_o: Brokerage,
    name: str,
    order_obj: StockOrder,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Call FidelityAutomation.transaction() and process its return."""
    # Get the driver
    fidelity_browser = cast("fidelity.FidelityAutomation", fidelity_o.get_logged_in_objects(name))
    # Get full list of accounts in case some had no holdings
    fidelity_browser.get_list_of_accounts()
    # Go trade
    for stock in order_obj.get_stocks():
        # Say what we are doing
        print_and_discord(
            f"{name}: {order_obj.get_action()}ing {order_obj.get_amount()} of {stock}",
            loop,
        )
        # Reload the page incase we were trading before
        fidelity_browser.page.reload()
        for account_number in fidelity_browser.account_dict:
            # If we are selling, check to see if the account has the stock to sell
            if order_obj.get_action().lower() == "sell" and stock not in fidelity_browser.get_stocks_in_account(account_number):
                # Doesn't have it, skip account
                continue

            # Go trade for all accounts for that stock
            success, error_message = cast(
                "tuple[bool, str | None]",
                fidelity_browser.transaction(
                    stock,
                    order_obj.get_amount(),
                    order_obj.get_action(),
                    account_number,
                    order_obj.get_dry(),
                ),
            )
            print_account = mask_string(account_number)
            # Report error if occurred
            if not success:
                print_and_discord(
                    f"{name} account {print_account}: Error: {error_message}",
                    loop,
                )
            # Print test run confirmation if test run
            elif success and order_obj.get_dry():
                print_and_discord(
                    f"DRY: {name} account {print_account}: {order_obj.get_action()} {order_obj.get_amount()} shares of {stock}",
                    loop,
                )
            # Print real run confirmation if real run
            elif success and not order_obj.get_dry():
                print_and_discord(
                    f"{name} account {print_account}: {order_obj.get_action()} {order_obj.get_amount()} shares of {stock}",
                    loop,
                )

    # Close browser
    fidelity_browser.close_browser()
