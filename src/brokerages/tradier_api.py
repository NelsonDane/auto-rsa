# Nelson Dane
# Tradier API

import json
import os
import traceback
from asyncio import AbstractEventLoop
from time import sleep
from typing import cast

import requests
from dotenv import load_dotenv

from src.helper_api import Brokerage, StockOrder, mask_string, print_all_holdings, print_and_discord

TRADIER_ENDPOINT = "https://api.tradier.com/v1"


def make_request(endpoint: str, bearer_token: str, data: dict[str, str] | None = None, params: dict[str, str] | None = None, method: str = "GET") -> dict | None:
    """Build Tradier API requests."""
    timeout = 10
    try:
        if method == "GET":
            response = requests.get(
                f"{TRADIER_ENDPOINT}{endpoint}",
                data=data,
                params=params,
                headers={
                    "Authorization": f"Bearer {bearer_token}",
                    "Accept": "application/json",
                },
                timeout=timeout,
            )
        elif method == "POST":
            response = requests.post(
                f"{TRADIER_ENDPOINT}{endpoint}",
                data=data,
                params=params,
                headers={
                    "Authorization": f"Bearer {bearer_token}",
                    "Accept": "application/json",
                },
                timeout=timeout,
            )
        else:
            msg = f"Invalid method: {method}"
            raise Exception(msg)
        if not response.ok:
            msg = f"Error making request to Tradier API {endpoint}: {response.text}"
            raise Exception(msg)
        json_response = response.json()
        if json_response.get("fault") and json_response["fault"].get("faultstring"):
            raise Exception(json_response["fault"]["faultstring"])
        sleep(0.1)
    except Exception as e:
        print(f"Error making request to Tradier API {endpoint}: {e}")
        print(f"Response: {response}")
        print(traceback.format_exc())
        sleep(1)
        return None
    else:
        return json_response


def tradier_init() -> Brokerage | None:
    """Initialize Tradier API client."""
    # Initialize .env file
    load_dotenv()
    # Import Tradier account
    if not os.getenv("TRADIER"):
        print("Tradier not found, skipping...")
        return None
    # Get access token and split into list
    accounts = os.environ["TRADIER"].strip().split(",")
    # Login to each account
    tradier_obj = Brokerage("Tradier")
    print("Logging in to Tradier...")
    for account in accounts:
        name = f"Tradier {accounts.index(account) + 1}"
        json_response = make_request("/user/profile", account)
        if json_response is None:
            continue
        # Multiple accounts have different JSON structure
        account_num = 1 if "'account': {'" in str(json_response) else len(json_response["profile"]["account"])
        print(f"Tradier accounts found: {account_num}")
        for x in range(account_num):
            if account_num == 1:
                an = json_response["profile"]["account"]["account_number"]
                at = json_response["profile"]["account"]["type"]
                a_status = json_response["profile"]["account"]["status"]
            else:
                an = json_response["profile"]["account"][x]["account_number"]
                at = json_response["profile"]["account"][x]["type"]
                a_status = json_response["profile"]["account"][x]["status"]
            if a_status != "active":
                print(f"Ignoring {mask_string(an)}: {a_status}")
                continue
            print(mask_string(an))
            tradier_obj.set_account_number(name, an)
            tradier_obj.set_account_type(name, an, at)
            # Get balances
            json_balances = make_request(f"/accounts/{an}/balances", account)
            if json_balances is None:
                tradier_obj.set_account_totals(name, an, 0)
                continue
            tradier_obj.set_account_totals(
                name,
                an,
                json_balances["balances"]["total_equity"],
            )
        # Get balances
        tradier_obj.set_logged_in_object(name, account)
    print("Logged in to Tradier!")
    return tradier_obj


def tradier_holdings(tradier_o: Brokerage, loop: AbstractEventLoop | None = None) -> None:  # noqa: C901
    """Retrieve and display all Tradier account holdings."""
    # Loop through accounts
    for key in tradier_o.get_account_numbers():
        obj = cast("str", tradier_o.get_logged_in_objects(key))
        for account_number in tradier_o.get_account_numbers(key):
            try:
                # Get holdings from API
                json_response = make_request(
                    f"/accounts/{account_number}/positions",
                    obj,
                )
                if json_response is None:
                    continue
                stocks: list[str] = []
                amounts = []
                # Check if there are no holdings
                if json_response["positions"] == "null":
                    continue
                # Check if there's only one holding
                if "symbol" in json_response["positions"]["position"]:
                    stocks.append(json_response["positions"]["position"]["symbol"])
                    amounts.append(json_response["positions"]["position"]["quantity"])
                else:
                    # Loop through holdings
                    for stock in json_response["positions"]["position"]:
                        stocks.append(stock["symbol"])
                        amounts.append(stock["quantity"])
                # Get current price of each stock
                current_price: list[float] = []
                for sym in stocks:
                    price_response = make_request(
                        "/markets/quotes",
                        obj,
                        params={"symbols": sym, "greeks": "false"},
                    )
                    if price_response is None or price_response["quotes"].get("quote") is None or price_response["quotes"]["quote"].get("last") is None:
                        current_price.append(0)
                    else:
                        current_price.append(price_response["quotes"]["quote"]["last"])
                # Print and send them
                for position in stocks:
                    # Set index for easy use
                    i = stocks.index(position)
                    tradier_o.set_holdings(
                        key,
                        account_number,
                        position,
                        amounts[i],
                        current_price[i],
                    )
            except Exception as e:
                print_and_discord(f"{key}: Error getting holdings: {e}", loop=loop)
                print(traceback.format_exc())
                continue
    print_all_holdings(tradier_o, loop=loop)


def tradier_transaction(tradier_o: Brokerage, order_obj: StockOrder, loop: AbstractEventLoop | None = None) -> None:
    """Handle Tradier API transactions."""
    print()
    print("==============================")
    print("Tradier")
    print("==============================")
    print()
    # Loop through accounts
    for s in order_obj.get_stocks():
        for key in tradier_o.get_account_numbers():
            print_and_discord(
                f"{key}: {order_obj.get_action()}ing {order_obj.get_amount()} of {s}",
                loop=loop,
            )
            obj = cast("str", tradier_o.get_logged_in_objects(key))
            for account in tradier_o.get_account_numbers(key):
                print_account = mask_string(account)
                # Tradier doesn't support fractional shares
                if not order_obj.get_amount().is_integer():
                    print_and_discord(
                        f"Tradier account {print_account} Error: Fractional share {order_obj.get_amount()} not supported",
                        loop=loop,
                    )
                    continue
                if not order_obj.get_dry():
                    try:
                        data = {
                            "class": "equity",
                            "symbol": s,
                            "side": order_obj.get_action(),
                            "quantity": str(order_obj.get_amount()),
                            "type": "market",
                            "duration": "day",
                        }
                        json_response = make_request(
                            f"/accounts/{account}/orders",
                            obj,
                            data=data,
                            method="POST",
                        )
                        if json_response is None:
                            print_and_discord(
                                f"Tradier account {print_account} Error: JSON response is None",
                                loop=loop,
                            )
                            continue
                        if json_response.get("order", {}).get("status") is not None:
                            print_and_discord(
                                f"Tradier account {print_account}: {order_obj.get_action()} {order_obj.get_amount()} of {s}: {json_response['order']['status']}",
                                loop=loop,
                            )
                            continue
                        print_and_discord(
                            f"Tradier account {print_account} Error: This order did not route. JSON response: {json.dumps(json_response, indent=2)}",
                            loop=loop,
                        )
                    except Exception as e:
                        print_and_discord(
                            f"Tradier account {print_account} Error: {e}",
                            loop=loop,
                        )
                        print(traceback.format_exc())
                        print(f"JSON response: {json.dumps(json_response, indent=2)}")
                        continue
                else:
                    print_and_discord(
                        f"Tradier account {print_account}: Running in DRY mode. Trasaction would've been: {order_obj.get_action()} {order_obj.get_amount()} of {s}",
                        loop=loop,
                    )
