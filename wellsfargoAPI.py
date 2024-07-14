import datetime
import os
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

DRIVER = getDriver(DOCKER=False)
load_dotenv()


def wellsfargo_error(driver: webdriver, error: str):
    print(f"Wells Fargo Error: {error}")
    driver.save_screenshot(f"wells-fargo-error-{datetime.datetime.now()}.png")
    print(traceback.format_exc())


def wellsfargo_init(WELLSFARGO_EXTERNAL=None, DOCKER=False):
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
                print("Username:", account[0], "Password:", (account[1]))
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
                # TODO check if auth needed
                sleep(10)
                WELLSFARGO_obj.set_url(driver.current_url)
                print(WELLSFARGO_obj.get_url())
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
    print()
    print("==============================")
    print("Wells Fargo Holdings")
    print("==============================")
    print()
    sleep(40)
    # dont make this hardcoded
    driver: webdriver = WELLSFARGO_o.get_logged_in_objects("WELLSFARGO 1")

    data = driver.execute_script(
        """
const array_all = Array.from(document.querySelector('tbody').querySelectorAll('tr'));
const data = [];

for (let i = 0; i < array_all.length; i++) {
    let curr = Array.from(array_all[i].querySelectorAll('td'));

    // Extracting data
    let name = curr[1].textContent.match(/([A-Z]+),popup/);
    let amount = curr[3].textContent.replace(/\n/g, '').match(/-?\d+(\.\d+)?/);
    let price = curr[4].textContent.replace(/\n/g, '').match(/-?\d+(\.\d+)?/);
    let my_value = curr[5].textContent.replace(/\n/g, '').match(/-?\d+(\.\d+)?/);

    // Checking if matches exist before accessing indices
    name = name ? name[1] : '';
    amount = amount ? amount[0] : '';
    price = price ? price[0] : '';
    my_value = my_value ? my_value[0] : '';

    // Pushing data as JSON object to array
    data.push({
        name: name,
        amount: amount,
        price: price,
        my_value: my_value
    });
}
return data
        """
    )
    print(data)


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

        for s in orderObj.get_stocks():

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

            # ticker
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
            price = driver.execute_script(
                "return document.getElementsByClassName('qeval')[0].textContent;"
            )

            # order type
            sleep(1)
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
            review = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.ID, "actionbtnContinue"))
            )
            review.click()

            # submit
            sleep(5)
            submit = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn-wfa-submit"))
            )
            submit.click()
            sleep(5)
            buy_next = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn-wfa-primary"))
            )
            buy_next.click()
