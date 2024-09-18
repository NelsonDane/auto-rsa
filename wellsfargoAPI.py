import datetime
import os
import re
import traceback
from time import sleep

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait


from helperAPI import (
    Brokerage,
    check_if_page_loaded,
    getDriver,
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


def wellsfargo_init(WELLSFARGO_EXTERNAL=None, DOCKER=False, loop=None):
    load_dotenv()

    if not os.getenv("WELLSFARGO"):
        print("WELLSFARGO environment variable not found.")
        return False
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
            print("Logging into WELLS FARGO...")
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
            account_numbers = driver.execute_script("""
                return Array.from(document.querySelectorAll('li'))
                    .filter(li => li.outerText.includes('WELLSTRADE'))
                    .map(li => li.outerText.match(/\\d{4}/)?.[0])
                    .filter(num => num !== undefined);
            """)
            for account_number in account_numbers:
                WELLSFARGO_obj.set_account_number(name, account_number)
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
                    EC.element_to_be_clickable(
                        (By.LINK_TEXT, "Holdings Snapshot")
                    )
                )
                more.click()
                position = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable(
                        (By.ID, "btnpositions")
                    )
                )
                position.click()
            except Exception as e:
                wellsfargo_error(driver, e)

            # Find accounts
            open_dropdown = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='dropdown1']"))
            )
            open_dropdown.click()

            accounts = driver.execute_script(
                "return document.getElementById('dropdownlist1').getElementsByTagName('li').length;"
            )
            accounts = int(accounts / 2)  # Adjust based on actual implementation
        except TimeoutException:
            print("Could not get to holdings")
            killSeleniumDriver(WELLSFARGO_o)
            return

        for account in range(accounts):
            try:
                # Choose account
                open_dropdown = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='dropdown1']"))
                )
                open_dropdown.click()
                sleep(1)
                driver.execute_script(
                    "document.getElementById('dropdownlist1').getElementsByTagName('li')["
                    + str(account + 2)
                    + "].click()"
                )
            except Exception:
                print("Could not change account")
                killSeleniumDriver(WELLSFARGO_o)
                continue

            # Sleep to allow new table to load.
            sleep(1)
            rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")

            for row in rows:
                cells = row.find_elements(By.CSS_SELECTOR, "td")
                if len(cells) >= 9:
                    # Extracting data
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
                        WELLSFARGO_o.get_account_numbers(key)[account],
                        name.strip(),
                        float(amount),
                        float(price),
                    )

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

        for account in range(accounts):
            try:
                # choose account
                open_dropdown = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='dropdown2']"))
                )
                open_dropdown.click()
                driver.execute_script(
                    "document.getElementById('dropdownlist2').getElementsByTagName('li')["
                    + str(account)
                    + "].click()"
                )
            except Exception:
                print("Could not change account")
                killSeleniumDriver(WELLSFARGO_o)
            # TODO check for the error check
            for s in orderObj.get_stocks():
                WebDriverWait(driver, 20).until(check_if_page_loaded)
                try:
                    leave = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, "btn-continue"))
                    )
                    leave.click()
                except Exception:
                    # this is just for the popup
                    pass
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
                tickerBox = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.ID, "Symbol"))
                )

                tickerBox.send_keys(s)
                tickerBox.send_keys(Keys.ENTER)

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
                if orderObj.get_action().lower() == "buy":
                    price += 0.01
                else:
                    price -= 0.01
                # order type
                driver.execute_script("document.getElementById('OrderTypeBtnText').click()")

                # limit price
                order = driver.find_element(By.LINK_TEXT, "Limit")
                order.click()

                tickerBox = driver.find_element(By.ID, "Price")
                tickerBox.send_keys(price)
                tickerBox.send_keys(Keys.ENTER)

                # timing
                driver.execute_script("document.getElementById('TIFBtn').click()")
                sleep(1)
                day = driver.find_element(By.LINK_TEXT, "Day")
                day.click()

                # preview
                review.click()
                try:
                    # submit
                    submit = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(
                            (By.CSS_SELECTOR, ".btn-wfa-submit")
                        )
                    )
                    driver.execute_script("arguments[0].scrollIntoView(true);", submit)
                    sleep(2)
                    submit.click()
                    # Send confirmation
                    printAndDiscord(
                        f"{key} {WELLSFARGO_o.get_account_numbers(key)[account]}: {orderObj.get_action()} {orderObj.get_amount()} shares of {s}",
                        loop,
                    )
                    # buy next
                    buy_next = driver.find_element(By.CSS_SELECTOR, ".btn-wfa-primary")
                    driver.execute_script("arguments[0].scrollIntoView(true);", buy_next)
                    sleep(2)
                    buy_next.click()
                except TimeoutException:
                    error_text = driver.find_element(By.XPATH, "//div[@class='alert-msg-summary']//p[1]").text
                    printAndDiscord(
                        f"{key} {WELLSFARGO_o.get_account_numbers(key)[account]}: {orderObj.get_action()} {orderObj.get_amount()} shares of {s}. FAILED! \n{error_text}",
                        loop,
                    )
