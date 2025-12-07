import os
import traceback
import json

import pyotp
import typing
from typing import Literal
import re

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright_stealth import StealthConfig, stealth_sync
import csv
from enum import Enum

# Needed for the download_prev_statement function
class fid_months(Enum):
    """
    Months that fidelity uses in the statement labeling
    """
    Jan = 1
    Feb = 2
    March = 3
    April = 4
    May = 5
    June = 6
    July = 7
    Aug = 8
    Sep = 9
    Oct = 10
    Nov = 11
    Dec = 12

class FidelityAutomation:
    """
    A class to manage and control a playwright webdriver with Fidelity.
    If you have multiple login sets and want to use cookies, make sure "title" is unique each time you create this class,
    otherwise the cookies will be overwritten each time. 

    Parameters
    ----------
    headless (bool)
        If False the browser will be headless.
    debug (bool)
        If the driver should print debug info. 
    title (str)
        The title of this session. Used for cookies file is present.
    source_account (str)
        Account to use as the "From" account for transfers.
    save_state (bool)
        Determine whether to save cookies in a json file.
    profile_path (str)
        Path used to store browser session data.

    """

    def __init__(self, headless: bool = True, debug: bool = False, title: str = None, source_account: str = None, save_state: bool = True, profile_path: str = ".") -> None:
        """
        Setup the class, create the driver, and apply stealth settings.
        """
        # Setup the webdriver
        self.headless: bool = headless
        self.title: str = title
        self.save_state: bool = save_state
        self.debug = debug
        self.profile_path: str = profile_path
        self.stealth_config = StealthConfig(
            navigator_languages=False,
            navigator_user_agent=False,
            navigator_vendor=False,
        )
        self.getDriver()
        # Some class variables
        self.account_dict: dict = {}
        self.source_account = source_account
        self.new_account_number = None

    def getDriver(self):
        """
        Initializes the playwright webdriver for use in subsequent functions.
        Creates and applies stealth settings to playwright context wrapper.
        If self.save_state is set to True, create a storage path for cookies and data

        Returns
        -------
        None
        """
        # Set the context wrapper
        self.playwright = sync_playwright().start()

        # Create or load cookies if save_state is set
        if self.save_state:
            self.profile_path = os.path.abspath(self.profile_path)
            # If title was given
            if self.title is not None:
                # Use the title for the json file
                self.profile_path = os.path.join(
                    self.profile_path, f"Fidelity_{self.title}.json"
                )
            else:
                # Use default name for json file
                self.profile_path = os.path.join(self.profile_path, "Fidelity.json")
            # If the path supplied doesn't exist, make it
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
            # If we want to save cookies and session data, set a path, else set to None
            storage_state=self.profile_path if self.save_state else None
        )

        # Take screenshots on actions
        if self.debug:
            self.context.tracing.start(name="fidelity_trace", screenshots=True, snapshots=True)

        self.page = self.context.new_page()
        # Apply stealth settings
        stealth_sync(self.page, self.stealth_config)

    def get_list_of_accounts(self, set_flag: bool = True, get_withdrawal_bal: bool = False):
        """
        Uses the transfers page's dropdown to obtain the list of accounts.
        Separates the account number and nickname and places them into `self.account_dict`
        if not already present

        Parameters
        ----------
        set_flag (bool) = True
            If set_flag is false, `self.account_dict` will not be updated
        get_withdrawal_bal (bool) = False
            If set to true, the function will provide the available balance that can be withdrawn from the account

        Post conditions
        ---------------
        `self.account_dict` is updated with account numbers and nicknames if set_flag is True or omitted

        Returns
        -------
        account_dict
            A dictionary of the account information using account numbers as keys. See set_account_dict
            for more info on how to use this dictionary.
        """
        try:
            # Go to the transfers page
            self.page.wait_for_load_state(state="load")
            self.page.goto(url="https://digital.fidelity.com/ftgw/digital/transfer/?quicktransfer=cash-shares")
            self.wait_for_loading_sign()

            # Select the source account from the 'From' dropdown
            from_select = self.page.get_by_label("From")
            options = from_select.locator("option").all()

            local_dict = {}
            # Get account number and nickname
            for option in options:
                # Try to find accounts by using a regular expression
                # This regex matches a string of numbers starting with a Z or a digit that
                # has a '(' in front of it and a ')' at the end. Must have at least 6 digits after the
                # Z or first digit.
                account_number = re.search(r'(?<=\()(Z|\d)\d{6,}(?=\))', option.inner_text())
                nickname = re.search(r'^.+?(?=\()', option.inner_text())
                with_bal = None

                # Get withdrawal balance once we find a valid account
                if get_withdrawal_bal and account_number and nickname:
                    # Select the account in the dropdown
                    acc_drpdwn_value = option.get_attribute("value")
                    from_select.select_option(acc_drpdwn_value)
                    # Wait for balance info to update. This is very fast but there is a delay
                    self.page.wait_for_timeout(100)
                    # Find the balance
                    with_bal = self.page.locator("tr.pvd-table__row:nth-child(2) > td:nth-child(2)").inner_text()
                    with_bal = float(with_bal.replace("$", "").replace(",", ""))

                # Add to the account dict
                if set_flag and account_number and nickname:
                    # Create entry if not already there
                    if not self.set_account_dict(
                        account_num=account_number.group(0),
                        nickname=nickname.group(0),
                        withdrawal_balance=with_bal if with_bal is not None else 0.0
                    ):
                        # If entry exists, overwrite withdrawal balance
                        self.add_withdrawal_bal_to_account_dict(
                            account_num=account_number.group(0),
                            withdrawal_balance=with_bal if with_bal is not None else 0.0,
                            overwrite=True
                        )
                        # Same with nickname
                        self.add_nickname_to_account_dict(
                            account_num=account_number.group(0),
                            nickname=nickname.group(0),
                            overwrite=True
                        )
                # Or to local copy
                elif not set_flag and account_number and nickname:
                    local_dict[account_number.group(0)] = {
                        "balance": 0.0,
                        "withdrawal_balance": with_bal if with_bal is not None else 0.0,
                        "nickname": nickname.group(0),
                        "stocks": []
                    }
            if not set_flag:
                return local_dict
            
            return self.account_dict

        except Exception as e:
            print(f"An error occurred in get_list_of_accounts: {str(e)}")
            return None

    def get_stocks_in_account(self, account_number: str) -> dict:
        """
        `self.getAccountInfo() must be called before this to work

        Returns
        -------
        all_stock_dict (dict)
            A dict of stocks that the account has.
            The dict is keyed by stocks and only has the quantity. 
            `all_stock_dict[stock] = quantity (int)`
        """
        if account_number in self.account_dict:
            all_stock_dict = {}
            for single_stock_dict in self.account_dict[account_number]["stocks"]:
                stock = single_stock_dict.get("ticker", None)
                quantity = single_stock_dict.get("quantity", None)
                if stock is not None and quantity is not None:
                    all_stock_dict[stock] = quantity

            return all_stock_dict

        return None

    def getAccountInfo(self):
        """
        Gets account numbers, account names, and account totals by downloading the csv of positions
        from fidelity.
        `Note` This will miss accounts that have no holdings! The positions csv doesn't show accounts
        with only pending activity either. Use `self.get_list_of_accounts` for a full list of accounts.

        Post Conditions:
            self.account_dict is populated with holdings for each account

        Returns
        -------
        account_dict (dict)
            A dictionary using account numbers as keys. Each key holds a dict which has:
            ```
            {
                'balance': float: Total account balance
                'nickname': str: The account nickname or default name
                "withdrawal_balance": Use get_list_of_accounts() to populate
                'stocks': list: A list of dictionaries for each stock found. The dict has:
                    {
                        'ticker': str: The ticker of the stock held
                        'quantity': str: The quantity of stocks with 'ticker' held
                        'last_price': str: The last price of the stock with the $ sign removed
                        'value': str: The total value of the position
                    }
            }
            ```
        None
            If an error occurred
        """
        try:
            # Go to positions page
            self.page.wait_for_load_state(state="load")
            self.page.goto("https://digital.fidelity.com/ftgw/digital/portfolio/positions")
            
            # This double wait is necessary. If you remove it, I'll kill you
            self.wait_for_loading_sign()
            self.page.wait_for_timeout(1000)
            # Sometimes this can take a while to load. Set to 2.5 minutes
            self.wait_for_loading_sign(timeout=2.5*60*1000)

            # Download the positions as a csv #
            # See if new UI is present
            new_ui = True
            try:
                self.page.get_by_role("button", name="Available Actions").click(timeout=8000)
                with self.page.expect_download() as download_info:
                    self.page.get_by_role("menuitem", name="Download").click()
                download = download_info.value
            except PlaywrightTimeoutError:
                new_ui = False
            if not new_ui:
                try:
                    # Use the old UI
                    with self.page.expect_download() as download_info:
                        self.page.get_by_label("Download Positions").click(timeout=8000)
                    download = download_info.value
                except PlaywrightTimeoutError:
                    print("Could not get positions csv")
                    return None
            # Get absolute path to file
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
                "Last Price Change",
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
                cur_val = str(row["Current Value"]).replace("$", "").replace("-", "")
                # Get the last price
                last_price = str(row["Last Price"]).replace("$", "").replace("-", "")
                # Get the last price change
                last_price_change = str(row["Last Price Change"]).replace("$", "")
                # Get quantity
                quantity = str(row["Quantity"]).replace("-", "")
                # Get ticker
                ticker = str(row["Symbol"])

                # Catch any pending activity with special handling
                if "Pending" in ticker:
                    cur_val = last_price_change
                # If the value isn't present, move to next row
                if len(cur_val) == 0:
                    continue
                # If the last price isn't available, just use the current value
                if len(last_price) == 0:
                    last_price = cur_val
                # If the quantity is missing set it to 1 (For SPAXX or any other cash position)
                if len(quantity) == 0:
                    quantity = 1
                
                # Check for anything that isn't a number 
                try:
                    float(cur_val)
                except ValueError:
                    cur_val = 0
                try:
                    float(last_price)
                except ValueError:
                    last_price = 0
                try:
                    float(quantity)
                except ValueError:
                    quantity = 0

                # Create list of dictionary for stock found
                stock_list = [create_stock_dict(ticker, float(quantity), float(last_price), float(cur_val))]
                # Try setting in the account dict without overwrite
                if not self.set_account_dict(
                    account_num=row["Account Number"],
                    balance=float(cur_val),
                    nickname=row["Account Name"],
                    stocks=stock_list,
                    overwrite=False,
                ):
                    # If the account exists already, add to it
                    self.add_stock_to_account_dict(row["Account Number"], stock_list[0])

            # Close the file
            csv_file.close()
            # Delete the file
            os.remove(positions_csv)

            return self.account_dict
        except Exception as e:
            print(f"Error in getAccountInfo: {e}")
            return None

    def set_account_dict(self, account_num: str, balance: float = None, withdrawal_balance: float = None, nickname: str = None, stocks: list = None, overwrite: bool = False):
        """
        Create or rewrite (if overwrite=True) an entry in the account_dict.
        The dictionary is keyed with account numbers such that:
        ```
        account_dict["12345678"] = 
        {
            "balance": balance if balance is not None else 0.0,
            "withdrawal_balance": withdrawal_balance if withdrawal_balance is not None else 0.0,
            "nickname": nickname,
            "stocks": stocks if stocks is not None else []
        }
        ```

        Parameters
        ----------
        account_num (str)
            The account number of a Fidelity account with no parenthesis. Ex: Z12345678
        balance (float)
            The balance of the account if present.
        withdrawal_balance (float)
            The available balance that can be withdrawn from the account as cash
        nickname (str)
            The nickname of the account. Ex: Individual
        stocks (list)
            A list of dictionaries that contain stock info. Each dictionary is defined as:
            ```
            {
                'ticker': str,
                'quantity': float,
                'last_price': float,
                'value': float
            }
            ```
        overwrite (bool)
            Whether to overwrite an existing entry if found.

        Returns
        -------
        True
            If successful

        False
            If entry exists and overwrite=False or stock list is incorrect
        """
        # Overwrite or create new entry
        if overwrite or account_num not in self.account_dict:
            # Check stocks first. This returns true is stocks is None
            if not validate_stocks(stocks):
                return False

            # Use the info given
            self.account_dict[account_num] = {
                "balance": round(balance, 2) if balance is not None else 0.0,
                "withdrawal_balance": round(withdrawal_balance, 2) if withdrawal_balance is not None else 0.0,
                "nickname": nickname,
                "stocks": stocks if stocks is not None else []
            }
            return True
        
        return False

    def add_stock_to_account_dict(self, account_num: str, stock: dict, overwrite: bool = False):
        """
        Add a stock to the account dict under an account.
        You can use/import `create_stock_dict` for help.

        Returns
        -------
        True
            If successful
        False
            If account doesn't yet exist in account_dict
        """
        if not validate_stocks([stock]):
            return False
        if account_num in self.account_dict:
            if overwrite:
                self.account_dict[account_num]["stocks"] = [stock]
                self.account_dict[account_num]["balance"] = round(stock["value"], 2)
            else:
                self.account_dict[account_num]["stocks"].append(stock)
                self.account_dict[account_num]["balance"] += round(stock["value"], 2)
            return True
        return False

    def add_withdrawal_bal_to_account_dict(self, account_num: str, withdrawal_balance: float, overwrite: bool = False):
        """
        Add the cash available to withdrawal to the account_dict if it is 0 or overwriting

        Returns
        -------
        True
            If successful
        False
            If account doesn't yet exist in account_dict
        """
        if (account_num in self.account_dict and
           (overwrite or self.account_dict["withdrawal_balance"] == 0.0)
        ):
            self.account_dict[account_num]["withdrawal_balance"] = withdrawal_balance
            return True
        return False

    def add_nickname_to_account_dict(self, account_num: str, nickname: str, overwrite: bool = False):
        """
        Add the nickname to the account_dict if it is not set or overwriting

        Returns
        -------
        True
            If successful
        False
            If account doesn't yet exist in account_dict
        """
        if (account_num in self.account_dict and
           (overwrite or self.account_dict["nickname"] is None)
        ):
            self.account_dict[account_num]["nickname"] = nickname
            return True
        return False

    def save_storage_state(self):
        """
        Saves the storage state of the browser to a file.

        This method saves the storage state of the browser to a file so that it can be restored later.
        This will do nothing if the class object was initialized with save_state=False
        """
        if self.save_state:
            storage_state = self.page.context.storage_state()
            with open(self.profile_path, "w") as f:
                json.dump(storage_state, f)

    def close_browser(self):
        """
        Closes the playwright browser.
        Use when you are completely done with this class.
        """
        # Save cookies
        self.save_storage_state()
        # Save screenshots if debugging
        if self.debug:
            self.context.tracing.stop(path=f'./fidelity_trace{self.title if self.title is not None else ""}.zip')
        # Close context before browser as directed by documentation
        self.context.close()
        self.browser.close()
        # Stop the instance of playwright
        self.playwright.stop()

    def login(self, username: str, password: str, totp_secret: str = None, save_device: bool = False) -> tuple[bool, bool]:
        """
        Logs into fidelity using the supplied username and password.

        If totp_secret is missing, the function will use sms code and login_2FA must be called with
        the code to complete the login

        Highly encouraged to use TOTP Secrets and to not save the device during login.
        Not saving the device allows other functions like open_account and enable_pennystock_trading
        to work reliably.

        Parameters
        ----------
        username (str)
            The username of the user.
        password (str)
            The password of the user.
        totp_secret (str)
            The totp secret, if using, of the user.
        save_device (bool)
            Flag to allow fidelity to remember this device.

        Returns
        -------
        True, True
            If completely logged in

        True, False
            If 2FA is needed which signifies that the initial login attempt was successful but further action is needed to finish logging in.

        False, False
            Initial login attempt failed.
        """
        try:
            # Go to the login page
            self.page.goto(
                url="https://digital.fidelity.com/prgw/digital/login/full-page",
                timeout=60000,
            )

            # Login page
            self.page.get_by_label("Username", exact=True).click()
            self.page.get_by_label("Username", exact=True).fill(username)
            self.page.get_by_label("Password", exact=True).click()
            self.page.get_by_label("Password", exact=True).fill(password)
            self.page.get_by_role("button", name="Log in").click()

            # Wait for loading spinner to go away
            self.wait_for_loading_sign()
            # The first spinner goes away then another one appears
            # This has been tested many times and this is necessary
            self.page.wait_for_timeout(1000)
            self.wait_for_loading_sign()

            if "summary" in self.page.url:
                return (True, True)

            # Check to see if TOTP secret is blank or "NA"
            totp_secret = None if totp_secret == "NA" else totp_secret

            # If we hit the 2fA page after trying to login
            if "login" in self.page.url:
                self.wait_for_loading_sign()
                widget = self.page.locator("#dom-widget div").first
                widget.wait_for(timeout=5000, state='visible')
                # If TOTP secret is provided, we are will use the TOTP key. See if authenticator code prompt is present
                if (totp_secret is not None and
                    self.page.get_by_role("heading", name="Enter the code from your").is_visible()
                ):
                    # Get authenticator code
                    code = pyotp.TOTP(totp_secret).now()
                    # Enter the code
                    self.page.get_by_placeholder("XXXXXX").click()
                    self.page.get_by_placeholder("XXXXXX").fill(code)

                    # Prevent future OTP requirements
                    if save_device:
                        # Check this box
                        self.page.locator("label").filter(has_text="Don't ask me again on this").check()
                        if (not self.page.locator("label").filter(has_text="Don't ask me again on this").is_checked()):
                            raise Exception("Cannot check 'Don't ask me again on this device' box")

                    # Log in with code
                    self.page.get_by_role("button", name="Continue").click()

                    # Wait for loading spinner to go away
                    self.wait_for_loading_sign()

                    # See if we got to the summary page
                    self.page.wait_for_url(
                        "https://digital.fidelity.com/ftgw/digital/portfolio/summary",
                        timeout=20000,
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
                    if save_device:
                        self.page.locator("label").filter(has_text="Don't ask me again on this").check()
                        if (not self.page.locator("label").filter(has_text="Don't ask me again on this").is_checked()):
                            raise Exception("Cannot check 'Don't ask me again on this device' box")

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
            traceback.print_exc()
            return (False, False)
        except Exception as e:
            print(f"An error occurred: {str(e)}")
            traceback.print_exc()
            return (False, False)

    def login_2FA(self, code: str, save_device: bool = True):
        """
        Completes the 2FA portion of the login using a phone text code.

        Parameters
        ----------
        code (str)
            The one time code sent to the user's phone
        save_device (bool)
            Flag to allow fidelity to remember this device.

        Returns
        -------
        True (bool)
            If login succeeded, return true.
        False (bool)
            If login failed, return false.
        """
        try:
            self.page.get_by_placeholder("XXXXXX").fill(code)

            if save_device:
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

    def summary_holdings(self) -> dict:
        """
        The getAccountInfo function `MUST` be called before this, otherwise an empty dictionary will be returned.
        The keys of the outer dictionary are the tickers of the stocks owned.
        Ex: `unique_stocks['NVDA'] = {'quantity': 2.0, 'last_price': 120.23, 'value': 240.46}`
        
        Returns
        -------
        unique_stocks (dict)
            A dictionary containing dictionaries for each stock owned across all accounts.
            ```
            {
                'quantity': float: The number of stocks held of 'ticker'
                'last_price': float: The last price of the stock
                'value': float: The total value of the stocks held
            }
            ```
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

        return unique_stocks

    def transaction(self, stock: str, quantity: float, action: str, account: str, dry: bool = True, limit_price: float = None) -> bool:
        """
        Process an order (transaction) using the dedicated trading page. Support extended hour trading.

        `NOTE`: If you use this function repeatedly but change the stock between ANY call,
        RELOAD the page before calling this. You can do this like so:
        ```
        FidelityAutomation.page.reload()
        ```

        For buying:
            If the price of the security is below $1, it will choose limit order and go off of the last price + a little
        For selling:
            Places a market order for the security

        Parameters
        ----------
        stock (str)
            The ticker that represents the security to be traded
        quantity (float)
            The amount to buy or sell of the security
        action (str)
            This must be 'buy' or 'sell'. It can be in any case state (i.e. 'bUY' is still valid)
        account (str)
            The account number to trade under.
        dry (bool)
            True for dry (test) run, False for real run.

        Returns
        -------
        (Success (bool), Error_message (str))
            If the order was successfully placed or tested (for dry runs) then True is
            returned and Error_message will be None. Otherwise, False will be returned and Error_message will not be None
        """
        try:
            # Go to the trade page
            self.page.wait_for_load_state(state="load")
            if (self.page.url != "https://digital.fidelity.com/ftgw/digital/trade-equity/index/orderEntry"):
                self.page.goto("https://digital.fidelity.com/ftgw/digital/trade-equity/index/orderEntry")

            # Find the account to trade under with retries to avoid transient dropdown issues
            account_clicked = False
            for attempt in range(3):
                self.page.query_selector("#dest-acct-dropdown").click()
                account_option = self.page.get_by_role("option").filter(has_text=account.upper()).first
                try:
                    account_option.wait_for(timeout=5000)
                except PlaywrightTimeoutError:
                    pass
                if account_option.count() > 0 and account_option.is_visible():
                    try:
                        account_option.click()
                        account_clicked = True
                        break
                    except PlaywrightTimeoutError:
                        pass
                # Retry: reload page and try again
                if attempt < 2:
                    print("Reloading...")
                    self.page.reload()
                    self.page.wait_for_load_state(state="load")
            if not account_clicked:
                return (False, f"Account {account} not available in trade dropdown after retries")

            # Enter the symbol
            self.page.get_by_label("Symbol", exact=True).click()
            # Fill in the ticker
            self.page.get_by_label("Symbol", exact=True).fill(stock)
            # Force the search to use exactly what was entered
            self.page.get_by_label("Symbol", exact=True).press("Enter")

            # Wait for quote panel to show up
            self.page.locator("#quote-panel").wait_for(timeout=5000)
            last_price = self.page.query_selector("#eq-ticket__last-price > span.last-price").text_content()
            last_price = last_price.replace("$", "")

            # Ensure we are in the expanded ticket
            if self.page.get_by_role("button", name="View expanded ticket").is_visible():
                self.page.get_by_role("button", name="View expanded ticket").click()
                # Wait for it to take effect
                self.page.get_by_role("button", name="Calculate shares").wait_for(timeout=5000)

            # When enabling extended hour trading
            extended = False
            precision = 3
            # Enable extended hours trading if available
            if self.page.get_by_text("Extended hours trading").is_visible():
                if self.page.get_by_text("Extended hours trading: OffUntil 8:00 PM ET").is_visible():
                    self.page.get_by_text("Extended hours trading: OffUntil 8:00 PM ET").check()
                extended = True
                precision = 2

            # Press the buy or sell button. Title capitalizes the first letter so 'buy' -> 'Buy'
            action_clicked = False
            for attempt in range(3):
                self.page.query_selector(".eq-ticket-action-label").click()
                action_option = self.page.get_by_role("option", name=action.lower().title(), exact=True).first
                try:
                    action_option.wait_for(timeout=5000)
                except PlaywrightTimeoutError:
                    pass
                try:
                    action_option.click()
                    action_clicked = True
                    break
                except PlaywrightTimeoutError:
                    pass
                self.page.wait_for_timeout(500)
            if not action_clicked:
                return (False, f"Could not select action {action.lower().title()} after retries")

            # Press the shares text box
            self.page.locator("#eqt-mts-stock-quatity div").filter(has_text="Quantity").click()
            self.page.get_by_text("Quantity", exact=True).fill(str(quantity))

            # If it should be limit
            if float(last_price) < 1 or extended or limit_price is not None:
                # Set if present
                if limit_price is not None:
                    wanted_price = limit_price
                # Buy above
                elif action.lower() == "buy":
                    difference_price = 0.01 if float(last_price) > 0.1 else 0.0001
                    wanted_price = round(float(last_price) + difference_price, precision)
                # Sell below
                else:
                    difference_price = 0.01 if float(last_price) > 0.1 else 0.0001
                    wanted_price = round(float(last_price) - difference_price, precision)

                # Click on the limit default option when in extended hours
                self.page.query_selector("#dest-dropdownlist-button-ordertype > span:nth-child(1)").click()
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
            self.wait_for_loading_sign()

            # If error occurred
            try:
                self.page.get_by_role("button", name="Place order", exact=False).wait_for(timeout=5000, state="visible")
            except PlaywrightTimeoutError:
                # Error must be present (or really slow page for some reason)
                # Try to report on error
                error_message = ""
                filtered_error = ""
                error_box_closed = False
                try:
                    error_message = (self.page.get_by_label("Error").locator("div").filter(has_text="critical").nth(2).text_content(timeout=2000))
                    self.page.get_by_role("button", name="Close dialog").click()
                    error_box_closed = True
                except Exception:
                    pass
                if error_message == "":
                    try:
                        error_message = self.page.wait_for_selector('.pvd-inline-alert__content font[color="red"]', timeout=2000).text_content()
                        self.page.get_by_role("button", name="Close dialog").click()
                        error_box_closed = True
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

                    error_message = filtered_error.replace("critical", "").strip().replace("\n", "")
                else:
                    error_message = "Could not retrieve error message from popup"

                # If the error box is still open, reload the page
                if not error_box_closed:
                    self.page.reload()
                return (False, error_message)

            # If no error occurred, continue with checking the order preview
            if (not self.page.locator("preview").filter(has_text=account.upper()).is_visible()
                or not self.page.get_by_text(f"Symbol{stock.upper()}", exact=True).is_visible()
                or not self.page.get_by_text(f"Action{action.lower().title()}").is_visible()
                or not self.page.get_by_text(f"Quantity{quantity}").is_visible()
            ):
                return (False, "Order preview is not what is expected")

            # If its a real run
            if not dry:
                self.page.get_by_role("button", name="Place order", exact=False).first.click()
                try:
                    self.wait_for_loading_sign()
                    # See that the order goes through
                    self.page.get_by_text("Order received", exact=True).wait_for(timeout=10000, state="visible")
                    # If no error, return with success
                    return (True, None)
                except PlaywrightTimeoutError as toe:
                    # Order didn't go through for some reason, go to the next and say error
                    return (False, f"Timed out waiting for 'Order received': {toe}")
            # If its a dry run, report back success
            return (True, None)
        except PlaywrightTimeoutError as toe:
            return (False, f"Driver timed out. Order not complete: {toe}")
        except Exception as e:
            return (False, f"Some error occurred: {e}")

    def open_account(self, type: typing.Optional[Literal["roth", "brokerage"]]) -> bool:
        """
        Opens either a brokerage or roth account. If a roth account is opened, the new account number is stored in
        `self.new_account_number`

        `NOTE` Use login(save_device=False) when logging in.
        If you do not authenticate with 2FA when creating this session and the device is remembered from a pervious
        login, fidelity can attempt to authenticate again which causes this function to fail.

        Parameters
        ----------
        type (str)
            The type of account to open.

        Returns
        -------
        success (bool)
            If the account was successfully opened
        """
        try:
            if type == "roth":
                # Go to open roth page
                self.page.goto(url="https://digital.fidelity.com/ftgw/digital/aox/RothIRAccountOpening/PersonalInformation")
                self.wait_for_loading_sign()

                # Open an account
                self.page.get_by_role("button", name="Open account").click()
                self.wait_for_loading_sign(timeout=60000)
                congrats_message = self.page.get_by_role("heading", name="Congratulations, your account")
                congrats_message.wait_for(state="visible")

                # Get the account number
                self.new_account_number = self.page.get_by_role("heading", name="Your account number is").text_content()
                self.new_account_number = self.new_account_number.replace("Your account number is ", "")
                return True
            if type == "brokerage":
                # Get list of accounts first
                old_dict = self.get_list_of_accounts(set_flag=False)

                # Go to individual brokerage page
                self.page.goto(url="https://digital.fidelity.com/ftgw/digital/aox/BrokerageAccountOpening/JointSelectionPage")
                self.wait_for_loading_sign()

                # First section (This won't be present if an application was already started)
                if self.page.get_by_role("heading", name="Account ownership").is_visible():
                    self.page.get_by_role("button", name="Next").click()
                    self.wait_for_loading_sign()

                # If application is already started, then there will only be 1 "Next" button
                # Rarely there will be no "Next" button
                try:
                    self.page.get_by_role("button", name="Next").click(timeout=15000)
                    self.wait_for_loading_sign()
                except:
                    pass
                
                # Open account
                self.page.get_by_role("button", name="Open account").click()
                self.wait_for_loading_sign(timeout=60000)   # Can take a while to open sometimes

                # Wait for page to load completely
                self.page.wait_for_load_state(state='load')
                self.wait_for_loading_sign()

                ## Getting the account number ##
                # Get new list of accounts
                new_dict = self.get_list_of_accounts(set_flag=False)
                # Reset new account number in case this was set before
                self.new_account_number = None
                # Compare old and new list
                for new_dict_acc in new_dict:
                    # If new account is found, collect and return
                    if new_dict_acc not in old_dict:
                        self.new_account_number = new_dict_acc
                        return True
                
                # No new account number was found, return false
                return False

            return False
        except Exception as e:
            print(e)
            self.page.pause()
            return False

    def transfer_acc_to_acc(self, source_account: str, destination_account: str, transfer_amount: float) -> bool:
        """
        Transfers requested amount from source account to destination account.

        Parameters
        ----------
        source_account (str)
            The account number of the source account.
        destination_account (str)
            The account number of the destination account.
        transfer_amount (float)
            The amount to transfer.
        
        Returns
        -------
        bool
            True if the transfer was successful, False otherwise.
        """
        try:
            # Navigate to the transfer page
            self.page.wait_for_load_state(state="load")
            self.page.goto(url="https://digital.fidelity.com/ftgw/digital/transfer/?quicktransfer=cash-shares")
            self.wait_for_loading_sign()

            # Select the source account from the 'From' dropdown
            from_select = self.page.get_by_label("From")
            options = from_select.locator("option").all()
            source_value = None
            for option in options:
                if source_account in option.inner_text():
                    source_value = option.get_attribute("value")
                    break

            if source_value is None:
                print(f"Source account {source_account} not found in dropdown")
                return False

            from_select.select_option(source_value)
            self.wait_for_loading_sign()

            # Select the new account from the 'To' dropdown
            to_select = self.page.get_by_label("To", exact=True)
            options = to_select.locator("option").all()
            destination_value = None
            for option in options:
                if destination_account in option.inner_text():
                    destination_value = option.get_attribute("value")
                    break

            if destination_value is None:
                print(f"Account {destination_account} not found in 'To' dropdown")
                return False

            to_select.select_option(destination_value)
            self.wait_for_loading_sign()

            # Get the available balance
            available_balance = self.page.locator("tr.pvd-table__row:nth-child(2) > td:nth-child(2)").inner_text()
            available_balance = float(available_balance.replace("$", "").replace(",", ""))

            # Check if there's enough balance
            transfer_amount = round(transfer_amount, 2)
            if transfer_amount > available_balance:
                print(f"Insufficient funds. Available: ${available_balance}, Attempted transfer: ${transfer_amount}")
                return False

            # Enter the transfer amount
            self.page.locator("#transfer-amount").fill(str(transfer_amount))

            # Submit the transfer
            self.page.get_by_role("button", name="Continue").click()
            self.wait_for_loading_sign()
            self.page.get_by_role("button", name="Submit").click()
            self.wait_for_loading_sign()

            try:
                # Check if the transfer was successful
                self.page.get_by_text("Request submitted").wait_for(state='visible')
            except PlaywrightTimeoutError:
                print("Transfer submission failed")
                return False

            return True

        except Exception as e:
            print(f"An error occurred during the transfer: {str(e)}")
            return False

    def enable_pennystock_trading(self, account: str) -> bool:
        """
        Enables penny stock trading for the account given.
        The account is just the account number, no nickname and no parenthesis

        `NOTE` Use login(save_device=False) when logging in.
        If you do not authenticate with 2FA when creating this session and the device is remembered from a pervious
        login, fidelity can attempt to authenticate again which causes this function to fail.

        Problems
        --------
        When the checkbox version comes around, sometimes it takes forever to load.
        When reloading the page or navigating away, it makes you sign in again

        Parameters
        ----------
        account (str)
            The account number to enable this feature for
        
        Returns
        -------
        bool
            If account was successfully enabled or not
        """
        try:
            self.page.wait_for_load_state(state="load")
            self.page.goto(url="https://digital.fidelity.com/ftgw/digital/portfolio/features")
            self.page.get_by_label("Manage Penny Stock Trading").click()

            self.page.wait_for_load_state(state="load", timeout=30000)
            self.wait_for_loading_sign()

            # Wait for and click the Start button
            self.page.get_by_role("button", name="Start").click(timeout=15000)
            self.wait_for_loading_sign()

            # See if we can enable any accounts
            try:
                self.page.get_by_text("This feature is already enabled").wait_for(state="visible", timeout=1000)
                print("All accounts have penny stock trading enabled already")
                return True
            except PlaywrightTimeoutError:
                pass
            # Ensure the page is loaded
            select_account_title = self.page.get_by_role("heading", name="Select an account")
            select_account_title.wait_for(timeout=30000, state="visible")

            # There are 2 versions of this. A checkbox and a drop down

            # Checkbox version
            # This one seems to have trouble with infinite loading sign
            if self.page.locator("label").filter(has_text=account).is_visible():
                # This seems to never work for checkbox version so reload and try for dropdown version
                self.page.locator("label").filter(has_text=account).click()

            # Dropdown version
            if self.page.get_by_label("Your eligible accounts").is_visible():
                self.page.get_by_label("Your eligible accounts").select_option(account)
            
            # Continue with enabling
            self.page.get_by_role("button", name="Continue").click()
            try:
                self.wait_for_loading_sign(timeout=60000)
            except PlaywrightTimeoutError:
                # Reload
                # TODO Still some problems here. It takes you to the login page upon navigating when the loading
                # sign is taking forever
                return self.enable_pennystock_trading(account=account)
            try:
                # Wait for extra loading
                self.page.wait_for_load_state(state="load")
                self.wait_for_loading_sign()
                # First link is more common, second link sometimes happens when going through checkbox page
                if ("https://digital.fidelity.com/ftgw/digital/easy/hrt/pst/termsandconditions" not in self.page.url and 
                    "https://digital.fidelity.com/ftgw/digital/brokerage-host/psta/TermsAndCondtions" not in self.page.url
                ):
                    return False
                # self.page.wait_for_url(url="https://digital.fidelity.com/ftgw/digital/easy/hrt/pst/termsandconditions")
                # TODO This is the page that it navigates to after the checkbox version
                # https://digital.fidelity.com/ftgw/digital/brokerage-host/psta/TermsAndCondtions
                # Also the page doesn't say success if it goes here. it says You're all set!. See pic in downloads
            except PlaywrightTimeoutError as e:
                if not "termsandconditions" in self.page.url.lower():
                    raise Exception(e)
            # Accept the risks
            self.page.query_selector(".pvd-checkbox__label").click()
            self.page.get_by_role("button", name="Submit").click()
            self.wait_for_loading_sign()
            self.page.wait_for_load_state(state="load")
            self.wait_for_loading_sign()
            # Verify success
            try:
                success_ribbon = self.page.get_by_text("Your account is now enabled.")
                success_ribbon.wait_for(state="visible", timeout=15000)
            except PlaywrightTimeoutError:
                print(f"Couldn't verify penny stock enabled. Error: {e}")
                return False
            # Return with success
            return True

        except Exception as e:
            print(f"Error: {e}")
            return False
    
    def download_statements(self, date: str):
        """
        Downloads the account statement(s) for the given month.

        Parameters
        ----------
        date (str)
            The month and year for the statement to download. Format of `YYYY/MM`  Ex: 2019/01
        
        Returns
        -------
        saved_files (str)
            A list of absolute file paths to statements downloaded. If error occurred, return None
        """

        # Trim date down
        target_month = date[-2:]
        target_year = date[:4]
        if not target_month.isdigit() or not target_year.isdigit():
            return None
        target_month = int(target_month)
        target_year = int(target_year)

        # Convert to target_month string
        fid_month = fid_months(target_month).name

        def beneficiary_popup_close():
            self.page.get_by_role("button", name="Close dialog").click()
            return True

        # Setup popup handler
        self.page.add_locator_handler(
            self.page.locator(".pvd3-cim-modal-root > .pvd-modal__overlay"),
            beneficiary_popup_close,
        )

        # Go to url
        self.page.wait_for_load_state(state="load")
        self.page.goto(url="https://digital.fidelity.com/ftgw/digital/portfolio/documents/dochub")

        # Select the proper year
        # Select the date change button
        self.page.get_by_role("button", name="Changing").click(timeout=5000)

        # Choose the corresponding year
        self.page.get_by_role("menuitem", name=f"{str(target_year)}").click(timeout=5000)

        # Wait for entries to load
        self.page.locator("statements-loading-skeleton div").nth(1).wait_for(state="hidden")

        # expand results or end if no results
        if self.page.get_by_text("There are no statements").is_visible():
            return None

        # If statement is not showing, expand if possible
        elif self.page.get_by_role("button", name="Load more results").is_visible():
            try:
                self.page.get_by_role("button", name="Load more results").click(timeout=5000)
            except PlaywrightTimeoutError:
                if not self.page.get_by_text("Showing all results").is_visible():
                    return None

        # If everything is showing, continue
        elif not self.page.get_by_text("Showing all results").is_visible():
            return None

        # Get list of elements
        # Wait for entries to load and filter themselves out
        self.page.wait_for_timeout(1000)
        items = self.page.get_by_role("row").all()
        valid_rows = []
        for item in items:
            text = item.inner_text()
            # Double check that text contains target_year
            if not re.search(str(target_year), text):
                continue
            # If we find a direct match, add to valid rows and continue
            if re.search(fid_month, text):
                valid_rows.append(item)
                continue

            # Otherwise, do more processing
            found_months = []
            for month in fid_months.__members__.keys():
                if len(found_months) >= 2:
                    break
                result = re.search(str(month), text)
                if result:
                    found_months.append(month)

            # If, for whatever reason, we didn't find 2 months, just go to the next item
            if len(found_months) != 2:
                continue
            # Determine if target date is in this statement period
            if fid_months[found_months[0]].value <= target_month and target_month <= fid_months[found_months[1]].value:
                valid_rows.append(item)

        saved_files = []
        # Determine sub folder name if necessary
        subfolder = ""
        if self.title is not None:
            subfolder = self.title + '/'
        for row in valid_rows:
            # Download matches
            with self.page.expect_download() as download_info:
                with self.page.expect_popup() as page1_info:
                    row.filter(has=self.page.get_by_role("link")).click(timeout=5000)
                page1 = page1_info.value
            download = download_info.value
            filename = f"./Statements/{subfolder}{str(len(saved_files))} - {download.suggested_filename}"
            if not os.path.exists(os.path.dirname(filename)):
                os.makedirs(os.path.dirname(filename), exist_ok=True)
            cur = os.getcwd()
            filename = os.path.join(cur, filename)
            # Create a copy to work on with the proper file name known
            download.save_as(filename)
            page1.close()
            saved_files.append(filename)
        # return a list of filenames
        return saved_files

    def wait_for_loading_sign(self, timeout: int = 30000):
        """
        Waits for known loading signs present in Fidelity by looping through a list of discovered types.
        Each iteration uses the timeout given.

        Parameters
        ----------
        timeout (int)
            The number of milliseconds to wait before throwing a PlaywrightTimeoutError exception
        """

        # Wait for all kinds of loading signs
        signs = [self.page.locator("div:nth-child(2) > .loading-spinner-mask-after").first,
                 self.page.locator(".pvd-spinner__mask-inner").first,
                 self.page.locator("pvd-loading-spinner").first,
                 self.page.locator(".pvd3-spinner-root > .pvd-spinner__spinner > .pvd-spinner__visual > div > .pvd-spinner__mask-inner").first,
                ]
        for sign in signs:
            sign.wait_for(timeout=timeout, state="hidden")

    def nickname_account(self, account_number: str, nickname: str):
        """
        Nicknames an account with the provided string.

        Parameters
        ----------
        account_number (str)
            The account number for the account to be nicknamed. Ex: `Z12345678`
        nickname (str)
            The nickname to use
            
        Returns
        -------
        Success (bool)
            True if successful, false otherwise
        """
        try:
            # Get to summary page
            self.page.wait_for_load_state(state='load')
            self.page.goto(url="https://digital.fidelity.com/ftgw/digital/portfolio/summary")
            self.wait_for_loading_sign()

            # Wait for customize button
            self.page.get_by_label("Customize Accounts", exact=True).wait_for(state='visible')
            new_view = False

            # Check for newer customize button
            if self.page.get_by_test_id("ap143528-account-customize-open-button").get_by_label("Customize Accounts").is_visible():
                # New view detected
                new_view = True
            # Click customize button
            self.page.get_by_label("Customize Accounts", exact=True).click()
            self.page.get_by_text("Display preferences").wait_for(state='visible')

            entries = self.page.locator(".custom-modal__accounts-item").first.wait_for(state='visible')
            entries = self.page.locator(".custom-modal__accounts-item").all()
            selected_entry = None
            for item in entries:
                if account_number in item.inner_text():
                    selected_entry = item
                    break

            # See if we found something
            if selected_entry is None:
                return False

            # Click it
            self.page.wait_for_timeout(500)
            selected_entry.click()
            self.page.wait_for_timeout(500)

            # Click the rename button
            self.page.get_by_role("button", name="Rename").click()

            # Enter the new name
            if new_view:
                self.page.get_by_test_id("ap143528-account-customize-account-input").get_by_role("textbox").fill(nickname)
            else:
                self.page.get_by_label("Accounts", exact=True).get_by_role("textbox").fill(nickname)

            self.page.get_by_role("button", name="save").click()
            # 2 loading signs follow this
            self.wait_for_loading_sign()
            self.wait_for_loading_sign()

            return True

        except Exception as e:
            print(e)
            return False

def create_stock_dict(ticker: str, quantity: float, last_price: float, value: float, stock_list: list = None):
    """
    Creates a dictionary for a stock.
    Appends it to a list if provided

    Returns
    -------
    stock_dict (dict)
        The dictionary for the stock with given info
    """
    # Build the dict for the stock
    stock_dict = {
        "ticker": ticker,
        "quantity": quantity,
        "last_price": last_price,
        "value": value,
    }
    if stock_list is not None:
        stock_list.append(stock_dict)
    return stock_dict

def validate_stocks(stocks: list):
    """
    Checks a list of stocks (which are dictionaries) for valid fields

    Returns
    -------
    True
        If stocks are none or valid
    False
        If fields are left empty or type are incorrect
    """
    if stocks is not None:
        for stock in stocks:
            try:
                if (stock["ticker"] is None or
                    stock["quantity"] is None or
                    stock["last_price"] is None or
                    stock["value"] is None
                ):
                    raise Exception("Missing fields")
                if (type(stock["ticker"]) is not str or
                    type(stock["quantity"]) is not float or
                    type(stock["last_price"]) is not float or
                    type(stock["value"]) is not float
                ):
                    raise Exception("Incorrect types for entries")
            except Exception as e:
                print(f"Error in stocks list. {e}")
                print("Create list of dictionaries with the following fields populated to initialize with given list")
                print("ticker: str")
                print("quantity: float")
                print("last_price: float")
                print("value: float")
                return False
    return True
