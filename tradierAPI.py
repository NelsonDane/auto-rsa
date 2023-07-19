# Nelson Dane
# Tradier API

import os
import traceback

import requests
from dotenv import load_dotenv
from helperAPI import Brokerage, printAndDiscord


def tradier_init(TRADIER_EXTERNAL=None):
    # Initialize .env file
    load_dotenv()
    # Import Tradier account
    if not os.getenv("TRADIER") and TRADIER_EXTERNAL is None:
        print("Tradier not found, skipping...")
        return None
    # Get access token and split into list
    accounts = os.environ["TRADIER"].strip().split(",") if TRADIER_EXTERNAL is None else TRADIER_EXTERNAL.strip().split(",")
    # Login to each account
    tradier_obj = Brokerage("Tradier")
    for account in accounts:
        index = accounts.index(account) + 1
        print(f"Logging in to Tradier {index}")
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
            an = json_response["profile"]["account"]["account_number"]
            print(an)
            tradier_obj.add_account_number(f"Tradier {index}", an)
        else:
            for x in range(account_num):
                an = json_response["profile"]["account"][x]["account_number"]
                print(an)
                tradier_obj.add_account_number(f"Tradier {index}", an)
        tradier_obj.loggedInObjects.append(account)
        print(f"Logged in to Tradier {index}!")
    return tradier_obj


def tradier_holdings(tradier_o, ctx=None, loop=None):
    print()
    print("==============================")
    print("Tradier")
    print("==============================")
    print()
    # Loop through accounts
    tradier = tradier_o.loggedInObjects
    for obj in tradier:
        index = tradier.index(obj) + 1
        for account_number in tradier_o.get_account_numbers(f"Tradier {index}"):
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
                # Check if holdings is empty
                if json_response["positions"] == "null":
                    printAndDiscord(f"Tradier {account_number}: No holdings", ctx=ctx, loop=loop)
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
                            "Authorization": f"Bearer {obj}",
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
                printAndDiscord(f"Holdings on Tradier {account_number}", ctx=ctx, loop=loop)
                print_string = ""
                for position in stocks:
                    # Set index for easy use
                    i = stocks.index(position)
                    print_string += f"{position}: {amounts[i]} @ ${current_price[i]} = ${current_value[i]}\n"
                printAndDiscord(print_string, ctx=ctx, loop=loop)
            except Exception as e:
                printAndDiscord(f"Tradier {account_number}: Error getting holdings: {e}", ctx=ctx, loop=loop)
                print(traceback.format_exc())


def tradier_transaction(
    tradier_o, action, stock, amount, price, time, DRY=True, ctx=None, loop=None
):
    print()
    print("==============================")
    print("Tradier")
    print("==============================")
    print()
    action = action.lower()
    stock = [x.upper() for x in stock]
    amount = int(amount)
    # Loop through accounts
    tradier = tradier_o.loggedInObjects
    for obj in tradier:
        index = tradier.index(obj) + 1
        for s in stock:
            printAndDiscord(f"Tradier {index}: {action}ing {amount} of {s}", ctx=ctx, loop=loop)
            for account_number in tradier_o.get_account_numbers(f"Tradier {index}"):
                if not DRY:
                    try:
                        response = requests.post(
                            f"https://api.tradier.com/v1/accounts/{account_number}/orders",
                            data={
                                "class": "equity",
                                "symbol": s,
                                "side": action,
                                "quantity": amount,
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
                                f"Tradier account {account_number} Error: {e} JSON response: {response}",
                                ctx=ctx,
                                loop=loop,
                            )
                            continue
                        if json_response["order"]["status"] == "ok":
                            printAndDiscord(
                                f"Tradier account {account_number}: {action} {amount} of {s}",
                                ctx=ctx,
                                loop=loop,
                            )
                        else:
                            printAndDiscord(
                                f"Tradier account {account_number} Error: {json_response['order']['status']}",
                                ctx=ctx,
                                loop=loop,
                            )
                            continue
                    except KeyError:
                        printAndDiscord(
                            f"Tradier account {account_number} Error: This order did not route. JSON response: {json_response}",
                            ctx=ctx,
                            loop=loop,
                        )
                    except Exception as e:
                        printAndDiscord(f"Tradier account {account_number}: Error: {e}", ctx=ctx, loop=loop)
                        print(traceback.format_exc())
                        print(json_response)
                else:
                    printAndDiscord(
                        f"Tradier account {account_number}: Running in DRY mode. Trasaction would've been: {action} {amount} of {s}",
                        ctx=ctx,
                        loop=loop,
                    )
