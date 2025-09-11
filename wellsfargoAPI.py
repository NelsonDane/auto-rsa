import asyncio
import datetime
import os
import re
import traceback
from time import sleep

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import (
    ElementNotInteractableException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
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


def wellsfargo_error(driver: webdriver, error: str):
    print(f"Wells Fargo Error: {error}")
    driver.save_screenshot(f"wells-fargo-error-{datetime.datetime.now()}.png")
    print(traceback.format_exc())


def wellsfargo_init(botObj, WELLSFARGO_EXTERNAL=None, DOCKER=False, loop=None):
    load_dotenv()

    if not os.getenv("WELLSFARGO"):
        print("WELLSFARGO environment variable not found.")
        return None
    accounts = (
        os.environ["WELLSFARGO"].strip().split(",")
        if WELLSFARGO_EXTERNAL is None
        else WELLSFARGO_EXTERNAL.strip().split(",")
    )
    WELLSFARGO_obj = Brokerage("WELLSFARGO")
    for account in accounts:
        index = accounts.index(account) + 1
        name = f"WELLSFARGO {index}"
        account = account.split(":")
        driver = None
        try:
            printAndDiscord("Logging into WELLS FARGO...", loop)
            driver = getDriver(DOCKER)
            if driver is None:
                raise Exception("Driver not found.")
            driver.get("https://connect.secure.wellsfargo.com/auth/login/present")
            WebDriverWait(driver, 20).until(check_if_page_loaded)
            # Login
            try:
                username_field = driver.find_element(By.XPATH, "//*[@id='j_username']")
                type_slowly(username_field, account[0])
                password_field = driver.find_element(By.XPATH, "//*[@id='j_password']")
                type_slowly(password_field, account[1])

                login_button = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, ".Button__modern___cqCp7")
                    )
                )
                login_button.click()
                WebDriverWait(driver, 20).until(check_if_page_loaded)
            except TimeoutException:
                print("TimeoutException: Login failed.")
                if driver:
                    driver.quit()
                return None

            WELLSFARGO_obj.set_logged_in_object(name, driver)
            
            # Handle 2FA
            try:
                auth_popup = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, ".ResponsiveModalContent__modalContent___guT3p")
                    )
                )
                auth_list = auth_popup.find_element(
                    By.CSS_SELECTOR, ".LineItemLinkList__lineItemLinkList___Dj6vb"
                )
                li_elements = auth_list.find_elements(By.TAG_NAME, "li")
                for li in li_elements:
                    if account[2] in li.text:
                        li.click()
                        break
                
                if botObj is not None and loop is not None:
                    code = asyncio.run_coroutine_threadsafe(
                        getOTPCodeDiscord(botObj, name, timeout=300, loop=loop),
                        loop,
                    ).result()
                else:
                    code = input("Enter security code: ")

                if code is None:
                    raise Exception("2FA code not provided.")

                code_input = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.ID, "otp"))
                )
                code_input.send_keys(code)
                WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']"))
                ).click()
            except TimeoutException:
                pass # 2FA not always required

            # Wait for dashboard to load
            WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.XPATH, "//*[@data-testid='Investments']"))
            )

            # Find the Investments category tile
            investments_category = driver.find_element(By.XPATH, "//*[@data-testid='Investments']")
            
            # Find all individual account tiles within the Investments category
            account_blocks = investments_category.find_elements(
                By.XPATH, ".//li[contains(@class, 'AccountTile__account-tile')]"
            )

            for account_block in account_blocks:
                # Extract the masked account number
                masked_number_element = account_block.find_element(
                    By.CSS_SELECTOR, '[data-testid$="-masked-number"]'
                )
                masked_number_text = masked_number_element.text.replace("...", "xxxx")
                WELLSFARGO_obj.set_account_number(name, masked_number_text)

                # Extract the balance
                balance_element = account_block.find_element(
                    By.CSS_SELECTOR, '[data-testid$="-balance"]'
                )
                balance_text = balance_element.text.replace("$", "").replace(",", "").strip()
                balance = float(balance_text)
                WELLSFARGO_obj.set_account_totals(name, masked_number_text, balance)

        except Exception as e:
            wellsfargo_error(driver, str(e))
            if driver:
                driver.quit()
            return None
            
    return WELLSFARGO_obj


def wellsfargo_holdings(WELLSFARGO_o: Brokerage, loop=None):
    for key in WELLSFARGO_o.get_account_numbers():
        driver: webdriver = WELLSFARGO_o.get_logged_in_objects(key)
        try:
            print("Navigating to the Brokerage page by clicking the link...")
            WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((By.ID, "BROKERAGE_LINK7P"))
            ).click()
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, "goholdings"))
            )
            print("DEBUG: Session established.")

            current_url = driver.current_url
            if '_x=' not in current_url:
                raise Exception("Could not find session token in URL.")
            session_token = current_url.split('_x=')[1]
            base_url = "https://wfawellstrade.wellsfargo.com/BW/holdings.do?account="
            
            print(f"DEBUG: Captured session token: {session_token}")

            last_account_holdings = None
            account_masks = WELLSFARGO_o.get_account_numbers(key)

            for i in range(len(account_masks) + 2):
                try:
                    direct_url = f"{base_url}{i}&_x={session_token}"
                    print(f"\n--- Navigating to holdings for account index {i} ---")
                    driver.get(direct_url)

                    holdings_table_xpath = "//table[@id='holdings-table']/tbody/tr"
                    WebDriverWait(driver, 30).until(
                        EC.presence_of_all_elements_located((By.XPATH, holdings_table_xpath))
                    )
                    
                    current_mask_element = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "#dropdown1_label .acctmask"))
                    )
                    current_mask = current_mask_element.text.strip().replace('*', 'xxxx')
                    print(f"DEBUG: Successfully loaded holdings page for account {current_mask}")

                    rows = driver.find_elements(By.XPATH, holdings_table_xpath)
                    current_holdings = {}
                    
                    # --- START: Corrected Parsing Logic ---
                    for row in rows:
                        # Find all cells in the current row
                        cells = row.find_elements(By.TAG_NAME, "td")
                        
                        # Ensure it's a valid data row
                        if len(cells) >= 6:
                            try:
                                # Use more specific selectors based on the provided HTML
                                name_div = cells[0].find_element(By.CSS_SELECTOR, "div.symbol-name")
                                name = name_div.text.strip()

                                quantity = cells[1].text.strip().replace(",", "")
                                price = cells[2].text.strip().replace("$", "").replace(",", "")

                                if name and "cash" not in name.lower() and quantity and float(quantity) > 0:
                                    print(f"Found Position: {name}, Qty: {quantity}, Price: {price}")
                                    current_holdings[name] = {"quantity": float(quantity), "price": float(price)}
                                    WELLSFARGO_o.set_holdings(
                                        key, current_mask, name, float(quantity), float(price)
                                    )
                            except NoSuchElementException:
                                # This can happen for summary rows or other non-holding rows, so we just skip them
                                continue
                    # --- END: Corrected Parsing Logic ---

                    if current_holdings and current_holdings == last_account_holdings:
                        print(f"DEBUG: Duplicate holdings found. Assuming end of accounts.")
                        if current_mask in WELLSFARGO_o.get_holdings(key):
                             del WELLSFARGO_o.get_holdings(key)[current_mask]
                        break
                    
                    last_account_holdings = current_holdings
                    print(f"Finished parsing holdings for account {current_mask}.")

                except TimeoutException:
                    print(f"DEBUG: Timed out waiting for holdings at index {i}. This is the end of the account list.")
                    break
                except Exception as e:
                    wellsfargo_error(driver, f"Error processing account index {i}: {e}")
                    continue

        except Exception as e:
            wellsfargo_error(driver, str(e))
        finally:
            printHoldings(WELLSFARGO_o, loop)
            killSeleniumDriver(WELLSFARGO_o)


def wellsfargo_transaction(WELLSFARGO_o: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("WELLS FARGO")
    print("==============================")
    print()

    for key in WELLSFARGO_o.get_account_numbers():
        driver: webdriver = WELLSFARGO_o.get_logged_in_objects(key)

        # Navigate to Trade
        try:
            brokerage = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='BROKERAGE_LINK7P']"))
            )
            brokerage.click()

            trade = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='trademenu']/span[1]"))
            )
            trade.click()

            trade_stock = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='linktradestocks']"))
            )
            trade_stock.click()

            # Find accounts
            open_dropdown = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='dropdown2']"))
            )
            open_dropdown.click()

            accounts = driver.execute_script(
                "return document.getElementById('dropdownlist2').getElementsByTagName('li').length;"
            )
            accounts = int(accounts)
        except TimeoutException:
            print("could not get to trade")
            killSeleniumDriver(WELLSFARGO_o)

        account_masks = WELLSFARGO_o.get_account_numbers(key)
        # Use to keep track of an order to know whether to reset the trading screen
        order_failed = False
        for account in range(accounts):
            WebDriverWait(driver, 20).until(check_if_page_loaded)
            if account >= len(account_masks):
                continue
            try:
                if order_failed and orderObj.get_dry():
                    trade = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, "//*[@id='trademenu']/span[1]")
                        )
                    )
                    trade.click()
                    trade_stock = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, "//*[@id='linktradestocks']")
                        )
                    )
                    trade_stock.click()
                    dismiss_prompt = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.ID, "btn-continue"))
                    )
                    dismiss_prompt.click()
                # choose account
                open_dropdown = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='dropdown2']"))
                )
                open_dropdown.click()
                find_account = """
                    var items = document.getElementById('dropdownlist2').getElementsByTagName('li');
                    for (var i = 0; i < items.length; i++) {
                        if (items[i].innerText.includes(arguments[0])) {
                            items[i].click();
                            return i;
                        }
                    }
                    return -1;
                """
                select_account = driver.execute_script(
                    find_account, account_masks[account].replace("*", "")
                )
                sleep(2)
                # Check for clear ticket prompt and accept
                try:
                    driver.find_element(By.ID, "btn-continue").click()
                except (NoSuchElementException, ElementNotInteractableException):
                    pass
                if select_account == -1:
                    print("Could not find the account with the specified text")
                    continue
            except Exception:
                traceback.print_exc()
                print("Could not change account")
                killSeleniumDriver(WELLSFARGO_o)
            for s in orderObj.get_stocks():
                WebDriverWait(driver, 20).until(check_if_page_loaded)
                # If an order fails need to sort of reset the tradings screen. Refresh does not work
                if order_failed:
                    trade = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, "//*[@id='trademenu']/span[1]")
                        )
                    )
                    trade.click()
                    trade_stock = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable(
                            (By.XPATH, "//*[@id='linktradestocks']")
                        )
                    )
                    trade_stock.click()
                    dismiss_prompt = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.ID, "btn-continue"))
                    )
                    dismiss_prompt.click()
                sleep(2)
                # idk why doing it through selenium doesnt work sometimes
                driver.execute_script('document.getElementById("BuySellBtn").click()')
                # Buy or Sell
                if orderObj.get_action().lower() == "buy":
                    action = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.LINK_TEXT, "Buy"))
                    )
                elif orderObj.get_action().lower() == "sell":
                    action = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.LINK_TEXT, "Sell"))
                    )
                else:
                    print("no buy or sell set")
                action.click()

                review = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.ID, "actionbtnContinue"))
                )
                driver.execute_script("arguments[0].scrollIntoView(true);", review)
                sleep(2)
                ticker_box = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.ID, "Symbol"))
                )

                ticker_box.send_keys(s)
                ticker_box.send_keys(Keys.ENTER)

                # quantity
                driver.execute_script(
                    "document.querySelector('#OrderQuantity').value ="
                    + str(int(orderObj.get_amount()))
                )

                # get price
                WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "qeval"))
                )

                price = driver.find_element(By.CLASS_NAME, "qeval").text
                price = float(price)
                if orderObj.get_action().lower() == "buy" and price < 2:
                    price_type = "Limit"
                    price += 0.01
                elif orderObj.get_action().lower() == "sell" and price < 2:
                    price_type = "Limit"
                    price -= 0.01
                else:
                    price_type = "Market"

                # order type
                driver.execute_script(
                    "document.getElementById('OrderTypeBtnText').click()"
                )

                # limit price
                order = driver.find_element(By.LINK_TEXT, price_type)
                order.click()
                if price_type == "Limit":
                    ticker_box = driver.find_element(By.ID, "Price")
                    ticker_box.send_keys(price)
                    ticker_box.send_keys(Keys.ENTER)

                    # timing
                    driver.execute_script("document.getElementById('TIFBtn').click()")
                    sleep(1)
                    day = driver.find_element(By.LINK_TEXT, "Day")
                    day.click()

                # preview
                driver.execute_script("arguments[0].click();", review)
                try:
                    if not orderObj.get_dry():
                        # submit
                        submit = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable(
                                (By.CSS_SELECTOR, ".btn-wfa-submit")
                            )
                        )
                        driver.execute_script(
                            "arguments[0].click();", submit
                        )  # Was getting visibility issues even though scrolling to it
                        # Send confirmation
                        printAndDiscord(
                            f"{key} {WELLSFARGO_o.get_account_numbers(key)[account]}: {orderObj.get_action()} {orderObj.get_amount()} shares of {s}",
                            loop,
                        )
                        # buy next
                        buy_next = driver.find_element(
                            By.CSS_SELECTOR, ".btn-wfa-primary"
                        )
                        driver.execute_script("arguments[0].click();", buy_next)
                        order_failed = False
                    elif orderObj.get_dry():
                        printAndDiscord(
                            f"DRY: {key} account {WELLSFARGO_o.get_account_numbers(key)[account]}: {orderObj.get_action()} {orderObj.get_amount()} shares of {s}",
                            loop,
                        )
                        order_failed = True
                except TimeoutException:
                    error_text = driver.find_element(
                        By.XPATH, "//div[@class='alert-msg-summary']//p[1]"
                    ).text
                    order_failed = True
                    printAndDiscord(
                        f"{key} {WELLSFARGO_o.get_account_numbers(key)[account]}: {orderObj.get_action()} {orderObj.get_amount()} shares of {s}. FAILED! \n{error_text}",
                        loop,
                    )
                    # Cancel the trade
                    cancel_button = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable(
                            (By.CSS_SELECTOR, "#actionbtnCancel")
                        )
                    )
                    driver.execute_script(
                        "arguments[0].click();", cancel_button
                    )  # Must be clicked with js since it's out of view
                    WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "#btn-continue"))
                    ).click()
        killSeleniumDriver(WELLSFARGO_o)
