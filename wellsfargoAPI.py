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
                type_slowly(username_field,account[0])
                # Wait for the password field and enter the password
                password_field = driver.find_element(By.XPATH, "//*[@id='j_password']")
                type_slowly(password_field,account[1])

                login_button = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable(
                        (By.CSS_SELECTOR, ".Button__modern___cqCp7")
                    )
                )
                login_button.click()
                WebDriverWait(driver, 20).until(check_if_page_loaded)
                #TODO check if auth needed
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


def wellsfargo_transaction(
    WELLSFARGO_o: Brokerage, orderObj: stockOrder, loop=None, DOCKER=False
):
    print()
    print("==============================")
    print("WELLS FARGO")
    print("==============================")
    print()

    #dont make this hardcoded
    driver: webdriver = WELLSFARGO_o.get_logged_in_objects("WELLSFARGO 1")
    try:
        driver.get(WELLSFARGO_o.get_url)
    except:
        print('wtf')


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
        print(orderObj.get_action)
        for s in orderObj.get_stocks():

            #idk why doing it through selenium doesnt work sometimes
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
            driver.execute_script("document.querySelector('#OrderQuantity').value ="+ str(int(orderObj.get_amount())))

            # order type
            #document.getElementById('OrderTypeBtnText').click()
            orderBox = driver.find_element(By.ID, "OrderTypeBtnText")
            orderBox.click()
            
            driver.execute_script("document.evaluate('/html/body/div[3]/div[5]/div/form/div/div[1]/div[4]/div[1]/div[2]/div[2]/ul/li[1]/a', document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue.click()")


            # limit price
            sleep(2000)
            price = driver.execute_script("return document.getElementsByClassName('qeval')[0].textContent;")
            tickerBox = driver.find_element(By.ID, "Price")
            tickerBox.send_keys(price)
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
