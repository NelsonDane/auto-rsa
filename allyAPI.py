# API to Interface with Ally
# Uses headless Selenium

import asyncio
import datetime
import os
import traceback
from time import sleep

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.wait import WebDriverWait

from helperAPI import (
    Brokerage,
    check_if_page_loaded,
    getDriver,
    getOTPCodeDiscord,
    killSeleniumDriver,
    printAndDiscord,
    printHoldings,
    stockOrder,
    type_slowly,
)


def ally_error(driver: webdriver, error: str):
    print(f"Ally Error: {error}")
    driver.save_screenshot(f"ally-error-{datetime.datetime.now()}.png")
    print(traceback.format_exc())


def ally_init(ALLY_EXTERNAL=None, DOCKER=False, botObj=None, loop=None):
    # Initialize .env file
    load_dotenv()
    # Import Ally account
    if not os.getenv("ALLY") and ALLY_EXTERNAL is None:
        print("Ally not found, skipping...")
        return None
    accounts = (
        os.environ["ALLY"].strip().split(",")
        if ALLY_EXTERNAL is None
        else ALLY_EXTERNAL.strip().split(",")
    )
    ally_obj = Brokerage("Ally")
    for account in accounts:
        index = accounts.index(account) + 1
        name = f"Ally {index}"
        account = account.split(":")
        try:
            print("Logging in to Ally...")
            # Init webdriver
            driver = getDriver(DOCKER)
            # We need this or all the elements change completely on us
            driver.set_window_size("800", "622")
            if driver is None:
                raise Exception("Error: Unable to get driver")
            # Log in to Ally account
            driver.get(
                "https://secure.ally.com/?redirect=%2Faccount%2Flogin"
            )
            # Wait for page load
            WebDriverWait(driver, 15).until(check_if_page_loaded)
            # Type in username and password and click login
            WebDriverWait(driver, 10).until(
                expected_conditions.element_to_be_clickable(
                    (By.CSS_SELECTOR, "#username")
                )
            )
            username_selector = "#username"
            password_selector = "#password"
            login_btn_selector = ".sc-fAGzit button.sc-fIGJwM"
            WebDriverWait(driver, 10).until(
                expected_conditions.element_to_be_clickable(
                    (By.CSS_SELECTOR, username_selector)
                )
            )
            username_field = driver.find_element(
                by=By.CSS_SELECTOR, value=username_selector
            )
            type_slowly(username_field, account[0])
            password_field = driver.find_element(
                by=By.CSS_SELECTOR, value=password_selector
            )
            type_slowly(password_field, account[1])
            driver.find_element(by=By.CSS_SELECTOR, value=login_btn_selector).click()

            # Make sure the next page loads fully
            if "send-code" not in driver.current_url:
                WebDriverWait(driver, 30).until(
                    expected_conditions.url_contains("send-code")
                )

            code_btn_selector = 'button[type="submit"].sc-fIGJwM span.sc-iA-DsXs'
            WebDriverWait(driver, 10).until(
                expected_conditions.visibility_of_element_located(
                    (By.CSS_SELECTOR, code_btn_selector))
            )
            driver.find_element(by=By.CSS_SELECTOR, value=code_btn_selector).click()
            if botObj is not None and loop is not None:
                code_field = "otpCode"
                WebDriverWait(driver, 10).until(
                    expected_conditions.presence_of_element_located(
                        (By.ID, code_field)
                    )
                )
                # Sometimes codes take a long time to arrive
                timeout = 300  # 5 minutes
                sms_code = asyncio.run_coroutine_threadsafe(
                    getOTPCodeDiscord(botObj, name, timeout=timeout, loop=loop),
                    loop,
                ).result()
                if sms_code is None:
                    raise Exception("No SMS code found")

                code_field = driver.find_element(
                    by=By.ID, value=code_field
                )
                type_slowly(code_field, str(sms_code))

                continue_btn_selector = 'button[type="submit"].sc-fIGJwM'
                driver.find_element(by=By.CSS_SELECTOR, value=continue_btn_selector).click()

                no_label_element = "//label[span[contains(text(), 'No')]]"
                WebDriverWait(driver, 10).until(
                    expected_conditions.presence_of_element_located(
                        (By.XPATH, no_label_element)
                    )
                )
                driver.find_element(by=By.XPATH, value=no_label_element).click()

                continue_btn_selector = "//button[span[contains(text(), 'Continue')]]"
                driver.find_element(by=By.XPATH, value=continue_btn_selector).click()

            # Wait for the dashboard page to load.
            if "dashboard" not in driver.current_url:
                print("Waiting for portfolio page to load...")
                WebDriverWait(driver, 30).until(
                    expected_conditions.url_contains("dashboard")
                )
            # Make sure all elements are loaded too
            WebDriverWait(driver, 10).until(
                expected_conditions.presence_of_element_located(
                    (By.CSS_SELECTOR, 'a[data-testid="account-link"]')
                )
            )
            ally_obj.set_logged_in_object(name, driver)
            # Get account numbers, types, and balances
            account_dict = ally_account_info(driver)
            if account_dict is None:
                raise Exception(f"{name}: Error getting account info")
            for acct in account_dict:
                ally_obj.set_account_number(name, acct)
                ally_obj.set_account_type(name, acct, account_dict[acct]["type"])
                ally_obj.set_account_totals(
                    name, acct, account_dict[acct]["balance"]
                )
            print(f"Logged in to {name}!")
        except Exception as e:
            ally_error(driver, e)
            driver.close()
            driver.quit()
            return None
    return ally_obj


def ally_account_info(driver: webdriver) -> dict | None:
    try:
        # Get account holdings
        # Initialize lists to store the extracted data
        account_numbers = []
        account_types = []
        account_balances = []

        length = len(driver.find_elements(By.CSS_SELECTOR, 'a[data-testid="account-link"]'))
        for i in range(length):
            # Assign each time so the element does not go stale
            row = driver.find_elements(By.CSS_SELECTOR, 'a[data-testid="account-link"]')[i]
            account_type = row.get_attribute('aria-label').split(' account ending in ')[0]
            account_number = '**' + row.get_attribute('aria-label').split(' account ending in ')[1]
            balance = row.find_element(By.XPATH, '//p[@color="slate-5"]').text

            account_types.append(account_type)
            account_numbers.append(account_number)
            account_balances.append(balance)

        # Make sure all lists are the same length
        if not (
                len(account_numbers) == len(account_types)
                and len(account_numbers) == len(account_balances)
        ):
            shortest = min(
                len(account_numbers), len(account_types), len(account_balances)
            )
            account_numbers = account_numbers[:shortest]
            account_types = account_types[:shortest]
            account_balances = account_balances[:shortest]
            print(
                f"Warning: Account numbers, values, and types are not the same length! Using shortest length: {shortest}"
            )
        # Construct dictionary of account numbers and balances
        account_dict = {}
        for i, account in enumerate(account_numbers):
            av = (
                account_balances[i]
                .replace(" ", "")
                .replace("$", "")
                .replace(",", "")
                .replace("»", "")
                .replace("‡", "")
                .replace("balance:", "")
            )
            account_dict[account] = {
                "balance": float(av),
                "type": account_types[i],
            }
        return account_dict
    except Exception as e:
        ally_error(driver, e)
        return None


def ally_holdings(ally_o: Brokerage, loop=None):
    print()
    print("==============================")
    print("Ally Holdings")
    print("==============================")
    print()
    for key in ally_o.get_account_numbers():
        driver: webdriver = ally_o.get_logged_in_objects(key)
        driver.find_elements(By.CSS_SELECTOR, 'a[data-testid="account-link"]')[0].click()
        # This one takes a very long time to load sometimes.
        WebDriverWait(driver, 30).until(
            expected_conditions.element_to_be_clickable(
                (By.CSS_SELECTOR, "label.select-trigger")
            )
        )
        for account in ally_o.get_account_numbers(key):
            try:
                # Use the Select class to interact with the dropdown
                change_account_element = driver.find_element(By.ID, "change-account-link-select")
                select = Select(change_account_element)

                account_select = None
                account_formatted = account.replace("*", "")
                for option in select.options:
                    if account_formatted in option.text:
                        account_select = option
                        break

                # Apply value
                select.select_by_value(account_select.get_attribute("value"))

                # Wait for page load
                WebDriverWait(driver, 10).until(check_if_page_loaded)
                sleep(1)  # This one is necessary
                WebDriverWait(driver, 10).until(
                    expected_conditions.element_to_be_clickable(
                        (By.CSS_SELECTOR, "label.select-trigger")
                    )
                )

                holdings_table = driver.find_elements(By.CSS_SELECTOR, ".table-container-wrapper tbody tr")
                for holdings_element in holdings_table:
                    stock = holdings_element.find_element(By.CSS_SELECTOR, ".symbol span").text
                    quantity = holdings_element.find_element(By.CSS_SELECTOR, "td:nth-of-type(3) span").text
                    price = holdings_element.find_element(By.CSS_SELECTOR, "td:nth-of-type(11) span").text.replace("$", "").replace("-", "")

                    if "-" in quantity:
                        continue

                    ally_o.set_holdings(key, account, stock, quantity, price)
            except Exception as e:
                ally_error(driver, e)
                continue
    printHoldings(ally_o, loop)
    killSeleniumDriver(ally_o)


def ally_transaction(ally_o: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Ally")
    print("==============================")
    print()
    for s in orderObj.get_stocks():
        for key in ally_o.get_account_numbers():
            printAndDiscord(
                f"{key}: {orderObj.get_action()}ing {orderObj.get_amount()} of {s}",
                loop,
            )
            driver = ally_o.get_logged_in_objects(key)
            driver.find_elements(By.CSS_SELECTOR, 'a[data-testid="account-link"]')[0].click()
            # This one takes a very long time to load sometimes.
            WebDriverWait(driver, 30).until(
                expected_conditions.element_to_be_clickable(
                    (By.CSS_SELECTOR, "label.select-trigger")
                )
            )

            # Complete on each account
            for account in ally_o.get_account_numbers(key):
                driver.get(
                    "https://live.invest.ally.com/trading-full/stocks"
                )

                # Wait for page to load
                WebDriverWait(driver, 30).until(check_if_page_loaded)
                WebDriverWait(driver, 30).until(
                    expected_conditions.element_to_be_clickable(
                        (By.CSS_SELECTOR, 'input[placeholder="Search"]')
                    )
                )
                try:
                    change_account_element = driver.find_element(By.CSS_SELECTOR, "#account-details-account-number select")
                    select = Select(change_account_element)

                    account_select = None
                    account_formatted = account.replace("*", "")
                    for option in select.options:
                        if account_formatted in option.text:
                            account_select = option
                            break

                    # Select account
                    select.select_by_value(account_select.get_attribute("value"))

                    # Wait for page to load
                    WebDriverWait(driver, 10).until(check_if_page_loaded)
                    sleep(1)
                    WebDriverWait(driver, 10).until(
                        expected_conditions.element_to_be_clickable(
                            (By.ID, "account-details-account-number")
                        )
                    )

                    # Type in ticker
                    ticker_box = driver.find_element(
                        by=By.CSS_SELECTOR, value='input[placeholder="Search"]'
                    )
                    WebDriverWait(driver, 10).until(
                        expected_conditions.element_to_be_clickable(ticker_box)
                    )
                    ticker_box.clear()
                    ticker_box.send_keys(s)
                    ticker_box.send_keys(Keys.RETURN)
                    sleep(1)

                    # Check if symbol not found is displayed
                    try:
                        driver.find_element(
                            by=By.XPATH,
                            value="//h3[contains(text(), 'Invalid Symbol')]",
                        )
                        printAndDiscord(f"{key} Error: Symbol {s} not found", loop)
                        print()
                        killSeleniumDriver(ally_o)
                        return None
                    except NoSuchElementException:
                        pass

                    # Only have to click something if selling.
                    if not orderObj.get_action() == "buy":
                        driver.find_element(
                            by=By.ID,
                            value="stock-sell",
                        ).click()

                    # Get last price
                    last_price = driver.find_element(
                        by=By.CSS_SELECTOR,
                        value=".company-info-last span",
                    ).text
                    last_price = last_price.replace("$", "")
                    limit_price = None
                    difference_price = 0.01 if float(last_price) > 0.1 else 0.0001
                    if orderObj.get_action() == "buy":
                        limit_price = round(
                            float(last_price) + difference_price, 3
                        )
                    else:
                        limit_price = round(
                            float(last_price) - difference_price, 3
                        )

                    # Check if extended hours trade is shown
                    try:
                        driver.find_element(
                            by=By.ID,
                            value="extended-hours-order-checkbox",
                        ).click()
                    except NoSuchElementException:
                        pass

                    # Always make it limit to prevent unable to do market order for security errors
                    driver.find_element(
                        by=By.ID,
                        value="stock-limit",
                    ).click()

                    # Set quantity
                    quantity_box = driver.find_element(
                        by=By.CSS_SELECTOR, value="#stock-quantity input"
                    )
                    quantity_box.clear()
                    quantity_box.send_keys(str(int(orderObj.get_amount())))  # Ally doesn't support fractional shares

                    # Set price
                    limit_box = driver.find_element(
                        by=By.CSS_SELECTOR, value="#stock-limit-input input"
                    )
                    limit_box.clear()
                    limit_box.send_keys(limit_price)

                    # Preview trade
                    driver.find_element(
                        by=By.CSS_SELECTOR,
                        value='ally-button[data-track-name="Preview Trade"] button',
                    ).click()

                    # If errors-warnings has children, there was a mistake somewhere
                    errors_warnings = driver.find_element(
                        by=By.CLASS_NAME,
                        value="errors-warnings",
                    )
                    children = errors_warnings.find_elements(
                        by=By.XPATH,
                        value=".//*",
                    )
                    if len(children) != 0:
                        raise Exception("Unable to place Ally trade!")

                    if not orderObj.get_dry():
                        # Submit the trade
                        try:
                            submit_button = ".trade-submit button"
                            WebDriverWait(driver, 10).until(
                                expected_conditions.element_to_be_clickable(
                                    (By.CSS_SELECTOR, ".trade-submit button")
                                )
                            )
                            driver.find_element(
                                by=By.CSS_SELECTOR,
                                value=submit_button,
                            ).click()

                            # Wait for page to load
                            WebDriverWait(driver, 10).until(check_if_page_loaded)
                            sleep(1)
                            # Send confirmation
                            printAndDiscord(
                                f"{key} {account}: {orderObj.get_action()} {orderObj.get_amount()} shares of {s}",
                                loop,
                            )
                        except NoSuchElementException:
                            printAndDiscord(
                                f"{key} account {account}: {orderObj.get_action()} {orderObj.get_amount()} shares of {s}. DID NOT COMPLETE! \nEither this account does not have enough shares, or an order is already pending.",
                                loop,
                            )
                        # Send confirmation
                    else:
                        printAndDiscord(
                            f"DRY: {key} account {account}: {orderObj.get_action()} {orderObj.get_amount()} shares of {s}",
                            loop,
                        )
                    sleep(3)
                except Exception as err:
                    ally_error(driver, err)
                    continue
            print()
    killSeleniumDriver(ally_o)
