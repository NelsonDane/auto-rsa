# Nelson Dane
# API to Interface with Fidelity
# Uses headless Selenium

import os
import sys
import logging
import traceback
from time import sleep
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from selenium.webdriver.edge.service import Service

def check_if_page_loaded(driver):
    """
    Check if the page is loaded through document.readyState
    :param driver:
    Selenium WebDriver instance
    :return:
    """
    readystate = driver.execute_script("return document.readyState;")
    return readystate == "complete"

def fidelity_init(DOCKER=False):
    try:
        # Initialize .env file
        load_dotenv()
        # Import Fidelity account
        if not os.getenv("FIDELITY_USERNAME") or not os.getenv("FIDELITY_PASSWORD"):
            print("Fidelity not found, skipping...")
            return None
        FIDELITY_USERNAME = os.environ["FIDELITY_USERNAME"]
        FIDELITY_PASSWORD = os.environ["FIDELITY_PASSWORD"]
        # Init webdriver options
        options = webdriver.EdgeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-notifications")
        options.add_argument("--log-level=3")
        if DOCKER:
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--no-sandbox")
        # Init webdriver
        os.environ['WDM_LOG'] = str(logging.NOTSET)
        driver = webdriver.Edge(
            service=Service(EdgeChromiumDriverManager(cache_valid_range=30).install()),
            options=options,
        )
        driver.maximize_window()
        print("Logging in to Fidelity...")
        # Log in to Fidelity account
        driver.get("https://digital.fidelity.com/prgw/digital/login/full-page?AuthRedUrl=https://digital.fidelity.com/ftgw/digital/portfolio/summary")
        # Wait for page load
        WebDriverWait(driver, 10).until(check_if_page_loaded)
        # Type in username and password   
        username_field = driver.find_element(by=By.CSS_SELECTOR, value="#userId-input")
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable(username_field)
        )
        username_field.send_keys(FIDELITY_USERNAME)
        password_field = driver.find_element(by=By.CSS_SELECTOR, value="#password")
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable(password_field)
        )
        password_field.send_keys(FIDELITY_PASSWORD)
        driver.find_element(by=By.CSS_SELECTOR, value="#fs-login-button").click()
        # Wait for page to load to summary page
        if not driver.current_url == "https://oltx.fidelity.com/ftgw/fbc/oftop/portfolio#summary":
            WebDriverWait(driver, 10).until(
                expected_conditions.url_to_be("https://oltx.fidelity.com/ftgw/fbc/oftop/portfolio#summary")
            )
        # Wait for page to load
        WebDriverWait(driver, 10).until(check_if_page_loaded)
        sleep(3)
        print("Logged in to Fidelity!")
    except Exception as e:
        print(f'Error logging in: "{e}"')
        print(traceback.print_exc())
        return None
    return driver
    
def fidelity_holdings(driver, ctx):
    print()
    print("==============================")
    print("Fidelity Holdings")
    print("==============================")
    print()
    # Make sure init didn't return None
    if driver is None:
        print("Error: No Fidelity account")
        return None
    try:
        # Get account holdings
        driver.get("https://oltx.fidelity.com/ftgw/fbc/oftop/portfolio#positions")
        # Wait for page load
        WebDriverWait(driver, 10).until(check_if_page_loaded)
        sleep(5)
        # Get total account value
        total_value = driver.find_elements(by=By.CSS_SELECTOR, value='body > div.fidgrid.fidgrid--shadow.fidgrid--nogutter > div.full-page--container > div.fidgrid--row.port-summary-container > div.port-summary-content.clearfix > div > div.fidgrid--content > div > div.account-selector-wrapper.port-nav.account-selector--reveal > div.account-selector.account-selector--normal-mode.clearfix > div.account-selector--main-wrapper > div.account-selector--accounts-wrapper > div.account-selector--tab.account-selector--tab-all.js-portfolio.account-selector--target-tab.js-selected > span.account-selector--tab-row.account-selector--all-accounts-balance.js-portfolio-balance')
        print(f'Total Fidelity account value: {total_value[0].text}')
        # Get value of individual and retirement accounts
        ind_accounts = driver.find_elements(by=By.CSS_SELECTOR, value='[data-group-id="IA"]')
        ret_accounts = driver.find_elements(by=By.CSS_SELECTOR, value='[data-group-id="RA"]')
        # Get text from elements
        test = ind_accounts[0].text
        test2 = ret_accounts[0].text
        # Split by new line
        info = test.splitlines()
        info2 = test2.splitlines()
        # Get every 4th element in the list, starting at the 3rd element
        # This is the account number
        ind_num = []
        ret_num = []
        for x in info[3::4]:
            ind_num.append(x)
        for x in info2[2::4]:
            ret_num.append(x)
        # Get every 4th element in the list, starting at the 4th element
        # This is the account value
        ind_val = []
        ret_val = []
        for x in info[4::4]:
            ind_val.append(x)
        for x in info2[3::4]:
            ret_val.append(x)
        # Print out account numbers and values
        print("Individual accounts:")
        for x in range(len(ind_num)):
            print(f'{ind_num[x]} value: {ind_val[x]}')
        print("Retirement accounts:")
        for x in range(len(ret_num)):
            print(f'{ret_num[x]} value: {ret_val[x]}')
        sleep(5)
        # We'll add positions later since that will be hard
    except Exception as e:
        print(f'Error getting holdings: {e}')
        print(traceback.format_exc())

# try:
#     print()
#     fidelity = fidelity_init()
#     #input("Press enter to continue to holdings...")
#     fidelity_holdings(fidelity)
#     fidelity.close()
#     fidelity.quit()
#     sys.exit(0)
# # Catch any errors
# except KeyboardInterrupt:
#     print("Quitting...")
#     sys.exit(1)
# except Exception as e:
#     print(e)
