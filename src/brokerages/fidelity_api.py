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


def _load_fidelity_skip_accounts() -> set[str]:
    """Load excluded Fidelity account identifiers from the environment."""
    raw = os.getenv("FIDELITY_SKIP_ACCOUNTS", "")
    if not raw.strip():
        return set()
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _account_is_skipped(account_number: str, skip_accounts: set[str]) -> bool:
    """Return True when the account number matches an exclusion entry."""
    if not skip_accounts:
        return False
    return account_number.lower() in skip_accounts


def _fidelity_login(browser: fidelity.FidelityAutomation, username: str, password: str, totp_secret: str | None) -> tuple[bool, bool]:
    """Repo-owned Fidelity login flow that is more tolerant of Fidelity's current 2FA pages."""
    page = browser.page
    try:
        page.goto("https://digital.fidelity.com/prgw/digital/login/full-page", timeout=60000)
        page.wait_for_load_state(state="domcontentloaded")
        page.wait_for_timeout(2000)
        page.get_by_label("Username", exact=True).wait_for(state="visible", timeout=60000)
        page.get_by_label("Username", exact=True).fill(username)
        page.get_by_label("Password", exact=True).wait_for(state="visible", timeout=60000)
        page.get_by_label("Password", exact=True).fill(password)
        page.get_by_role("button", name="Log in").click()

        page.wait_for_timeout(3000)
        page.wait_for_load_state(state="domcontentloaded")

        if "summary" in page.url:
            return True, True

        totp_secret = None if totp_secret == "NA" else totp_secret  # noqa: S105
        code_field = page.get_by_placeholder("XXXXXX")
        if code_field.count() and code_field.first.is_visible():
            return True, False

        if page.get_by_role("link", name="Try another way").count() and page.get_by_role("link", name="Try another way").first.is_visible():
            page.get_by_role("link", name="Try another way").click()
            page.wait_for_timeout(1000)

        if code_field.count() and code_field.first.is_visible():
            return True, False

        if page.get_by_role("button", name="Text me the code").count() and page.get_by_role("button", name="Text me the code").first.is_visible():
            page.get_by_role("button", name="Text me the code").click()
            page.get_by_placeholder("XXXXXX").wait_for(state="visible", timeout=60000)
            return True, False

        if totp_secret is not None and page.get_by_role("heading", name="Enter the code from your").count() and page.get_by_role("heading", name="Enter the code from your").first.is_visible():
            return True, False

        if "signin/retail" in page.url or "login" in page.url:
            msg = f"Login page did not resolve to a recognizable 2FA state. Current URL: {page.url}"
            raise Exception(msg)
        msg = f"Cannot determine login state. Current URL: {page.url}"
        raise Exception(msg)
    except Exception as e:
        print(f"Error during Fidelity login flow: {e}")
        print(traceback.format_exc())
        raise


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
    skip_accounts = _load_fidelity_skip_accounts()

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
            skip_accounts=skip_accounts,
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


def fidelity_init(  # noqa: C901, PLR0912, PLR0915
    account: str,
    name: str,
    *,
    headless: bool = True,
    bot_obj: Bot | None = None,
    loop: asyncio.AbstractEventLoop | None = None,
    skip_accounts: set[str] | None = None,
) -> Brokerage | None:
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
        print(f"{name}: creating FidelityAutomation browser")
        fidelity_browser = fidelity.FidelityAutomation(
            headless=headless,
            title=name,
            profile_path="./creds",
        )
        print(f"{name}: browser created, page url={fidelity_browser.page.url}")
        # Fidelity's login page can render slowly, especially in visible mode.
        fidelity_browser.page.set_default_timeout(60000)
        fidelity_browser.page.set_default_navigation_timeout(60000)

        # Log into fidelity with repo-owned flow so we can handle current 2FA screens.
        print(f"{name}: starting login flow")
        step_1, step_2 = _fidelity_login(
            fidelity_browser,
            account_creds[0],
            account_creds[1],
            account_creds[2] if len(account_creds) > 2 else "NA",  # noqa: PLR2004
        )
        print(f"{name}: login flow returned step_1={step_1}, step_2={step_2}, url={fidelity_browser.page.url}")
        # If 2FA is present, ask for code
        if step_1 and not step_2:
            code = None
            if bot_obj is None and loop is None:
                code = input("Enter Fidelity SMS/TOTP code: ").strip()
            elif bot_obj is not None and loop is not None:
                # Should wait for 60 seconds before timeout
                sms_code = asyncio.run_coroutine_threadsafe(
                    get_otp_from_discord(bot_obj, name, code_len=6, loop=loop),
                    loop,
                ).result()
                if sms_code is None:
                    msg = f"{name}: No SMS code found"
                    raise Exception(msg, loop)
                code = sms_code.strip()

            if code:
                try:
                    fidelity_browser.page.get_by_placeholder("XXXXXX").wait_for(state="visible", timeout=60000)
                    fidelity_browser.page.get_by_placeholder("XXXXXX").fill(code)
                    remember_device = fidelity_browser.page.locator("label").filter(has_text="Don't ask me again on this")
                    if remember_device.count() and remember_device.first.is_visible():
                        remember_device.first.check()
                    submit_button = fidelity_browser.page.get_by_role("button", name="Submit")
                    if submit_button.is_visible():
                        submit_button.click()
                    else:
                        fidelity_browser.page.get_by_role("button", name="Continue").click()
                    fidelity_browser.page.wait_for_url(
                        "https://digital.fidelity.com/ftgw/digital/portfolio/summary",
                        timeout=180000,
                    )
                except Exception:
                    print(f"{name}: waiting for Fidelity to finish 2FA approval or SMS verification...")
                    print(f"{name}: current URL after 2FA submit: {fidelity_browser.page.url}")
        elif not step_1:
            msg = f"{name}: Login Failed. Got Error Page: Current URL: {fidelity_browser.page.url}"
            raise Exception(msg, loop)

        # By this point, we should be logged in so save the driver
        print(f"{name}: saving logged in browser session")
        fidelity_obj.set_logged_in_object(name, fidelity_browser)

        # Getting account numbers, names, and balances
        print(f"{name}: fetching account info")
        account_dict = fidelity_browser.getAccountInfo()
        print(f"{name}: account info fetch returned {None if account_dict is None else len(account_dict)} accounts")

        if account_dict is None:
            msg = f"{name}: Error getting account info"
            raise Exception(msg, loop)
        # Set info into fidelity brokerage object
        for acct in account_dict:
            if _account_is_skipped(acct, skip_accounts or set()):
                print(f"{name}: skipping excluded account {acct} ({account_dict[acct].get('nickname')})")
                continue
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
    skip_accounts = _load_fidelity_skip_accounts()
    for account_number in account_dict:
        if _account_is_skipped(account_number, skip_accounts):
            continue
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


def fidelity_transaction(  # noqa: C901
    fidelity_o: Brokerage,
    name: str,
    order_obj: StockOrder,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Call FidelityAutomation.transaction() and process its return."""
    # Get the driver
    fidelity_browser = cast("fidelity.FidelityAutomation", fidelity_o.get_logged_in_objects(name))
    skip_accounts = _load_fidelity_skip_accounts()
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
            if _account_is_skipped(account_number, skip_accounts):
                print(f"{name}: skipping excluded account {mask_string(account_number)}")
                continue
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
                if error_message == "Could not retrieve error message from popup":
                    try:
                        page_text = fidelity_browser.page.locator("body").inner_text(timeout=5000)
                        for candidate in ("009972", "restricted", "account specified in this order is restricted"):
                            if candidate.lower() in page_text.lower():
                                error_message = next(
                                    (line.strip() for line in page_text.splitlines() if candidate.lower() in line.lower()),
                                    page_text.strip(),
                                )
                                break
                    except Exception as e:
                        print(f"{name} account {print_account}: Error retrieving error message from page: {e}")
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
