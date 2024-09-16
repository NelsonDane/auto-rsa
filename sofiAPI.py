import asyncio
import datetime
import os
import traceback
from time import sleep
import logging

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
import pyotp

from helperAPI import (
    Brokerage,
    check_if_page_loaded,
    getDriver,
    killSeleniumDriver,
    printAndDiscord,
    printHoldings,
    stockOrder,
    getOTPCodeDiscord,
    load_cookies,
    save_cookies
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def sofi_error(driver, loop=None):
    if driver is not None:
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_name = f"SoFi-error-{timestamp}.png"
            driver.save_screenshot(screenshot_name)
        except Exception:
            pass

    try:
        error_message = f"SoFi Error: {traceback.format_exc()}"
        printAndDiscord(error_message, loop, embed=False)
    except Exception:
        pass


def get_2fa_code(secret):
    totp = pyotp.TOTP(secret)
    return totp.now()


def sofi_init(SOFI_EXTERNAL=None,DOCKER=False, botObj=None, loop=None):
    load_dotenv()

    if not os.getenv("SOFI") and SOFI_EXTERNAL is None:
        printAndDiscord("SoFi environment variable not found.", loop)
        return None

    accounts = (
        os.environ["SOFI"].strip().split(",")
        if SOFI_EXTERNAL is None
        else SOFI_EXTERNAL.strip().split(",")
    )
    sofi_obj = Brokerage("SoFi")

    for account in accounts:
        index = accounts.index(account) + 1
        name = f"SoFi {index}"
        account = account.split(":")
        cookie_filename = f"sofi{index}.pkl"
        cookie_path = "creds"

        try:
            driver = getDriver(DOCKER)
            if driver is None:
                raise Exception("Driver not found.")
            
            # Step 1: Navigate to SoFi homepage first
            driver.get('https://www.sofi.com')

            # Step 2: Load cookies and check if they are valid
            cookies_loaded = load_cookies(driver, cookie_filename, path=cookie_path)
            if cookies_loaded:
                driver.get('https://www.sofi.com/wealth/app')  # Navigate to the wealth page
                WebDriverWait(driver, 10).until(EC.url_contains("overview"))

                # Check if cookies are valid and you are logged in
                if "overview" in driver.current_url:
                    print(f"Successfully bypassed login with cookies for {name}")
                    save_cookies(driver, cookie_filename, path=cookie_path)  # Save the fresh cookies

                    # Step 5: After login or cookie bypass, check if page is loaded and continue
                    WebDriverWait(driver, 60).until(check_if_page_loaded)

                    # Retrieve and set account information
                    account_dict = sofi_account_info(driver)
                    if account_dict is None:
                        raise Exception(f"{name}: Error getting account info")

                    for acct in account_dict:
                        sofi_obj.set_account_number(name, acct)
                        sofi_obj.set_account_totals(name, acct, account_dict[acct]["balance"])

                    sofi_obj.set_logged_in_object(name, driver)

                    continue

            print(f"Cookies not valid or expired for {name}, proceeding with login flow.")
            driver.get('https://www.sofi.com/login')
            username_field = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='username']"))
            )
            username_field.send_keys(account[0])

            password_field = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='password']"))
            )
            password_field.send_keys(account[1])

            login_button = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='widget_block']/div/div[2]/div/div/main/section/div/div/div/form/div[2]/button"))
            )
            driver.execute_script("arguments[0].click();", login_button)

            # Step 4: Handle 2FA if necessary
            secret = account[2] if len(account) > 2 else None

            if secret:
                try:
                    # Use the authenticator 2FA code if the secret exists
                    two_fa_code = get_2fa_code(secret)
                    code_field = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, "code"))
                    )
                    code_field.send_keys(two_fa_code)

                    # Ensure "Remember this device" is checked
                    remember_checkbox = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, '//*[@id="widget_block"]/div/div[2]/div/div/main/section/div/div/div/form/div[2]'))
                    )
                    if not remember_checkbox.is_selected():
                        remember_checkbox.click()
                    print("Checked 'Remember this device' checkbox.")

                    # Simulate hitting the "Enter" key after entering the 2FA code
                    code_field.send_keys(Keys.RETURN)

                    # Wait for successful login URL
                    driver.get('https://www.sofi.com/wealth/app/overview')
                    WebDriverWait(driver, 30).until(
                        EC.url_contains("https://www.sofi.com/wealth/app/overview")
                    )

                except Exception:
                    sofi_error(driver, loop)
                    return None

            else:
                # Check if SMS 2FA is required
                try:
                    WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.ID, "code")))
                except TimeoutException:
                    return None

                # Proceed with SMS 2FA
                max_attempts = 3
                attempts = 0

                while attempts < max_attempts:
                    try:
                        if botObj is not None and loop is not None:
                            sms_code = asyncio.run_coroutine_threadsafe(
                                getOTPCodeDiscord(botObj, name, timeout=300, loop=loop),
                                loop,
                            ).result()
                            if sms_code is None:
                                raise Exception("No SMS code found")
                        else:
                            sms_code = input("Enter security code: ")

                        code_field = WebDriverWait(driver, 60).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='code']"))
                        )
                        code_field.send_keys(sms_code)

                        # Ensure "Remember this device" is checked
                        remember_checkbox = driver.find_element(By.XPATH, '//*[@id="widget_block"]/div/div[2]/div/div/main/section/div/div/div/form/div[2]')
                        if not remember_checkbox.is_selected():
                            remember_checkbox.click()
                        print("Checked 'Remember this device' checkbox.")

                        code_field.send_keys(Keys.RETURN)
                        sleep(3)

                        if driver.find_elements(By.XPATH, "//*[@id='code']"):
                            attempts += 1
                            if attempts >= max_attempts:
                                raise TimeoutException("Max 2FA attempts reached. Exiting...")
                        else:
                            break

                    except TimeoutException:
                        if attempts >= max_attempts:
                            raise TimeoutException("Max 2FA attempts reached due to timeouts. Exiting...")

            # Step 5: After login and 2FA, check if login is successful
            WebDriverWait(driver, 60).until(check_if_page_loaded)

            # Capture and save all cookies after successful login
            save_cookies(driver, cookie_filename, path=cookie_path)

            # Retrieve and set account information
            account_dict = sofi_account_info(driver)
            if account_dict is None:
                raise Exception(f"{name}: Error getting account info")

            for acct in account_dict:
                sofi_obj.set_account_number(name, acct)
                sofi_obj.set_account_totals(name, acct, account_dict[acct]["balance"])

            sofi_obj.set_logged_in_object(name, driver)

        except TimeoutException:
            printAndDiscord(f"TimeoutException: Login failed for {name}.", loop)
            return False

        except Exception:
            sofi_error(driver, loop)
            driver.close()
            driver.quit()
            return None

    return sofi_obj


def sofi_account_info(driver: webdriver, loop=None) -> dict | None:
    try:
        logger.info("Navigating to SoFi account overview page...")
        driver.get('https://www.sofi.com/wealth/app/overview')
        WebDriverWait(driver, 60).until(check_if_page_loaded)

        logger.info("Collecting account information...")
        # Collect all account links
        account_boxes = WebDriverWait(driver, 60).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, '.AccountCardWrapper-PyEjZ .linked-card > a'))
        )

        account_dict = {}
        for index, account_box in enumerate(account_boxes):
            try:
                # Open the account link in a new tab
                account_link = account_box.get_attribute('href')
                driver.execute_script(f"window.open('{account_link}', '_blank');")
                driver.switch_to.window(driver.window_handles[-1])  # Switch to the newly opened tab

                # Wait for the account page to load
                WebDriverWait(driver, 60).until(check_if_page_loaded)

                # Extract account number from the account page
                account_number_element = WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '#page-wrap > section:nth-child(2) > div.StyledFlex-hyCQyL.dPIcoC.HeaderWithSearchWrapper-Xeaqb.AccountHeaderWrapper-cvufWC.cSaibV.hHdLiB > div.AccountHeader-edyzFd.rVUTO > h1'))
                )
                account_number_text = account_number_element.text.strip()
                account_number = account_number_text.split("#")[1].split(")")[0].strip()
                logger.info("Account number: %s", account_number)

                # Extract total value
                current_value_element = WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '#page-wrap > section:nth-child(6) > div:nth-child(3) > div > span:nth-child(2)'))
                )
                current_value = current_value_element.text.strip().replace('$', '').replace(',', '')
                logger.info("Current value for account %s: %s", account_number, current_value)

                # Assuming a default account type, you can adjust this if needed
                account_type = "Investment Account"

                # Store account info in the dictionary
                account_dict[account_number] = {
                    'type': account_type,
                    'balance': float(current_value),
                }

                # Close the tab after extracting the information
                driver.close()
                driver.switch_to.window(driver.window_handles[0])

            except Exception as e:
                logger.error("Error processing account information for account %d: %s", index + 1, e)
                # Close the tab if any error occurs and switch back
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                continue

        if not account_dict:
            raise Exception("No accounts found or elements were missing.")

        return account_dict

    except Exception:
        sofi_error(driver, loop)
        return None


def sofi_holdings(SoFi_o: Brokerage, loop=None):
    # Get holdings on each account
    for key in list(SoFi_o.get_account_numbers()):
        driver: webdriver = SoFi_o.get_logged_in_objects(key)
        try:
            logger.info("Processing holdings for account: %s", key)

            # Process each account link one by one
            account_boxes = driver.find_elements(By.CSS_SELECTOR, '.AccountCardWrapper-PyEjZ .linked-card > a')
            account_links = [box.get_attribute('href') for box in account_boxes]
            logger.info("Found %d account links to process.", len(account_links))

            for index, link in enumerate(account_links):
                try:
                    logger.info("Processing account link %d/%d: %s", index + 1, len(account_links), link)

                    driver.execute_script(f"window.open('{link}', '_blank');")
                    driver.switch_to.window(driver.window_handles[-1])  # Switch to the newly opened tab

                    sleep(5)
                    WebDriverWait(driver, 60).until(check_if_page_loaded)

                    account_number_element = WebDriverWait(driver, 60).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '#page-wrap > section:nth-child(2) > div.StyledFlex-hyCQyL.dPIcoC.HeaderWithSearchWrapper-Xeaqb.AccountHeaderWrapper-cvufWC.cSaibV.hHdLiB > div.AccountHeader-edyzFd.rVUTO > h1'))
                    )
                    account_number_text = account_number_element.text.strip()
                    account_number = account_number_text.split("#")[1].split(")")[0].strip()
                    logger.info("Account number: %s", account_number)

                    current_value_element = WebDriverWait(driver, 60).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '#page-wrap > section:nth-child(6) > div:nth-child(3) > div > span:nth-child(2)'))
                    )
                    current_value = current_value_element.text.strip()
                    logger.info("Current value for account %s: %s", account_number, current_value)

                    holdings_data = extract_holdings(driver, loop)

                    for holding in holdings_data:
                        SoFi_o.set_holdings(key, account_number, holding['company_name'], holding['shares'], holding['price'])
                    SoFi_o.set_account_totals(key, account_number, current_value)

                except Exception as extract_e:
                    logger.error("Error extracting account information for account %s: %s", key, extract_e)
                    printAndDiscord(f"Error extracting account information: {extract_e}", loop)
                    continue

                driver.close()
                driver.switch_to.window(driver.window_handles[0])

        except Exception as e:
            logger.error("Error processing SoFi holdings for account %s: %s", key, e)
            printAndDiscord(f"{key}: Error processing SoFi holdings: {e}", loop)
            continue

    logger.info("Finished processing all accounts, sending holdings to Discord.")
    printHoldings(SoFi_o, loop)
    killSeleniumDriver(SoFi_o)
    logger.info("Completed SoFi holdings processing.")


def extract_holdings(driver, loop=None):
    holdings_data = []
    try:
        holdings_elements = driver.find_elements(By.CSS_SELECTOR, "#page-wrap > section:nth-child(6) > div:nth-child(2) > a")
        logger.info("Found %d holdings elements to process.", len(holdings_elements))
        if len(holdings_elements) == 0:
            logger.error("No holdings elements found, double-check the CSS selector.")

        for holding_element in holdings_elements:
            try:
                company_name_element = holding_element.find_element(By.CSS_SELECTOR, 'div.HoldingDataItem-fFUjpV.bsvLGX.company')
                company_name = company_name_element.text.strip()

                shares_element = holding_element.find_element(By.CSS_SELECTOR, 'div.HoldingDataItem-fFUjpV.bsvLGX.shares')
                shares = shares_element.text.strip().split(' ')[0]

                price_element = holding_element.find_element(By.CSS_SELECTOR, 'div.HoldingDataGroup-wCUgj.HoldingDataGroupRight-jzGrzD.hkqyAE.fHYwpE > div.HoldingDataItem-fFUjpV.bsvLGX.market-price')
                price = price_element.text.strip()

                price_float = float(price.replace('$', '').replace(',', ''))

                logger.info("Scraped holding: %s, Shares: %s, Price: %f", company_name, shares, price_float)

                holdings_data.append({
                    'company_name': company_name,
                    'shares': shares,
                    'price': price_float
                })
            except Exception as e:
                logger.error("Error scraping a holding element: %s", e)
                continue
    except Exception:
        sofi_error(driver, loop)

    return holdings_data


def sofi_transaction(SoFi_o: Brokerage, orderObj: stockOrder, loop=None):
    print("\n==============================")
    print("SoFi")
    print("==============================\n")

    for s in orderObj.get_stocks():
        for key in SoFi_o.get_account_numbers():
            driver = SoFi_o.get_logged_in_objects(key)
            driver.get("https://www.sofi.com/wealth/app/overview")
            print(f"Navigated to SoFi overview page for account {key}")

            try:
                search_field = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.NAME, "search-bar"))
                )
                search_field.send_keys(s)
                print(f"Entered stock symbol {s} into the search bar")
            except TimeoutException:
                try:
                    invest_search_field = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[1]/div/div/div/input"))
                    )
                    invest_search_field.send_keys(s)
                    print(f"Entered stock symbol {s} into the alternative search field")
                except TimeoutException:
                    print(f"Search field for {s} not found.")
                    printAndDiscord(f"SoFi search field not found for {s}.", loop)
                    continue

            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_all_elements_located((By.XPATH, "//*[@id='page-wrap']/div[1]/div/div/div/ul/li"))
                )
                dropdown_items = driver.find_elements(By.XPATH, "//*[@id='page-wrap']/div[1]/div/div/div/ul/li")
                total_items = len(dropdown_items)
                print(f"Found {total_items} search results for {s}")

                if total_items == 0:
                    print(f"No stock found for {s}. Moving to next stock.")
                    printAndDiscord(f"SoFi doesn't have {s}.", loop)
                    continue

                found_stock = False
                for item in dropdown_items:
                    ticker_name = item.find_element(By.XPATH, "./a/div/p[1]").text
                    if ticker_name == s:
                        found_stock = True
                        item.click()
                        print(f"Found and selected stock {s}")
                        break

                if not found_stock:
                    print(f"SoFi doesn't have {s}. Moving to next stock.")
                    printAndDiscord(f"SoFi doesn't have {s}.", loop)
                    continue
            except TimeoutException:
                print(f"Search results did not appear for {s}. Moving to next stock.")
                printAndDiscord(f"SoFi search results did not appear for {s}.", loop)
                continue

            if orderObj.get_action() == "buy":
                process_account_transaction(driver, s, orderObj, key, loop, transaction_type="buy")
            elif orderObj.get_action() == "sell":
                process_account_transaction(driver, s, orderObj, key, loop, transaction_type="sell")

    print("Completed all transactions, Exiting...")
    killSeleniumDriver(SoFi_o)


def process_account_transaction(driver, stock, orderObj, key, loop, transaction_type):
    clicked_values = set()  # Set to keep track of processed accounts
    DRY = orderObj.get_dry()
    QUANTITY = orderObj.get_amount()
    print("DRY MODE:", DRY)
    account_number = 1

    while True:
        try:
            # Wait for the buy/sell page to load by ensuring the "Buy" button is present
            print(f"Waiting for the {transaction_type} page to load for {stock}.")
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[2]/div/button[1]"))
            )
            print(f"{transaction_type.capitalize()} page loaded for {stock}.")

            if transaction_type == "buy":
                print("Attempting to click the buy button")
                buy_button = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[2]/div/button[1]"))
                )
                driver.execute_script("arguments[0].click();", buy_button)
                print("Buy button clicked")
            else:
                print("Attempting to click the sell button")
                sell_button = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[2]/div/button[2]"))
                )
                driver.execute_script("arguments[0].click();", sell_button)
                print("Sell button clicked")

            accounts_dropdown = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.NAME, "account"))
            )
            select = Select(accounts_dropdown)

            for option in select.options:
                value = option.get_attribute('value')
                if value not in clicked_values:
                    select.select_by_value(value)
                    print(f"Selected account {account_number} (real: {key}): {value} (dropdown selection value)")
                    account_number += 1
                    clicked_values.add(value)
                    break
            else:
                print(f"All accounts have been processed for {stock}.")
                break

            if transaction_type == "buy":
                handle_buy_process(driver, stock, QUANTITY, DRY, key, loop)
            else:
                handle_sell_process(driver, stock, QUANTITY, DRY, key, loop)

        except TimeoutException:
            print(f"{transaction_type.capitalize()} button not found for {stock}. Moving to next stock.")
            printAndDiscord(f"SoFi {transaction_type} button not found for {stock}.", loop)
            break


def handle_buy_process(driver, stock, QUANTITY, DRY, key, loop):
    try:
        # Enter quantity to buy
        sleep(2)
        print(f"Entering quantity {QUANTITY} for {stock}.")
        quant = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.NAME, "shares"))
        )
        quant.send_keys(str(QUANTITY))
        print(f"Quantity {QUANTITY} entered for {stock}.")

        # Check if the forced limit order element is present (price < $1)
        try:
            print(f"Checking if forced limit order is required for {stock}.")
            limit_price_element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/p'))
            )
            live_price = limit_price_element.text.split('$')[1]
            rounded_price = round(float(live_price), 2)
            print(f"Found forced limit order for {stock}. Market price: {live_price}. Rounded price: {rounded_price}.")

            limit_price_input = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[name="value"][placeholder="Add"]'))
            )
            limit_price_input.click()
            limit_price_input.clear()
            limit_price_input.send_keys(str(rounded_price))
            print(f"Entered limit price {rounded_price} for {stock}.")

            review_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[8]/button'))
            )
            review_button.click()
            printAndDiscord(f"Forced Limit Order: Buying {QUANTITY} shares of {stock} at {rounded_price} in account {key}.", loop)

        except TimeoutException:
            print(f"Checking if market order is applicable for {stock}.")
            try:
                # If forced limit order is not present, attempt market price lookup
                market_price_element = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[5]/div'))
                )
                market_price = market_price_element.text.split('$')[1]
                rounded_price = round(float(market_price), 2)
                print(f"Market price for {stock} is {market_price}. Rounded price: {rounded_price}.")

                review_button = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[6]/button'))
                )
                review_button.click()
                printAndDiscord(f"Market Order: Buying {QUANTITY} shares of {stock} at {rounded_price} in account {key}.", loop)

            except TimeoutException:
                printAndDiscord(f"Market price element not found for {stock} in account {key}.", loop)
                cancel_and_return(driver)  # Cancel and return to the main page
                return

        # If not in dry mode, submit the order and click 'Done'
        if not DRY:
            submit_button = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[4]/button[1]"))
            )
            submit_button.click()
            printAndDiscord(f"SoFi: Buy {QUANTITY} shares of {stock} at {rounded_price} in account {key}.", loop)

            # Click the 'Done' button after confirming the order
            done_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[2]/button'))
            )
            done_button.click()
            print(f"Clicked 'Done' button to confirm buy for {stock}.")
            printAndDiscord(f"Buy order for {stock} in account {key} completed successfully.", loop)
        else:
            # Simulate the buy order in dry mode and click cancel
            printAndDiscord(f"DRY MODE: Simulated buy {QUANTITY} shares of {stock} at {rounded_price} in account {key}.", loop)
            cancel_and_return(driver)  # Click cancel in dry mode

    except Exception as e:
        sofi_error(driver, loop)
        printAndDiscord(f"Error processing buy for {stock} in account {key}: {e}", loop)
        cancel_and_return(driver)  # Cancel and return after an error


def handle_sell_process(driver, stock, QUANTITY, DRY, key, loop):
    try:
        # Fetch available shares
        available_shares_element = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/h2'))
        )
        available_shares = float(available_shares_element.text.split(' ')[0])

        # If available shares are 0, skip to the next account
        if available_shares == 0:
            print(f"No available shares for {stock} in account {key}. Skipping to next account.")
            printAndDiscord(f"No available shares for {stock} in account {key}.", loop)
            cancel_and_return(driver)  # Cancel and return to the main page
            return

        # Ensure the quantity doesn't exceed available shares
        if QUANTITY > available_shares:
            print(f"Requested quantity exceeds available shares ({available_shares}).")
            printAndDiscord(f"Requested quantity exceeds available shares for {stock} in account {key}. Skipping.", loop)
            cancel_and_return(driver)  # Cancel and return to the main page
            return

        # Enter the quantity
        print(f"Entering quantity {QUANTITY} for {stock}.")
        quant = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.NAME, "shares"))
        )
        quant.send_keys(str(QUANTITY))
        print(f"Quantity {QUANTITY} entered for {stock}.")

        # Select 'Limit Price' order type dynamically
        print(f"Selecting 'Limit Price' for {stock}.")
        limit_price_option = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, '//select[@id="OrderTypedDropDown"]/option[@value="LIMIT"]'))
        )
        limit_price_option.click()

        # Fetch and round the current market price
        print(f"Fetching live price for {stock}.")
        market_price_element = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[5]/div[2]'))
        )
        market_price = market_price_element.text.split('$')[1]
        rounded_price = round(float(market_price) - 0.01, 2)
        print(f"Market price for {stock} is {market_price}. Setting limit price to {rounded_price}.")

        # Enter the limit price
        limit_price_input = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[name="value"][placeholder="Add"]'))
        )
        limit_price_input.click()
        limit_price_input.clear()
        limit_price_input.send_keys(str(rounded_price))
        print(f"Entered limit price {rounded_price} for {stock}.")

        # Review and confirm the order
        review_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//button[contains(text(), "Sell All") or contains(text(), "Review")]'))
        )
        review_button.click()
        printAndDiscord(f"Limit Order: Selling {QUANTITY} shares of {stock} at {rounded_price} in account {key}.", loop)

        # If not in dry mode, submit the order
        if not DRY:
            print(f"Submitting sell order for {QUANTITY} shares of {stock} at {rounded_price}.")
            submit_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, f'//button[contains(text(), "Sell {stock}")]'))
            )
            submit_button.click()
            printAndDiscord(f"SoFi account {key}: sell {QUANTITY} shares of {stock} at {rounded_price}.", loop)

            # Click the 'Done' button after confirming the order
            done_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[2]/button'))
            )
            done_button.click()
            print(f"Clicked 'Done' button to confirm sell for {stock}.")
            printAndDiscord(f"Sell order for {stock} in account {key} completed successfully.", loop)
        else:
            # Dry mode, simulate the sell order
            printAndDiscord(f"DRY MODE: Simulated sell {QUANTITY} shares of {stock} at {rounded_price} in account {key}.", loop)
            cancel_and_return(driver)  # Click cancel in dry mode

    except Exception as e:
        sofi_error(driver, loop)
        printAndDiscord(f"Error processing sell for {stock} in account {key}: {e}", loop)
        cancel_and_return(driver)  # Cancel and return after an error


def cancel_and_return(driver):
    try:
        cancel_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/a'))
        )
        cancel_button.click()
        print("Clicked 'Cancel' button to return to the main page.")
    except TimeoutException:
        print("Cancel button not found, could not return to the main page.")
