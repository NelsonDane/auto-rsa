# Nelson Dane
# Helper functions and classes
# to share between scripts

import asyncio
import contextlib
import datetime
import json
import operator
import os
import re
import sys
import textwrap
import traceback
from collections.abc import Callable
from importlib.metadata import version
from io import BytesIO
from pathlib import Path
from queue import Queue
from threading import Lock, Thread
from time import sleep
from typing import Any, Literal, TypedDict, TypeVar, cast

import requests
from discord.ext import commands
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromiumService
from selenium.webdriver.remote.webelement import WebElement
from selenium_stealth import stealth

from src.brokers import BrokerInfo

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
DISCORD_CHANNEL = os.getenv("DISCORD_CHANNEL", "")
DISCORD_MESSAGES_URL = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL}/messages"
HEADLESS = os.getenv("HEADLESS", "true").lower() != "false"
SORT_BROKERS = os.getenv("SORT_BROKERS", "true").lower() != "false"
CURRENT_RSA_VERSION = version("auto_rsa_bot")


class EmbedFieldType(TypedDict):
    """Type hints for Discord embed fields."""

    name: str
    value: str
    inline: bool


class EmbedType(TypedDict):
    """Type hints for Discord embed messages."""

    title: str
    color: int
    fields: list[EmbedFieldType]


class NonEmbedType(TypedDict):
    """Type hints for non-embed messages."""

    content: str


# Create task queue
task_queue: Queue[tuple[str | EmbedType, bool]] = Queue()


class StockOrder:  # noqa: PLR0904
    """Object representing a stock order."""

    def __init__(self) -> None:
        """Initialize a stock order."""
        self.__action: str = ""  # Buy or sell
        self.__amount: float = 0.0  # Amount of shares to buy/sell
        self.__stock: list[str] = []  # List of stock tickers to buy/sell
        self.__time: str = "day"  # Only supports day for now
        self.__price: str | float = "market"  # Default to market price
        self.__brokers: list[BrokerInfo] = []  # List of brokerages to use
        self.__notbrokers: list[BrokerInfo] = []  # List of brokerages to not use
        self.__dry: bool = True  # Dry run mode
        self.__holdings: bool = False  # Get holdings from enabled brokerages
        self.__logged_in: dict[
            str,
            Brokerage,
        ] = {}  # Dict of logged in brokerage objects

    def set_action(self, action: Literal["buy", "sell"]) -> None:
        """Set the action to be performed (buy/sell)."""
        self.__action = action

    def set_amount(self, amount: float) -> None:
        """Set the amount of shares to buy/sell."""
        self.__amount = amount

    def set_stock(self, stock: str) -> None:
        """Set the stock ticker to buy/sell."""
        self.__stock.append(stock.upper())

    def set_time(self, time: Literal["day", "gtc"]) -> None:
        """Set the time in force for the order."""
        self.__time = time

    def set_price(self, price: Literal["market", "limit"] | float) -> None:
        """Set the price for the order."""
        self.__price = round(price, 2) if isinstance(price, float) else price

    def set_brokers(self, brokers: BrokerInfo | list[BrokerInfo]) -> None:
        """Set the list of brokers to use."""
        if isinstance(brokers, list):
            for b in brokers:
                self.__brokers.append(b)
        else:
            self.__brokers.append(brokers)

    def set_notbrokers(self, notbrokers: BrokerInfo | list[BrokerInfo]) -> None:
        """Set the list of brokers to not use."""
        if isinstance(notbrokers, list):
            for b in notbrokers:
                self.__notbrokers.append(b)
        else:
            self.__notbrokers.append(notbrokers)

    def set_dry(self, *, dry: bool) -> None:
        """Set the dry run flag."""
        self.__dry = dry

    def set_holdings(self, *, holdings: bool) -> None:
        """Set the holdings flag."""
        self.__holdings = holdings

    def set_logged_in(self, logged_in: "Brokerage", broker: str) -> None:
        """Set the logged in brokerage object for a specific broker."""
        self.__logged_in[broker] = logged_in

    def get_action(self) -> str:
        """Get the action to be performed (buy/sell)."""
        return self.__action

    def get_amount(self) -> float:
        """Get the amount of shares to buy/sell."""
        return self.__amount

    def get_stocks(self) -> list[str]:
        """Get the list of stock tickers to buy/sell."""
        return self.__stock

    def get_time(self) -> str:
        """Get the time in force for the order."""
        return self.__time

    def get_price(self) -> str | float:
        """Get the price for the order."""
        return self.__price

    def get_brokers(self) -> list[BrokerInfo]:
        """Get the list of brokers to use."""
        return self.__brokers

    def get_notbrokers(self) -> list[BrokerInfo]:
        """Get the list of brokers to not use."""
        return self.__notbrokers

    def get_dry(self) -> bool:
        """Get the dry run flag."""
        return self.__dry

    def get_holdings(self) -> bool:
        """Get the holdings flag."""
        return self.__holdings

    def get_logged_in(self, broker: str) -> "Brokerage":
        """Get the logged in brokerage object for a specific broker."""
        return self.__logged_in[broker]

    def de_dupe(self) -> None:
        """Remove duplicate entries from lists."""
        self.__stock = list(dict.fromkeys(self.__stock))
        self.__brokers = list(set(self.__brokers))
        self.__notbrokers = list(set(self.__notbrokers))

    def alphabetize(self) -> None:
        """Sort the stock, brokers, and notbrokers lists if enabled."""
        if SORT_BROKERS:
            self.__stock.sort()
            self.__brokers.sort(key=lambda x: x.name)
            self.__notbrokers.sort(key=lambda x: x.name)

    def order_validate(self, *, pre_login: bool = False) -> ValueError | None:
        """Validate that order object is properly configured."""
        # Check for required fields (doesn't apply to holdings)
        if not self.__holdings:
            # These checks were previously `is None`, but the fields
            # default to "" / 0.0 and are never None — so they never
            # fired and a blank action or a 0-share amount sailed
            # through. Check the actual invalid values instead.
            if not self.__action:
                msg = "Action must be set (buy or sell)"
                raise ValueError(msg)
            if self.__amount <= 0:
                msg = "Amount must be a positive number of shares"
                raise ValueError(msg)
            if len(self.__stock) == 0:
                msg = "Stock must be set"
                raise ValueError(msg)
        if len(self.__brokers) == 0:
            msg = "Brokers must be set"
            raise ValueError(msg)
        if len(self.__logged_in) == 0 and not pre_login:
            msg = "Logged In must be set"
            raise ValueError(msg)
        # Clean up lists
        self.de_dupe()
        self.alphabetize()
        # Remove notbrokers from brokers
        for b in self.__notbrokers:
            if b in self.__brokers:
                self.__brokers.remove(b)
        return None

    def __str__(self) -> str:
        """Return a string representation of the order."""
        return f"Self: \n \
                Action: {self.__action}\n \
                Amount: {self.__amount}\n \
                Stock: {self.__stock}\n \
                Time: {self.__time}\n \
                Price: {self.__price}\n \
                Brokers: {','.join(str(b.name) for b in self.__brokers)}\n \
                Not Brokers: {','.join(str(b.name) for b in self.__notbrokers)}\n \
                Dry: {self.__dry}\n \
                Holdings: {self.__holdings}\n \
                Logged In: {self.__logged_in}"


T = TypeVar("T")


class Brokerage:
    """Object representing all logins and accounts at a brokerage."""

    def __init__(self, name: str) -> None:
        """Initialize a brokerage."""
        self.__name: str = name  # Name of brokerage
        self.__account_numbers: dict[
            str,
            list[str],
        ] = {}  # Dictionary of account names and numbers under parent
        self.__logged_in_objects: dict[
            str,
            Any,
        ] = {}  # Dictionary of logged in objects under parent
        self.__holdings: dict = {}  # Dictionary of holdings under parent
        self.__account_totals: dict = {}  # Dictionary of account totals
        self.__account_types: dict = {}  # Dictionary of account types

    def set_name(self, name: str) -> None:
        """Set the name of the brokerage."""
        self.__name = name

    def set_account_number(self, parent_name: str, account_number: str) -> None:
        """Set the account number for a specific parent."""
        if parent_name not in self.__account_numbers:
            self.__account_numbers[parent_name] = []
        self.__account_numbers[parent_name].append(account_number)

    def set_logged_in_object(
        self,
        parent_name: str,
        logged_in_object: object,
        account_name: str | None = None,
    ) -> None:
        """Set the logged in object for a specific account. If setting multiple, set account_name to retrieve them later."""
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
    ) -> None:
        """Set the holdings for a specific account."""
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
                key=operator.itemgetter(0),
            ),
        )

    def set_account_totals(
        self,
        parent_name: str,
        account_name: str,
        total: str | float,
    ) -> None:
        """Set the account totals for a specific account."""
        if isinstance(total, str):
            total = total.replace(",", "").replace("$", "").strip()
        if parent_name not in self.__account_totals:
            self.__account_totals[parent_name] = {}
        self.__account_totals[parent_name][account_name] = round(float(total), 2)
        self.__account_totals[parent_name]["total"] = sum(value for key, value in self.__account_totals[parent_name].items() if key != "total")

    def set_account_type(
        self,
        parent_name: str,
        account_name: str,
        account_type: str,
    ) -> None:
        """Set the account type for a specific account."""
        if parent_name not in self.__account_types:
            self.__account_types[parent_name] = {}
        self.__account_types[parent_name][account_name] = account_type

    def get_name(self) -> str:
        """Get the name of the brokerage."""
        return self.__name

    def get_account_numbers(self, parent_name: str | None = None) -> list | dict:
        """Get the account numbers for a specific parent."""
        if parent_name is None:
            return self.__account_numbers
        return self.__account_numbers.get(parent_name, [])

    def get_logged_in_objects(
        self,
        parent_name: str | None = None,
        account_name: str | None = None,
    ) -> object:
        """Get the logged in object for a specific account."""
        if parent_name is None:
            return self.__logged_in_objects
        if account_name is None:
            return self.__logged_in_objects.get(parent_name, {})
        return self.__logged_in_objects.get(parent_name, {}).get(account_name, {})

    def get_holdings(
        self,
        parent_name: str | None = None,
        account_name: str | None = None,
    ) -> dict:
        """Get the holdings for a specific account."""
        if parent_name is None:
            return self.__holdings
        if account_name is None:
            return self.__holdings.get(parent_name, {})
        return self.__holdings.get(parent_name, {}).get(account_name, {})

    def get_account_totals(
        self,
        parent_name: str | None = None,
        account_name: str | None = None,
    ) -> dict:
        """Get the account totals for a specific account."""
        if parent_name is None:
            return self.__account_totals
        if account_name is None:
            return self.__account_totals.get(parent_name, {})
        return self.__account_totals.get(parent_name, {}).get(account_name, 0)

    def get_account_types(
        self,
        parent_name: str | None = None,
        account_name: str | None = None,
    ) -> dict:
        """Get the account types for a specific account."""
        if account_name is None:
            return self.__account_types.get(parent_name, {})
        return self.__account_types.get(parent_name, {}).get(account_name, "")

    def __str__(self) -> str:
        """Return string representation of brokerage object."""
        return textwrap.dedent(
            f"""
            Brokerage: {self.__name}
            Account Numbers: {self.__account_numbers}
            Logged In Objects: {self.__logged_in_objects}
            Holdings: {self.__holdings}
            Account Totals: {self.__account_totals}
            Account Types: {self.__account_types}
        """,
        )


class ThreadHandler:
    """Thread manager for running brokerage functions."""

    def __init__(self, func: Callable, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Initialize the thread handler."""
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.queue: Queue[tuple[Any | None, str | None]] = Queue()
        # Daemon so a wedged broker (e.g. a browser order stuck after
        # hours) can never block interpreter/scheduler exit.
        self.thread = Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            result = self.func(*self.args, **self.kwargs)
            self.queue.put((result, None))
        except Exception as e:
            traceback.print_exc()
            self.queue.put((None, str(e)))

    def start(self) -> None:
        """Start the thread."""
        self.thread.start()

    def join(self, timeout: float | None = None) -> None:
        """Wait for the thread to finish (optionally bounded)."""
        self.thread.join(timeout)

    def is_alive(self) -> bool:
        """Return True if the worker is still running (timed-out join)."""
        return self.thread.is_alive()

    def get_result(self) -> tuple[Any | None, str | None]:
        """Get the result from the thread."""
        return self.queue.get()


def is_up_to_date() -> None:
    """Check if the current version is up to date."""
    response = requests.get("https://pypi.org/pypi/auto_rsa_bot/json", timeout=10)
    if not response.ok:
        print(f"Error checking for update: {response.status_code}")
        return
    version: str = response.json()["info"]["version"]
    parts = version.split(".")
    if (int(parts[0]), int(parts[1]), int(parts[2])) > tuple(
        map(int, CURRENT_RSA_VERSION.split(".")),
    ):
        print(f"Error: A new version of auto_rsa_bot is available ({version}). Please update to the latest version.")
        return


def type_slowly(element: WebElement, string: str, delay: float = 0.3) -> None:
    """Type text into a web element slowly."""
    # Type slower
    for character in string:
        element.send_keys(character)
        sleep(delay)


def check_if_page_loaded(driver: webdriver.Chrome) -> bool:
    """Check if the page is fully loaded."""
    readystate = str(driver.execute_script("return document.readyState;"))
    return readystate == "complete"


def get_selenium_driver(
    *,
    docker_mode: bool = False,
    user_data_dir: str | None = None,
) -> webdriver.Chrome | None:
    """Initialize a Selenium WebDriver.

    ``user_data_dir`` (opt-in) points Chrome at a persistent profile so
    a broker's "remember this device" cookie survives between runs and
    later logins skip 2FA. Omitted (None) -> a fresh ephemeral profile,
    exactly the previous behavior (Tornado etc. unchanged).
    """
    # Init webdriver options
    try:
        options = webdriver.ChromeOptions()
        if user_data_dir:
            # Best-effort: clear a stale singleton lock from a crashed
            # prior run so Chrome will reopen (not wipe) the profile.
            udd = Path(user_data_dir)
            udd.mkdir(parents=True, exist_ok=True)
            for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                with contextlib.suppress(OSError):
                    (udd / lock).unlink(missing_ok=True)
            options.add_argument(f"--user-data-dir={udd.resolve()}")
        options.add_argument("start-maximized")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        # NOTE: do NOT set the "useAutomationExtension" experimental option.
        # It is removed in modern Chrome/chromedriver and, on Chrome 115+,
        # destabilizes the session ("invalid session id: browser has closed
        # the connection / not connected to DevTools").
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-notifications")
        options.add_argument("--log-level=3")
        # Stability flags for the "DevTools disconnected / renderer crashed"
        # failure class on recent Chrome with Selenium.
        options.add_argument("--remote-allow-origins=*")
        options.add_argument("--disable-dev-shm-usage")
        if docker_mode:
            # Special Docker options
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-gpu")
        if docker_mode or HEADLESS:
            options.add_argument("--headless")
        driver = webdriver.Chrome(
            options=options,
            # Docker uses specific chromedriver installed via apt
            service=ChromiumService("/usr/bin/chromedriver") if docker_mode else None,
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


def kill_all_selenium_drivers(broker_obj: Brokerage) -> None:
    """Kill all selenium drivers on the given brokerage object."""
    count = 0
    if broker_obj is not None:
        for key in broker_obj.get_account_numbers():
            print(f"Killing driver for {key}")
            driver = broker_obj.get_logged_in_objects(key)
            if driver is not None and isinstance(driver, webdriver.Chrome):
                driver.close()
                driver.quit()
                count += 1
        if count > 0:
            print(f"Killed {count} {broker_obj.get_name()} drivers")


def total_embed_length(embed: EmbedType) -> int:
    """Get the total length of an embed (title + fields)."""
    fields = [embed["title"]]
    fields.extend([field["name"] for field in embed["fields"]])
    fields.extend([field["value"] for field in embed["fields"]])
    return sum(len(field) for field in fields)


def split_embed(embed: EmbedType) -> list[EmbedType]:
    """Split an embed into smaller chunks."""
    max_embed_length = 6000
    max_embed_fields = 25
    # Split embed into chunks if too long
    chunks = []
    current_embed = cast(
        "EmbedType",
        {key: value for key, value in embed.items() if key != "fields"},
    )
    current_embed["fields"] = []
    current_length = total_embed_length(current_embed)
    for field in embed["fields"]:
        field_length = len(field["name"]) + len(field["value"])
        if (current_length + field_length > max_embed_length) or (len(current_embed["fields"]) >= max_embed_fields):
            chunks.append(current_embed)
            current_embed = cast(
                "EmbedType",
                {key: value for key, value in embed.items() if key != "fields"},
            )
            current_embed["fields"] = []
            current_length = total_embed_length(current_embed)
        current_embed["fields"].append(field)
        current_length += field_length
    chunks.append(current_embed)
    return chunks


async def process_discord_messages(
    message: EmbedType | str,
    *,
    embed: bool = False,
) -> None:
    """Send messages to Discord."""
    # Send message to discord via request post
    headers = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "Content-Type": "application/json",
    }
    # Split into chunks if needed
    full_embed = split_embed(cast("EmbedType", message)) if embed else cast("NonEmbedType", [{"content": message, "embeds": []}])
    for embed_chunk in full_embed:
        payload = {
            "content": "" if embed else message,
            "embeds": [embed_chunk] if embed else [],
        }
        # Keep trying until success
        success = False
        while success is False:
            try:
                response = requests.post(  # noqa: ASYNC210
                    DISCORD_MESSAGES_URL,
                    headers=headers,
                    json=payload,
                    timeout=10,
                )
                # Process response
                if response.ok:
                    success = True
                elif response.status_code == 429:  # noqa: PLR2004
                    rate_limit = response.json()["retry_after"] * 2
                    await asyncio.sleep(rate_limit)
                else:
                    print(f"Error: {response.status_code}: {response.text}")
                    break
            except Exception as e:
                print(f"Error Sending Message: {e}")
                break
        await asyncio.sleep(0.5)


def account_allowed(broker_key: str, account: object, action: str = "") -> bool:
    """Return whether an order may touch this sub-account.

    Driven by the ``RSA_ACCOUNT_FILTER`` env var, a JSON map of
    ``{"<broker_key>": ["<mask>", ...]}``. Semantics, chosen for safety
    and to match the existing ``SCHWAB_ACCOUNT_NUMBERS`` convention:

    * unset/blank/unparseable filter -> allowed (today's behavior).
    * a broker absent from the map -> unrestricted (all its accounts).
    * a broker present -> only its listed accounts; an explicitly empty
      list means trade nothing for that broker.
    * sells are never filtered, so liquidation always reaches every
      account regardless of the buy allow-list.

    Matching is digit-normalized so a last-4 mask reconciles against a
    full account number.
    """
    if action and action.lower() == "sell":
        return True
    raw = os.getenv("RSA_ACCOUNT_FILTER", "").strip()
    if not raw:
        return True
    try:
        filt = json.loads(raw)
    except (ValueError, TypeError):
        return True
    bkey = str(broker_key).lower()
    if not isinstance(filt, dict) or bkey not in filt:
        return True
    wanted = filt.get(bkey) or []
    acct = re.sub(r"\D", "", str(account))
    for want in wanted:
        wdig = re.sub(r"\D", "", str(want))
        if wdig and (acct == wdig or acct.endswith(wdig)):
            return True
    return False


# Per-broker sub-account usage for the current run, enforcing a Friend
# tier's "1 account per broker" cap. Reset at the start of every run via
# reset_subaccount_caps() (fun_run / fun_run_parallel). Guarded because a
# parallel run reserves across broker threads concurrently.
_SUBACCT_LOCK = Lock()
_SUBACCT_USED: dict[str, int] = {}


def reset_subaccount_caps() -> None:
    """Clear the per-broker sub-account counters (call at run start)."""
    with _SUBACCT_LOCK:
        _SUBACCT_USED.clear()


def _subaccount_cap_for_run() -> int | None:
    """Accounts-per-broker cap for the active license tier (None = off)."""
    try:
        from src.license import subaccount_cap  # noqa: PLC0415

        return subaccount_cap()
    except Exception:
        return None


def reserve_or_skip(  # noqa: PLR0913
    *,
    broker_key: str,
    account: object,
    ticker: str,
    order_obj: "StockOrder",
    display_label: str = "",
    loop: asyncio.AbstractEventLoop | None = None,
) -> "Play | None":  # noqa: F821  -- Play imported lazily to avoid circular
    """Apply the C1 + C2 real-money guards before an order is placed.

    Returns the :class:`Play` to pass to :func:`complete_or_fail` once
    the order attempt resolves, or ``None`` if the order must be
    skipped (filter excluded, or ledger says already executed). The
    caller MUST honor a ``None`` return with ``continue``.

    Behavior:

    * **C2 — account filter**: if ``account_allowed(broker_key,
      account, order_obj.get_action())`` is False, prints a skip
      message and returns None.
    * **C1 — ledger intent reservation**: builds a :class:`Play` with
      the per-source ``RSA_PLAY_KEY`` and economic ``RSA_PLAY_SPLIT_KEY``
      (so cross-feed dedupe works across producers). On a real run,
      ``record_intent`` is called; if it returns False (already
      EXECUTED, INTENDED, or economic split already filled), prints a
      skip message and returns None. Dry runs bypass the ledger
      reservation but still honor the filter.

    Display label defaults to the broker's title-cased key + masked
    account so log lines remain consistent across brokers.
    """
    from src.ledger import Play, record_intent  # noqa: PLC0415

    action = order_obj.get_action()
    label = display_label or f"{broker_key.title()} account {mask_string(str(account))}"
    if not account_allowed(broker_key, account, action):
        print_and_discord(
            f"{label}: skipped {ticker} (not in account filter)",
            loop,
        )
        return None
    # Friend-tier per-broker account cap: only the first N accounts of a
    # broker may trade per run. Reserve the slot optimistically (so a
    # parallel run's threads can't both pass), and release it below if the
    # order turns out to be a ledger dedup skip (it didn't actually trade).
    bkey = broker_key.lower()
    subacct_cap = _subaccount_cap_for_run()
    slot_taken = False
    if subacct_cap is not None:
        over_cap = False
        with _SUBACCT_LOCK:
            used = _SUBACCT_USED.get(bkey, 0)
            if used >= subacct_cap:
                over_cap = True
            else:
                _SUBACCT_USED[bkey] = used + 1
                slot_taken = True
        # Log OUTSIDE the lock (print_and_discord may do I/O).
        if over_cap:
            print_and_discord(
                f"{label}: skipped {ticker} — this license allows "
                f"{subacct_cap} account per broker; not trading additional "
                f"{broker_key} accounts this run.",
                loop,
            )
            return None
    # A MANUAL trade is scoped to the CURRENT DAY so the double-buy guard
    # only stops an accidental same-day re-run — it does NOT lock a ticker
    # forever. You can buy the same stock again on another day (or after a
    # second reverse split) with no reset. A SIGNAL run keeps its own
    # economic RSA_PLAY_KEY (unchanged) so cross-feed dedupe still holds.
    manual_day = datetime.datetime.now(get_local_timezone()).date().isoformat()
    play = Play(
        key=os.getenv("RSA_PLAY_KEY")
        or f"MANUAL:{ticker}:{action.lower()}:{manual_day}",
        broker=broker_key,
        account=str(account),
        ticker=ticker,
        action=action,
        split_key=os.getenv("RSA_PLAY_SPLIT_KEY", ""),
    )
    if not order_obj.get_dry() and not record_intent(
        play, order_obj.get_amount(),
    ):
        # Dedup skip — this account did NOT place an order, so give its
        # sub-account slot back (it shouldn't count against the cap).
        if slot_taken:
            with _SUBACCT_LOCK:
                _SUBACCT_USED[bkey] = max(0, _SUBACCT_USED.get(bkey, 1) - 1)
        print_and_discord(
            f"{label}: skipped {ticker} — already recorded as "
            f"{action.lower()} today (double-buy guard). To {action.lower()} "
            f"it again, reset {ticker} in the app (Trade tab → 'Having "
            f"trouble re-trading a stock?', or the Ledger tab), then re-run.",
            loop,
        )
        return None
    return play


def complete_or_fail(
    play: "Play",  # noqa: F821  -- Play imported lazily to avoid circular
    *,
    order_obj: "StockOrder",
    success: bool,
    detail: str = "",
) -> None:
    """Apply the C1-post guard: record the outcome in the ledger.

    No-op for dry runs (matching :func:`reserve_or_skip` semantics
    where dry runs never wrote an INTENDED row). Idempotent — calling
    it twice for the same play is harmless because :func:`mark_result`
    is itself idempotent on the INTENDED → EXECUTED|FAILED transition.
    """
    from src.ledger import mark_result  # noqa: PLC0415

    if order_obj.get_dry():
        return
    mark_result(play, success=success, detail=str(detail or ""))


def record_fill(
    play: "Play",  # noqa: F821  -- Play imported lazily to avoid circular
    *,
    order_obj: "StockOrder",
    result: object,
    source: str = "inline",
) -> str:
    """Record a VERIFIED fill outcome (a FillResult) in the ledger.

    The fill-aware companion to :func:`complete_or_fail`: instead of a
    coarse success/fail, it records the exact
    :class:`~src.brokerages.fill_result.FillState`, so an accepted-but-
    unfilled order lands as PENDING (blocking, not a fill) rather than
    EXECUTED. No-op for dry runs, matching :func:`complete_or_fail`.
    Returns the ledger status written (empty string on a dry run).
    """
    from src.ledger import mark_fill  # noqa: PLC0415

    if order_obj.get_dry():
        return ""
    return mark_fill(play, result, source=source)


def print_and_discord(
    message: str | EmbedType,
    loop: asyncio.AbstractEventLoop | None = None,
    *,
    embed: bool = False,
) -> None:
    """Print message to console and send over Discord."""
    # Print message
    if not embed:
        print(message)
    # Add message to discord queue
    if loop is not None:
        task_queue.put((message, embed))
        if task_queue.qsize() == 1:
            asyncio.run_coroutine_threadsafe(process_queue(), loop)


async def process_queue() -> None:
    """Process the discord queue."""
    while not task_queue.empty():
        message, embed = task_queue.get()
        await process_discord_messages(message, embed=embed)
        task_queue.task_done()


async def get_otp_from_discord(
    bot_obj: commands.Bot,
    broker_name: str,
    code_len: int = 6,
    timeout: int = 60,  # noqa: ASYNC109
    loop: asyncio.AbstractEventLoop | None = None,
) -> str | None:
    """Wait for a user-input OTP code from Discord."""
    print_and_discord(f"{broker_name} requires OTP code", loop)
    print_and_discord(
        f"Please enter OTP code or type cancel within {timeout} seconds",
        loop,
    )
    # Get OTP code from Discord
    while True:
        try:
            code = await bot_obj.wait_for(
                "message",
                # Ignore bot messages and messages not in the correct channel
                check=lambda m: m.author != bot_obj.user and m.channel.id == int(os.environ["DISCORD_CHANNEL"]),
                timeout=timeout,
            )
        except TimeoutError:
            print_and_discord(
                f"Timed out waiting for OTP code input for {broker_name}",
                loop,
            )
            return None
        if code.content.lower() == "cancel":
            print_and_discord(f"Cancelling OTP code for {broker_name}", loop)
            return None
        try:
            # Check if code is numbers only
            int(code.content)
        except ValueError:
            print_and_discord("OTP code must be numbers only", loop)
            continue
        # Check if code is correct length
        if len(code.content) != code_len:
            print_and_discord(f"OTP code must be {code_len} digits", loop)
            continue
        return str(code.content)


async def get_input_from_discord(
    bot_obj: commands.Bot,
    prompt: str,
    timeout: int = 60,  # noqa: ASYNC109
    loop: asyncio.AbstractEventLoop | None = None,
) -> str | None:
    """Wait for user input from Discord."""
    print_and_discord(prompt, loop)
    print_and_discord(
        f"Please enter the input or type cancel within {timeout} seconds",
        loop,
    )
    try:
        code = await bot_obj.wait_for(
            "message",
            check=lambda m: m.author != bot_obj.user and m.channel.id == int(DISCORD_CHANNEL),
            timeout=timeout,
        )
    except TimeoutError:
        print_and_discord("Timed out waiting for input", loop)
        return None
    if code.content.lower() == "cancel":
        print_and_discord("Input canceled by user", loop)
        return None
    return str(code.content)


async def send_captcha_to_discord(file: BytesIO) -> None:
    """Send CAPTCHA image to Discord."""
    headers = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
    }
    files = {"file": ("captcha.png", file, "image/png")}
    success = False
    while not success:
        response = requests.post(  # noqa: ASYNC210
            DISCORD_MESSAGES_URL,
            headers=headers,
            files=files,
            timeout=10,
        )
        if response.ok:
            success = True
        elif response.status_code == 429:  # noqa: PLR2004
            rate_limit = response.json()["retry_after"] * 2
            await asyncio.sleep(rate_limit)
        else:
            print(
                f"Error sending CAPTCHA image: {response.status_code}: {response.text}",
            )
            break


def mask_string(string: str, num_visible: int = 4) -> str:
    """Mask account string (12345678 -> xxxx5678)."""
    string = str(string)
    if len(string) < num_visible:
        return string
    return "x" * (len(string) - num_visible) + string[-num_visible:]


def _emit_discovered_account(
    broker_name: str, parent: str, account: object,
) -> None:
    r"""Emit a sentinel line so the GUI can persist a discovered sub-account.

    Only active inside the GUI engine subprocess (RSA_GUI_ENGINE=1) so
    CLI/Docker output stays clean. The broker name is normalized to the
    canonical key the GUI uses (e.g. "WELLSFARGO" -> "wellsfargo"); the
    parent login (e.g. "Fidelity 1") is kept so the picker can group by
    login. The parent runner parses these; the engine can't touch the
    vault. Format: ``<SENTINEL><broker>\t<parent>\t<account>``.
    """
    if os.getenv("RSA_GUI_ENGINE") != "1":
        return
    broker_key = re.sub(r"\W", "", str(broker_name)).lower()
    parent_clean = str(parent).replace("\t", " ").replace("\n", " ").strip()
    acct = str(account)
    if not broker_key or not acct:
        return
    try:
        from src.gui.core.engine_proc import ACCOUNT_SENTINEL  # noqa: PLC0415

        # Single atomic write (see _emit_progress) so a concurrent broker
        # in a parallel run can't split this sentinel line.
        sys.stdout.write(f"{ACCOUNT_SENTINEL}{broker_key}\t{parent_clean}\t{acct}\n")
        sys.stdout.flush()
    except Exception as exc:  # discovery is best-effort
        print(f"(account discovery skipped for {broker_key}: {exc})")


def _emit_holding(
    broker_name: str,
    parent: object,
    account: object,
    stock: str,
    quantity: float,
    price: float,
    total: float,
) -> None:
    r"""Emit one structured position line for the GUI to capture.

    Only active inside the GUI engine subprocess (RSA_GUI_ENGINE=1) so
    CLI/Docker output stays clean. Lets the GUI build a real holdings
    table and reconcile positions against the execution ledger. Format:
    ``<SENTINEL><broker>\t<parent>\t<account>\t<stock>\t<qty>\t<price>\t<total>``.
    Best-effort — a formatting error never breaks the holdings printout.
    """
    if os.getenv("RSA_GUI_ENGINE") != "1":
        return
    broker_key = re.sub(r"\W", "", str(broker_name)).lower()
    stock_clean = str(stock).replace("\t", " ").replace("\n", " ").strip()
    if not broker_key or not stock_clean:
        return

    def _clean(v: object) -> str:
        return str(v).replace("\t", " ").replace("\n", " ").strip()

    try:
        from src.gui.core.engine_proc import HOLDINGS_SENTINEL  # noqa: PLC0415

        # Single atomic write (see _emit_progress) so a concurrent broker
        # in a parallel run can't split this sentinel line.
        sys.stdout.write(
            f"{HOLDINGS_SENTINEL}{broker_key}\t{_clean(parent)}\t"
            f"{_clean(account)}\t{stock_clean}\t{float(quantity)}\t"
            f"{float(price)}\t{float(total)}\n",
        )
        sys.stdout.flush()
    except Exception as exc:  # holdings capture is best-effort
        print(f"(holdings capture skipped for {broker_key}: {exc})")


def print_all_holdings(
    broker_obj: Brokerage,
    loop: asyncio.AbstractEventLoop | None = None,
    *,
    mask_account_number: bool = True,
) -> None:
    """Format and display holdings information."""
    embed: EmbedType = {
        "title": f"{broker_obj.get_name()} Holdings",
        "color": 3447003,
        "fields": [],
    }
    print(
        f"\n==============================\n{broker_obj.get_name()} Holdings\n==============================",
    )
    for key in broker_obj.get_account_numbers():
        for account in broker_obj.get_account_numbers(key):
            _emit_discovered_account(broker_obj.get_name(), key, account)
            acc_name = f"{key} ({mask_string(account) if mask_account_number else account})"
            field: EmbedFieldType = {
                "name": acc_name,
                "inline": False,
                "value": "",
            }
            print(acc_name)
            print_string = ""
            holdings = broker_obj.get_holdings(key, account)
            if holdings == {}:
                print_string += "No holdings in Account\n"
            else:
                for stock in holdings:
                    quantity = holdings[stock]["quantity"]
                    price = holdings[stock]["price"]
                    total = holdings[stock]["total"]
                    print_string += f"{stock}: {quantity} @ ${format(price, '0.2f')} = ${format(total, '0.2f')}\n"
                    _emit_holding(
                        broker_obj.get_name(), key, account,
                        stock, quantity, price, total,
                    )
            account_total = float(broker_obj.get_account_totals(key, account) or 0)
            print_string += f"Total: ${format(account_total, '0.2f')}\n"
            # Emit the account total too, so the GUI can derive cash
            # (cash = account total - sum of position values) and show a
            # per-account cash figure. A synthetic stock marker keeps the
            # sentinel format unchanged; the GUI filters it from the ticker
            # table. Best-effort, GUI-engine only.
            _emit_holding(
                broker_obj.get_name(), key, account,
                "__ACCOUNT_TOTAL__", 1, account_total, account_total,
            )
            print(print_string)
            # If somehow longer than 1024, chop and add ...
            max_length = 1024
            field["value"] = str(
                print_string[:1020] + "..." if len(print_string) > max_length else print_string,
            )
            embed["fields"].append(field)
    print_and_discord(embed, loop, embed=True)
    print("==============================")


def get_local_timezone() -> datetime.tzinfo:
    """Return the local timezone."""
    return datetime.datetime.now().astimezone().tzinfo or datetime.UTC
