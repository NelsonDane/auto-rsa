# Nelson Dane
# Helper functions and classes
# to share between scripts

import asyncio
import os
import textwrap
from queue import Queue
from time import sleep

import requests
from dotenv import load_dotenv
from git import Repo
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromiumService
from webdriver_manager.chrome import ChromeDriverManager

# Create task queue
task_queue = Queue()


class stockOrder:
    def __init__(self):
        self.__action = None  # Buy or sell
        self.__amount = None  # Amount of shares to buy/sell
        self.__stock = []  # List of stock tickers to buy/sell
        self.__time = "day"  # Only supports day for now
        self.__price = "market"  # Default to market price
        self.__brokers = []  # List of brokerages to use
        self.__notbrokers = []  # List of brokerages to not use !ally
        self.__dry = True  # Dry run mode
        self.__holdings = False  # Get holdings from enabled brokerages
        self.__logged_in = {}  # Dict of logged in brokerage objects

    def set_action(self, action):
        if action.lower() not in ["buy", "sell"]:
            raise ValueError("Action must be buy or sell")
        self.__action = action.lower()

    def set_amount(self, amount):
        # Only allow ints for now
        try:
            amount = int(amount)
        except ValueError:
            raise ValueError("Amount must be an integer")
        if int(amount) < 1:
            raise ValueError("Amount must be greater than 0")
        self.__amount = int(amount)

    def set_stock(self, stock):
        # Only allow strings for now
        if not isinstance(stock, str):
            raise ValueError("Stock must be a string")
        self.__stock.append(stock.upper())

    def set_time(self, time):
        # Only allow strings for now
        if not isinstance(time, str):
            raise ValueError("Time must be a string")
        if time.lower() not in ["day", "gtc"]:
            raise ValueError("Time must be day or gtc")
        self.__time = time.lower()

    def set_price(self, price):
        # Check if it's market
        if isinstance(price, str):
            self.__price = price.lower()
        elif isinstance(price, (int, float)):
            self.__price = float(price)
        else:
            raise ValueError("Price must be a string or float")

    def set_brokers(self, brokers):
        # Only allow strings or lists
        if not isinstance(brokers, (str, list)):
            raise ValueError("Brokers must be a string or list")
        if isinstance(brokers, list):
            for b in brokers:
                self.__brokers.append(b.lower())
        else:
            self.__brokers.append(brokers.lower())

    def set_notbrokers(self, notbrokers):
        # Only allow strings for now
        if not isinstance(notbrokers, str):
            raise ValueError("Not Brokers must be a string")
        self.__notbrokers.append(notbrokers.lower())

    def set_dry(self, dry):
        self.__dry = dry

    def set_holdings(self, holdings):
        self.__holdings = holdings

    def set_logged_in(self, logged_in, broker):
        self.__logged_in[broker] = logged_in

    def get_action(self):
        return self.__action

    def get_amount(self):
        return self.__amount

    def get_stocks(self):
        return self.__stock

    def get_time(self):
        return self.__time

    def get_price(self):
        return self.__price

    def get_brokers(self):
        return self.__brokers

    def get_notbrokers(self):
        return self.__notbrokers

    def get_dry(self):
        return self.__dry

    def get_holdings(self):
        return self.__holdings

    def get_logged_in(self, broker=None):
        if broker is None:
            return self.__logged_in
        return self.__logged_in[broker]

    def deDupe(self):
        self.__stock = list(dict.fromkeys(self.__stock))
        self.__brokers = list(dict.fromkeys(self.__brokers))
        self.__notbrokers = list(dict.fromkeys(self.__notbrokers))

    def alphabetize(self):
        self.__stock.sort()
        self.__brokers.sort()
        self.__notbrokers.sort()

    def order_validate(self, preLogin=False):
        # Check for required fields (doesn't apply to holdings)
        if not self.__holdings:
            if self.__action is None:
                raise ValueError("Action must be set")
            if self.__amount is None:
                raise ValueError("Amount must be set")
            if len(self.__stock) == 0:
                raise ValueError("Stock must be set")
        if len(self.__brokers) == 0:
            raise ValueError("Brokers must be set")
        if len(self.__logged_in) == 0 and not preLogin:
            raise ValueError("Logged In must be set")
        # Clean up lists
        self.deDupe()
        self.alphabetize()
        # Remove notbrokers from brokers
        for b in self.__notbrokers:
            if b in self.__brokers:
                self.__brokers.remove(b)

    def __str__(self) -> str:
        return f"Self: \n \
                Action: {self.__action}\n \
                Amount: {self.__amount}\n \
                Stock: {self.__stock}\n \
                Time: {self.__time}\n \
                Price: {self.__price}\n \
                Brokers: {self.__brokers}\n \
                Not Brokers: {self.__notbrokers}\n \
                Dry: {self.__dry}\n \
                Holdings: {self.__holdings}\n \
                Logged In: {self.__logged_in}"


class Brokerage:
    def __init__(self, name):
        self.__name = name  # Name of brokerage
        self.__account_numbers = (
            {}
        )  # Dictionary of account names and numbers under parent
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
        if isinstance(total, str):
            total = total.replace(",", "").replace("$", "").strip()
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
        return textwrap.dedent(
            f"""
            Brokerage: {self.__name}
            Account Numbers: {self.__account_numbers}
            Logged In Objects: {self.__logged_in_objects}
            Holdings: {self.__holdings}
            Account Totals: {self.__account_totals}
            Account Types: {self.__account_types}
        """
        )


def updater():
    # Check if disabled
    if os.getenv("ENABLE_AUTO_UPDATE", "").lower() != "true":
        print("Auto update disabled, skipping...")
        return
    else:
        print(
            "Starting auto update. To disable, set ENABLE_AUTO_UPDATE to true in .env"
        )
    repo = Repo(".")
    if repo.is_dirty():
        # Print warning and let users take care of changes themselves
        print(
            "ERROR: Conflicting changes found. Please commit, stash, or remove your changes before updating."
        )
        return
    if not repo.bare:
        repo.remotes.origin.pull()
        print(f"Pulled lates changes from {repo.active_branch}.")
    else:
        repo.init()
        repo.create_remote("origin", "https://github.com/NelsonDane/auto-rsa")
        repo.remotes.origin.fetch()
        repo.create_head("main", repo.remotes.origin.refs.main)
        repo.heads.main.set_tracking_branch(repo.remotes.origin.refs.main)
        repo.heads.main.checkout(True)
        print(f"Cloned repo from {repo.active_branch}.")
    print("Update complete.")
    return


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
    if (
        os.getenv("WEBDRIVER_VERSION")
        and os.getenv("WEBDRIVER_VERSION") != ""
        and os.getenv("WEBDRIVER_VERSION") != "latest"
    ):
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
                service=ChromiumService(
                    ChromeDriverManager(driver_version=version).install()
                ),
                options=options,
            )
    except Exception as e:
        if ("unable to get driver" in str(e).lower()) or (
            "no such driver" in str(e).lower()
        ):
            if version is None:
                print(f"Unable to find latest chromedriver version: {e}")
            else:
                print(f"Unable to find chromedriver version {version}: {e}")
            print(
                "Please go to https://chromedriver.chromium.org/downloads and pass the latest version to WEBDRIVER_VERSION in .env"
            )
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
        if driver is not None:
            print(f"Killing {brokerObj.get_name()} drivers...")
            driver.close()
            driver.quit()
            count += 1
    print(f"Killed {count} {brokerObj.get_name()} drivers")


async def processTasks(message):
    # Get details from env (they are used prior so we know they exist)
    load_dotenv()
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    CHANNEL_ID = os.getenv("CHANNEL_ID")
    # Send message to discord via request post
    BASE_URL = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
    HEADERS = {
        "Authorization": f"Bot {BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    PAYLOAD = {
        "content": message,
    }
    # Keep trying until success
    success = False
    while success is False:
        try:
            response = requests.post(BASE_URL, headers=HEADERS, json=PAYLOAD)
            # Process response
            match response.status_code:
                case 200:
                    success = True
                case 401:
                    print("Error 401 Unauthorized: Invalid Channel ID")
                    break
                case 429:
                    rate_limit = response.json()["retry_after"] * 2
                    print(
                        f"We are being rate limited. Retrying in {rate_limit} seconds"
                    )
                    await asyncio.sleep(rate_limit)
                case _:
                    print(f"Error: {response.status_code}: {response.text}")
                    break
        except Exception as e:
            print(f"Error Sending Message: {e}")
            break


def printAndDiscord(message, loop=None):
    # Print message
    print(message)
    # Add message to discord queue
    if loop is not None:
        task_queue.put((message))
        if task_queue.qsize() == 1:
            asyncio.run_coroutine_threadsafe(processQueue(), loop)


async def processQueue():
    # Process discord queue
    while not task_queue.empty():
        message = task_queue.get()
        await processTasks(message)
        task_queue.task_done()


def printHoldings(brokerObj: Brokerage, loop=None):
    # Helper function for holdings formatting
    printAndDiscord(
        f"==============================\n{brokerObj.get_name()} Holdings\n==============================",
        loop,
    )
    for key in brokerObj.get_account_numbers():
        for account in brokerObj.get_account_numbers(key):
            printAndDiscord(f"{key} ({account}):", loop)
            holdings = brokerObj.get_holdings(key, account)
            if holdings == {}:
                printAndDiscord("No holdings in Account\n", loop)
            else:
                print_string = ""
                for stock in holdings:
                    quantity = holdings[stock]["quantity"]
                    price = holdings[stock]["price"]
                    total = holdings[stock]["total"]
                    print_string += f"{stock}: {quantity} @ ${format(price, '0.2f')} = ${format(total, '0.2f')}\n"
                printAndDiscord(print_string, loop)
            printAndDiscord(
                f"Total: ${format(brokerObj.get_account_totals(key, account), '0.2f')}\n",
                loop,
            )
    printAndDiscord("==============================", loop)
