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
DRIVER=getDriver(DOCKER=False)
load_dotenv()

def wellsfargo_error(driver: webdriver, error: str):
    print(f"Wells Fargo Error: {error}")
    driver.save_screenshot(f"wells-fargo-error-{datetime.datetime.now()}.png")
    print(traceback.format_exc())

def wellsfargo_init(WELLSFARGO_EXTERNAL=None,DOCKER=Fasle):
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
            driver=DRIVER
            if driver is None:
                raise Exception("Driver not found.")
            driver.get(
                'https://connect.secure.wellsfargo.com/auth/login/present'
            )
            WebDriverWait(driver, 20).until(check_if_page_loaded)
            # Login
            try:
                print("Username:", account[0], "Password:", (account[1]))
                username_field = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='j_username']")))
                username_field.send_keys(account[0])

                # Wait for the password field and enter the password
                password_field = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='j_password']")))
                password_field.send_keys(account[1])

                login_button = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".Button__modern___cqCp7")))
                login_button.click()
                WebDriverWait(driver, 20).until(check_if_page_loaded)
                WELLSFARGO_obj.set_url(driver.current_url)
                print("=====================================================\n")
            except TimeoutException:
                print("TimeoutException: Login failed.")
                return False
            WELLSFARGO_obj.set_logged_in_object(name, driver)

        except Exception as e:
            wellsfargo_error(driver,e)
            driver.close()
            driver.quit()
            return None
    return WELLSFARGO_obj

    

