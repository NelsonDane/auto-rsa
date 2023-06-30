# Nelson Dane
# API to Interface with Fidelity
# Uses headless Selenium

import asyncio
import os
import datetime
import traceback
from time import sleep

from dotenv import load_dotenv
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait

from helperAPI import *


def fidelity_init(FIDELITY_EXTERNAL=None, DOCKER=False):
    # Initialize .env file
    load_dotenv()
    # Import Fidelity account
    if not os.getenv("FIDELITY") and FIDELITY_EXTERNAL is None:
        print("Fidelity not found, skipping...")
        return None
    accounts = os.environ["FIDELITY"].strip().split(",") if FIDELITY_EXTERNAL is None else FIDELITY_EXTERNAL.strip().split(",")
    fidelity_obj = Brokerage("Fidelity")
    # Init webdriver
    for account in accounts:
        index = accounts.index(account) + 1
        account = account.split(":")
        try:
            print("Logging in to Fidelity...")
            driver = getDriver(DOCKER)
            # Log in to Fidelity account
            driver.get(
                "https://login.fidelity.com/ftgw/Fas/Fidelity/RtlCust/Refresh/Init/df.chf.ra/?AuthRedUrl=https://digital.fidelity.com/ftgw/digital/portfolio/summary"
            )
            # Wait for page load
            WebDriverWait(driver, 20).until(check_if_page_loaded)
            # Type in username and password and click login
            WebDriverWait(driver, 10).until(
                expected_conditions.element_to_be_clickable(
                    (By.CSS_SELECTOR, "#userId-input")
                )
            )
            username_field = driver.find_element(by=By.CSS_SELECTOR, value="#userId-input")
            type_slowly(username_field, account[0])
            WebDriverWait(driver, 10).until(
                expected_conditions.element_to_be_clickable((By.CSS_SELECTOR, "#password"))
            )
            password_field = driver.find_element(by=By.CSS_SELECTOR, value="#password")
            type_slowly(password_field, account[1])
            driver.find_element(by=By.CSS_SELECTOR, value="#fs-login-button").click()
            WebDriverWait(driver, 10).until(check_if_page_loaded)
            sleep(3)
            # Wait for page to load to summary page
            if "summary" not in driver.current_url:
                print("Waiting for portfolio page to load...")
                WebDriverWait(driver, 30).until(expected_conditions.url_contains("summary"))
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
            fidelity_obj.loggedInObjects.append(driver)
            ind, ret = fidelity_account_numbers(driver, index=index)[0:2]
            for i in ind:
                fidelity_obj.add_account_number(f"Fidelity {index} (Individual)", i)
            for i in ret:
                fidelity_obj.add_account_number(f"Fidelity {index} (Retirement)", i)
            print("Logged in to Fidelity!")
        except Exception as e:
            print(f'Error logging in: "{e}"')
            driver.save_screenshot(f"fidelity-login-error-{datetime.datetime.now()}.png")
            traceback.print_exc()
            return None
    return fidelity_obj


def fidelity_account_numbers(driver, ctx=None, loop=None, index=1):
    ret_acc = True
    try:
        # Get account holdings
        driver.get("https://digital.fidelity.com/ftgw/digital/portfolio/positions")
        # Wait for page load
        WebDriverWait(driver, 10).until(check_if_page_loaded)
        sleep(5)
        # Get total account value
        total_value = driver.find_elements(
            by=By.CSS_SELECTOR,
            value="body > ap143528-portsum-dashboard-root > dashboard-root > div > div.account-selector__outer-box.account-selector__outer-box--expand-in-pc > accounts-selector > nav > div.acct-selector__acct-list > pvd3-link > s-root > span > a > span > s-slot > s-assigned-wrapper > div > div > div > span:nth-child(2)",
        )
        print(f"Total Fidelity {index} account value: {total_value[0].text}")
        if ctx and loop:
            asyncio.ensure_future(
                ctx.send(f"Total Fidelity {index} account value: {total_value[0].text}"),
                loop=loop,
            )
        # Get value of individual and retirement accounts
        ind_accounts = driver.find_elements(
            by=By.CSS_SELECTOR, value=r"#Investment\ Accounts"
        )
        ret_accounts = driver.find_elements(
            by=By.CSS_SELECTOR, value=r"#Retirement\ Accounts"
        )
        # Get text from elements
        account_list = ind_accounts[0].text.replace("\n", " ").split(" ")[1::5]
        values = ind_accounts[0].text.replace("\n", " ").split(" ")[2::5]
        try:
            ret_account_list = ret_accounts[0].text.replace("\n", " ").split(" ")[2::6]
            ret_values = ret_accounts[0].text.replace("\n", " ").split(" ")[3::6]
        except IndexError:
            print("No retirement accounts found, skipping...")
            ret_acc = False
        # Print out account numbers and values
        print("Individual accounts:")
        if ctx and loop:
            asyncio.ensure_future(ctx.send("Individual accounts:"), loop=loop)
        for x, item in enumerate(account_list):
            print(f"{item} value: {values[x]}")
            if ctx and loop:
                asyncio.ensure_future(ctx.send(f"{item} value: {values[x]}"), loop=loop)
        if ret_acc:
            print("Retirement accounts:")
            if ctx and loop:
                asyncio.ensure_future(ctx.send("Retirement accounts:"), loop=loop)
            for x, item in enumerate(ret_account_list):
                print(f"{item} value: {ret_values[x]}")
                if ctx and loop:
                    asyncio.ensure_future(
                        ctx.send(f"{item} value: {ret_values[x]}"), loop=loop
                    )
        return account_list, ret_account_list, values, ret_values
    except Exception as e:
        print(f"Fidelity {index}: Error getting holdings: {e}")
        driver.save_screenshot(f"fidelity-an-error-{datetime.datetime.now()}.png")
        print(traceback.format_exc())
        return None, None, None, None


def fidelity_holdings(drivers, ctx=None, loop=None):
    print()
    print("==============================")
    print("Fidelity Holdings")
    print("==============================")
    print()
    for driver in drivers.loggedInObjects:
        index = drivers.loggedInObjects.index(driver) + 1
        # Get account holdings
        fidelity_account_numbers(driver, ctx=ctx, loop=loop, index=index)


def fidelity_transaction(
    driver_o, action, stock, amount, price, time, DRY=True, ctx=None, loop=None
):
    print()
    print("==============================")
    print("Fidelity")
    print("==============================")
    print()
    action = action.lower()
    stock = stock.upper()
    amount = int(amount)
    drivers = driver_o.loggedInObjects
    for driver in drivers:
        index = drivers.index(driver) + 1
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
            test = driver.find_element(by=By.CSS_SELECTOR, value="#ett-acct-sel-list")
            accounts_list = test.find_elements(by=By.CSS_SELECTOR, value="li")
            print(f"Number of accounts: {len(accounts_list)}")
            number_of_accounts = len(accounts_list)
            # Click a second time to clear the account list
            driver.execute_script("arguments[0].click();", accounts_dropdown)
        except:
            print("Error: No accounts foundin dropdown")
            traceback.print_exc()
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
                accounts_dropdown_in = test.find_elements(by=By.CSS_SELECTOR, value="li")
                account_label = accounts_dropdown_in[x].text
                accounts_dropdown_in[x].click()
                sleep(1)
                # Type in ticker
                ticker_box = driver.find_element(
                    by=By.CSS_SELECTOR, value="#eq-ticket-dest-symbol"
                )
                WebDriverWait(driver, 10).until(
                    expected_conditions.element_to_be_clickable(ticker_box)
                )
                ticker_box.send_keys(stock)
                ticker_box.send_keys(Keys.RETURN)
                sleep(1)
                # Check if symbol not found is displayed
                try:
                    driver.find_element(
                        by=By.CSS_SELECTOR,
                        value="body > div.app-body > ap122489-ett-component > div > order-entry > div.eq-ticket.order-entry__container-height > div > div > form > div.order-entry__container-content.scroll > div:nth-child(2) > symbol-search > div > div.eq-ticket--border-top > div > div:nth-child(2) > div > div > div > pvd3-inline-alert > s-root > div > div.pvd-inline-alert__content > s-slot > s-assigned-wrapper",
                    )
                    print(f"Error: Symbol {stock} not found")
                    return None
                except:
                    pass
                # Get ask/bid price
                ask_price = (
                    driver.find_element(
                        by=By.CSS_SELECTOR,
                        value="#quote-panel > div > div.eq-ticket__quote--blocks-container > div:nth-child(2) > div > span > span",
                    )
                ).text
                bid_price = (
                    driver.find_element(
                        by=By.CSS_SELECTOR,
                        value="#quote-panel > div > div.eq-ticket__quote--blocks-container > div:nth-child(1) > div > span > span",
                    )
                ).text
                # If price is under $1, then we have to use a limit order
                LIMIT = bool(float(ask_price) < 1 or float(bid_price) < 1)
                # Set buy/sell
                if action == "buy":
                    buy_button = driver.find_element(
                        by=By.CSS_SELECTOR,
                        value="#action-buy > s-root > div > label > s-slot > s-assigned-wrapper",
                    )
                    buy_button.click()
                elif action == "sell":
                    sell_button = driver.find_element(
                        by=By.CSS_SELECTOR,
                        value="#action-sell > s-root > div > label > s-slot > s-assigned-wrapper",
                    )
                    sell_button.click()
                else:
                    print(f"Error: Invalid action {action}")
                    return None
                # Set amount (and clear previous amount)
                amount_box = driver.find_element(
                    by=By.CSS_SELECTOR, value="#eqt-shared-quantity"
                )
                amount_box.clear()
                amount_box.send_keys(amount)
                # Set market/limit
                if not LIMIT:
                    market_button = driver.find_element(
                        by=By.CSS_SELECTOR,
                        value="#market-yes > s-root > div > label > s-slot > s-assigned-wrapper",
                    )
                    market_button.click()
                else:
                    limit_button = driver.find_element(
                        by=By.CSS_SELECTOR,
                        value="#market-no > s-root > div > label > s-slot > s-assigned-wrapper",
                    )
                    limit_button.click()
                    # Set price
                    if action == "buy":
                        wanted_price = round(float(ask_price) + 0.01, 3)
                    elif action == "sell":
                        wanted_price = round(float(bid_price) - 0.01, 3)
                    price_box = driver.find_element(
                        by=By.CSS_SELECTOR, value="#eqt-ordsel-limit-price-field"
                    )
                    price_box.clear()
                    price_box.send_keys(wanted_price)
                # Preview order
                WebDriverWait(driver, 10).until(check_if_page_loaded)
                sleep(1)
                preview_button = driver.find_element(
                    by=By.CSS_SELECTOR, value="#previewOrderBtn"
                )
                preview_button.click()
                # Wait for page to load
                WebDriverWait(driver, 10).until(check_if_page_loaded)
                sleep(1)
                # Place order
                if not DRY:
                    # Check for error popup and clear it if the account cannot sell the stock for some reason.
                    try:
                        place_button = driver.find_element(
                            by=By.CSS_SELECTOR, value="#placeOrderBtn"
                        )
                        place_button.click()

                        # Wait for page to load
                        WebDriverWait(driver, 10).until(check_if_page_loaded)
                        sleep(1)
                        # Send confirmation
                        message = (
                            f"Fidelity {index} {account_label}: {action} {amount} shares of {stock}"
                        )
                        print(message)
                        if ctx and loop:
                            asyncio.ensure_future(ctx.send(message), loop=loop)
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
                        driver.execute_script("arguments[0].click();", error_dismiss)
                        if action == "sell":
                            message = f"Fidelity {index} {account_label}: {action} {amount} shares of {stock}. DID NOT COMPLETE! \nEither this account does not have enough shares, or an order is already pending."
                        elif action == "buy":
                            message = f"Fidelity {index} {account_label}: {action} {amount} shares of {stock}. DID NOT COMPLETE! \nEither this account does not have enough cash, or an order is already pending."
                        print(message)
                        if ctx and loop:
                            asyncio.ensure_future(ctx.send(message), loop=loop)
                    # Send confirmation
                else:
                    message = f"DRY: Fidelity {index} {account_label}: {action} {amount} shares of {stock}"
                    print(message)
                    if ctx and loop:
                        asyncio.ensure_future(ctx.send(message), loop=loop)
                sleep(3)
            except Exception as e:
                print(e)
                traceback.print_exc()
                driver.save_screenshot(f"fidelity-login-error-{datetime.datetime.now()}.png")
                continue

