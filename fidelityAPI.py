# Nelson Dane
# API to Interface with Fidelity
# Uses headless Selenium

import os
import datetime
import traceback
from time import sleep

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.wait import WebDriverWait

from helperAPI import Brokerage, stockOrder, getDriver, type_slowly, check_if_page_loaded, printAndDiscord


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
            fidelity_obj.set_logged_in_object(name, driver)
            ind, ret, health, values, ret_values, health_values = fidelity_account_numbers(driver, name=name)
            for i in ind:
                fidelity_obj.set_account_number(name, i)
                fidelity_obj.set_account_type(name, i, "Individual")
                fidelity_obj.set_account_totals(name, i, values[ind.index(i)])
            for i in ret:
                fidelity_obj.set_account_number(name, i)
                fidelity_obj.set_account_type(name, i, "Retirement")
                fidelity_obj.set_account_totals(name, i, ret_values[ret.index(i)])
            for i in health:
                fidelity_obj.set_account_number(name, i)
                fidelity_obj.set_account_type(name, i, "Health")
                fidelity_obj.set_account_totals(name, i, health_values[health.index(i)])
            print("Logged in to Fidelity!")
        except Exception as e:
            print(f'Error logging in: "{e}"')
            if driver is not None:
                driver.save_screenshot(f"fidelity-login-error-{datetime.datetime.now()}.png")
            traceback.print_exc()
            return None
    return fidelity_obj


def fidelity_account_numbers(driver: webdriver, ctx=None, loop=None, name="Fidelity"):
    ret_acc = True
    health_acc = True
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
        printAndDiscord(f"Total {name} account value: {total_value[0].text}", ctx, loop)
        # Get value of individual accounts
        ind_accounts = driver.find_elements(
            by=By.CSS_SELECTOR, value=r"#Investment\ Accounts"
        )
        account_list = ind_accounts[0].text.replace("\n", " ").split(" ")[1::5]
        values = values = [x.replace("$", "") for x in ind_accounts[0].text.replace("\n", " ").split(" ")[2::5]]
        try:
            # Get value of retirement accounts
            ret_accounts = driver.find_elements(
                by=By.CSS_SELECTOR, value=r"#Retirement\ Accounts"
            )
            ret_account_list = ret_accounts[0].text.replace("\n", " ").split(" ")[2::6]
            ret_values = [x.replace("$", "") for x in ret_accounts[0].text.replace("\n", " ").split(" ")[3::6]]
        except IndexError:
            print("No retirement accounts found, skipping...")
            ret_account_list = []
            ret_values = []
            ret_acc = False
        try:
            # Get value of health savings accounts
            health_accounts = driver.find_elements(
                by=By.CSS_SELECTOR, value=r"#Health\ Savings\ Accounts"
            )
            health_account_list = health_accounts[0].get_attribute("textContent").replace("\n", " ").split(" ")[27::9]
            health_values = [x.replace("$", "") for x in health_accounts[0].get_attribute("textContent").replace("\n", " ").split(" ")[31::5]]
        except IndexError:
            print("No health accounts found, skipping...")
            health_account_list = []
            health_values = []
            health_acc = False
        # Print out account numbers and values
        printAndDiscord("Individual accounts:", ctx, loop)
        for x, item in enumerate(account_list):
            printAndDiscord(f"{item} value: ${values[x]}", ctx, loop)
        if ret_acc:
            printAndDiscord("Retirement accounts:", ctx, loop)
            for x, item in enumerate(ret_account_list):
                printAndDiscord(f"{item} value: ${ret_values[x]}", ctx, loop)
        if health_acc:
            printAndDiscord("Health Savings accounts:", ctx, loop)
            for x, item in enumerate(health_account_list):
                printAndDiscord(f"{item} value: {health_values[x]}", ctx, loop)
        return account_list, ret_account_list, health_account_list, values, ret_values, health_values
    except Exception as e:
        print(f"{name}: Error getting holdings: {e}")
        driver.save_screenshot(f"fidelity-an-error-{datetime.datetime.now()}.png")
        print(traceback.format_exc())
        return None, None, None, None


def fidelity_holdings(fidelity_o: Brokerage, ctx=None, loop=None):
    print()
    print("==============================")
    print("Fidelity Holdings")
    print("==============================")
    print()
    for key in fidelity_o.get_account_numbers():
        driver = fidelity_o.get_logged_in_objects(key)
        # Get account holdings since holdings is not yet implemented
        fidelity_account_numbers(driver, ctx=ctx, loop=loop, name=key)


def fidelity_transaction(
    fidelity_o: Brokerage, orderObj: stockOrder, ctx=None, loop=None
):
    print()
    print("==============================")
    print("Fidelity")
    print("==============================")
    print()
    for s in orderObj.get_stocks():
        for key in fidelity_o.get_account_numbers():
            printAndDiscord(f"{key}: {orderObj.get_action()}ing {orderObj.get_amount()} of {s}", ctx, loop)
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
                test = driver.find_element(by=By.CSS_SELECTOR, value="#ett-acct-sel-list")
                accounts_list = test.find_elements(by=By.CSS_SELECTOR, value="li")
                print(f"Number of accounts: {len(accounts_list)}")
                number_of_accounts = len(accounts_list)
                # Click a second time to clear the account list
                driver.execute_script("arguments[0].click();", accounts_dropdown)
            except Exception as e:
                print(f"Error: No accounts foundin dropdown: {e}")
                traceback.print_exc()
                return
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
                    ticker_box.send_keys(s)
                    ticker_box.send_keys(Keys.RETURN)
                    sleep(1)
                    # Check if symbol not found is displayed
                    try:
                        driver.find_element(
                            by=By.CSS_SELECTOR,
                            value="body > div.app-body > ap122489-ett-component > div > order-entry > div.eq-ticket.order-entry__container-height > div > div > form > div.order-entry__container-content.scroll > div:nth-child(2) > symbol-search > div > div.eq-ticket--border-top > div > div:nth-child(2) > div > div > div > pvd3-inline-alert > s-root > div > div.pvd-inline-alert__content > s-slot > s-assigned-wrapper",
                        )
                        print(f"Error: Symbol {s} not found")
                        return
                    except Exception:
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
                    if orderObj.get_action() == "buy":
                        buy_button = driver.find_element(
                            by=By.CSS_SELECTOR,
                            value="#action-buy > s-root > div > label > s-slot > s-assigned-wrapper",
                        )
                        buy_button.click()
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
                        if orderObj.get_action() == "buy":
                            wanted_price = round(float(ask_price) + 0.01, 3)
                        else:
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
                                ctx,
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
                            driver.execute_script("arguments[0].click();", error_dismiss)
                            printAndDiscord(
                                f"{key} {account_label}: {orderObj.get_action()} {orderObj.get_amount()} shares of {s}. DID NOT COMPLETE! \nEither this account does not have enough shares, or an order is already pending.",
                                ctx,
                                loop,
                            )
                        # Send confirmation
                    else:
                        printAndDiscord(
                            f"DRY: {key} {account_label}: {orderObj.get_action()} {orderObj.get_amount()} shares of {s}",
                            ctx,
                            loop,
                        )
                    sleep(3)
                except Exception as err:
                    print(err)
                    traceback.print_exc()
                    driver.save_screenshot(f"fidelity-login-error-{datetime.datetime.now()}.png")
                    continue
            print()
