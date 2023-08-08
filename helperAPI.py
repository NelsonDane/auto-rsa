# Nelson Dane
# Helper functions and classes
# to share between scripts

import os
import asyncio
import textwrap
from dotenv import load_dotenv
from time import sleep
from queue import Queue

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromiumService
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType


# Create task queue
task_queue = Queue()


class Brokerage:
    def __init__(self, name):
        self.__name = name  # Name of brokerage
        self.__account_numbers = {}  # Dictionary of account names and numbers under parent
        self.__logged_in_objects = {}  # Dictionary of logged in objects under parent
        self.__holdings = {}  # Dictionary of holdings under parent
        self.__account_totals = {}  # Dictionary of account totals
        self.__account_types = {}  # Dictionary of account types

    def set_name(self, name):
        self.__name = name

    def set_account_number(self, parent_name, account_number):
        if parent_name not in self.__account_numbers:
            self.__account_numbers[parent_name] = []
        self.__account_numbers[parent_name].append(account_number)

    def set_logged_in_object(self, parent_name, logged_in_object, account_name=None):
        if parent_name not in self.__logged_in_objects:
            self.__logged_in_objects[parent_name] = {}
        if account_name is None:
            self.__logged_in_objects[parent_name] = logged_in_object
        else:
            self.__logged_in_objects[parent_name][account_name] = logged_in_object

    def set_holdings(self, parent_name, account_name, stock, quantity, price):
        quantity = 0 if quantity == "N/A" else quantity
        price = 0 if price == "N/A" else price
        if parent_name not in self.__holdings:
            self.__holdings[parent_name] = {}
        if account_name not in self.__holdings[parent_name]:
            self.__holdings[parent_name][account_name] = {}
        self.__holdings[parent_name][account_name][stock] = {
            "quantity": round(float(quantity), 2),
            "price": round(float(price), 2),
            "total": round(float(quantity) * float(price), 2),
        }

    def set_account_totals(self, parent_name, account_name, total):
        if parent_name not in self.__account_totals:
            self.__account_totals[parent_name] = {}
        self.__account_totals[parent_name][account_name] = round(float(total), 2)
        self.__account_totals[parent_name]["total"] = sum(
            self.__account_totals[parent_name].values()
        )

    def set_account_type(self, parent_name, account_name, account_type):
        if parent_name not in self.__account_types:
            self.__account_types[parent_name] = {}
        self.__account_types[parent_name][account_name] = account_type

    def get_name(self):
        return self.__name

    def get_account_numbers(self, parent_name=None):
        if parent_name is None:
            return self.__account_numbers
        return self.__account_numbers.get(parent_name, [])

    def get_logged_in_objects(self, parent_name=None, account_name=None):
        if parent_name is None:
            return self.__logged_in_objects
        if account_name is None:
            return self.__logged_in_objects.get(parent_name, {})
        return self.__logged_in_objects.get(parent_name, {}).get(account_name, {})

    def get_holdings(self, parent_name=None, account_name=None):
        if parent_name is None:
            return self.__holdings
        if account_name is None:
            return self.__holdings.get(parent_name, {})
        return self.__holdings.get(parent_name, {}).get(account_name, {})

    def get_account_totals(self, parent_name=None, account_name=None):
        if parent_name is None:
            return self.__account_totals
        if account_name is None:
            return self.__account_totals.get(parent_name, {})
        return self.__account_totals.get(parent_name, {}).get(account_name, 0)

    def get_account_types(self, parent_name, account_name=None):
        if account_name is None:
            return self.__account_types.get(parent_name, {})
        return self.__account_types.get(parent_name, {}).get(account_name, "")

    def __str__(self):
        return textwrap.dedent(f"""
            Brokerage: {self.__name}
            Account Numbers: {self.__account_numbers}
            Logged In Objects: {self.__logged_in_objects}
            Holdings: {self.__holdings}
            Account Totals: {self.__account_totals}
            Account Types: {self.__account_types}
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
    # Check for custom driver version else use latest
    load_dotenv()
    if os.getenv("WEBDRIVER_VERSION") and os.getenv("WEBDRIVER_VERSION") != "":
        version = os.getenv("WEBDRIVER_VERSION")
        print(f"Using chromedriver version {version}")
    else:
        version = None
        print("Using latest chromedriver version")
    # Init webdriver options
    try:
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-notifications")
        if DOCKER:
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-gpu")
            # Docker uses specific chromedriver installed via apt
            driver = webdriver.Chrome(
                service=ChromiumService("/usr/bin/chromedriver"),
                options=options,
            )
        else:
            driver = webdriver.Chrome(
                service=ChromiumService(ChromeDriverManager(driver_version=version).install()),
                options=options,
            )
    except Exception as e:
        if ("unable to get driver" in str(e).lower()) or ("no such driver" in str(e).lower()):
            if version is None:
                print(f"Unable to find latest chromedriver version: {e}")
            else:
                print(f"Unable to find chromedriver version {version}: {e}")
            print("Please go to https://chromedriver.chromium.org/downloads and pass the latest version to WEBDRIVER_VERSION in .env")
        else:
            print(f"Error: Unable to initialize chromedriver: {e}")
        return None
    driver.maximize_window()
    return driver


def killDriver(brokerObj: Brokerage):
    # Kill all drivers
    count = 0
    for key in brokerObj.get_account_numbers():
        driver = brokerObj.get_logged_in_objects(key)
        print(f"Killing {brokerObj.get_name()} drivers...")
        driver.close()
        driver.quit()
        count += 1
    print(f"Killed {count} {brokerObj.get_name()} drivers")


async def processTasks(message, ctx):
    # Send message to discord
    await asyncio.sleep(0.5)
    await ctx.send(message)


def printAndDiscord(message, ctx=None, loop=None):
    # Print message
    print(message)
    # Add message to discord queue
    if ctx is not None and loop is not None:
        task_queue.put((message, ctx))
        if task_queue.qsize() == 1:
            asyncio.run_coroutine_threadsafe(processQueue(), loop)


async def processQueue():
    # Process discord queue
    while not task_queue.empty():
        message, ctx = task_queue.get()
        await processTasks(message, ctx)
        task_queue.task_done()

        
def printHoldings(brokerObj: Brokerage, ctx=None, loop=None):
    # Helper function for holdings formatting
    printAndDiscord(f"==============================\n{brokerObj.get_name()} Holdings\n==============================", ctx, loop)
    for key in brokerObj.get_account_numbers():
        for account in brokerObj.get_account_numbers(key):
            printAndDiscord(f"{key} ({account}):", ctx, loop)
            holdings = brokerObj.get_holdings(key, account)
            if holdings == {}:
                printAndDiscord("No holdings in Account\n", ctx, loop)
            else:
                print_string = ""
                for stock in holdings:
                    quantity = holdings[stock]["quantity"]
                    price = holdings[stock]["price"]
                    total = holdings[stock]["total"]
                    print_string += f"{stock}: {quantity} @ ${format(price, '0.2f')} = ${format(total, '0.2f')}\n"
                printAndDiscord(print_string, ctx, loop)
            printAndDiscord(f"Total: ${format(brokerObj.get_account_totals(key, account), '0.2f')}\n", ctx, loop)
    printAndDiscord("==============================", ctx, loop)
