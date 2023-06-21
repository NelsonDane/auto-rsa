# Nelson Dane
# Tradier API

import asyncio
import os
import traceback

import requests
from dotenv import load_dotenv

class Tradier:
    def __init__(self, bearer, account_list):
        self.bearer = bearer
        self.account_list = account_list

    def __str__(self) -> str:
        return f"Tradier: {self.bearer}, {self.account_list}"
    

def load_accounts():
    # Initialize .env file
    load_dotenv()
    # Import Tradier account
    if not os.getenv("TRADIER"):
        print("Tradier not found, skipping...")
        return None
    # Get access token and split into list
    accounts = os.environ["TRADIER_ACCESS_TOKEN"].split(",")
    return [x.strip() for x in accounts]


def tradier_init():
    accounts = load_accounts()
    if accounts is None:
        return None
    # Login to each account
    tradier_objs = []
    for account in accounts:
        tradier_accounts = []
        print("Logging in to Tradier")
        try:
            response = requests.get(
                "https://api.tradier.com/v1/user/profile",
                params={},
                headers={"Authorization": f"Bearer {account}", "Accept": "application/json"},
            )
            json_response = response.json()
            if json_response is None:
                raise Exception("Error: Tradier API returned None")
        except Exception as e:
            print(f"Error logging in to Tradier: {e}")
            return None
        # Multiple accounts have different JSON structure
        if "'account': {'" in str(json_response):
            account_num = 1
        else:
            account_num = len(json_response["profile"]["account"])
        print(f"Tradier accounts found: {account_num}")
        # Print account numbers
        if account_num == 1:
            print(f"{json_response['profile']['account']['account_number']}")
            tradier_accounts.append(json_response["profile"]["account"]["account_number"])
        else:
            for x in range(account_num):
                print(f"{json_response['profile']['account'][x]['account_number']}")
                tradier_accounts.append(
                    json_response["profile"]["account"][x]["account_number"]
                )
        print("Logged in to Tradier!")
        tradier_objs.append(Tradier(account, tradier_accounts))
    return tradier_objs


def tradier_holdings(tradier, ctx=None, loop=None):
    print()
    print("==============================")
    print("Tradier")
    print("==============================")
    print()
    # Loop through accounts
    for obj in tradier:
        for account_number in obj.account_list:
            try:
                # Get holdings from API
                response = requests.get(
                    f"https://api.tradier.com/v1/accounts/{account_number}/positions",
                    params={},
                    headers={
                        "Authorization": f"Bearer {obj.bearer}",
                        "Accept": "application/json",
                    },
                )
                # Convert to JSON
                json_response = response.json()
                # Check if holdings is empty
                if json_response["positions"] == "null":
                    print(f"Tradier {account_number}: No holdings")
                    if ctx and loop:
                        asyncio.ensure_future(
                            ctx.send(f"Tradier {account_number}: No holdings"), loop=loop
                        )
                    continue
                # Create list of holdings and amounts
                stocks = []
                amounts = []
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
                current_price = []
                for sym in stocks:
                    response = requests.get(
                        "https://api.tradier.com/v1/markets/quotes",
                        params={"symbols": sym, "greeks": "false"},
                        headers={
                            "Authorization": f"Bearer {obj.bearer}",
                            "Accept": "application/json",
                        },
                    )
                    json_response = response.json()
                    current_price.append(json_response["quotes"]["quote"]["last"])
                # Current value for position
                current_value = []
                for value in stocks:
                    # Set index for easy use
                    i = stocks.index(value)
                    current_value.append(amounts[i] * current_price[i])
                # Round to 2 decimal places
                for i in range(len(current_value)):
                    current_value[i] = round(current_value[i], 2)
                    current_price[i] = round(current_price[i], 2)
                # Print and send them
                print(f"Holdings on Tradier account {account_number}")
                if ctx and loop:
                    asyncio.ensure_future(
                        ctx.send(f"Holdings on Tradier account {account_number}"), loop=loop
                    )
                for position in stocks:
                    # Set index for easy use
                    i = stocks.index(position)
                    print(
                        f"{position}: {amounts[i]} @ ${current_price[i]} = ${current_value[i]}"
                    )
                    if ctx and loop:
                        asyncio.ensure_future(
                            ctx.send(
                                f"{position}: {amounts[i]} @ ${current_price[i]} = ${current_value[i]}"
                            ),
                            loop=loop,
                        )
            except Exception as e:
                print(f"Tradier {account_number}: Error getting holdings: {e}")
                if ctx and loop:
                    asyncio.ensure_future(
                        ctx.send(f"Tradier {account_number}: Error getting holdings: {e}"),
                        loop=loop,
                    )
                print(traceback.format_exc())


def tradier_transaction(
    tradier, action, stock, amount, price, time, DRY=True, ctx=None, loop=None
):
    print()
    print("==============================")
    print("Tradier")
    print("==============================")
    print()
    action = action.lower()
    stock = stock.upper()
    amount = int(amount)
    # Loop through accounts
    for obj in tradier:
        for account_number in obj.account_list:
            if not DRY:
                response = requests.post(
                    f"https://api.tradier.com/v1/accounts/{account_number}/orders",
                    data={
                        "class": "equity",
                        "symbol": stock,
                        "side": action,
                        "quantity": amount,
                        "type": "market",
                        "duration": "day",
                    },
                    headers={
                        "Authorization": f"Bearer {obj.bearer}",
                        "Accept": "application/json",
                    },
                )
                json_response = response.json()
                try:
                    if json_response["order"]["status"] == "ok":
                        print(
                            f"Tradier account {account_number}: {action} {amount} of {stock}"
                        )
                        if ctx and loop:
                            asyncio.ensure_future(
                                ctx.send(
                                    f"Tradier account {account_number}: {action} {amount} of {stock}"
                                ),
                                loop=loop,
                            )
                    else:
                        print(
                            f"Tradier account {account_number} Error: {json_response['order']['status']}"
                        )
                        if ctx and loop:
                            asyncio.ensure_future(
                                ctx.send(
                                    f"Tradier account {account_number} Error: {json_response['order']['status']}"
                                ),
                                loop=loop,
                            )
                        return None
                except KeyError:
                    print(
                        f"Tradier account {account_number} Error: This order did not route. Is this a new account?"
                    )
                    if ctx and loop:
                        asyncio.ensure_future(
                            ctx.send(
                                f"Tradier account {account_number} Error: This order did not route. Is this a new account?"
                            ),
                            loop=loop,
                        )
            else:
                print(
                    f"Tradier account {account_number}: Running in DRY mode. Trasaction would've been: {action} {amount} of {stock}"
                )
                if ctx and loop:
                    asyncio.ensure_future(
                        ctx.send(
                            f"Tradier account {account_number}: Running in DRY mode. Trasaction would've been: {action} {amount} of {stock}"
                        ),
                        loop=loop,
                    )
