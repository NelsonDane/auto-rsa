# Nelson Dane
# API to Interface with Fidelity
# Uses headless Selenium

import asyncio
import datetime
import os
import re
import traceback
from time import sleep

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait

from helperAPI import (
    Brokerage,
    check_if_page_loaded,
    getDriver,
    getOTPCodeDiscord,
    killSeleniumDriver,
    maskString,
    printAndDiscord,
    printHoldings,
    stockOrder,
    type_slowly,
)


def fidelity_error(driver: webdriver, error: str):
    print(f"Fidelity Error: {error}")
    driver.save_screenshot(f"fidelity-error-{datetime.datetime.now()}.png")
    print(traceback.format_exc())


def javascript_get_classname(driver: webdriver, className) -> list:
    script = f"""
    var accounts = document.getElementsByClassName("{className}");
    var account_list = [];
    for (var i = 0; i < accounts.length; i++) {{
        account_list.push(accounts[i].textContent.trim());
    }}
    return account_list;
    """
    text = driver.execute_script(script)
    sleep(1)
    return text


def fidelity_init(FIDELITY_EXTERNAL=None, DOCKER=False, botObj=None, loop=None):
    # Initialize .env file
    load_dotenv()
    # Import Fidelity account
    if not os.getenv("FIDELITY") and FIDELITY_EXTERNAL is None:
        print("Fidelity not found, skipping...")
        return None
    accounts = (
        os.environ["FIDELITY"].strip().split(",")
        if FIDELITY_EXTERNAL is None
        else FIDELITY_EXTERNAL.strip().split(",")
    )
    fidelity_obj = Brokerage("Fidelity")
    # Init webdriver
    for account in accounts:
        index = accounts.index(account) + 1
        name = f"Fidelity {index}"
        account = account.split(":")
        try:
            print("Logging in to Fidelity...")
            driver = getDriver(DOCKER)
            if driver is None:
                raise Exception("Error: Unable to get driver")
            # Log in to Fidelity account
            driver.get(
                "https://digital.fidelity.com/prgw/digital/login/full-page?AuthRedUrl=digital.fidelity.com/ftgw/digital/portfolio/summary"
            )
            # Wait for page load
            WebDriverWait(driver, 20).until(check_if_page_loaded)
            # Type in username and password and click login
            # Fidelity has different login views, so check for both
            try:
                WebDriverWait(driver, 10).until(
                    expected_conditions.element_to_be_clickable(
                        (By.CSS_SELECTOR, "#dom-username-input")
                    )
                )
                username_selector = "#dom-username-input"
                password_selector = "#dom-pswd-input"
                login_btn_selector = "#dom-login-button > div"
            except TimeoutException:
                username_selector = "#userId-input"
                password_selector = "#password"
                login_btn_selector = "#fs-login-button"
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
            WebDriverWait(driver, 10).until(check_if_page_loaded)
            sleep(3)
            try:
                # Look for: Sorry, we can't complete this action right now. Please try again.
                go_back_selector = "#dom-sys-err-go-to-login-button > span > s-slot > s-assigned-wrapper"
                WebDriverWait(driver, 10).until(
                    expected_conditions.element_to_be_clickable(
                        (By.CSS_SELECTOR, go_back_selector)
                    ),
                ).click()
                username_field = driver.find_element(
                    by=By.CSS_SELECTOR, value=username_selector
                )
                type_slowly(username_field, account[0])
                password_field = driver.find_element(
                    by=By.CSS_SELECTOR, value=password_selector
                )
                type_slowly(password_field, account[1])
                driver.find_element(
                    by=By.CSS_SELECTOR, value=login_btn_selector
                ).click()
            except TimeoutException:
                pass
            # Check for mobile 2fa page
            try:
                try_another_way = "a#dom-try-another-way-link"
                WebDriverWait(driver, 10).until(
                    expected_conditions.element_to_be_clickable(
                        (By.CSS_SELECTOR, try_another_way)
                    ),
                ).click()
            except TimeoutException:
                pass
            # Check for normal 2fa page
            try:
                text_me_button = "//*[@id='dom-channel-list-primary-button' and contains(string(.), 'Text me the code')]"  # Make sure it doesn't duplicate from mobile page
                WebDriverWait(driver, 10).until(
                    expected_conditions.element_to_be_clickable(
                        (By.XPATH, text_me_button)
                    ),
                ).click()
                # Make sure the next page loads fully
                code_field = "#dom-otp-code-input"
                WebDriverWait(driver, 10).until(
                    expected_conditions.visibility_of_element_located(
                        (By.CSS_SELECTOR, code_field)
                    )
                )
                # Sometimes codes take a long time to arrive
                timeout = 300  # 5 minutes
                if botObj is not None and loop is not None:
                    sms_code = asyncio.run_coroutine_threadsafe(
                        getOTPCodeDiscord(botObj, name, timeout=timeout, loop=loop),
                        loop,
                    ).result()
                    if sms_code is None:
                        raise Exception("No SMS code found")
                else:
                    sms_code = input("Enter security code: ")

                code_field = driver.find_element(by=By.CSS_SELECTOR, value=code_field)
                code_field.send_keys(str(sms_code))
                continue_btn_selector = "#dom-otp-code-submit-button"
                driver.find_element(By.CSS_SELECTOR, continue_btn_selector).click()
            except TimeoutException:
                pass
            # Wait for page to load to summary page
            if "summary" not in driver.current_url:
                if "errorpage" in driver.current_url.lower():
                    raise Exception(
                        f"{name}: Login Failed. Got Error Page: Current URL: {driver.current_url}"
                    )
                print("Waiting for portfolio page to load...")
                WebDriverWait(driver, 30).until(
                    expected_conditions.url_contains("summary")
                )
            # Make sure fidelity site is not in old view
            try:
                if "digital" not in driver.current_url:
                    print(f"Old view detected: {driver.current_url}")
                    driver.find_element(by=By.CSS_SELECTOR, value="#optout-btn").click()
                    WebDriverWait(driver, 10).until(check_if_page_loaded)
                    # Wait for page to be in new view
                    if "digital" not in driver.current_url:
                        WebDriverWait(driver, 60).until(
                            expected_conditions.url_contains("digital")
                        )
                    WebDriverWait(driver, 10).until(check_if_page_loaded)
                    print("Disabled old view!")
            except (TimeoutException, NoSuchElementException):
                print(
                    "Failed to disable old view! This might cause issues but maybe not..."
                )
            sleep(3)
            fidelity_obj.set_logged_in_object(name, driver)
            # Get account numbers, types, and balances
            account_dict = fidelity_account_info(driver)
            if account_dict is None:
                raise Exception(f"{name}: Error getting account info")
            for acct in account_dict:
                fidelity_obj.set_account_number(name, acct)
                fidelity_obj.set_account_type(name, acct, account_dict[acct]["type"])
                fidelity_obj.set_account_totals(
                    name, acct, account_dict[acct]["balance"]
                )
            print(f"Logged in to {name}!")
        except Exception as e:
            fidelity_error(driver, e)
            driver.close()
            driver.quit()
            return None
    return fidelity_obj


def fidelity_account_info(driver: webdriver) -> dict | None:
    try:
        # Get account holdings
        driver.get("https://digital.fidelity.com/ftgw/digital/portfolio/positions")
        # Wait for page load
        WebDriverWait(driver, 10).until(check_if_page_loaded)
        # Get account numbers via javascript
        WebDriverWait(driver, 10).until(
            expected_conditions.presence_of_element_located(
                (By.CLASS_NAME, "acct-selector__acct-num")
            )
        )
        account_numbers = javascript_get_classname(driver, "acct-selector__acct-num")
        # Get account balances via javascript
        account_values = javascript_get_classname(driver, "acct-selector__acct-balance")
        # Get account names via javascript
        account_types = javascript_get_classname(driver, "acct-selector__acct-name")
        # Make sure all lists are the same length
        if not (
            len(account_numbers) == len(account_values)
            and len(account_numbers) == len(account_types)
        ):
            shortest = min(
                len(account_numbers), len(account_values), len(account_types)
            )
            account_numbers = account_numbers[:shortest]
            account_values = account_values[:shortest]
            account_types = account_types[:shortest]
            print(
                f"Warning: Account numbers, values, and types are not the same length! Using shortest length: {shortest}"
            )
        # Construct dictionary of account numbers and balances
        account_dict = {}
        for i, account in enumerate(account_numbers):
            av = (
                account_values[i]
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
        fidelity_error(driver, e)
        return None


def fidelity_holdings(fidelity_o: Brokerage, loop=None):
    for key in fidelity_o.get_account_numbers():
        driver: webdriver = fidelity_o.get_logged_in_objects(key)
        for account in fidelity_o.get_account_numbers(key):
            try:
                driver.get(
                    f"https://digital.fidelity.com/ftgw/digital/portfolio/positions#{account}"
                )
                # Wait for page load
                WebDriverWait(driver, 10).until(check_if_page_loaded)
                # Get holdings via javascript
                WebDriverWait(driver, 10).until(
                    expected_conditions.presence_of_element_located(
                        (By.CLASS_NAME, "ag-pinned-left-cols-container")
                    )
                )
                stocks_list = javascript_get_classname(
                    driver, "ag-pinned-left-cols-container"
                )
                # Find 1-5 letter words surrounded by 2 spaces on each side
                for i in range(len(stocks_list)):
                    stocks_list[i].replace(" \n ", "").replace("*", "")
                    stocks_list[i] = re.findall(
                        r"(?<=\s{2})[a-zA-Z]{1,5}(?=\s{2})", stocks_list[i]
                    )
                stocks_list = stocks_list[0]
                # holdings_info = javascript_get_classname(
                #     driver, "ag-center-cols-container"
                # )
                # print(f"Holdings Info: {holdings_info}")
                for stock in stocks_list:
                    fidelity_o.set_holdings(key, account, stock, "N/A", "N/A")
            except Exception as e:
                fidelity_error(driver, e)
                continue
    printHoldings(fidelity_o, loop)
    killSeleniumDriver(fidelity_o)


def fidelity_transaction(fidelity_o: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Fidelity")
    print("==============================")
    print()
    new_style = False
    for s in orderObj.get_stocks():
        for key in fidelity_o.get_account_numbers():
            printAndDiscord(
                f"{key}: {orderObj.get_action()}ing {orderObj.get_amount()} of {s}",
                loop,
            )
            driver = fidelity_o.get_logged_in_objects(key)
            # Go to trade page
            driver.get(
                "https://digital.fidelity.com/ftgw/digital/trade-equity/index/orderEntry"
            )
            # Wait for page to load
            WebDriverWait(driver, 20).until(check_if_page_loaded)
            sleep(3)
            # Get number of accounts
            try:
                accounts_dropdown = driver.find_element(
                    by=By.CSS_SELECTOR, value="#dest-acct-dropdown"
                )
                driver.execute_script("arguments[0].click();", accounts_dropdown)
                WebDriverWait(driver, 10).until(
                    expected_conditions.presence_of_element_located(
                        (By.CSS_SELECTOR, "#ett-acct-sel-list")
                    )
                )
                test = driver.find_element(
                    by=By.CSS_SELECTOR, value="#ett-acct-sel-list"
                )
                accounts_list = test.find_elements(by=By.CSS_SELECTOR, value="li")
                number_of_accounts = len(accounts_list)
                # Click a second time to clear the account list
                driver.execute_script("arguments[0].click();", accounts_dropdown)
            except Exception as e:
                fidelity_error(driver, f"No accounts found in dropdown: {e}")
                killSeleniumDriver(fidelity_o)
                return None
            # Complete on each account
            # Because of stale elements, we need to re-find the elements each time
            for x in range(number_of_accounts):
                try:
                    # Select account
                    accounts_dropdown_in = driver.find_element(
                        by=By.CSS_SELECTOR, value="#eq-ticket-account-label"
                    )
                    driver.execute_script("arguments[0].click();", accounts_dropdown_in)
                    WebDriverWait(driver, 10).until(
                        expected_conditions.presence_of_element_located(
                            (By.ID, "ett-acct-sel-list")
                        )
                    )
                    test = driver.find_element(by=By.ID, value="ett-acct-sel-list")
                    accounts_dropdown_in = test.find_elements(
                        by=By.CSS_SELECTOR, value="li"
                    )
                    account_number = fidelity_o.get_account_numbers(key)[x]
                    account_label = maskString(account_number)
                    accounts_dropdown_in[x].click()
                    sleep(1)
                    # Type in ticker
                    ticker_box = driver.find_element(
                        by=By.CSS_SELECTOR, value="#eq-ticket-dest-symbol"
                    )
                    WebDriverWait(driver, 10).until(
                        expected_conditions.element_to_be_clickable(ticker_box)
                    )
                    ticker_box.send_keys(s)
                    ticker_box.send_keys(Keys.RETURN)
                    sleep(1)
                    # Check if symbol not found is displayed
                    try:
                        driver.find_element(
                            by=By.CSS_SELECTOR,
                            value="body > div.app-body > ap122489-ett-component > div > order-entry-base > div > div > div.order-entry__container-content.scroll > div > equity-order-selection > div:nth-child(1) > symbol-search > div > div.eq-ticket--border-top > div > div:nth-child(2) > div > div > div > pvd3-inline-alert > s-root > div > div.pvd-inline-alert__content > s-slot > s-assigned-wrapper",
                        )
                        printAndDiscord(f"{key} Error: Symbol {s} not found", loop)
                        print()
                        killSeleniumDriver(fidelity_o)
                        return None
                    except Exception:
                        pass
                    # Get last price
                    last_price = driver.find_element(
                        by=By.CSS_SELECTOR,
                        value="#eq-ticket__last-price > span.last-price",
                    ).text
                    last_price = last_price.replace("$", "")
                    # If price is under $1, then we have to use a limit order
                    LIMIT = bool(float(last_price) < 1)
                    # Figure out whether page is in old or new style
                    try:
                        action_dropdown = driver.find_element(
                            by=By.CSS_SELECTOR,
                            value="#dest-dropdownlist-button-action",
                        )
                        new_style = True
                    except NoSuchElementException:
                        pass
                    # Set buy/sell
                    if orderObj.get_action() == "buy":
                        # buy is default in dropdowns so do not need to click
                        if new_style:
                            driver.find_element(
                                by=By.CSS_SELECTOR,
                                value="#dest-dropdownlist-button-action",
                            ).click()
                            driver.find_element(
                                by=By.CSS_SELECTOR,
                                value="#order-action-container-id > dropdownlist-ett-ap122489 > div > div > div.dropdownlist_items.ett-tabkey-idx-sel-cls > div > div.dropdownlist_items--item.dropdownlist_items--item_hover",
                            ).click()
                        else:
                            buy_button = driver.find_element(
                                by=By.CSS_SELECTOR,
                                value="#action-buy > s-root > div > label > s-slot > s-assigned-wrapper",
                            )
                            buy_button.click()
                    else:
                        if new_style:
                            action_dropdown = driver.find_element(
                                by=By.CSS_SELECTOR,
                                value="#dest-dropdownlist-button-action",
                            )
                            action_dropdown.click()
                            driver.find_element(
                                by=By.CSS_SELECTOR,
                                value="#order-action-container-id > dropdownlist-ett-ap122489 > div > div > div.dropdownlist_items.ett-tabkey-idx-sel-cls > div > div:nth-child(2)",
                            ).click()
                        else:
                            sell_button = driver.find_element(
                                by=By.CSS_SELECTOR,
                                value="#action-sell > s-root > div > label > s-slot > s-assigned-wrapper",
                            )
                            sell_button.click()
                    # Set amount (and clear previous amount)
                    amount_box = driver.find_element(
                        by=By.CSS_SELECTOR, value="#eqt-shared-quantity"
                    )
                    amount_box.clear()
                    amount_box.send_keys(str(orderObj.get_amount()))
                    # Set market/limit
                    if not LIMIT:
                        if new_style:
                            driver.find_element(
                                by=By.CSS_SELECTOR,
                                value="#dest-dropdownlist-button-ordertype",
                            ).click()
                            driver.find_element(
                                by=By.CSS_SELECTOR,
                                value="#order-type-container-id > dropdownlist-ett-ap122489 > div > div > div.dropdownlist_items.ett-tabkey-idx-sel-cls > div.dropdownlist_items--results-container > div:nth-child(1)",
                            ).click()
                        else:
                            market_button = driver.find_element(
                                by=By.CSS_SELECTOR,
                                value="#market-yes > s-root > div > label > s-slot > s-assigned-wrapper",
                            )
                            market_button.click()
                    else:
                        if new_style:
                            driver.find_element(
                                by=By.CSS_SELECTOR,
                                value="#dest-dropdownlist-button-ordertype",
                            ).click()
                            driver.find_element(
                                by=By.CSS_SELECTOR,
                                value="#order-type-container-id > dropdownlist-ett-ap122489 > div > div > div.dropdownlist_items.ett-tabkey-idx-sel-cls > div.dropdownlist_items--results-container > div:nth-child(2)",
                            ).click()
                        else:
                            limit_button = driver.find_element(
                                by=By.CSS_SELECTOR,
                                value="#market-no > s-root > div > label > s-slot > s-assigned-wrapper",
                            )
                            limit_button.click()
                        # Set price
                        difference_price = 0.01 if float(last_price) > 0.1 else 0.0001
                        if orderObj.get_action() == "buy":
                            wanted_price = round(
                                float(last_price) + difference_price, 3
                            )
                        else:
                            wanted_price = round(
                                float(last_price) - difference_price, 3
                            )
                        if new_style:
                            price_box = driver.find_element(
                                by=By.CSS_SELECTOR, value="#eqt-mts-limit-price"
                            )
                        else:
                            price_box = driver.find_element(
                                by=By.CSS_SELECTOR,
                                value="#eqt-ordsel-limit-price-field",
                            )
                        price_box.clear()
                        price_box.send_keys(wanted_price)
                    # Check for margin account
                    try:
                        margin_cash = driver.find_element(
                            by=By.ID, value="tradetype-cash"
                        )
                        margin_cash.click()
                        print("Margin account found!")
                    except NoSuchElementException:
                        pass
                    # Preview order
                    WebDriverWait(driver, 10).until(check_if_page_loaded)
                    sleep(1)
                    preview_button = driver.find_element(
                        by=By.CSS_SELECTOR, value="#previewOrderBtn"
                    )
                    preview_button.click()
                    # Wait for page to load
                    WebDriverWait(driver, 10).until(check_if_page_loaded)
                    sleep(3)
                    # Check for error popup and clear
                    try:
                        error_dismiss = driver.find_element(
                            by=By.XPATH,
                            value="(//button[@class='pvd-modal__close-button'])[3]",
                        )
                        driver.execute_script("arguments[0].click();", error_dismiss)
                    except NoSuchElementException:
                        pass
                    # Place order
                    if not orderObj.get_dry():
                        # Check for error popup and clear it if the
                        # account cannot sell the stock for some reason
                        try:
                            place_button = driver.find_element(
                                by=By.CSS_SELECTOR, value="#placeOrderBtn"
                            )
                            place_button.click()

                            # Wait for page to load
                            WebDriverWait(driver, 10).until(check_if_page_loaded)
                            sleep(1)
                            # Send confirmation
                            printAndDiscord(
                                f"{key} {account_label}: {orderObj.get_action()} {orderObj.get_amount()} shares of {s}",
                                loop,
                            )
                        except NoSuchElementException:
                            # Check for error
                            WebDriverWait(driver, 10).until(
                                expected_conditions.presence_of_element_located(
                                    (
                                        By.XPATH,
                                        "(//button[@class='pvd-modal__close-button'])[3]",
                                    )
                                )
                            )
                            error_dismiss = driver.find_element(
                                by=By.XPATH,
                                value="(//button[@class='pvd-modal__close-button'])[3]",
                            )
                            driver.execute_script(
                                "arguments[0].click();", error_dismiss
                            )
                            printAndDiscord(
                                f"{key} account {account_label}: {orderObj.get_action()} {orderObj.get_amount()} shares of {s}. DID NOT COMPLETE! \nEither this account does not have enough shares, or an order is already pending.",
                                loop,
                            )
                        # Send confirmation
                    else:
                        printAndDiscord(
                            f"DRY: {key} account {account_label}: {orderObj.get_action()} {orderObj.get_amount()} shares of {s}",
                            loop,
                        )
                    sleep(3)
                except Exception as err:
                    fidelity_error(driver, err)
                    continue
            print()
    killSeleniumDriver(fidelity_o)
