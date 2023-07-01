# Nelson Dane
# Helper functions and classes
# to share between scripts

import textwrap
from time import sleep

from selenium import webdriver
from selenium.webdriver.edge.service import Service
from webdriver_manager.microsoft import EdgeChromiumDriverManager


class Brokerage:
    def __init__(self, name):
        self.name = name # Name of brokerage
        self.account_numbers = {} # Dictionary of accounts
        self.loggedInObjects = [] # List of logged in objects

    def add_account_number(self, name, number):
        if name in self.account_numbers:
            self.account_numbers[name].append(number)
        else:
            self.account_numbers[name] = [number]

    def get_account_numbers(self, name):
        return self.account_numbers[name]

    def __str__(self):
        return textwrap.dedent(f"""
            Brokerage: {self.name}
            Account Numbers: {self.account_numbers}
            Logged In Objects: {self.loggedInObjects}
        """)

def type_slowly(element, string, delay=0.3):
    # Type slower
    for character in string:
        element.send_keys(character)
        sleep(delay)


def check_if_page_loaded(driver):
    # Check if page is loaded
    readystate = driver.execute_script("return document.readyState;")
    return readystate == "complete"


def getDriver(DOCKER=False):
    # Init webdriver options
    options = webdriver.EdgeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-notifications")
    if DOCKER:
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
    # Init webdriver
    driver = webdriver.Edge(
        service=Service(EdgeChromiumDriverManager(cache_valid_range=30).install()),
        options=options,
    )
    driver.maximize_window()
    return driver


def killDriver(brokerObj):
    # Kill all drivers
    for driver in brokerObj.loggedInObjects:
        print(f"Killed Selenium driver {brokerObj.loggedInObjects.index(driver) + 1}")
        driver.close()
        driver.quit()
