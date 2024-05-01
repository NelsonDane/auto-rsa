# Nelson Dane
# Helper functions and classes
# to share between scripts

import asyncio
import os
import subprocess
import sys
import textwrap
import traceback
from pathlib import Path
from queue import Queue
from threading import Thread
from time import sleep

import pkg_resources
import requests
from discord.ext import commands
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromiumService
from selenium.webdriver.edge.service import Service as EdgeService

# Create task queue
task_queue = Queue()


class stockOrder:
    def __init__(self):
        self.__action: str = None  # Buy or sell
        self.__amount: float = None  # Amount of shares to buy/sell
        self.__stock: list = []  # List of stock tickers to buy/sell
        self.__time: str = "day"  # Only supports day for now
        self.__price: str = "market"  # Default to market price
        self.__brokers: list = []  # List of brokerages to use
        self.__notbrokers: list = []  # List of brokerages to not use
        self.__dry: bool = True  # Dry run mode
        self.__holdings: bool = False  # Get holdings from enabled brokerages
        self.__logged_in: dict = {}  # Dict of logged in brokerage objects

    def set_action(self, action: str) -> None | ValueError:
        if action.lower() not in ["buy", "sell"]:
            raise ValueError("Action must be buy or sell")
        self.__action = action.lower()

    def set_amount(self, amount: float) -> None | ValueError:
        # Only allow floats
        try:
            amount = float(amount)
        except ValueError:
            raise ValueError(f"Amount ({amount}) must be a number")
        self.__amount = amount

    def set_stock(self, stock: str) -> None | ValueError:
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

    def set_price(self, price: str | float) -> None | ValueError:
        # Only "market" or float
        if not isinstance(price, (str, float)):
            raise ValueError("Price must be a string or float")
        if isinstance(price, float):
            price = round(price, 2)
        if isinstance(price, str):
            price = price.lower()
        self.__price = price

    def set_brokers(self, brokers: list) -> None | ValueError:
        # Only allow strings or lists
        if not isinstance(brokers, (str, list)):
            raise ValueError("Brokers must be a string or list")
        if isinstance(brokers, list):
            for b in brokers:
                self.__brokers.append(b.lower())
        else:
            self.__brokers.append(brokers.lower())

    def set_notbrokers(self, notbrokers: list) -> None | ValueError:
        # Only allow strings or lists
        if not isinstance(notbrokers, str):
            raise ValueError("Not Brokers must be a string")
        if isinstance(notbrokers, list):
            for b in notbrokers:
                self.__notbrokers.append(b.lower())
        else:
            self.__notbrokers.append(notbrokers.lower())

    def set_dry(self, dry: bool) -> None | ValueError:
        # Only allow bools
        if not isinstance(dry, bool):
            raise ValueError("Dry must be a boolean")
        self.__dry = dry

    def set_holdings(self, holdings: bool) -> None | ValueError:
        # Only allow bools
        if not isinstance(holdings, bool):
            raise ValueError("Holdings must be a boolean")
        self.__holdings = holdings

    def set_logged_in(self, logged_in, broker: str):
        self.__logged_in[broker] = logged_in

    def get_action(self) -> str:
        return self.__action

    def get_amount(self) -> float:
        return self.__amount

    def get_stocks(self) -> list:
        return self.__stock

    def get_time(self) -> str:
        return self.__time

    def get_price(self) -> str | float:
        return self.__price

    def get_brokers(self) -> list:
        return self.__brokers

    def get_notbrokers(self) -> list:
        return self.__notbrokers

    def get_dry(self) -> bool:
        return self.__dry

    def get_holdings(self) -> bool:
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

    def order_validate(self, preLogin=False) -> None | ValueError:
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
        self.__name: str = name  # Name of brokerage
        self.__account_numbers: dict = (
            {}
        )  # Dictionary of account names and numbers under parent
        self.__logged_in_objects: dict = (
            {}
        )  # Dictionary of logged in objects under parent
        self.__holdings: dict = {}  # Dictionary of holdings under parent
        self.__account_totals: dict = {}  # Dictionary of account totals
        self.__account_types: dict = {}  # Dictionary of account types

    def set_name(self, name: str):
        if not isinstance(name, str):
            raise ValueError("Name must be a string")
        self.__name = name

    def set_account_number(self, parent_name: str, account_number: str):
        if parent_name not in self.__account_numbers:
            self.__account_numbers[parent_name] = []
        self.__account_numbers[parent_name].append(account_number)

    def set_logged_in_object(
        self, parent_name: str, logged_in_object, account_name: str = None
    ):
        if parent_name not in self.__logged_in_objects:
            self.__logged_in_objects[parent_name] = {}
        if account_name is None:
            self.__logged_in_objects[parent_name] = logged_in_object
        else:
            self.__logged_in_objects[parent_name][account_name] = logged_in_object

    def set_holdings(
        self,
        parent_name: str,
        account_name: str,
        stock: str,
        quantity: float,
        price: float,
    ):
        quantity = 0 if quantity == "N/A" else quantity
        price = 0 if price == "N/A" else price
        if parent_name not in self.__holdings:
            self.__holdings[parent_name] = {}
        if account_name not in self.__holdings[parent_name]:
            self.__holdings[parent_name][account_name] = {}
        self.__holdings[parent_name][account_name][stock] = {
            "quantity": float(quantity),
            "price": round(float(price), 2),
            "total": round(float(quantity) * float(price), 2),
        }

    def set_account_totals(self, parent_name: str, account_name: str, total: float):
        if isinstance(total, str):
            total = total.replace(",", "").replace("$", "").strip()
        if parent_name not in self.__account_totals:
            self.__account_totals[parent_name] = {}
        self.__account_totals[parent_name][account_name] = round(float(total), 2)
        self.__account_totals[parent_name]["total"] = sum(
            self.__account_totals[parent_name].values()
        )

    def set_account_type(self, parent_name: str, account_name: str, account_type: str):
        if parent_name not in self.__account_types:
            self.__account_types[parent_name] = {}
        self.__account_types[parent_name][account_name] = account_type

    def get_name(self) -> str:
        return self.__name

    def get_account_numbers(self, parent_name: str = None) -> list | dict:
        if parent_name is None:
            return self.__account_numbers
        return self.__account_numbers.get(parent_name, [])

    def get_logged_in_objects(
        self, parent_name: str = None, account_name: str = None
    ) -> dict:
        if parent_name is None:
            return self.__logged_in_objects
        if account_name is None:
            return self.__logged_in_objects.get(parent_name, {})
        return self.__logged_in_objects.get(parent_name, {}).get(account_name, {})

    def get_holdings(self, parent_name: str = None, account_name: str = None) -> dict:
        if parent_name is None:
            return self.__holdings
        if account_name is None:
            return self.__holdings.get(parent_name, {})
        return self.__holdings.get(parent_name, {}).get(account_name, {})

    def get_account_totals(
        self, parent_name: str = None, account_name: str = None
    ) -> dict:
        if parent_name is None:
            return self.__account_totals
        if account_name is None:
            return self.__account_totals.get(parent_name, {})
        return self.__account_totals.get(parent_name, {}).get(account_name, 0)

    def get_account_types(self, parent_name: str, account_name: str = None) -> dict:
        if account_name is None:
            return self.__account_types.get(parent_name, {})
        return self.__account_types.get(parent_name, {}).get(account_name, "")

    def __str__(self) -> str:
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


class ThreadHandler:
    def __init__(self, func, *args, **kwargs):
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self._active_threads = []
        self.queue = Queue()
        self.thread = Thread(target=self._run)

    def _run(self):
        try:
            result = self.func(*self.args, **self.kwargs)
            self.queue.put((result, None))
        except Exception as e:
            print(traceback.print_exc())
            self.queue.put((None, e))

    def start(self):
        self.thread.start()

    def join(self):
        self.thread.join()

    def get_result(self):
        return self.queue.get()


def updater():
    # Check if disabled
    if os.getenv("ENABLE_AUTO_UPDATE", "").lower() == "false":
        print("Auto update disabled, skipping...")
        print()
        return
    # Check if git is installed
    try:
        import git
        from git import Repo
    except ImportError:
        print(
            "UPDATE ERROR: Git is not installed. Please install Git and then run pip install -r requirements.txt"
        )
        print()
        return
    print("Starting auto update. To disable, set ENABLE_AUTO_UPDATE to false in .env")
    try:
        repo = Repo(".")
    except git.exc.InvalidGitRepositoryError:
        # If downloaded as zip, repo won't exist, so create it
        repo = Repo.init(".")
        repo.create_remote("origin", "https://github.com/NelsonDane/auto-rsa")
        repo.remotes.origin.fetch()
        # Always create main branch
        repo.create_head("main", repo.remotes.origin.refs.main)
        repo.heads.main.set_tracking_branch(repo.remotes.origin.refs.main)
        # If downloaded from other branch, zip has branch name
        current_dir = Path.cwd()
        if current_dir.name != "auto-rsa-main":
            branch = str.replace(current_dir.name, "auto-rsa-", "")
            try:
                repo.create_head(branch, repo.remotes.origin.refs[branch])
                repo.heads[branch].set_tracking_branch(repo.remotes.origin.refs[branch])
                repo.heads[branch].checkout(True)
            except:
                print(f"No branch {branch} found, using main")
        else:
            repo.heads.main.checkout(True)
        print(f"Cloned repo from {repo.active_branch}")
    if repo.is_dirty():
        # Print warning and let users take care of changes themselves
        print(
            "UPDATE ERROR: Conflicting changes found. Please commit, stash, or remove your changes before updating."
        )
        print()
        return
    if not repo.bare:
        try:
            repo.remotes.origin.pull(repo.active_branch)
            print(f"Pulled latest changes from {repo.active_branch}")
        except Exception as e:
            print(
                f"UPDATE ERROR: Cannot pull from {repo.active_branch}. Local repository is not set up correctly: {e}"
            )
            print()
            return
    revision_head = str(repo.head.commit)[:7]
    print(f"Update complete! Using commit {revision_head}")
    print()
    return


def check_package_versions():
    print("Checking package versions...")
    # Check if pip packages are up to date
    required_packages = []
    required_repos = []
    f = open("requirements.txt", "r")
    for line in f:
        # Not commented pip packages
        if not line.startswith("#") and "==" in line:
            required_packages.append(line.strip())
        # Not commented git repos
        elif not line.startswith("#") and "git+" in line:
            required_repos.append(line.strip())
    SHOULD_CONTINUE = True
    for package in required_packages:
        if "==" not in package:
            continue
        package_name = package.split("==")[0].lower()
        required_version = package.split("==")[1]
        installed_version = pkg_resources.get_distribution(package_name).version
        if installed_version < required_version:
            print(
                f"Required package {package_name} is out of date (Want {required_version} but have {installed_version})."
            )
            SHOULD_CONTINUE = False
        elif installed_version > required_version:
            print(
                f"WARNING: Required package {package_name} is newer than required (Want {required_version} but have {installed_version})."
            )
    for repo in required_repos:
        repo_name = repo.split("/")[-1].split(".")[0].lower()
        package_name = repo.split("egg=")[-1].lower()
        required_version = repo.split("@")[-1].split("#")[0]
        if len(required_version) != 40:
            # Invalid hash
            print(f"Required repo {repo_name} has invalid hash {required_version}.")
            continue
        package_data = subprocess.run(
            ["pip", "show", package_name], capture_output=True, text=True, check=True
        ).stdout
        if "Editable project location:" in package_data:
            epl = (
                package_data.split("Editable project location:")[1]
                .split("\n")[0]
                .strip()
            )
            installed_hash = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                cwd=epl,
                text=True,
                check=True,
            )
            installed_hash = installed_hash.stdout.strip()
            if installed_hash != required_version:
                print(
                    f"Required repo {repo_name} is out of date (Want {required_version} but have {installed_hash})."
                )
                SHOULD_CONTINUE = False
        else:
            print(
                f"Required repo {repo_name} is installed as a package, not a git repo."
            )
            SHOULD_CONTINUE = False
            continue
    if not SHOULD_CONTINUE:
        print(
            'Please run "pip install -r requirements.txt" to install/update required packages.'
        )
        sys.exit(1)
    else:
        print("All required packages are installed and up to date.")
        print()
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
    # Init webdriver options
    try:
        if DOCKER:
            # Docker uses Chromium
            options = webdriver.ChromeOptions()
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-notifications")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-gpu")
            # Docker uses specific chromedriver installed via apt
            driver = webdriver.Chrome(
                service=ChromiumService(),
                options=options,
            )
        else:
            # Otherwise use Edge
            options = webdriver.EdgeOptions()
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-notifications")
            driver = webdriver.Edge(
                service=EdgeService(),
                options=options,
            )
    except Exception as e:
        print(f"Error getting Driver: {e}")
        return None
    driver.maximize_window()
    return driver


def killSeleniumDriver(brokerObj: Brokerage):
    # Kill all selenium drivers
    count = 0
    if brokerObj is not None:
        for key in brokerObj.get_account_numbers():
            print(f"Killing driver for {key}")
            driver: webdriver = brokerObj.get_logged_in_objects(key)
            if driver is not None:
                driver.close()
                driver.quit()
                count += 1
        if count > 0:
            print(f"Killed {count} {brokerObj.get_name()} drivers")


async def processTasks(message):
    # Get details from env (they are used prior so we know they exist)
    load_dotenv()
    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    DISCORD_CHANNEL = os.getenv("DISCORD_CHANNEL")
    # Send message to discord via request post
    BASE_URL = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL}/messages"
    HEADERS = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
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
            if response.status_code == 200:
                success = True
            elif response.status_code == 429:
                rate_limit = response.json()["retry_after"] * 2
                await asyncio.sleep(rate_limit)
            else:
                print(f"Error: {response.status_code}: {response.text}")
                break
        except Exception as e:
            print(f"Error Sending Message: {e}")
            break
    sleep(0.5)


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


async def getOTPCodeDiscord(
    botObj: commands.Bot, brokerName, code_len=6, timeout=60, loop=None
):
    printAndDiscord(f"{brokerName} requires OTP code", loop)
    printAndDiscord(
        f"Please enter OTP code or type cancel within {timeout} seconds", loop
    )
    # Get OTP code from Discord
    otp_code = None
    while otp_code is None:
        try:
            code = await botObj.wait_for(
                "message",
                # Ignore bot messages and messages not in the correct channel
                check=lambda m: m.author != botObj.user
                and m.channel.id == int(os.getenv("DISCORD_CHANNEL")),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            printAndDiscord(
                f"Timed out waiting for OTP code input for {brokerName}", loop
            )
            return None
        if code.content.lower() == "cancel":
            printAndDiscord(f"Cancelling OTP code for {brokerName}", loop)
            return None
        try:
            otp_code = int(code.content)
        except ValueError:
            printAndDiscord("OTP code must be numbers only", loop)
            continue
        if len(code.content) != code_len:
            printAndDiscord(f"OTP code must be {code_len} digits", loop)
            continue
    return otp_code


def maskString(string):
    # Mask string (12345678 -> xxxx5678)
    string = str(string)
    if len(string) < 4:
        return string
    masked = "x" * (len(string) - 4) + string[-4:]
    return masked


def printHoldings(brokerObj: Brokerage, loop=None):
    # Helper function for holdings formatting
    printAndDiscord(
        f"==============================\n{brokerObj.get_name()} Holdings\n==============================",
        loop,
    )
    for key in brokerObj.get_account_numbers():
        for account in brokerObj.get_account_numbers(key):
            printAndDiscord(f"{key} ({maskString(account)}):", loop)
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
