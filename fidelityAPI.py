# Nelson Dane
# API to Interface with Fidelity
# Uses headless Selenium

import asyncio
import os
import traceback
from time import sleep

from dotenv import load_dotenv
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait

from seleniumAPI import *


def fidelity_init(DOCKER=False):
    try:
        # Initialize .env file
        load_dotenv()
        # Import Fidelity account
        if not os.getenv("FIDELITY_USERNAME") or not os.getenv("FIDELITY_PASSWORD"):
            print("Fidelity not found, skipping...")
            return None
        FIDELITY_USERNAME = os.environ["FIDELITY_USERNAME"]
        FIDELITY_PASSWORD = os.environ["FIDELITY_PASSWORD"]
        # Init webdriver
        print("Logging in to Fidelity...")
        driver = getDriver(DOCKER)
        # Log in to Fidelity account
        driver.get(
            "https://digital.fidelity.com/prgw/digital/login/full-page?AuthRedUrl=https://digital.fidelity.com/ftgw/digital/portfolio/summary"
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
        username_field.send_keys(FIDELITY_USERNAME)
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable((By.CSS_SELECTOR, "#password"))
        )
        password_field = driver.find_element(by=By.CSS_SELECTOR, value="#password")
        password_field.send_keys(FIDELITY_PASSWORD)
        driver.find_element(by=By.CSS_SELECTOR, value="#fs-login-button").click()
        WebDriverWait(driver, 10).until(check_if_page_loaded)
        sleep(3)
        # Wait for page to load to summary page
        if not "summary" in driver.current_url:
            WebDriverWait(driver, 60).until(expected_conditions.url_contains("summary"))
        # Make sure fidelity site is not in beta view
        try:
            WebDriverWait(driver, 30).until(
                expected_conditions.presence_of_element_located(
                    (By.LINK_TEXT, "Try Beta view")
                )
            )
            print("Beta view already disabled!")
        except TimeoutException:
            print("Disabling beta view...")
            driver.find_element(by=By.CSS_SELECTOR, value="#optout-btn").click()
            WebDriverWait(driver, 10).until(check_if_page_loaded)
            # Wait for page to be in old view
            if not "oltx" in driver.current_url:
                WebDriverWait(driver, 60).until(
                    expected_conditions.url_contains("oltx")
                )
            WebDriverWait(driver, 10).until(check_if_page_loaded)
            print("Disabled beta view!")
        sleep(3)
        print("Logged in to Fidelity!")
    except Exception as e:
        print(f'Error logging in: "{e}"')
        traceback.print_exc()
        return None
    return driver


def fidelity_holdings(driver, ctx=None, loop=None):
    print()
    print("==============================")
    print("Fidelity Holdings")
    print("==============================")
    print()
    ret_acc = True
    # Make sure init didn't return None
    if driver is None:
        print("Error: No Fidelity account")
        return None
    try:
        # Get account holdings
        driver.get("https://oltx.fidelity.com/ftgw/fbc/oftop/portfolio#positions")
        # Wait for page load
        WebDriverWait(driver, 10).until(check_if_page_loaded)
        sleep(5)
        # Get total account value
        total_value = driver.find_elements(
            by=By.CSS_SELECTOR,
            value="body > div.fidgrid.fidgrid--shadow.fidgrid--nogutter > div.full-page--container > div.fidgrid--row.port-summary-container > div.port-summary-content.clearfix > div > div.fidgrid--content > div > div.account-selector-wrapper.port-nav.account-selector--reveal > div.account-selector.account-selector--normal-mode.clearfix > div.account-selector--main-wrapper > div.account-selector--accounts-wrapper > div.account-selector--tab.account-selector--tab-all.js-portfolio.account-selector--target-tab.js-selected > span.account-selector--tab-row.account-selector--all-accounts-balance.js-portfolio-balance",
        )
        print(f"Total Fidelity account value: {total_value[0].text}")
        if ctx and loop:
            asyncio.ensure_future(
                ctx.send(f"Total Fidelity account value: {total_value[0].text}"),
                loop=loop,
            )
        # Get value of individual and retirement accounts
        ind_accounts = driver.find_elements(
            by=By.CSS_SELECTOR, value='[data-group-id="IA"]'
        )
        ret_accounts = driver.find_elements(
            by=By.CSS_SELECTOR, value='[data-group-id="RA"]'
        )
        # Get text from elements
        test = ind_accounts[0].text
        try:
            test2 = ret_accounts[0].text
        except IndexError:
            print("No retirement accounts found, skipping...")
            ret_acc = False
        # Split by new line
        info = test.splitlines()
        if ret_acc:
            info2 = test2.splitlines()
        # Get every 4th element in the list, starting at the 3rd element
        # This is the account number
        ind_num = []
        ret_num = []
        for x in info[3::4]:
            ind_num.append(x)
        if ret_acc:
            for x in info2[2::4]:
                ret_num.append(x)
        # Get every 4th element in the list, starting at the 4th element
        # This is the account value
        ind_val = []
        ret_val = []
        for x in info[4::4]:
            ind_val.append(x)
        if ret_acc:
            for x in info2[3::4]:
                ret_val.append(x)
        # Print out account numbers and values
        print("Individual accounts:")
        if ctx and loop:
            asyncio.ensure_future(ctx.send("Individual accounts:"), loop=loop)
        for x, item in enumerate(ind_num):
            print(f"{item} value: {ind_val[x]}")
            if ctx and loop:
                asyncio.ensure_future(
                    ctx.send(f"{item} value: {ind_val[x]}"), loop=loop
                )
        if ret_acc:
            print("Retirement accounts:")
            if ctx and loop:
                asyncio.ensure_future(ctx.send("Retirement accounts:"), loop=loop)
            for x, item in enumerate(ret_num):
                print(f"{item} value: {ret_val[x]}")
                if ctx and loop:
                    asyncio.ensure_future(
                        ctx.send(f"{item} value: {ret_val[x]}"), loop=loop
                    )
            # We'll add positions later since that will be hard
    except Exception as e:
        print(f"Error getting holdings: {e}")
        print(traceback.format_exc())


def fidelity_transaction(
    driver, action, stock, amount, price, time, DRY=True, ctx=None, loop=None
):
    # Make sure init didn't return None
    if driver is None:
        print("Error: No Fidelity account")
        return None
    print()
    print("==============================")
    print("Fidelity")
    print("==============================")
    print()
    action = action.lower()
    stock = stock.upper()
    amount = int(amount)
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
            by=By.CSS_SELECTOR, value="#eq-ticket-account-label"
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
                        f"Fidelity {account_label}: {action} {amount} shares of {stock}"
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
                        message = f"Fidelity {account_label}: {action} {amount} shares of {stock}. DID NOT COMPLETE! \nEither this account does not have enough shares, or an order is already pending."
                    elif action == "buy":
                        message = f"Fidelity {account_label}: {action} {amount} shares of {stock}. DID NOT COMPLETE! \nEither this account does not have enough cash, or an order is already pending."
                    print(message)
                    if ctx and loop:
                        asyncio.ensure_future(ctx.send(message), loop=loop)
                # Send confirmation
            else:
                message = f"DRY: Fidelity {account_label}: {action} {amount} shares of {stock}"
                print(message)
                if ctx and loop:
                    asyncio.ensure_future(ctx.send(message), loop=loop)
            sleep(3)
        except Exception as e:
            print(e)
            traceback.print_exc()
            continue
