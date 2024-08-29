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
    maskString,
    printAndDiscord,
    printHoldings,
    stockOrder,
    type_slowly,
)


def wellsfargo_error(driver: webdriver, error: str):
    print(f"Wells Fargo Error: {error}")
    driver.save_screenshot(f"wells-fargo-error-{datetime.datetime.now()}.png")
    print(traceback.format_exc())


def wellsfargo_init(WELLSFARGO_EXTERNAL=None, botObj=None, loop=None, DOCKER=False):
    #DRIVER = getDriver(DOCKER=False)
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
            WELLSFARGO_obj.set_url(driver.current_url)
            print("=====================================================\n")
        except TimeoutException:
            print("TimeoutException: Login failed.")
            return False
        WELLSFARGO_obj.set_logged_in_object(name, driver)

    except Exception as e:
        wellsfargo_error(driver, e)
        driver.close()
        driver.quit()
        return None
    return WELLSFARGO_obj


def wellsfargo_holdings(WELLSFARGO_o: Brokerage, loop=None):
    print("wtf")
    print(WELLSFARGO_o.get_account_numbers())
    #for key in WELLSFARGO_o.get_account_numbers():
    print("help")
    driver: webdriver = WELLSFARGO_o.get_logged_in_objects("WELLSFARGO 1")
    try:
        brokerage = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//*[@id='BROKERAGE_LINK7P']"))
        )
        brokerage.click()

        try:
            more = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable(
                    (By.CLASS_NAME, "withicon holdingssnaphot")
                )
            )
            more.click()
        except Exception:
            print("error :(")
            sleep(10)
            pass

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

    for account in len(accounts):
        try:
            # Choose account
            open_dropdown = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='dropdown1']"))
            )
            open_dropdown.click()
            driver.execute_script(
                "document.getElementById('dropdownlist1').getElementsByTagName('li')["
                + str(account_index + 1)
                + "].click()"
            )

        except:
            print("Could not change account")
            killSeleniumDriver(WELLSFARGO_o)
            continue

        rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")
        # Iterate through each row
        for row in rows:
            # Find all cells in the current row
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
                my_value_match = re.search(
                    r"-?\d+(\.\d+)?", cells[5].text.replace("\n", "")
                )
                # Checking if matches exist before accessing indices
                name = name_match.group(0) if name_match else cells[1].text
                amount = amount_match.group(0) if amount_match else "0"
                price = price_match.group(0) if price_match else "0"
                my_value = my_value_match.group(0) if my_value_match else "0"
                # Assuming you want to store the quantity and price in the holdings
                WELLSFARGO_o.set_holdings(
                    key,  # Use the previously set account name
                    account_index,  # account_name (you could use account index or name here)
                    name.strip(),  # stock (ensure to strip whitespace)
                    float(amount),  # quantity (ensure it's a number)
                    float(price),  # price
                )
                print(WELLSFARGO_o.get_holdings(key, account_index))
    printHoldings(WELLSFARGO_o, loop)
    killSeleniumDriver(WELLSFARGO_o)


def wellsfargo_transaction(WELLSFARGO_o: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("WELLS FARGO")
    print("==============================")
    print()

    # dont make this hardcoded
    driver: webdriver = WELLSFARGO_o.get_logged_in_objects("WELLSFARGO 1")

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
        except:
            print("could not change account")
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
                print("??")
                pass
            # idk why doing it through selenium doesnt work sometimes
            driver.execute_script('document.getElementById("BuySellBtn").click()')
            # Buy or Sell
            if orderObj.get_action().lower() == "buy":
                action = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.LINK_TEXT, "Buy"))
                )
            elif orderObj.get_action().lower() == "sell":
                action = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.LINK_TEXT, "Buy"))
                )
            else:
                print("no buy or sell set")
            action.click()

            review = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.ID, "actionbtnContinue"))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", review)
            print("doneee")
            sleep(10)
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
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "qeval"))
            )

            price = driver.find_element(By.CLASS_NAME, "qeval").text
            print(price)

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

            day = driver.find_element(By.LINK_TEXT, "Day")
            day.click()

            # preview
            review.click()

            # submit
            WebDriverWait(driver, 20).until(check_if_page_loaded)
            submit = driver.find_element(By.CSS_SELECTOR, ".btn-wfa-submit")
            driver.execute_script("arguments[0].scrollIntoView(true);", submit)
            sleep(5)
            submit.click()

            # buy next
            buy_next = driver.find_element(By.CSS_SELECTOR, ".btn-wfa-primary")
            driver.execute_script("arguments[0].scrollIntoView(true);", buy_next)
            sleep(5)
            buy_next.click()
