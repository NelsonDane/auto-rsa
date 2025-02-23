# Nelson Dane
# Helper functions and classes
# to share between scripts

import asyncio
import os
import pickle
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
from selenium_stealth import stealth

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL = os.getenv("DISCORD_CHANNEL")
HEADLESS = os.getenv("HEADLESS", "true").lower() != "false"
SORT_BROKERS = os.getenv("SORT_BROKERS", "true").lower() != "false"

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
        if not isinstance(stock, str) or stock == "":
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
        if SORT_BROKERS:
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
        quantity: float | str,
        price: float | str,
    ):
        if isinstance(quantity, str) and quantity.lower() == "n/a":
            quantity = 0
        if isinstance(price, str) and price.lower() == "n/a":
            price = 0
        if parent_name not in self.__holdings:
            self.__holdings[parent_name] = {}
        if account_name not in self.__holdings[parent_name]:
            self.__holdings[parent_name][account_name] = {}
        self.__holdings[parent_name][account_name][stock] = {
            "quantity": float(quantity),
            "price": round(float(price), 2),
            "total": round(float(quantity) * float(price), 2),
        }
        # Alphabetize by stock
        self.__holdings[parent_name][account_name] = dict(
            sorted(
                self.__holdings[parent_name][account_name].items(),
                key=lambda item: item[0],
            )
        )

    def set_account_totals(self, parent_name: str, account_name: str, total: float):
        if isinstance(total, str):
            total = total.replace(",", "").replace("$", "").strip()
        if parent_name not in self.__account_totals:
            self.__account_totals[parent_name] = {}
        self.__account_totals[parent_name][account_name] = round(float(total), 2)
        self.__account_totals[parent_name]["total"] = sum(
            value
            for key, value in self.__account_totals[parent_name].items()
            if key != "total"
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


def is_up_to_date(remote, branch):
    # Assume succeeded in updater()
    import git

    # Check if local branch is up to date with ls-remote
    up_to_date = False
    is_fork = False
    remote_hash = ""
    local_commit = git.Repo(".").head.commit.hexsha
    try:
        g = git.cmd.Git()
        ls_remote = g.ls_remote(remote, branch)
        remote_hash = ls_remote.split("\n")
        wanted_remote = f"refs/heads/{branch}"
        for line in remote_hash:
            if wanted_remote in line:
                remote_hash = line.split("\t")[0]
                break
        if isinstance(remote_hash, list):
            remote_hash = ""
            is_fork = True
            raise Exception(
                f"Branch {branch} not found in remote {remote}. Perhaps you are on a fork?"
            )
        if local_commit == remote_hash:
            up_to_date = True
            print(f"You are up to date with {remote}/{branch}")
    except Exception as e:
        print(f"Error running ls-remote: {e}")
    if not up_to_date and not is_fork:
        if remote_hash == "":
            remote_hash = "NOT FOUND"
        print(
            f"WARNING: YOU ARE OUT OF DATE. Please run 'git pull' to update from {remote}/{branch}. Local hash: {local_commit}, Remote hash: {remote_hash}"
        )
    return up_to_date


def updater():
    # Check if git is installed
    try:
        import git
    except ImportError:
        print(
            "UPDATE ERROR: Git is not installed. Please install Git and then run pip install -r requirements.txt"
        )
        print()
        return
    print("Starting Git auto update...")
    try:
        repo = git.Repo(".")
    except git.exc.InvalidGitRepositoryError:
        # If downloaded as zip, repo won't exist, so create it
        repo = git.Repo.init(".")
        repo.create_remote("origin", "https://github.com/NelsonDane/auto-rsa")
        repo.remotes.origin.fetch()
        # Always create main branch
        repo.create_head("main", repo.remotes.origin.refs.main)
        repo.heads.main.set_tracking_branch(repo.remotes.origin.refs.main)
        repo.heads.main.checkout(True)
        # When downloaded as zip, it contains the branch name
        branch = str(Path.cwd().name).split("-")[-1]
        if branch != "main":
            try:
                repo.create_head(branch, repo.remotes.origin.refs[branch])
                repo.heads[branch].set_tracking_branch(repo.remotes.origin.refs[branch])
                repo.heads[branch].checkout(True)
            except Exception:
                print(f"No branch named {branch} found, using main")
        print(f"Cloned repo from {repo.active_branch}")
    if repo.is_dirty():
        # Print warning and let users take care of changes themselves
        print(
            "UPDATE ERROR: Conflicting changes found. Please commit, stash, or remove your changes before updating."
        )
        print(f"Using commit {str(repo.head.commit)[:7]}")
        is_up_to_date("origin", repo.active_branch)
        print()
        return
    if not repo.bare:
        try:
            repo.git.pull()
            print(f"Pulled latest changes from {repo.active_branch}")
        except Exception as e:
            print(
                f"UPDATE ERROR: Cannot pull from {repo.active_branch}. Local repository is not set up correctly: {e}"
            )
            print()
            return
    print(f"Update complete! Now using commit {str(repo.head.commit)[:7]}")
    is_up_to_date("origin", repo.active_branch)
    print()
    return


def check_package_versions():
    print("Checking Python pip package versions...")
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
        options = webdriver.ChromeOptions()
        options.add_argument("start-maximized")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-notifications")
        options.add_argument("--log-level=3")
        if DOCKER:
            # Special Docker options
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-gpu")
        if DOCKER or HEADLESS:
            options.add_argument("--headless")
        driver = webdriver.Chrome(
            options=options,
            # Docker uses specific chromedriver installed via apt
            service=ChromiumService("/usr/bin/chromedriver") if DOCKER else None,
        )
        stealth(
            driver=driver,
            platform="Win32",
            fix_hairline=True,
        )
    except Exception as e:
        print(f"Error getting Driver: {e}")
        return None
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


def total_embed_length(embed):
    # Get length of entire embed (title + fields)
    fields = [embed["title"]]
    fields.extend([field["name"] for field in embed["fields"]])
    fields.extend([field["value"] for field in embed["fields"]])
    return sum([len(field) for field in fields])


def split_embed(embed):
    MAX_EMBED_LENGTH = 6000
    MAX_FIELDS = 25
    # Split embed into chunks if too long
    chunks = []
    current_embed = {key: value for key, value in embed.items() if key != "fields"}
    current_embed["fields"] = []
    current_length = total_embed_length(current_embed)
    for field in embed["fields"]:
        field_length = len(field["name"]) + len(field["value"])
        if (current_length + field_length > MAX_EMBED_LENGTH) or (
            len(current_embed["fields"]) >= MAX_FIELDS
        ):
            chunks.append(current_embed)
            current_embed = {
                key: value for key, value in embed.items() if key != "fields"
            }
            current_embed["fields"] = []
            current_length = total_embed_length(current_embed)
        current_embed["fields"].append(field)
        current_length += field_length
    chunks.append(current_embed)
    return chunks


async def processTasks(message, embed=False):
    # Send message to discord via request post
    BASE_URL = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL}/messages"
    HEADERS = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "Content-Type": "application/json",
    }
    # Split into chunks if needed
    if embed:
        full_embed = split_embed(message)
    else:
        full_embed = [{"content": message, "embeds": []}]
    for embed_chunk in full_embed:
        PAYLOAD = {
            "content": "" if embed else message,
            "embeds": [embed_chunk] if embed else [],
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
        await asyncio.sleep(0.5)


def printAndDiscord(message, loop=None, embed=False):
    # Print message
    if not embed:
        print(message)
    # Add message to discord queue
    if loop is not None:
        task_queue.put((message, embed))
        if task_queue.qsize() == 1:
            asyncio.run_coroutine_threadsafe(processQueue(), loop)


async def processQueue():
    # Process discord queue
    while not task_queue.empty():
        message, embed = task_queue.get()
        await processTasks(message, embed)
        task_queue.task_done()


async def getOTPCodeDiscord(
    botObj: commands.Bot, brokerName, code_len=6, timeout=60, loop=None
):
    printAndDiscord(f"{brokerName} requires OTP code", loop)
    printAndDiscord(
        f"Please enter OTP code or type cancel within {timeout} seconds", loop
    )
    # Get OTP code from Discord
    while True:
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
            # Check if code is numbers only
            int(code.content)
        except ValueError:
            printAndDiscord("OTP code must be numbers only", loop)
            continue
        # Check if code is correct length
        if len(code.content) != code_len:
            printAndDiscord(f"OTP code must be {code_len} digits", loop)
            continue
        return code.content


async def getUserInputDiscord(botObj: commands.Bot, prompt, timeout=60, loop=None):
    printAndDiscord(prompt, loop)
    printAndDiscord(
        f"Please enter the input or type cancel within {timeout} seconds", loop
    )
    try:
        code = await botObj.wait_for(
            "message",
            check=lambda m: m.author != botObj.user
            and m.channel.id == int(DISCORD_CHANNEL),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        printAndDiscord("Timed out waiting for input", loop)
        return None
    if code.content.lower() == "cancel":
        printAndDiscord("Input canceled by user", loop)
        return None
    return code.content


async def send_captcha_to_discord(file):
    BASE_URL = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL}/messages"
    HEADERS = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
    }
    files = {"file": ("captcha.png", file, "image/png")}
    success = False
    while not success:
        response = requests.post(BASE_URL, headers=HEADERS, files=files)
        if response.status_code == 200:
            success = True
        elif response.status_code == 429:
            rate_limit = response.json()["retry_after"] * 2
            await asyncio.sleep(rate_limit)
        else:
            print(
                f"Error sending CAPTCHA image: {response.status_code}: {response.text}"
            )
            break


def maskString(string):
    # Mask string (12345678 -> xxxx5678)
    string = str(string)
    if len(string) < 4:
        return string
    masked = "x" * (len(string) - 4) + string[-4:]
    return masked


def printHoldings(brokerObj: Brokerage, loop=None, mask=True):
    # Helper function for holdings formatting
    EMBED = {
        "title": f"{brokerObj.get_name()} Holdings",
        "color": 3447003,
        "fields": [],
    }
    print(
        f"==============================\n{brokerObj.get_name()} Holdings\n=============================="
    )
    for key in brokerObj.get_account_numbers():
        for account in brokerObj.get_account_numbers(key):
            acc_name = f"{key} ({maskString(account) if mask else account})"
            field = {
                "name": acc_name,
                "inline": False,
            }
            print(acc_name)
            print_string = ""
            holdings = brokerObj.get_holdings(key, account)
            if holdings == {}:
                print_string += "No holdings in Account\n"
            else:
                for stock in holdings:
                    quantity = holdings[stock]["quantity"]
                    price = holdings[stock]["price"]
                    total = holdings[stock]["total"]
                    print_string += f"{stock}: {quantity} @ ${format(price, '0.2f')} = ${format(total, '0.2f')}\n"
            print_string += f"Total: ${format(brokerObj.get_account_totals(key, account), '0.2f')}\n"
            print(print_string)
            # If somehow longer than 1024, chop and add ...
            field["value"] = (
                print_string[:1020] + "..."
                if len(print_string) > 1024
                else print_string
            )
            EMBED["fields"].append(field)
    printAndDiscord(EMBED, loop, True)
    print("==============================")


def save_cookies(driver, filename, path=None, important_cookies=None):
    if path is not None:
        filename = os.path.join(path, filename)
    if path is not None and not os.path.exists(path):
        os.makedirs(path)
    cookies = driver.get_cookies()
    if important_cookies is not None:
        # Save only the important cookies
        cookies_to_save = [
            cookie for cookie in cookies if cookie["name"] in important_cookies
        ]
    else:
        # Save all cookies
        cookies_to_save = cookies
    # Save cookies to a pickle file
    with open(filename, "wb") as f:
        pickle.dump(cookies_to_save, f)


def load_cookies(driver, filename, path=None):
    if path is not None:
        filename = os.path.join(path, filename)
    if not os.path.exists(filename):
        return False
    try:
        with open(filename, "rb") as f:
            cookies = pickle.load(f)
        for cookie in cookies:
            try:
                driver.add_cookie(cookie)
            except Exception:
                continue
        return True
    except Exception as e:
        print(f"Error loading cookies: {e}")
        return False


def clear_cookies(driver, important_cookies=None):
    cookies = driver.get_cookies()
    for cookie in cookies:
        if important_cookies is None or cookie["name"] not in important_cookies:
            driver.delete_cookie(cookie["name"])
