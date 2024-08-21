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
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sofi_error(driver, loop=None):
    if driver is not None:
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_name = f"SOFI-error-{timestamp}.png"
            driver.save_screenshot(screenshot_name)
            print(f"Screenshot saved as {screenshot_name}")
        except Exception as e:
            print(f"Failed to take screenshot: {e}")
    else:
        print("WebDriver not initialized; skipping screenshot.")

    # Proceed with error reporting
    try:
        error_message = f"SOFI Error: {traceback.format_exc()}"
        printAndDiscord(error_message, loop, embed=False)
    except Exception as e:
        print(f"Failed to send error message: {e}")


def get_2fa_code(secret):
    totp = pyotp.TOTP(secret)
    return totp.now()


def sofi_init(SOFI_EXTERNAL=None, botObj=None, loop=None):
    load_dotenv()

    if not os.getenv("SOFI") and SOFI_EXTERNAL is None:
        printAndDiscord("SOFI environment variable not found.", loop)
        return None

    accounts = (
        os.environ["SOFI"].strip().split(",")
        if SOFI_EXTERNAL is None
        else SOFI_EXTERNAL.strip().split(",")
    )
    SOFI_obj = Brokerage("SOFI")
    for account in accounts:
        index = accounts.index(account) + 1
        name = f"SOFI {index}"
        account = account.split(":")

        try:
            driver = getDriver()
            if driver is None:
                raise Exception("Driver not found.")
            driver.get(
                'https://login.sofi.com/u/login?state=hKFo2SBiMkxuWUxGckdxdVJ0c3BKLTlBdEk1dFgwQnZCcWo0ZKFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIHdDekRxWk81cURTYWVZOVJleEJORE9vMExBVFVjMEw2o2NpZNkgNkxuc0xDc2ZGRUVMbDlTQzBDaWNPdkdlb2JvZXFab2I'
            )
            WebDriverWait(driver, 30).until(check_if_page_loaded)

            # Log in with username and password
            try:
                username_field = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='username']")))
                username_field.send_keys(account[0])

                password_field = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='password']")))
                password_field.send_keys(account[1])

                login_button = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='widget_block']/div/div[2]/div/div/main/section/div/div/div/form/div[2]/button")))
                driver.execute_script("arguments[0].click();", login_button)

                # Determine if authenticator 2FA is needed
                secret = account[2] if len(account) > 2 else None

                if secret:
                    try:
                        # Use the authenticator 2FA code if the secret exists
                        two_fa_code = get_2fa_code(secret)
                        code_field = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.ID, "code")))  # ID for the authenticator code
                        code_field.send_keys(two_fa_code)

                        code_button = WebDriverWait(driver, 30).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, "#widget_block > div > div.right-column > div > div > main > section > div > div > div > form > div.cc199ae96 > button")))
                        code_button.click()

                        # Wait for successful login URL
                        WebDriverWait(driver, 30).until(
                            EC.url_contains("https://www.sofi.com/member-home/")  # The URL after successful login
                        )

                    except TimeoutException:
                        print("Authenticator 2FA code failed or timed out.")
                        return None  # If authenticator 2FA fails, don't proceed with SMS 2FA

                else:
                    # Check if the SMS 2FA element is present
                    try:
                        WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((By.ID, "code"))  # Check if the 2FA SMS code field is present
                        )
                        print("SMS 2FA required.")
                    except TimeoutException:
                        print("No 2FA required or no SMS 2FA element detected.")
                        return None

                    # Proceed with SMS 2FA
                    max_attempts = 3
                    attempts = 0

                    while attempts < max_attempts:
                        try:
                            # Retrieve the SMS code via Discord or manual input
                            if botObj is not None and loop is not None:
                                sms_code = asyncio.run_coroutine_threadsafe(
                                    getOTPCodeDiscord(botObj, name, timeout=300, loop=loop),
                                    loop,
                                ).result()
                                if sms_code is None:
                                    raise Exception("No SMS code found")
                            else:
                                sms_code = input("Enter security code: ")

                            # Wait for the code field to be clickable and enter the code
                            code_field = WebDriverWait(driver, 60).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='code']")))
                            code_field.send_keys(sms_code)

                            # Click the submit button or the appropriate element to continue
                            code_button = WebDriverWait(driver, 20).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='widget_block']/div/div[2]/div/div/main/section/div/div/div/div[1]/div/form/div[3]/button")))
                            code_button.click()

                            # Wait briefly to allow the page to process the input
                            sleep(3)

                            # Check if the 2FA input field is still present
                            if driver.find_elements(By.XPATH, "//*[@id='code']"):
                                attempts += 1
                                print(f"Attempt {attempts} failed. Incorrect code.")

                                # If max attempts are reached, print a message and exit the loop
                                if attempts >= max_attempts:
                                    print("Too many attempts. Please try again later.")
                                    raise TimeoutException("Max 2FA attempts reached. Exiting...")

                            else:
                                print("2FA code accepted. Proceeding...")
                                break  # Exit the loop if the 2FA code is correct and accepted

                        except TimeoutException:
                            if attempts >= max_attempts:
                                print("Too many attempts. Please try again later.")
                                raise TimeoutException("Max 2FA attempts reached due to timeouts. Exiting...")

                WebDriverWait(driver, 60).until(check_if_page_loaded)

                # Retrieve and set account information
                account_dict = sofi_account_info(driver)
                if account_dict is None:
                    raise Exception(f"{name}: Error getting account info")

                for acct in account_dict:
                    SOFI_obj.set_account_number(name, acct)
                    SOFI_obj.set_account_totals(name, acct, account_dict[acct]["balance"])

                SOFI_obj.set_logged_in_object(name, driver)

            except TimeoutException:
                printAndDiscord(f"TimeoutException: Login failed for {name}.", loop)
                return False

        except Exception:
            sofi_error(driver, loop)
            driver.close()
            driver.quit()
            return None
    return SOFI_obj


def sofi_account_info(driver: webdriver, loop=None) -> dict | None:
    try:
        logger.info("Navigating to SOFI account overview page...")
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


def sofi_holdings(SOFI_o: Brokerage, loop=None):
    # Get holdings on each account
    for key in list(SOFI_o.get_account_numbers()):
        driver: webdriver = SOFI_o.get_logged_in_objects(key)
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
                        SOFI_o.set_holdings(key, account_number, holding['company_name'], holding['shares'], holding['price'])
                    SOFI_o.set_account_totals(key, account_number, current_value)

                except Exception as extract_e:
                    logger.error("Error extracting account information for account %s: %s", key, extract_e)
                    printAndDiscord(f"Error extracting account information: {extract_e}", loop)
                    continue

                driver.close()
                driver.switch_to.window(driver.window_handles[0])

        except Exception as e:
            logger.error("Error processing SOFI holdings for account %s: %s", key, e)
            printAndDiscord(f"{key}: Error processing SOFI holdings: {e}", loop)
            continue

    logger.info("Finished processing all accounts, sending holdings to Discord.")
    printHoldings(SOFI_o, loop)
    killSeleniumDriver(SOFI_o)
    logger.info("Completed SOFI holdings processing.")


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


def sofi_transaction(SOFI_o: Brokerage, orderObj: stockOrder, loop=None):
    print("\n==============================")
    print("SOFI")
    print("==============================\n")

    for s in orderObj.get_stocks():
        for key in SOFI_o.get_account_numbers():
            driver = SOFI_o.get_logged_in_objects(key)
            driver.get("https://www.sofi.com/wealth/app/overview")
            print(f"Navigated to SOFI overview page for account {key}")

            try:
                search_field = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.NAME, "search-bar")))
                search_field.send_keys(s)
                print(f"Entered stock symbol {s} into the search bar")
            except TimeoutException:
                try:
                    invest_search_field = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[1]/div/div/div/input")))
                    invest_search_field.send_keys(s)
                    print(f"Entered stock symbol {s} into the alternative search field")
                except TimeoutException:
                    print(f"Search field for {s} not found.")
                    printAndDiscord(f"SOFI search field not found for {s}.", loop)
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
                    printAndDiscord(f"SOFI doesn't have {s}.", loop)
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
                    print(f"SOFI doesn't have {s}. Moving to next stock.")
                    printAndDiscord(f"SOFI doesn't have {s}.", loop)
                    continue
            except TimeoutException:
                print(f"Search results did not appear for {s}. Moving to next stock.")
                printAndDiscord(f"SOFI search results did not appear for {s}.", loop)
                continue

            if orderObj.get_action() == "buy":
                clicked_values = set()  # Set to keep track of processed accounts

                DRY = orderObj.get_dry()
                QUANTITY = orderObj.get_amount()
                print("DRY MODE:", DRY)
                account_number = 1
                sleep(4)

                while True:
                    sleep(1)
                    try:
                        print("Attempting to click the buy button")
                        buy_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[2]/div/button[1]")))
                        driver.execute_script("arguments[0].click();", buy_button)
                        print("Buy button clicked")
                    except TimeoutException:
                        print(f"Buy button not found for {s}. Moving to next stock.")
                        printAndDiscord(f"SOFI buy button not found for {s}.", loop)
                        break

                    try:
                        accounts_dropdown = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.NAME, "account")))
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
                            print(f"All accounts have been processed for {s}.")
                            break

                        print("Fetching live price for the stock")
                        try:
                            live_price_element = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/p")))
                            live_price = live_price_element.text.split('$')[1]
                        except TimeoutException:
                            live_price_element = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[4]/div[2]")))
                            live_price = live_price_element.text.split('$')[1]

                        print(f"Live price fetched: {live_price}")
                    except TimeoutException:
                        print(f"Failed to fetch live price for {s}. Moving to next stock.")
                        printAndDiscord(f"SOFI failed to fetch live price for {s}.", loop)
                        break

                    try:
                        sleep(1)
                        print(f"Entering quantity {QUANTITY}")
                        quant = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.NAME, "shares")))
                        quant.send_keys(QUANTITY)
                        print(f"Quantity {QUANTITY} entered")
                    except TimeoutException:
                        print(f"Failed to enter quantity for {s}. Moving to next stock.")
                        printAndDiscord(f"SOFI failed to enter quantity for {s}.", loop)
                        break

                    try:
                        # Check if the order type is already set to "Limit price"
                        limit_price_label_present = driver.find_elements(By.XPATH, "//p[contains(text(), 'Limit price')]")
                        
                        if limit_price_label_present:
                            print("Order type already set to 'Limit price'. Skipping JavaScript execution.")
                        else:
                            # Ensure the order type is set to "Limit price" using JavaScript
                            driver.execute_script("""
                                var dropdown = document.querySelector("#OrderTypedDropDown");
                                dropdown.focus();
                                var event = new MouseEvent('mousedown', {
                                    'view': window,
                                    'bubbles': true,
                                    'cancelable': true
                                });
                                dropdown.dispatchEvent(event);
                                dropdown.value = 'LIMIT';
                                dropdown.dispatchEvent(new Event('change', { bubbles: true }));
                                dropdown.dispatchEvent(new MouseEvent('mouseup', {
                                    'view': window,
                                    'bubbles': true,
                                    'cancelable': true
                                }));
                                dropdown.dispatchEvent(new Event('focusout', { bubbles: true }));
                            """)
                            print("Order type set to 'Limit price'")

                        print("Entering limit price")
                        rounded_price = round(float(live_price) + 0.01 if float(live_price) >= 0.11 else float(live_price), 2)
                        limit_price = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.NAME, "value")))
                        limit_price.send_keys(str(rounded_price))
                        print(f"Limit price entered: {rounded_price}")
                    except TimeoutException:
                        print(f"Failed to enter limit price for {s}. Moving to next stock.")
                        printAndDiscord(f"SOFI failed to enter limit price for {s}.", loop)
                        break

                    review_button = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-mjs='inv-trade-buy-review']")))
                    review_button.click()

                    if DRY is False:
                        try:
                            sleep(2)
                            submit_button = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[4]/button[1]")))
                            driver.execute_script("arguments[0].scrollIntoView(true);", submit_button)
                            submit_button.click()
                            print(f"Order submitted for {QUANTITY} shares of {s} at {rounded_price}")
                            done_button = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[2]/button")))
                            done_button.click()
                            printAndDiscord(f"SOFI account {key}: buy {QUANTITY} shares of {s} at {rounded_price}", loop)
                        except TimeoutException:
                            print(f"Failed to submit buy order for {s}. Moving to next stock.")
                            printAndDiscord(f"SOFI failed to submit buy order for {s}.", loop)
                            break
                        except Exception as e:
                            print(f"Encountered an unexpected error when submitting the buy order for {s}: {e}")
                            printAndDiscord(f"SOFI unexpected error when submitting buy order for {s}: {e}", loop)
                            break
                    else:
                        back_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[4]/button[2]")))
                        back_button.click()
                        sleep(2)
                        print(f"DRY MODE: Simulated order BUY for {QUANTITY} shares of {s} at {rounded_price}")
                        printAndDiscord(f"SOFI account {key}: dry run buy {QUANTITY} shares of {s} at {rounded_price}", loop)
                        cancel_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                        cancel_button.click()

            elif orderObj.get_action() == "sell":
                clicked_values = set()  # Set to keep track of processed accounts

                DRY = orderObj.get_dry()
                QUANTITY = orderObj.get_amount()
                print("DRY MODE:", DRY)
                account_number = 1
                sleep(4)
                while True:
                    sleep(1)
                    try:
                        print("Attempting to click the sell button")
                        sell = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[2]/div/button[2]")))
                        sell.click()
                        print("Sell button clicked")
                    except TimeoutException:
                        print(f"Sell button not found for {s}. Moving to next stock.")
                        printAndDiscord(f"SOFI sell button not found for {s}.", loop)
                        break

                    try:
                        accounts_dropdown = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.NAME, "account")))
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
                            print(f"All accounts have been processed for {s}.")
                            break

                        try:
                            print(f"Checking available shares for {s}")
                            available_shares = WebDriverWait(driver, 20).until(
                                EC.presence_of_element_located((By.XPATH, '/html/body/div[1]/div/main/div[2]/div[2]/div[3]/div/h2'))).text.split(' ')[0]
                            print(f"Available shares: {available_shares}")
                        except TimeoutException:
                            print(f"Failed to fetch available shares for {s}. Moving to next stock.")
                            printAndDiscord(f"SOFI failed to fetch available shares for {s}.", loop)
                            break

                        if QUANTITY > float(available_shares):
                            QUANTITY = float(available_shares) if float(available_shares) > 0 else 0
                            if QUANTITY == 0:
                                print("No shares available")
                                continue

                        try:
                            print(f"Entering quantity {QUANTITY}")
                            quant = WebDriverWait(driver, 20).until(
                                EC.element_to_be_clickable((By.NAME, "shares")))
                            quant.send_keys(QUANTITY)
                            print(f"Quantity {QUANTITY} entered")
                        except TimeoutException:
                            print(f"Failed to enter quantity for {s}. Moving to next stock.")
                            printAndDiscord(f"SOFI failed to enter quantity for {s}.", loop)
                            break

                        # Ensure the order type is set to "Limit price" using the working JavaScript
                        driver.execute_script("""
                            var dropdown = document.querySelector("#OrderTypedDropDown");
                            dropdown.focus();
                            var event = new MouseEvent('mousedown', {
                                'view': window,
                                'bubbles': true,
                                'cancelable': true
                            });
                            dropdown.dispatchEvent(event);
                            dropdown.value = 'LIMIT';
                            dropdown.dispatchEvent(new Event('change', { bubbles: true }));
                            dropdown.dispatchEvent(new MouseEvent('mouseup', {
                                'view': window,
                                'bubbles': true,
                                'cancelable': true
                            }));
                            dropdown.dispatchEvent(new Event('focusout', { bubbles: true }));
                        """)
                        print("Order type set to 'Limit price'")

                        print("Fetching live price for the stock")
                        live_price = WebDriverWait(driver, 20).until(
                            EC.presence_of_element_located((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[5]/div[2]'))).text.split('$')[1]
                        print(f"Live price fetched: {live_price}")

                        try:
                            # Click to activate the limit price input field
                            limit_price_input = WebDriverWait(driver, 10).until(
                                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[name='value']"))
                            )
                            limit_price_input.click()  # Click to activate the field
                            limit_price_input.send_keys(live_price)
                            print("Limit price entered successfully")
                        except TimeoutException:
                            print("Failed to locate the limit price input field.")

                        print("Clicking sell button")
                        sell_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//button[@class='sc-fKVqWL gkmrQz StyledActionButton-hdOdyk iUbDdu' and @data-mjs='inv-trade-sell-review' and @type='button']")))

                        sell_button.click()
                    except TimeoutException:
                        print(f"Failed to click sell button for {s}. Moving to next stock.")
                        printAndDiscord(f"SOFI failed to click sell button for {s}.", loop)
                        break

                    if DRY:
                        try:
                            cancel_button = WebDriverWait(driver, 20).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[4]/button[1]")))
                            cancel_button.click()
                            print(f"DRY MODE: Simulated order SELL for {QUANTITY} shares of {s} at {float(live_price) - 0.01}")
                            printAndDiscord(f"SOFI account {key}: dry run sell {QUANTITY} shares of {s} at {float(live_price) - 0.01}", loop)
                        except TimeoutException:
                            print(f"Failed to click cancel button on sell order for {s}. Moving to next stock.")
                            printAndDiscord(f"SOFI failed to click cancel button on sell order for {s}.", loop)
                            break
                    else:
                        try:
                            submit_button = WebDriverWait(driver, 20).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                            submit_button.click()
                            print(f"Order submitted for {QUANTITY} shares of {s} at {float(live_price) - 0.01}")
                            printAndDiscord(f"SOFI account {key}: sell {QUANTITY} shares of {s} at {float(live_price) - 0.01}", loop)
                            done_button = WebDriverWait(driver, 20).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[2]/button")))
                            done_button.click()
                        except TimeoutException:
                            print(f"Failed to submit sell order for {s}. Moving to next stock.")
                            printAndDiscord(f"SOFI failed to submit sell order for {s}.", loop)
                            break

    print("Completed all transactions, Exiting...")
    killSeleniumDriver(SOFI_o)  # Properly close and quit the Selenium driver
