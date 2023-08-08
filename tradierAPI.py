# Nelson Dane
# Tradier API

import os
import traceback

import requests
from dotenv import load_dotenv

from helperAPI import Brokerage, printAndDiscord, printHoldings, stockOrder


def tradier_init(TRADIER_EXTERNAL=None):
    # Initialize .env file
    load_dotenv()
    # Import Tradier account
    if not os.getenv("TRADIER") and TRADIER_EXTERNAL is None:
        print("Tradier not found, skipping...")
        return None
    # Get access token and split into list
    accounts = (
        os.environ["TRADIER"].strip().split(",")
        if TRADIER_EXTERNAL is None
        else TRADIER_EXTERNAL.strip().split(",")
    )
    # Login to each account
    tradier_obj = Brokerage("Tradier")
    print("Logging in to Tradier...")
    for account in accounts:
        name = f"Tradier {accounts.index(account) + 1}"
        try:
            response = requests.get(
                "https://api.tradier.com/v1/user/profile",
                params={},
                headers={
                    "Authorization": f"Bearer {account}",
                    "Accept": "application/json",
                },
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
        for x in range(account_num):
            if account_num == 1:
                an = json_response["profile"]["account"]["account_number"]
            else:
                an = json_response["profile"]["account"][x]["account_number"]
            print(an)
            tradier_obj.set_account_number(name, an)
            tradier_obj.set_account_type(
                name, an, json_response["profile"]["account"][x]["type"]
            )
            # Get balances
            try:
                balances = requests.get(
                    f"https://api.tradier.com/v1/accounts/{an}/balances",
                    params={},
                    headers={
                        "Authorization": f"Bearer {account}",
                        "Accept": "application/json",
                    },
                )
                json_balances = balances.json()
                tradier_obj.set_account_totals(
                    name, an, json_balances["balances"]["total_equity"]
                )
            except Exception as e:
                print(f"Error getting balances for {an}: {e}")
                tradier_obj.set_account_totals(name, an, 0)
        # Get balances
        tradier_obj.set_logged_in_object(name, account)
    print("Logged in to Tradier!")
    return tradier_obj


def tradier_holdings(tradier_o: Brokerage, ctx=None, loop=None):
    # Loop through accounts
    for key in tradier_o.get_account_numbers():
        for account_number in tradier_o.get_account_numbers(key):
            obj: str = tradier_o.get_logged_in_objects(key)
            try:
                # Get holdings from API
                response = requests.get(
                    f"https://api.tradier.com/v1/accounts/{account_number}/positions",
                    params={},
                    headers={
                        "Authorization": f"Bearer {obj}",
                        "Accept": "application/json",
                    },
                )
                # Convert to JSON
                json_response = response.json()
                stocks = []
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
                current_price = []
                for sym in stocks:
                    response = requests.get(
                        "https://api.tradier.com/v1/markets/quotes",
                        params={"symbols": sym, "greeks": "false"},
                        headers={
                            "Authorization": f"Bearer {obj}",
                            "Accept": "application/json",
                        },
                    )
                    json_response = response.json()
                    current_price.append(json_response["quotes"]["quote"]["last"])
                # Print and send them
                for position in stocks:
                    # Set index for easy use
                    i = stocks.index(position)
                    tradier_o.set_holdings(
                        key, account_number, position, amounts[i], current_price[i]
                    )
            except Exception as e:
                printAndDiscord(
                    f"{key}: Error getting holdings: {e}", ctx=ctx, loop=loop
                )
                print(traceback.format_exc())
                continue
    printHoldings(tradier_o, ctx=ctx, loop=loop)


def tradier_transaction(
    tradier_o: Brokerage, orderObj: stockOrder, ctx=None, loop=None
):
    print()
    print("==============================")
    print("Tradier")
    print("==============================")
    print()
    # Loop through accounts
    for s in orderObj.get_stocks():
        for key in tradier_o.get_account_numbers():
            printAndDiscord(
                f"{key}: {orderObj.get_action()}ing {orderObj.get_amount()} of {s}",
                ctx=ctx,
                loop=loop,
            )
            for account in tradier_o.get_account_numbers(key):
                obj: str = tradier_o.get_logged_in_objects(key)
                if not orderObj.get_dry():
                    try:
                        response = requests.post(
                            f"https://api.tradier.com/v1/accounts/{account}/orders",
                            data={
                                "class": "equity",
                                "symbol": s,
                                "side": orderObj.get_action(),
                                "quantity": orderObj.get_amount(),
                                "type": "market",
                                "duration": "day",
                            },
                            headers={
                                "Authorization": f"Bearer {obj}",
                                "Accept": "application/json",
                            },
                        )
                        try:
                            json_response = response.json()
                        except requests.exceptions.JSONDecodeError as e:
                            printAndDiscord(
                                f"Tradier account {account} Error: {e} JSON response: {response}",
                                ctx=ctx,
                                loop=loop,
                            )
                            continue
                        if json_response["order"]["status"] == "ok":
                            printAndDiscord(
                                f"Tradier account {account}: {orderObj.get_action()} {orderObj.get_amount()} of {s}",
                                ctx=ctx,
                                loop=loop,
                            )
                        else:
                            printAndDiscord(
                                f"Tradier account {account} Error: {json_response['order']['status']}",
                                ctx=ctx,
                                loop=loop,
                            )
                            continue
                    except KeyError:
                        printAndDiscord(
                            f"Tradier account {account} Error: This order did not route. JSON response: {json_response}",
                            ctx=ctx,
                            loop=loop,
                        )
                    except Exception as e:
                        printAndDiscord(
                            f"Tradier account {account}: Error: {e}", ctx=ctx, loop=loop
                        )
                        print(traceback.format_exc())
                        print(json_response)
                else:
                    printAndDiscord(
                        f"Tradier account {account}: Running in DRY mode. Trasaction would've been: {orderObj.get_action()} {orderObj.get_amount()} of {s}",
                        ctx=ctx,
                        loop=loop,
                    )
