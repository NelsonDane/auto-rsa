import datetime
import os
import re
import traceback
from time import sleep

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support.ui import Select


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


def wellsfargo_init(WELLSFARGO_EXTERNAL=None, DOCKER=Fasle):
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
            driver = DRIVER
            if driver is None:
                raise Exception("Driver not found.")
            driver.get("https://connect.secure.wellsfargo.com/auth/login/present")
            WebDriverWait(driver, 20).until(check_if_page_loaded)
            # Login
            try:
                print("Username:", account[0], "Password:", (account[1]))
                username_field = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='j_username']"))
                )
                username_field.send_keys(account[0])

                # Wait for the password field and enter the password
                password_field = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='j_password']"))
                )
                password_field.send_keys(account[1])

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


def wellsfargo_transaction(
    WELLSFARGO_o: Brokerage, orderObj: stockOrder, loop=None, DOCKER=False
):
    print()
    print("==============================")
    print("WELLS FARGO")
    print("==============================")
    print()

    driver = DRIVER

    driver.get(WELLSFARGO_o.get_url)

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

            driver.execute_script('document.getElementById("BuySellBtn").click()')
            # Buy or Sell
            action = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.LINK_TEXT, orderObj.get_action()))
            )
            action.click()

            # ticker
            tickerBox = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.ID, "Symbol"))
            )
            tickerBox.send_keys(s)
            tickerBox.send_keys(Keys.ENTER)

            # quantity
            quantBox = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.ID, "OrderQuantity"))
            )
            quantBox.send_keys(orderObj.get_amount())
            quantBox.send_keys(Keys.ENTER)

            # order type
            orderBox = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.ID, "OrderTypeBtnText"))
            )
            orderBox.click()

            order = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.ID, "Limit"))
            )
            order.click()

            # limit price
            tickerBox = driver.find_element(By.ID, "Price")
            tickerBox.send_keys(ticker[1])
            tickerBox.send_keys(Keys.ENTER)

            # timing
            timing = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.ID, "TIFBtn"))
            )
            timing.click()
            day = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.ID, "Day"))
            )
            day.click()

            # preview
            review = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.ID, "actionbtnContinue"))
            )
            review.click()

            # submit
            submit = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn-wfa-submit"))
            )
            submit.click()

            buy_next = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn-wfa-primary"))
            )
            buy_next.click()
