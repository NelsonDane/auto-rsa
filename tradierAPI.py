# Nelson Dane
# Tradier API

import os
import sys
import requests
from time import sleep
from dotenv import load_dotenv

def tradier_init():
    # Initialize .env file
    load_dotenv()
    # Import Tradier account
    if not os.environ["TRADIER_ACCESS_TOKEN"]:
        print("Error: Missing Tradier Access Token")
        return None
    # Get access token
    BEARER = os.environ["TRADIER_ACCESS_TOKEN"]
    # Log in to Tradier account
    print("Logging in to Tradier...")
    try:
        response = requests.get('https://api.tradier.com/v1/user/profile',
        params={},
        headers={'Authorization': f'Bearer {BEARER}', 'Accept': 'application/json'}
        )
        json_response = response.json()
        if json_response is None:
            raise Exception("Error: Tradier API returned None")
    except Exception as e:
        print(f'Error logging in to Tradier: {e}')
        return None
    # Print number of accounts found
    print(f"Tradier accounts found: {len(json_response['profile']['account'])}")
    # Print account numbers
    tradier_accounts = []
    for x in range(len(json_response['profile']['account'])):
        print(f"{json_response['profile']['account'][x]['account_number']}")
        tradier_accounts.append(json_response['profile']['account'][x]['account_number'])
    print("Logged in to Tradier!")
    return tradier_accounts

def tradier_transaction(tradier, action, stock, amount, price, time, DRY):
    print()
    print("==============================")
    print("Tradier")
    print("==============================")
    print()
    action = action.lower()
    stock = stock.upper()
    BEARER = os.environ["TRADIER_ACCESS_TOKEN"]
    # Make sure init didn't return None
    if tradier is None:
        print("Error: No Tradier account")
        return None
    # Loop through accounts
    for account_number in tradier:
        if not DRY:
            response = requests.post(f'https://api.tradier.com/v1/accounts/{account_number}/orders',
            data={'class': 'equity', 'symbol': stock, 'side': action, 'quantity': amount, 'type': 'market', 'duration': 'day'},
            headers={'Authorization': f'Bearer {BEARER}', 'Accept': 'application/json'}
            )
            json_response = response.json()
            #print(response.status_code)
            #print(json_response)
            if json_response['order']['status'] == "ok":
                print(f"{action} {amount} of {stock} on Tradier account {account_number}")
            else:
                print(f"Error: {json_response['order']['status']}")
                return None
        else:
            print(f"Running in DRY mode. Trasaction would've been: {action} {amount} of {stock} on Tradier account {account_number}")