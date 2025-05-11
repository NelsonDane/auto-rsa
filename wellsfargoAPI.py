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
                # Wait for the password field and enter the password
                password_field = driver.find_element(By.XPATH, "//*[@id='j_password']")
                type_slowly(password_field, account[1])

                login_button = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, ".Button__modern___cqCp7")
                    )
                )
                login_button.click()
                WebDriverWait(driver, 20).until(check_if_page_loaded)
                print("=====================================================\n")
            except TimeoutException:
                print("TimeoutException: Login failed.")
                return False
            WELLSFARGO_obj.set_logged_in_object(name, driver)
            try:
                auth_popup = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            ".ResponsiveModalContent__modalContent___guT3p",
                        )
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
                print("Clicked on phone number")
                # Get the OTP code from the user
                if botObj is not None and loop is not None:
                    code = asyncio.run_coroutine_threadsafe(
                        getOTPCodeDiscord(botObj, name, timeout=300, loop=loop),
                        loop,
                    ).result()
                else:
                    code = input("Enter security code: ")
                code_input = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.ID, "otp"))
                )
                code_input.send_keys(code)
                WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']"))
                ).click()
            except TimeoutException:
                pass

            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.LINK_TEXT, "Locations"))
            )

            # TODO: This will not show accounts that do not have settled cash funds
            account_blocks = driver.find_elements(
                By.CSS_SELECTOR, 'li[data-testid^="WELLSTRADE"]'
            )
            for account_block in account_blocks:
                masked_number_element = account_block.find_element(
                    By.CSS_SELECTOR, '[data-testid$="-masked-number"]'
                )
                masked_number_text = masked_number_element.text.replace(".", "*")
                WELLSFARGO_obj.set_account_number(name, masked_number_text)
                balance_element = account_block.find_element(
                    By.CSS_SELECTOR, '[data-testid$="-balance"]'
                )
                balance = float(balance_element.text.replace("$", "").replace(",", ""))
                WELLSFARGO_obj.set_account_totals(name, masked_number_text, balance)
        except Exception as e:
            wellsfargo_error(driver, e)
            driver.close()
            driver.quit()
            return None
    return WELLSFARGO_obj


def wellsfargo_holdings(WELLSFARGO_o: Brokerage, loop=None):
    for key in WELLSFARGO_o.get_account_numbers():
        driver: webdriver = WELLSFARGO_o.get_logged_in_objects(key)
        try:
            brokerage = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='BROKERAGE_LINK7P']"))
            )
            brokerage.click()

            try:
                more = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.LINK_TEXT, "Holdings Snapshot"))
                )
                more.click()
                position = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "btnpositions"))
                )
                position.click()
            except Exception as e:
                wellsfargo_error(driver, e)
                killSeleniumDriver(WELLSFARGO_o)
                return

            # Check if multi-account dropdown exists
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//*[@id='dropdown1']"))
                )
                is_multi_account = True
            except TimeoutException:
                is_multi_account = False

            account_masks = WELLSFARGO_o.get_account_numbers(key)
            if not account_masks:
                print(f"Error: No account masks found stored for {key}")
                killSeleniumDriver(WELLSFARGO_o)
                return

            if is_multi_account:
                # Original multi-account logic
                open_dropdown = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='dropdown1']"))
                )
                open_dropdown.click()

                accounts = driver.execute_script(
                    "return document.getElementById('dropdownlist1').getElementsByTagName('li').length;"
                )
                accounts = int(accounts - 3)  # Adjust based on actual implementation

                for account in range(accounts):
                    if account >= len(account_masks):
                        continue
                    try:
                        open_dropdown = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable(
                                (By.XPATH, "//*[@id='dropdown1']")
                            )
                        )
                        open_dropdown.click()
                        sleep(1)
                        find_account = """
                            var items = document.getElementById('dropdownlist1').getElementsByTagName('li');
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
                        if select_account == -1:
                            print("Could not find the account with the specified text")
                            continue
                    except Exception:
                        print("Could not change account")
                        killSeleniumDriver(WELLSFARGO_o)
                        continue

                    sleep(1)
                    rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")

                    for row in rows:
                        cells = row.find_elements(By.CSS_SELECTOR, "td")
                        if len(cells) >= 9:
                            name_match = re.search(r"^[^\n]*", cells[1].text)
                            amount_match = re.search(
                                r"-?\d+(\.\d+)?", cells[3].text.replace("\n", "")
                            )
                            price_match = re.search(
                                r"-?\d+(\.\d+)?", cells[4].text.replace("\n", "")
                            )
                            name = name_match.group(0) if name_match else cells[1].text
                            amount = amount_match.group(0) if amount_match else "0"
                            price = price_match.group(0) if price_match else "0"

                            WELLSFARGO_o.set_holdings(
                                key,
                                account_masks[account],
                                name.strip(),
                                float(amount),
                                float(price),
                            )
            else:
                # Single account logic
                current_mask = account_masks[0]
                sleep(1)
                rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")

                for row in rows:
                    cells = row.find_elements(By.CSS_SELECTOR, "td")
                    if len(cells) >= 9:
                        name_match = re.search(r"^[^\n]*", cells[1].text)
                        amount_match = re.search(
                            r"-?\d+(\.\d+)?", cells[3].text.replace("\n", "")
                        )
                        price_match = re.search(
                            r"-?\d+(\.\d+)?", cells[4].text.replace("\n", "")
                        )
                        name = name_match.group(0) if name_match else cells[1].text
                        amount = amount_match.group(0) if amount_match else "0"
                        price = price_match.group(0) if price_match else "0"

                        WELLSFARGO_o.set_holdings(
                            key,
                            current_mask,
                            name.strip(),
                            float(amount),
                            float(price),
                        )

        except TimeoutException:
            print("Could not get to holdings")
            killSeleniumDriver(WELLSFARGO_o)
            return

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
