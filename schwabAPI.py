# Nelson Dane
# Schwab API

import os
import asyncio
import json
from time import sleep
from dotenv import load_dotenv
from seleniumAPI import *

def schwab_init(DOCKER=False):
    # Initialize .env file
    load_dotenv()
    # Import Schwab account
    if not os.getenv("SCHWAB_USERNAME") or not os.getenv("SCHWAB_PASSWORD") or not os.getenv("SCHWAB_TOTP_SECRET"):
        print("Schwab not found, skipping...")
        return None
    SCHWAB_USERNAME = os.environ["SCHWAB_USERNAME"]
    SCHWAB_PASSWORD = os.environ["SCHWAB_PASSWORD"]
    SCHWAB_TOTP_SECRET = os.environ["SCHWAB_TOTP_SECRET"]
    # Log in to Schwab account
    print("Logging in to Schwab...")
    try:
        driver = getDriver(DOCKER)
        driver.get("https://itsjafer.com/#/reversesplit")
        WebDriverWait(driver, 10).until(check_if_page_loaded)
        sleep(3)
        # Type in username, password, and TOTP
        username_field = driver.find_element(by=By.CSS_SELECTOR, value="#root > div > div > div:nth-child(4) > div > div > form > input[type=text]:nth-child(2)")
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable(username_field)
        )
        username_field.send_keys(SCHWAB_USERNAME)
        password_field = driver.find_element(by=By.CSS_SELECTOR, value="#root > div > div > div:nth-child(4) > div > div > form > input[type=password]:nth-child(3)")
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable(password_field)
        )
        password_field.send_keys(SCHWAB_PASSWORD)
        totp_field = driver.find_element(by=By.CSS_SELECTOR, value="#root > div > div > div:nth-child(4) > div > div > form > div > input[type=text]")
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable(totp_field)
        )
        totp_field.send_keys(SCHWAB_TOTP_SECRET)
        # Click login button
        login_button = driver.find_element(by=By.CSS_SELECTOR, value="#root > div > div > div:nth-child(4) > div > div > form > input[type=submit]:nth-child(11)")
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable(login_button)
        )
        # Make sure button has correct text
        if not login_button.get_attribute("value") == "Get Account Info":
            print(f"Error: Login button has incorrect text: {login_button.get_attribute('value')}")
            return None
        login_button.click()
        # Wait for waiting to appear
        WebDriverWait(driver, 60).until(
            expected_conditions.presence_of_element_located((By.CSS_SELECTOR, "#root > div > div > div:nth-child(4) > div > div > span"))
        )
        print("Getting account info...")
        # Wait for account info to appear
        WebDriverWait(driver, 60).until(
            # Wait for class react-tabs to appear
            expected_conditions.presence_of_element_located((By.CSS_SELECTOR, "#root > div > div > div:nth-child(4) > div > div > div:nth-child(2) > div"))
        )
        # Loop through tabs of accounts
        ul = driver.find_element(by=By.CSS_SELECTOR, value="#root > div > div > div:nth-child(4) > div > div > div:nth-child(2) > div > ul")
        accounts = ul.find_elements(by=By.TAG_NAME, value="li")
        for account in accounts:
            print(f"Account: {account.text}")
        print("Logged in to Schwab!")
        return driver
    except Exception as e:
        print(f'Error logging in to Schwab: {e}')
        traceback.print_exc()
        return None

async def schwab_holdings(driver, ctx=None):
    # Make sure init didn't return None
    if driver is None:
        print()
        print("Error: No Schwab account")
        return None
    print()
    print("==============================")
    print("Schwab Holdings")
    print("==============================")
    print()
    # Loop through tabs of accounts
    try:
        ul = driver.find_element(by=By.CSS_SELECTOR, value="#root > div > div > div:nth-child(4) > div > div > div:nth-child(2) > div > ul")
        accounts = ul.find_elements(by=By.TAG_NAME, value="li")
        for account in accounts:
            account.click()
            # Get pretty json
            response = driver.find_element(by=By.CSS_SELECTOR, value="#json-pretty > pre")
            json_response = json.loads(response.text)
            print(f"Account {account.text} value: ${json_response[account.text]['account_value']}")
            if ctx:
                await ctx.send(f"Account {account.text} value: ${json_response[account.text]['account_value']}")
            # Loop through positions
            for pos in json_response[account.text]['positions']:
                amount = pos['quantity']
                if amount == 0:
                    continue
                sym = pos['symbol']
                if sym == "":
                    sym = "UNKNOWN"
                current_price = round(float(pos['market_value']/amount), 2)
                message = f"{sym}: {amount} @ ${current_price}: ${pos['market_value']}"
                print(message)
                if ctx:
                    await ctx.send(message)
            print()
            sleep(1)
    except Exception as e:
        print(f'Error getting Schwab holdings: {e}')
        traceback.print_exc()
        return None
        
async def schwab_transaction(driver, action, stock, amount, price, time, DRY=True, ctx=None):
    # Make sure init didn't return None
    if driver is None:
        print("Error: No Schwab account")
        return None
    print()
    print("==============================")
    print("Schwab")
    print("==============================")
    print()
    # Get correct capitalization for action
    if action.lower() == "buy":
        action = "Buy"
    elif action.lower() == "sell":
        action = "Sell"
    stock = stock.upper()
    amount = int(amount)
    # It already does it on all accounts
    try:
        # Stock input
        stock_input = driver.find_element(by=By.CSS_SELECTOR, value="#root > div > div > div:nth-child(4) > div > div > form > input[type=text]:nth-child(7)")
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable(stock_input)
        )
        stock_input.clear()
        stock_input.send_keys(stock)
        # Amount input
        amount_input = driver.find_element(by=By.CSS_SELECTOR, value="#root > div > div > div:nth-child(4) > div > div > form > input[type=number]:nth-child(8)")
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable(amount_input)
        )
        amount_input.clear()
        amount_input.send_keys(amount)
        # Select buy/sell
        select = Select(driver.find_element(by=By.CSS_SELECTOR, value="#root > div > div > div:nth-child(4) > div > div > form > select:nth-child(9)"))
        select.select_by_visible_text(action)
        # Make sure schwab is selected
        schwabSelect = Select(driver.find_element(by=By.CSS_SELECTOR, value="#root > div > div > div:nth-child(4) > div > div > form > select:nth-child(10)"))
        schwabSelect.select_by_visible_text("Schwab")
        # And go!
        sleep(1)
        place_order_button = driver.find_element(by=By.CSS_SELECTOR, value="#root > div > div > div:nth-child(4) > div > div > form > input[type=submit]:nth-child(11)")
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable(place_order_button)
        )
        # Make sure text is correct
        if not place_order_button.get_attribute("value") == "Place Trade (on all accounts)":
            print(f"Error: Place order button has incorrect text: {place_order_button.get_attribute('value')}")
            return None
        if not DRY:
            place_order_button.click()
            sleep(1)
            # Make sure waiting comes up
            # Wait for waiting to appear
            WebDriverWait(driver, 60).until(
                expected_conditions.presence_of_element_located((By.CSS_SELECTOR, "#root > div > div > div:nth-child(4) > div > div > span"))
            )
            # That means order is placed
            # Now wait for it to disappear
            WebDriverWait(driver, 120).until(
                expected_conditions.invisibility_of_element_located((By.CSS_SELECTOR, "#root > div > div > div:nth-child(4) > div > div > span"))
            )
            # That means order is done
            print(f"Schwab: {action} {amount} {stock} on all accounts")
            if ctx:
                await ctx.send(f"Schwab: {action} {amount} {stock} on all accounts")
        else:
            print(f"DRY Schwab: {action} {amount} {stock} on all accounts")
            if ctx:
                await ctx.send(f"DRY Schwab: {action} {amount} {stock} on all accounts")
    except Exception as e:
        print(f'Error placing Schwab order: {e}')
        traceback.print_exc()
        return None

# test = schwab_init()
# schwab_holdings(test)