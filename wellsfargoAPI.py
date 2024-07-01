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
