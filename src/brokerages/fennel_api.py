import asyncio
import os
import time
import traceback
from typing import cast

from discord.ext.commands import Bot
from dotenv import load_dotenv
from fennel_invest_api import Fennel

from src.helper_api import Brokerage, StockOrder, get_otp_from_discord, print_all_holdings, print_and_discord


def fennel_init(bot_obj: Bot | None = None, loop: asyncio.AbstractEventLoop | None = None) -> Brokerage | None:
    """Initialize Fennel API."""
    # Initialize .env file
    load_dotenv()
    # Import Fennel account
    fennel_obj = Brokerage("Fennel")
    if not os.getenv("FENNEL"):
        print("Fennel not found, skipping...")
        return None
    big_fennel = os.environ["FENNEL"].strip().split(",")
    # Log in to Fennel account
    print("Logging in to Fennel...")
    for index, account in enumerate(big_fennel):
        name = f"Fennel {index + 1}"
        try:
            try:
                fb = Fennel(filename=f"fennel{index + 1}.pkl", path="./creds/")
                if bot_obj is None or loop is None:
                    # Login from CLI
                    fb.login(
                        email=account,
                        wait_for_code=True,
                    )
                else:
                    # Login from Discord and check for 2fa required message
                    fb.login(
                        email=account,
                        wait_for_code=False,
                    )
            except Exception as e:
                if "2FA" in str(e) and bot_obj is not None and loop is not None:
                    # Sometimes codes take a long time to arrive
                    timeout = 300  # 5 minutes
                    otp_code = asyncio.run_coroutine_threadsafe(
                        get_otp_from_discord(bot_obj, name, timeout=timeout, loop=loop),
                        loop,
                    ).result()
                    if otp_code is None:
                        raise Exception("No OTP code found")
                    fb.login(
                        email=account,
                        wait_for_code=False,
                        code=otp_code,
                    )
                else:
                    raise
            fennel_obj.set_logged_in_object(name, fb, "fb")
            _wrap_market_open_retry(fb, label=name, loop=loop)
            try:
                full_accounts = fb.get_full_accounts()
            except AttributeError:
                account_ids = _get_account_ids_with_retry(fb, label=name, loop=loop)
                for account_index, account_id in enumerate(account_ids):
                    account_name = f"Account {account_index + 1}"
                    fennel_obj.set_account_number(name, account_name)
                    summary = _get_portfolio_summary_with_retry(fb, account_id, label=f"{name} {account_name}", loop=loop)
                    if summary is None:
                        print_and_discord(
                            f"{name} {account_name}: Unable to fetch portfolio summary, using 0 total",
                            loop,
                        )
                        total_cash = 0
                    else:
                        total_cash = summary["cash"]["balance"]["canTrade"]
                    fennel_obj.set_account_totals(
                        name,
                        account_name,
                        total_cash,
                    )
                    fennel_obj.set_logged_in_object(name, account_id, account_name)
                    print(f"Found {account_name}")
            else:
                for account_info in full_accounts:
                    fennel_obj.set_account_number(name, account_info["name"])
                    try:
                        total_cash = account_info["portfolio"]["cash"]["balance"]["canTrade"]
                    except KeyError:
                        print_and_discord(
                            f"{name} {account_info.get('name', 'Account')}: Unable to read portfolio summary, using 0 total",
                            loop,
                        )
                        total_cash = 0
                    fennel_obj.set_account_totals(
                        name,
                        account_info["name"],
                        total_cash,
                    )
                    fennel_obj.set_logged_in_object(name, account_info["id"], account_info["name"])
                    print(f"Found {account_info['name']}")
            print(f"{name}: Logged in")
        except Exception as e:
            print(f"Error logging into Fennel: {e}")
            print(traceback.format_exc())
            continue
    print("Logged into Fennel!")
    return fennel_obj


def _wrap_market_open_retry(
    obj: Fennel,
    *,
    label: str,
    retries: int = 3,
    delay: float = 1.5,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    original = obj.is_market_open

    def wrapped() -> bool:
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                result = original()
                if result is None:
                    raise Exception("Market open check returned no data")
                return bool(result)
            except Exception as exc:
                last_error = exc
                if attempt < retries - 1:
                    print_and_discord(
                        f"{label}: retrying market open check ({attempt + 2}/{retries}) after error: {exc}",
                        loop,
                    )
                    time.sleep(delay)
                    continue
                raise Exception(f"Market open check failed after {retries} attempts: {last_error}") from last_error
        return False

    obj.is_market_open = wrapped


def _place_order_with_retry(
    obj: Fennel,
    account_id: str,
    symbol: str,
    order_obj: StockOrder,
    *,
    label: str,
    retries: int = 3,
    delay: float = 5.0,
    loop: asyncio.AbstractEventLoop | None = None,
) -> dict:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return obj.place_order(
                account_id=account_id,
                ticker=symbol,
                quantity=order_obj.get_amount(),
                side=order_obj.get_action(),
                dry_run=order_obj.get_dry(),
            )
        except TypeError as exc:
            last_error = exc
        except Exception as exc:
            last_error = exc
            msg = str(exc)
            if "securityMarketInfo" not in msg and "Market Open Request failed" not in msg:
                raise
        if attempt < retries - 1:
            print_and_discord(
                f"{label}: retrying order for {symbol} ({attempt + 2}/{retries}) after error: {last_error}",
                loop,
            )
            time.sleep(delay)
            continue
        raise Exception(f"Fennel order failed after {retries} attempts: {last_error}") from last_error
    raise Exception("Fennel order failed unexpectedly")


def _get_account_ids_with_retry(
    obj: Fennel,
    *,
    label: str,
    retries: int = 3,
    delay: float = 5.0,
    loop: asyncio.AbstractEventLoop | None = None,
) -> list:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return obj.get_account_ids()
        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                print_and_discord(
                    f"{label}: retrying account IDs ({attempt + 2}/{retries}) after error: {exc}",
                    loop,
                )
                time.sleep(delay)
                continue
            raise Exception(f"Failed to retrieve Fennel account IDs after {retries} attempts: {last_error}") from last_error
    raise Exception("Failed to retrieve Fennel account IDs unexpectedly")


def _get_portfolio_summary_with_retry(
    obj: Fennel,
    account_id: str,
    *,
    label: str,
    retries: int = 3,
    delay: float = 5.0,
    loop: asyncio.AbstractEventLoop | None = None,
) -> dict | None:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return obj.get_portfolio_summary(account_id)
        except Exception as exc:
            last_error = exc
            if attempt < retries - 1:
                print_and_discord(
                    f"{label}: retrying portfolio summary ({attempt + 2}/{retries}) after error: {exc}",
                    loop,
                )
                time.sleep(delay)
                continue
            print(f"Error fetching Fennel portfolio summary for {account_id}: {last_error}")
            return None
    return None


def fennel_holdings(fbo: Brokerage, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Retrieve and display all Fennel account holdings."""
    for key in fbo.get_account_numbers():
        obj = cast("Fennel", fbo.get_logged_in_objects(key, "fb"))
        for account in fbo.get_account_numbers(key):
            try:
                # Get account holdings
                account_id = fbo.get_logged_in_objects(key, account)
                positions = obj.get_stock_holdings(account_id)
                if positions:
                    for holding in positions:
                        qty = holding["investment"]["ownedShares"]
                        if float(qty) == 0:
                            continue
                        sym = holding["security"]["ticker"]
                        price = holding["security"]["currentStockPrice"]
                        if price is None:
                            price = "N/A"
                        fbo.set_holdings(key, account, sym, qty, price)
            except Exception as e:
                print_and_discord(f"Error getting Fennel holdings: {e}")
                print(traceback.format_exc())
                continue
    print_all_holdings(fbo, loop, mask_account_number=False)


def fennel_transaction(fbo: Brokerage, order_obj: StockOrder, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Handle Fennel API transactions."""
    print()
    print("==============================")
    print("Fennel")
    print("==============================")
    print()
    for s in order_obj.get_stocks():
        for key in fbo.get_account_numbers():
            print_and_discord(
                f"{key}: {order_obj.get_action()}ing {order_obj.get_amount()} of {s}",
                loop,
            )
            for account in fbo.get_account_numbers(key):
                obj = cast("Fennel", fbo.get_logged_in_objects(key, "fb"))
                account_id = fbo.get_logged_in_objects(key, account)
                try:
                    order = _place_order_with_retry(
                        obj,
                        account_id,
                        s,
                        order_obj,
                        label=f"{key} {account}",
                        loop=loop,
                    )
                    if order_obj.get_dry():
                        message = "Dry Run Success"
                        if not order.get("dry_run_success", False):
                            message = "Dry Run Failed"
                    else:
                        message = "Success"
                        if order.get("data", {}).get("createOrder") != "pending":
                            message = order.get("data", {}).get("createOrder")
                    print_and_discord(
                        f"{key}: {order_obj.get_action()} {order_obj.get_amount()} of {s} in {account}: {message}",
                        loop,
                    )
                except Exception as e:
                    print_and_discord(f"{key} {account}: Error placing order: {e}", loop)
                    print(traceback.format_exc())
                    continue
