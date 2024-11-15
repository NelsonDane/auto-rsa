# Kenneth Tang
# API to Interface with Fidelity
# Uses headless Playwright
# 2024/09/19
# Adapted from Nelson Dane's Selenium based code and created with the help of playwright codegen

import asyncio
import os
import traceback

from dotenv import load_dotenv
from fidelity import fidelity

from helperAPI import (
    Brokerage,
    getOTPCodeDiscord,
    maskString,
    printAndDiscord,
    printHoldings,
    stockOrder,
)


def fidelity_run(
    orderObj: stockOrder, command=None, botObj=None, loop=None, FIDELITY_EXTERNAL=None
):
    """
    Entry point from main function. Gathers credentials and go through commands for
    each set of credentials found in the FIDELITY env variable

    Returns:
        None
    """
    # Initialize .env file
    load_dotenv()
    # Import Chase account
    if not os.getenv("FIDELITY") and FIDELITY_EXTERNAL is None:
        print("Fidelity not found, skipping...")
        return None
    accounts = (
        os.environ["FIDELITY"].strip().split(",")
        if FIDELITY_EXTERNAL is None
        else FIDELITY_EXTERNAL.strip().split(",")
    )
    # Get headless flag
    headless = os.getenv("HEADLESS", "true").lower() == "true"
    # Set the functions to be run
    _, second_command = command

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
            botObj=botObj,
            loop=loop,
        )
        if fidelityobj is not None:
            # Store the Brokerage object for fidelity under 'fidelity' in the orderObj
            orderObj.set_logged_in(fidelityobj, "fidelity")
            if second_command == "_holdings":
                fidelity_holdings(fidelityobj, name, loop=loop)
            # Only other option is _transaction
            else:
                fidelity_transaction(fidelityobj, name, orderObj, loop=loop)
    return None


def fidelity_init(account: str, name: str, headless=True, botObj=None, loop=None):
    """
    Log into fidelity. Creates a fidelity brokerage object and a FidelityAutomation object.
    The FidelityAutomation object is stored within the brokerage object and some account information
    is gathered.

    Post conditions: Logs into fidelity using the supplied credentials

    Returns:
        fidelity_obj: Brokerage: A fidelity brokerage object that holds information on the account
        and the webdriver to use for further actions
    """

    # Log into Fidelity account
    print("Logging into Fidelity...")

    # Create brokerage class object and call it Fidelity
    fidelity_obj = Brokerage("Fidelity")

    try:
        # Split the login into into separate items
        account = account.split(":")
        # Create a Fidelity browser object
        fidelity_browser = fidelity.FidelityAutomation(
            headless=headless, title=name, profile_path="./creds"
        )

        # Log into fidelity
        step_1, step_2 = fidelity_browser.login(
            account[0], account[1], account[2] if len(account) > 2 else None
        )
        # If 2FA is present, ask for code
        if step_1 and not step_2:
            if botObj is None and loop is None:
                fidelity_browser.login_2FA(input("Enter code: "))
            else:
                # Should wait for 60 seconds before timeout
                sms_code = asyncio.run_coroutine_threadsafe(
                    getOTPCodeDiscord(botObj, name, code_len=6, loop=loop), loop
                ).result()
                if sms_code is None:
                    raise Exception(f"{name} No SMS code found", loop)
                fidelity_browser.login_2FA(sms_code)
        elif not step_1:
            raise Exception(
                f"{name}: Login Failed. Got Error Page: Current URL: {fidelity_browser.page.url}"
            )

        # By this point, we should be logged in so save the driver
        fidelity_obj.set_logged_in_object(name, fidelity_browser)

        # Getting account numbers, names, and balances
        account_dict = fidelity_browser.getAccountInfo()

        if account_dict is None:
            raise Exception(f"{name}: Error getting account info")
        # Set info into fidelity brokerage object
        for acct in account_dict:
            fidelity_obj.set_account_number(name, acct)
            fidelity_obj.set_account_type(name, acct, account_dict[acct]["nickname"])
            fidelity_obj.set_account_totals(name, acct, account_dict[acct]["balance"])
        print(f"Logged in to {name}!")
        return fidelity_obj

    except Exception as e:
        print(f"Error logging in to Fidelity: {e}")
        print(traceback.format_exc())
        return None


def fidelity_holdings(fidelity_o: Brokerage, name: str, loop=None):
    """
    Retrieves the holdings per account by reading from the previously downloaded positions csv file.
    Prints holdings for each account and provides a summary if the user has more than 5 accounts.

    Parameters:
        fidelity_o: Brokerage: The brokerage object that contains account numbers and the
        FidelityAutomation class object that is logged into fidelity
        name: str: The name of this brokerage object (ex: Fidelity 1)
        loop: AbstractEventLoop: The event loop to be used

    Returns:
        None
    """

    # Get the browser back from the fidelity object
    fidelity_browser: fidelity.FidelityAutomation = fidelity_o.get_logged_in_objects(
        name
    )
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
    printHoldings(fidelity_o, loop)

    # Close browser
    fidelity_browser.close_browser()


def fidelity_transaction(
    fidelity_o: Brokerage, name: str, orderObj: stockOrder, loop=None
):
    """
    Using the Brokerage object, call FidelityAutomation.transaction() and process its' return

    Parameters:
        fidelity_o: Brokerage: The brokerage object that contains account numbers and the
        FidelityAutomation class object that is logged into fidelity
        name: str: The name of this brokerage object (ex: Fidelity 1)
        orderObj: stockOrder: The stock object used for storing stocks to buy or sell
        loop: AbstractEventLoop: The event loop to be used

    Returns:
        None
    """

    # Get the driver
    fidelity_browser: fidelity.FidelityAutomation = fidelity_o.get_logged_in_objects(
        name
    )
    # Get full list of accounts in case some had no holdings
    fidelity_browser.get_list_of_accounts()
    # Go trade
    for stock in orderObj.get_stocks():
        # Say what we are doing
        printAndDiscord(
            f"{name}: {orderObj.get_action()}ing {orderObj.get_amount()} of {stock}",
            loop,
        )
        # Reload the page incase we were trading before
        fidelity_browser.page.reload()
        for account_number in fidelity_browser.account_dict:
            # If we are selling, check to see if the account has the stock to sell
            if (
                orderObj.get_action().lower() == "sell"
                and stock not in fidelity_browser.get_stocks_in_account(account_number)
            ):
                # Doesn't have it, skip account
                continue

            # Go trade for all accounts for that stock
            success, error_message = fidelity_browser.transaction(
                stock,
                orderObj.get_amount(),
                orderObj.get_action(),
                account_number,
                orderObj.get_dry(),
            )
            print_account = maskString(account_number)
            # Report error if occurred
            if not success:
                printAndDiscord(
                    f"{name} account {print_account}: Error: {error_message}",
                    loop,
                )
            # Print test run confirmation if test run
            elif success and orderObj.get_dry():
                printAndDiscord(
                    f"DRY: {name} account {print_account}: {orderObj.get_action()} {orderObj.get_amount()} shares of {stock}",
                    loop,
                )
            # Print real run confirmation if real run
            elif success and not orderObj.get_dry():
                printAndDiscord(
                    f"{name} account {print_account}: {orderObj.get_action()} {orderObj.get_amount()} shares of {stock}",
                    loop,
                )

    # Close browser
    fidelity_browser.close_browser()
