import datetime
import os
import traceback
from time import sleep
import logging

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
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
    maskString,
    printAndDiscord,
    printHoldings,
    stockOrder,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sofi_error(driver, e, loop=None):
    driver.save_screenshot(f"SOFI-error-{datetime.datetime.now()}.png")
    printAndDiscord(f"SOFI Error: {traceback.format_exc()}", loop, embed=False)

def get_2fa_code(secret):
    totp = pyotp.TOTP(secret)
    return totp.now()

def sofi_init(SOFI_EXTERNAL=None, DOCKER=False, loop=None):
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
            driver = getDriver(DOCKER=False)
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
                login_button.click()

                # Handle 2FA
                if len(account) > 2:
                    secret = account[2]
                else:
                    secret = input('2FA Secret not found in .env. Please enter your 2FA Secret:')
                
                two_fa_code = get_2fa_code(secret)
                code_field = WebDriverWait(driver, 60).until(
                    EC.element_to_be_clickable((By.ID, "code")))
                code_field.send_keys(two_fa_code)

                code_button = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "#widget_block > div > div.right-column > div > div > main > section > div > div > div > form > div.cc199ae96 > button")))
                code_button.click()

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

        except Exception as e:
            sofi_error(driver, e, loop)
            driver.close()
            driver.quit()
            return None
    return SOFI_obj

def sofi_account_info(driver: webdriver) -> dict | None:
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
                driver.execute_script("window.open('{}', '_blank');".format(account_link))
                driver.switch_to.window(driver.window_handles[-1])  # Switch to the newly opened tab

                # Wait for the account page to load
                WebDriverWait(driver, 60).until(check_if_page_loaded)
                
                # Extract account number from the account page
                account_number_element = WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '#page-wrap > section:nth-child(2) > div.StyledFlex-hyCQyL.dPIcoC.HeaderWithSearchWrapper-Xeaqb.AccountHeaderWrapper-cvufWC.cSaibV.hHdLiB > div.AccountHeader-edyzFd.rVUTO > h1'))
                )
                account_number_text = account_number_element.text.strip()
                account_number = account_number_text.split("#")[1].split(")")[0].strip()
                logger.info(f"Account number: {account_number}")

                # Extract total value
                current_value_element = WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '#page-wrap > section:nth-child(6) > div:nth-child(3) > div > span:nth-child(2)'))
                )
                current_value = current_value_element.text.strip().replace('$', '').replace(',', '')
                logger.info(f"Current value for account {account_number}: {current_value}")

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
                logger.error(f"Error processing account information for account {index + 1}: {str(e)}")
                # Close the tab if any error occurs and switch back
                driver.close()
                driver.switch_to.window(driver.window_handles[0])
                continue

        if not account_dict:
            raise Exception("No accounts found or elements were missing.")
        
        return account_dict
    except TimeoutException as e:
        sofi_error(driver, e)
        return None
    except Exception as e:
        sofi_error(driver, e)
        return None

def sofi_holdings(SOFI_o: Brokerage, loop=None):
    # Get holdings on each account
    for key in list(SOFI_o.get_account_numbers()):
        driver: webdriver = SOFI_o.get_logged_in_objects(key)
        try:
            logger.info(f"Processing holdings for account: {key}")
            
            # Process each account link one by one
            account_boxes = driver.find_elements(By.CSS_SELECTOR, '.AccountCardWrapper-PyEjZ .linked-card > a')
            account_links = [box.get_attribute('href') for box in account_boxes]
            logger.info(f"Found {len(account_links)} account links to process.")
            
            for index, link in enumerate(account_links):
                try:
                    logger.info(f"Processing account link {index + 1}/{len(account_links)}: {link}")
                    
                    driver.execute_script("window.open('{}', '_blank');".format(link))
                    driver.switch_to.window(driver.window_handles[-1])  # Switch to the newly opened tab

                    sleep(5)
                    WebDriverWait(driver, 60).until(check_if_page_loaded)
                    
                    account_number_element = WebDriverWait(driver, 60).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '#page-wrap > section:nth-child(2) > div.StyledFlex-hyCQyL.dPIcoC.HeaderWithSearchWrapper-Xeaqb.AccountHeaderWrapper-cvufWC.cSaibV.hHdLiB > div.AccountHeader-edyzFd.rVUTO > h1'))
                    )
                    account_number_text = account_number_element.text.strip()
                    account_number = account_number_text.split("#")[1].split(")")[0].strip()
                    logger.info(f"Account number: {account_number}")

                    current_value_element = WebDriverWait(driver, 60).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, '#page-wrap > section:nth-child(6) > div:nth-child(3) > div > span:nth-child(2)'))
                    )
                    current_value = current_value_element.text.strip()
                    logger.info(f"Current value for account {account_number}: {current_value}")

                    holdings_data = extract_holdings(driver, loop)
                    
                    for holding in holdings_data:
                        SOFI_o.set_holdings(key, account_number, holding['company_name'], holding['shares'], holding['price'])
                    SOFI_o.set_account_totals(key, account_number, current_value)

                except Exception as extract_e:
                    logger.error(f"Error extracting account information for account {key}: {extract_e}")
                    printAndDiscord(f"Error extracting account information: {extract_e}", loop)
                    continue

                driver.close()
                driver.switch_to.window(driver.window_handles[0])

        except Exception as e:
            logger.error(f"Error processing SOFI holdings for account {key}: {e}")
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
        logger.info(f"Found {len(holdings_elements)} holdings elements to process.")
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

                logger.info(f"Scraped holding: {company_name}, Shares: {shares}, Price: {price_float}")
                
                holdings_data.append({
                    'company_name': company_name,
                    'shares': shares,
                    'price': price_float
                })
            except Exception as e:
                logger.error(f"Error scraping a holding element: {str(e)}")
                continue
    except Exception as e:
        sofi_error(driver, e, loop)
    
    return holdings_data

def sofi_transaction(SOFI_o: Brokerage, orderObj: stockOrder, loop=None, DOCKER=False):
    print()
    print("==============================")
    print("SOFI")
    print("==============================")
    print()

    for s in orderObj.get_stocks():
        for key in SOFI_o.get_account_numbers():
            driver = SOFI_o.get_logged_in_objects(key)
            investment_button = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='root']/div/header/nav/div[3]/a[4]")))
            investment_button.click()
            try:
                search_field = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='page-wrap']/div[1]/div/div/div/div/input")))
                search_field.send_keys(s)
                WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located((By.XPATH, "//*[@id='page-wrap']/div[1]/div/div/div/ul/li")))
                dropdown_items = driver.find_elements(By.XPATH, "//*[@id='page-wrap']/div[1]/div/div/div/ul/li")
                total_items = len(dropdown_items)
            except TimeoutException:
                try:
                    invest_search_field = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[1]/div/div/div/input")))
                    invest_search_field.send_keys(s)
                    WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[1]/div/div/ul/li")))
                    dropdown_items = driver.find_elements(By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[1]/div/div/ul/li")
                    total_items = len(dropdown_items)
                except TimeoutException:
                    print("Search field not found")
                    return

            if total_items == 0:
                print("No stock found")
                return

            found_stock = False
            for item in dropdown_items:
                ticker_name = item.find_element(By.XPATH, "./a/div/p[1]").text
                if ticker_name == s:
                    found_stock = True
                    item.click()
                    break

            if not found_stock:
                print(f"SOFI DOESN'T HAVE {s}")
                return

            if orderObj.get_action() == "buy":
                clicked_values = set()
                DRY = orderObj.get_dry()
                QUANTITY = orderObj.get_amount()
                print("DRY MODE:", DRY)
                account_number = 1

                while True:
                    sleep(5)
                    buy_button = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[2]/div/button[1]")))
                    driver.execute_script("arguments[0].click();", buy_button)

                    try:
                        OrderTypedDropDown = WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='OrderTypedDropDown']")))
                        OrderTypedDropDown.click()

                        OrderTypedDropDown_limit = WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='OrderTypedDropDown']/option[2]")))
                        OrderTypedDropDown_limit.click()
                    except TimeoutException:
                        pass

                    live_price = WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/p"))).text
                    live_price = live_price.split('$')[1]

                    accounts_dropdown = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.NAME, "account")))
                    select = Select(accounts_dropdown)

                    for option in select.options:
                        value = option.get_attribute('value')
                        if value not in clicked_values:
                            select.select_by_value(value)
                            print("Selected account", account_number, ":", {value})
                            account_number += 1
                            clicked_values.add(value)
                            break
                    else:
                        print(f"All accounts have been processed for {s}.")
                        try:
                            cancel_button = WebDriverWait(driver, 20).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                            cancel_button.click()
                        except TimeoutException:
                            pass
                        break

                    sleep(2)
                    quant = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.NAME, "shares")))
                    quant.send_keys(QUANTITY)

                    limit_price = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.NAME, "value")))

                    if float(live_price) < 0.1:
                        limit_price.send_keys(str(float(live_price) + 0.005))
                    else:
                        limit_price.send_keys(str(float(live_price) + 0.01))

                    try:
                        available_funds = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/h2"))).text
                        available_funds = available_funds.split('$')[1]
                        order_price = QUANTITY * (float(live_price) + 0.01)
                        if order_price > float(available_funds):
                            print(f"Insufficient funds. {s}'s price is {live_price}, Order price ${order_price} Available funds ${available_funds}.")
                            cancel_button = WebDriverWait(driver, 20).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                            cancel_button.click()
                            continue
                    except TimeoutException:
                        pass

                    try:
                        xpaths = [
                            "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[8]/button",
                            "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[7]/button",
                            "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[6]/button"
                        ]

                        review_button = None
                        for xpath in xpaths:
                            try:
                                review_button = WebDriverWait(driver, 3).until(
                                    EC.element_to_be_clickable((By.XPATH, xpath))
                                )
                                break
                            except TimeoutException:
                                continue

                        if review_button is None:
                            raise Exception("Review button not found")

                        review_button.click()
                    except:
                        continue

                    if DRY is False:
                        submit_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[4]/button[1]")))
                        submit_button.click()
                        if float(live_price) < 0.1:
                            print("Order submitted for", QUANTITY, "shares of", s, "at", str(float(live_price) + 0.005))
                        else:
                            print("Order submitted for", QUANTITY, "shares of", s, "at", str(float(live_price) + 0.01))

                        done_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[2]/button")))
                        done_button.click()
                        print("Order completed and confirmed.")

                    elif DRY is True:
                        sleep(4)
                        back_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[4]/button[2]")))
                        back_button.click()
                        sleep(2)
                        print("DRY MODE")
                        print("Submitting order BUY for", QUANTITY, "shares of", s, "at", str(float(live_price) + 0.01))

                        cancel_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                        cancel_button.click()

            elif orderObj.get_action() == "sell":
                clicked_values = set()
                DRY = orderObj.get_dry()
                QUANTITY = orderObj.get_amount()
                print("DRY MODE:", DRY)
                account_number = 1

                while True:
                    sleep(5)
                    sell = WebDriverWait(driver, 50).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[2]/div/button[2]")))
                    sell.click()
                    logger.info('sell button clicked')

                    accounts_dropdown = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.NAME, "account")))

                    select = Select(accounts_dropdown)
                    logger.info('account dropdown selected')
                    sleep(3)

                    for option in select.options:
                        value = option.get_attribute('value')
                        if value not in clicked_values:
                            select.select_by_value(value)
                            print("Selected account", account_number, ":", {value})
                            account_number += 1
                            clicked_values.add(value)
                            break
                    else:
                        print("All accounts have been processed.")
                        break

                    sleep(1)
                    quant = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.NAME, "shares")))
                    quant.send_keys(QUANTITY)
                    logger.info('quantity sent')

                    available_shares = WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/h2'))).text
                    available_shares = available_shares.split(' ')[0]
                    print("Available shares:", {available_shares})

                    if QUANTITY > float(available_shares):
                        logger.info('not enough shares')
                        cancel_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                        cancel_button.click()
                        continue

                    live_price = WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[4]/div[2]'))).text
                    live_price = live_price.split('$')[1]
                    print('Live price:', live_price)

                    try:
                        review_button = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[7]/button')))
                        review_button.click()
                    except:
                        try:
                            limit_price = WebDriverWait(driver, 20).until(
                                EC.element_to_be_clickable((By.XPATH, '//*[@id="input-33"]')))
                            limit_price.send_keys(str(float(live_price) - 0.01))

                            review_button = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[8]/button')))
                            driver.execute_script("arguments[0].click();", review_button)
                        except:
                            print('neither review button worked')
                            continue

                    try:
                        okay_button = WebDriverWait(driver, 2).until(
                            EC.element_to_be_clickable((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[7]/div/button[1]')))
                        okay_button.click()
                    except:
                        pass

                    if DRY is False:
                        sleep(2)
                        submit_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[5]/button[1]")))
                        submit_button.click()
                        print("LIVE MODE")
                        done = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[2]/button")))
                        done.click()
                        print("Submitting order SELL for", QUANTITY, "shares of", s, "at", str(float(live_price) - 0.01))

                    elif DRY is True:
                        try:
                            sleep(3)
                            back_button = WebDriverWait(driver, 10).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[5]/button[2]")))
                            back_button.click()
                        except TimeoutException:
                            try:
                                logger.info('couldnt find back button')
                                Out_of_market_back_button = WebDriverWait(driver, 20).until(
                                    EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[6]/div/button[2]")))
                                Out_of_market_back_button.click()
                            except TimeoutException:
                                print("Neither button was found.")

                        print("Submitting order SELL for", QUANTITY, "shares of", s, "at", live_price)
                        sleep(1)
                        cancel_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                        cancel_button.click()

    print("Completed all transactions, Exiting...")
    driver.close()
    driver.quit()