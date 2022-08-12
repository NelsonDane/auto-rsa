# Nelson Dane
# API to Interface with Fidelity
# Uses headless Selenium

# NOT FINISHED

import sys
from time import sleep
from selenium import webdriver
# from selenium.common.exceptions import (
#     StaleElementReferenceException,
#     TimeoutException,
#     NoSuchElementException,
# )
# from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from selenium.webdriver.edge.service import Service

def fidelity_init():
    # Do nothing since it's disabled
    print("Fidelity disabled, skipping...")
    return None
    try:
        driver.get("https://www.fidelity.com/")
        username_field = driver.find_element(by=By.CSS_SELECTOR, value="#userId-input")
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable(username_field)
        )
        username_field.send_keys(username)
        password_field = driver.find_element(by=By.CSS_SELECTOR, value="#password")
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable(password_field)
        )
        password_field.send_keys(password)
        driver.find_element(by=By.CSS_SELECTOR, value="#fs-login-button").click()
        print("Login successful!")
    except Exception as e:
        print(f'Error logging in: {e}')
    
# def fidelity_main(username, password):
#     print("Logging in...")
    #fidelity_init(username, password)

# # Webdriver initialization
# options = webdriver.EdgeOptions()
# options.add_argument("--disable-blink-features=AutomationControlled")

# driver = webdriver.Edge(
#     service=Service(EdgeChromiumDriverManager(cache_valid_range=30).install()),
#     options=options,
# )

# driver.maximize_window()

# #sleep(100)
# # Run main program
# try:
#     print()
#     fidelity_main(None, None)
# # Catch any errors
# except KeyboardInterrupt:
#     print("Quitting...")
#     driver.quit()
#     sys.exit(1)
# except Exception as e:
#     print(e)
#     driver.close()