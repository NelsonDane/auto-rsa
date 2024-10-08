# Kenneth Tang
# API to Interface with Fidelity
# Uses headless Playwright
# 2024/09/19
# Adapted from Nelson Dane's Selenium based code and created with the help of playwright codegen

import asyncio
import csv
import json
import os
import traceback

import pyotp
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from playwright_stealth import StealthConfig, stealth_sync

from helperAPI import (
    Brokerage,
    getOTPCodeDiscord,
    printAndDiscord,
    printHoldings,
    stockOrder,
)


class FidelityAutomation:
    """
    A class to manage and control a playwright webdriver with Fidelity
    """

    def __init__(self, headless=True, title=None, profile_path=".") -> None:
        # Setup the webdriver
        self.headless: bool = headless
        self.title: str = title
        self.profile_path: str = profile_path
        self.account_dict: dict = {}
        self.stealth_config = StealthConfig(
            navigator_languages=False,
            navigator_user_agent=False,
            navigator_vendor=False,
        )
        self.getDriver()

    def getDriver(self):
        """
        Initializes the playwright webdriver for use in subsequent functions.
        Creates and applies stealth settings to playwright context wrapper.
        """
        # Set the context wrapper
        self.playwright = sync_playwright().start()

        # Create or load cookies
        self.profile_path = os.path.abspath(self.profile_path)
        if self.title is not None:
            self.profile_path = os.path.join(
                self.profile_path, f"Fidelity_{self.title}.json"
            )
        else:
            self.profile_path = os.path.join(self.profile_path, "Fidelity.json")
        if not os.path.exists(self.profile_path):
            os.makedirs(os.path.dirname(self.profile_path), exist_ok=True)
            with open(self.profile_path, "w") as f:
                json.dump({}, f)

        # Launch the browser
        self.browser = self.playwright.firefox.launch(
            headless=self.headless,
            args=["--disable-webgl", "--disable-software-rasterizer"],
        )

        self.context = self.browser.new_context(
            storage_state=self.profile_path if self.title is not None else None
        )
        self.page = self.context.new_page()
        # Apply stealth settings
        stealth_sync(self.page, self.stealth_config)

    def save_storage_state(self):
        """
        Saves the storage state of the browser to a file.

        This method saves the storage state of the browser to a file so that it can be restored later.

        Args:
            filename (str): The name of the file to save the storage state to.
        """
        storage_state = self.page.context.storage_state()
        with open(self.profile_path, "w") as f:
            json.dump(storage_state, f)

    def close_browser(self):
        """
        Closes the playwright browser
        Use when you are completely done with this class
        """
        # Save cookies
        self.save_storage_state()
        # Close context before browser as directed by documentation
        self.context.close()
        self.browser.close()
        # Stop the instance of playwright
        self.playwright.stop()

    def login(self, username: str, password: str, totp_secret: str = None) -> bool:
        """
        Logs into fidelity using the supplied username and password.

        Returns:
            True, True: If completely logged in, return (True, True)
            True, False: If 2FA is needed, this function will return (True, False) which signifies that the
            initial login attempt was successful but further action is needed to finish logging in.
            False, False: Initial login attempt failed.
        """
        try:
            # Go to the login page
            self.page.goto(
                "https://digital.fidelity.com/prgw/digital/login/full-page",
                timeout=60000,
            )

            # Login page
            self.page.get_by_label("Username", exact=True).click()
            self.page.get_by_label("Username", exact=True).fill(username)
            self.page.get_by_label("Password", exact=True).click()
            self.page.get_by_label("Password", exact=True).fill(password)
            self.page.get_by_role("button", name="Log in").click()
            try:
                # See if we got to the summary page
                self.page.wait_for_url(
                    "https://digital.fidelity.com/ftgw/digital/portfolio/summary",
                    timeout=30000,
                )
                # Got to the summary page, return True
                return (True, True)
            except PlaywrightTimeoutError:
                # Didn't get there yet, continue trying
                pass

            # Check to see if blank
            totp_secret = None if totp_secret == "NA" else totp_secret

            # If we hit the 2fA page after trying to login
            if "login" in self.page.url:

                # If TOTP secret is provided, we are will use the TOTP key. See if authenticator code is present
                if (
                    totp_secret is not None
                    and self.page.get_by_role(
                        "heading", name="Enter the code from your"
                    ).is_visible()
                ):
                    # Get authenticator code
                    code = pyotp.TOTP(totp_secret).now()
                    # Enter the code
                    self.page.get_by_placeholder("XXXXXX").click()
                    self.page.get_by_placeholder("XXXXXX").fill(code)

                    # Prevent future OTP requirements
                    self.page.locator("label").filter(
                        has_text="Don't ask me again on this"
                    ).check()
                    if (
                        not self.page.locator("label")
                        .filter(has_text="Don't ask me again on this")
                        .is_checked()
                    ):
                        raise Exception(
                            "Cannot check 'Don't ask me again on this device' box"
                        )

                    # Log in with code
                    self.page.get_by_role("button", name="Continue").click()

                    # See if we got to the summary page
                    self.page.wait_for_url(
                        "https://digital.fidelity.com/ftgw/digital/portfolio/summary",
                        timeout=5000,
                    )
                    # Got to the summary page, return True
                    return (True, True)

                # If the authenticator code is the only way but we don't have the secret, return error
                if self.page.get_by_text(
                    "Enter the code from your authenticator app This security code will confirm the"
                ).is_visible():
                    raise Exception(
                        "Fidelity needs code from authenticator app but TOTP secret is not provided"
                    )

                # If the app push notification page is present
                if self.page.get_by_role("link", name="Try another way").is_visible():
                    self.page.locator("label").filter(
                        has_text="Don't ask me again on this"
                    ).check()
                    if (
                        not self.page.locator("label")
                        .filter(has_text="Don't ask me again on this")
                        .is_checked()
                    ):
                        raise Exception(
                            "Cannot check 'Don't ask me again on this device' box"
                        )

                    # Click on alternate verification method to get OTP via text
                    self.page.get_by_role("link", name="Try another way").click()

                # Press the Text me button
                self.page.get_by_role("button", name="Text me the code").click()
                self.page.get_by_placeholder("XXXXXX").click()

                return (True, False)

            # Can't get to summary and we aren't on the login page, idk what's going on
            raise Exception("Cannot get to login page. Maybe other 2FA method present")

        except PlaywrightTimeoutError:
            print("Timeout waiting for login page to load or navigate.")
            return (False, False)
        except Exception as e:
            print(f"An error occurred: {str(e)}")
            traceback.print_exc()
            return (False, False)

    def login_2FA(self, code):
        """
        Completes the 2FA portion of the login using a phone text code.

        Returns:
            True: bool: If login succeeded, return true.
            False: bool: If login failed, return false.
        """
        try:
            self.page.get_by_placeholder("XXXXXX").fill(code)

            # Prevent future OTP requirements
            self.page.locator("label").filter(
                has_text="Don't ask me again on this"
            ).check()
            if (
                not self.page.locator("label")
                .filter(has_text="Don't ask me again on this")
                .is_checked()
            ):
                raise Exception("Cannot check 'Don't ask me again on this device' box")
            self.page.get_by_role("button", name="Submit").click()

            self.page.wait_for_url(
                "https://digital.fidelity.com/ftgw/digital/portfolio/summary",
                timeout=5000,
            )
            return True

        except PlaywrightTimeoutError:
            print("Timeout waiting for login page to load or navigate.")
            return False
        except Exception as e:
            print(f"An error occurred: {str(e)}")
            traceback.print_exc()
            return False

    def getAccountInfo(self):
        """
        Gets account numbers, account names, and account totals by downloading the csv of positions from fidelity.

        Post Conditions:
            self.account_dict is populated with holdings for each account
        Returns:
            account_dict: dict: A dictionary using account numbers as keys. Each key holds a dict which has:
            'balance': float: Total account balance
            'type': str: The account nickname or default name
            'stocks': list: A list of dictionaries for each stock found. The dict has:
                'ticker': str: The ticker of the stock held
                'quantity': str: The quantity of stocks with 'ticker' held
                'last_price': str: The last price of the stock with the $ sign removed
                'value': str: The total value of the position
        """
        # Go to positions page
        self.page.goto("https://digital.fidelity.com/ftgw/digital/portfolio/positions")

        # Download the positions as a csv
        with self.page.expect_download() as download_info:
            self.page.get_by_label("Download Positions").click()
        download = download_info.value
        cur = os.getcwd()
        positions_csv = os.path.join(cur, download.suggested_filename)
        # Create a copy to work on with the proper file name known
        download.save_as(positions_csv)

        csv_file = open(positions_csv, newline="", encoding="utf-8-sig")

        reader = csv.DictReader(csv_file)
        # Ensure all fields we want are present
        required_elements = [
            "Account Number",
            "Account Name",
            "Symbol",
            "Description",
            "Quantity",
            "Last Price",
            "Current Value",
        ]
        intersection_set = set(reader.fieldnames).intersection(set(required_elements))
        if len(intersection_set) != len(required_elements):
            raise Exception("Not enough elements in fidelity positions csv")

        for row in reader:
            # Skip empty rows
            if row["Account Number"] is None:
                continue
            # Last couple of rows have some disclaimers, filter those out
            if "and" in row["Account Number"]:
                break
            # Skip accounts that start with 'Y' (Fidelity managed)
            if row["Account Number"][0] == "Y":
                continue
            # Get the value and remove '$' from it
            val = str(row["Current Value"]).replace("$", "")
            # Get the last price
            last_price = str(row["Last Price"]).replace("$", "")
            # Get quantity
            quantity = str(row["Quantity"]).replace("-", "")
            # Get ticker
            ticker = str(row["Symbol"])

            # Don't include this if present
            if "Pending" in ticker:
                continue
            # If the value isn't present, move to next row
            if len(val) == 0:
                continue
            if val.lower() == "n/a":
                val = 0
            # If the last price isn't available, just use the current value
            if len(last_price) == 0:
                last_price = val
            # If the quantity is missing set it to 1 (SPAXX)
            if len(quantity) == 0:
                quantity = 1

            # If the account number isn't populated yet, add it
            if row["Account Number"] not in self.account_dict:
                # Add retrieved info.
                # Yeah I know is kinda messy and hard to think about but it works
                # Just need a way to store all stocks with the account number
                # 'stocks' is a list of dictionaries. Each ticker gets its own index and is described by a dictionary
                self.account_dict[row["Account Number"]] = {
                    "balance": float(val),
                    "type": row["Account Name"],
                    "stocks": [
                        {
                            "ticker": ticker,
                            "quantity": quantity,
                            "last_price": last_price,
                            "value": val,
                        }
                    ],
                }
            # If it is present, add to it
            else:
                self.account_dict[row["Account Number"]]["stocks"].append(
                    {
                        "ticker": ticker,
                        "quantity": quantity,
                        "last_price": last_price,
                        "value": val,
                    }
                )
                self.account_dict[row["Account Number"]]["balance"] += float(val)

        # Close the file
        csv_file.close()
        os.remove(positions_csv)

        return self.account_dict

    def summary_holdings(self) -> dict:
        """
        NOTE: The getAccountInfo function MUST be called before this, otherwise an empty dictionary will be returned
        Returns a dictionary containing dictionaries for each stock owned across all accounts.
        The keys of the outer dictionary are the tickers of the stocks owned.
        Ex: unique_stocks['NVDA'] = {'quantity': 2.0, 'last_price': 120.23, 'value': 240.46}
        'quantity': float: The number of stocks held of 'ticker'
        'last_price': float: The last price of the stock
        'value': float: The total value of the stocks held
        """

        unique_stocks = {}

        for account_number in self.account_dict:
            for stock_dict in self.account_dict[account_number]["stocks"]:
                # Create a list of unique holdings
                if stock_dict["ticker"] not in unique_stocks:
                    unique_stocks[stock_dict["ticker"]] = {
                        "quantity": float(stock_dict["quantity"]),
                        "last_price": float(stock_dict["last_price"]),
                        "value": float(stock_dict["value"]),
                    }
                else:
                    unique_stocks[stock_dict["ticker"]]["quantity"] += float(
                        stock_dict["quantity"]
                    )
                    unique_stocks[stock_dict["ticker"]]["value"] += float(
                        stock_dict["value"]
                    )

        # Create a summary of holdings
        summary = ""
        for stock, st_dict in unique_stocks.items():
            summary += f"{stock}: {round(st_dict['quantity'], 2)} @ {st_dict['last_price']} = {round(st_dict['value'], 2)}\n"
        return unique_stocks

    def transaction(
        self, stock: str, quantity: float, action: str, account: str, dry: bool = True
    ) -> bool:
        """
        Process an order (transaction) using the dedicated trading page.
        NOTE: If you use this function repeatedly but change the stock between ANY call,
        RELOAD the page before calling this

        For buying:
            If the price of the security is below $1, it will choose limit order and go off of the last price + a little
        For selling:
            Places a market order for the security

        Parameters:
            stock: str: The ticker that represents the security to be traded
            quantity: float: The amount to buy or sell of the security
            action: str: This must be 'buy' or 'sell'. It can be in any case state (i.e. 'bUY' is still valid)
            account: str: The account number to trade under.
            dry: bool: True for dry (test) run, False for real run.

        Returns:
            (Success: bool, Error_message: str) If the order was successfully placed or tested (for dry runs) then True is
            returned and Error_message will be None. Otherwise, False will be returned and Error_message will not be None
        """
        try:
            # Go to the trade page
            if (
                self.page.url
                != "https://digital.fidelity.com/ftgw/digital/trade-equity/index/orderEntry"
            ):
                self.page.goto(
                    "https://digital.fidelity.com/ftgw/digital/trade-equity/index/orderEntry"
                )

            # Click on the drop down
            self.page.query_selector("#dest-acct-dropdown").click()

            if (
                not self.page.get_by_role("option")
                .filter(has_text=account.upper())
                .is_visible()
            ):
                # Reload the page and hit the drop down again
                # This is to prevent a rare case where the drop down is empty
                print("Reloading...")
                self.page.reload()
                # Click on the drop down
                self.page.query_selector("#dest-acct-dropdown").click()
            # Find the account to trade under
            self.page.get_by_role("option").filter(has_text=account.upper()).click()

            # Enter the symbol
            self.page.get_by_label("Symbol").click()
            # Fill in the ticker
            self.page.get_by_label("Symbol").fill(stock)
            # Find the symbol we wanted and click it
            self.page.get_by_label("Symbol").press("Enter")

            # Wait for quote panel to show up
            self.page.locator("#quote-panel").wait_for(timeout=2000)
            last_price = self.page.query_selector(
                "#eq-ticket__last-price > span.last-price"
            ).text_content()
            last_price = last_price.replace("$", "")

            # Ensure we are in the expanded ticket
            if self.page.get_by_role(
                "button", name="View expanded ticket"
            ).is_visible():
                self.page.get_by_role("button", name="View expanded ticket").click()
                # Wait for it to take effect
                self.page.get_by_role("button", name="Calculate shares").wait_for(
                    timeout=2000
                )

            # When enabling extended hour trading
            extended = False
            precision = 3
            # Enable extended hours trading if available
            if self.page.get_by_text("Extended hours trading").is_visible():
                if self.page.get_by_text(
                    "Extended hours trading: OffUntil 8:00 PM ET"
                ).is_visible():
                    self.page.get_by_text(
                        "Extended hours trading: OffUntil 8:00 PM ET"
                    ).check()
                extended = True
                precision = 2

            # Press the buy or sell button. Title capitalizes the first letter so 'buy' -> 'Buy'
            self.page.query_selector(".eq-ticket-action-label").click()
            self.page.get_by_role(
                "option", name=action.lower().title(), exact=True
            ).wait_for()
            self.page.get_by_role(
                "option", name=action.lower().title(), exact=True
            ).click()

            # Press the shares text box
            self.page.locator("#eqt-mts-stock-quatity div").filter(
                has_text="Quantity"
            ).click()
            self.page.get_by_text("Quantity", exact=True).fill(str(quantity))

            # If it should be limit
            if float(last_price) < 1 or extended:
                # Buy above
                if action.lower() == "buy":
                    difference_price = 0.01 if float(last_price) > 0.1 else 0.0001
                    wanted_price = round(
                        float(last_price) + difference_price, precision
                    )
                # Sell below
                else:
                    difference_price = 0.01 if float(last_price) > 0.1 else 0.0001
                    wanted_price = round(
                        float(last_price) - difference_price, precision
                    )

                # Click on the limit default option when in extended hours
                self.page.query_selector(
                    "#dest-dropdownlist-button-ordertype > span:nth-child(1)"
                ).click()
                self.page.get_by_role("option", name="Limit", exact=True).click()
                # Enter the limit price
                self.page.get_by_text("Limit price", exact=True).click()
                self.page.get_by_label("Limit price").fill(str(wanted_price))
            # Otherwise its market
            else:
                # Click on the market
                self.page.locator("#order-type-container-id").click()
                self.page.get_by_role("option", name="Market", exact=True).click()

            # Continue with the order
            self.page.get_by_role("button", name="Preview order").click()

            # If error occurred
            try:
                self.page.get_by_role(
                    "button", name="Place order clicking this"
                ).wait_for(timeout=4000, state="visible")
            except PlaywrightTimeoutError:
                # Error must be present (or really slow page for some reason)
                # Try to report on error
                error_message = ""
                filtered_error = ""
                try:
                    error_message = (
                        self.page.get_by_label("Error")
                        .locator("div")
                        .filter(has_text="critical")
                        .nth(2)
                        .text_content(timeout=2000)
                    )
                    self.page.get_by_role("button", name="Close dialog").click()
                except Exception:
                    pass
                if error_message == "":
                    try:
                        error_message = self.page.wait_for_selector(
                            '.pvd-inline-alert__content font[color="red"]', timeout=2000
                        ).text_content()
                        self.page.get_by_role("button", name="Close dialog").click()
                    except Exception:
                        pass
                # Return with error and trim it down (it contains many spaces for some reason)
                if error_message != "":
                    for i, character in enumerate(error_message):
                        if (
                            (character == " " and error_message[i - 1] == " ")
                            or character == "\n"
                            or character == "\t"
                        ):
                            continue
                        filtered_error += character
                    filtered_error = filtered_error.replace("critical", "").strip()
                    error_message = filtered_error.replace("\n", "")
                else:
                    error_message = "Could not retrieve error message from popup"
                return (False, error_message)

            # If no error occurred, continue with checking the order preview
            if (
                not self.page.locator("preview")
                .filter(has_text=account.upper())
                .is_visible()
                or not self.page.get_by_text(
                    f"Symbol{stock.upper()}", exact=True
                ).is_visible()
                or not self.page.get_by_text(
                    f"Action{action.lower().title()}"
                ).is_visible()
                or not self.page.get_by_text(f"Quantity{quantity}").is_visible()
            ):
                return (False, "Order preview is not what is expected")

            # If its a real run
            if not dry:
                self.page.get_by_role(
                    "button", name="Place order clicking this"
                ).click()
                try:
                    # See that the order goes through
                    self.page.get_by_text("Order received").wait_for(
                        timeout=5000, state="visible"
                    )
                    # If no error, return with success
                    return (True, None)
                except PlaywrightTimeoutError:
                    # Order didn't go through for some reason, go to the next and say error
                    return (False, "Order failed to complete")
            # If its a dry run, report back success
            return (True, None)
        except PlaywrightTimeoutError:
            return (False, "Driver timed out. Order not complete")
        except Exception as e:
            return (False, e)


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
        fidelity_browser = FidelityAutomation(
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
            fidelity_obj.set_account_type(name, acct, account_dict[acct]["type"])
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
    fidelity_browser: FidelityAutomation = fidelity_o.get_logged_in_objects(name)
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
    fidelity_browser: FidelityAutomation = fidelity_o.get_logged_in_objects(name)
    # Go trade
    for stock in orderObj.get_stocks():
        # Say what we are doing
        printAndDiscord(
            f"{name}: {orderObj.get_action()}ing {orderObj.get_amount()} of {stock}",
            loop,
        )
        # Reload the page incase we were trading before
        fidelity_browser.page.reload()
        for account_number in fidelity_o.get_account_numbers(name):
            # Go trade for all accounts for that stock
            success, error_message = fidelity_browser.transaction(
                stock,
                orderObj.get_amount(),
                orderObj.get_action(),
                account_number,
                orderObj.get_dry(),
            )
            # Report error if occurred
            if not success:
                printAndDiscord(
                    f"{name} account xxxxx{account_number[-4:]}: {orderObj.get_action()} {orderObj.get_amount()} {error_message}",
                    loop,
                )
            # Print test run confirmation if test run
            elif success and orderObj.get_dry():
                printAndDiscord(
                    f"DRY: {name} account xxxxx{account_number[-4:]}: {orderObj.get_action()} {orderObj.get_amount()} shares of {stock}",
                    loop,
                )
            # Print real run confirmation if real run
            elif success and not orderObj.get_dry():
                printAndDiscord(
                    f"{name} account xxxxx{account_number[-4:]}: {orderObj.get_action()} {orderObj.get_amount()} shares of {stock}",
                    loop,
                )

    # Close browser
    fidelity_browser.close_browser()
