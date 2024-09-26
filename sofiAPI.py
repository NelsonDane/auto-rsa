import asyncio
import os
import logging
import pyotp
import nodriver as uc
import requests
import traceback
import datetime
import json
from dotenv import load_dotenv
from time import sleep

from helperAPI import (
    Brokerage,
    printAndDiscord,
    printHoldings,
    stockOrder,
    getOTPCodeDiscord,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

COOKIES_PATH = "creds"
# Get or create the event loop
try:
    sofi_loop = asyncio.get_event_loop()
except RuntimeError:
    sofi_loop = asyncio.new_event_loop()


def create_creds_folder():
    """Create the 'creds' folder if it doesn't exist."""
    if not os.path.exists(COOKIES_PATH):
        os.makedirs(COOKIES_PATH)
        logger.info(f"Created '{COOKIES_PATH}' folder.")


async def save_cookies_to_pkl(browser, cookie_filename):
    try:
        await browser.cookies.save(cookie_filename)
        print("Cookies saved.")
    except Exception as e:
        print(f"Failed to save cookies: {e}")


async def load_cookies_from_pkl(browser, page, cookie_filename):
    try:
        await browser.cookies.load(cookie_filename)
        await page.reload()
        print("Cookies loaded.")
        return True
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Failed to load cookies: {e}")
    except FileNotFoundError:
        print("Cookie file does not exist.")
    return False


async def sofi_error(page, discord_loop=None):
    if page is not None:
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_name = f"SoFi-error-{timestamp}.png"
            await page.save_screenshot(filename=screenshot_name, full_page=True)
            print(f"Screenshot saved as {screenshot_name}")
        except Exception as e:
            print(f"Failed to take screenshot: {str(e)}")

    try:
        error_message = f"SoFi Error: {traceback.format_exc()}"
        printAndDiscord(error_message, discord_loop, embed=False)
    except Exception as e:
        print(f"Failed to log error: {str(e)}")


async def get_current_url(page):
    """Get the current page URL by evaluating JavaScript."""
    await page.sleep(1)
    await page.select('body')
    try:
        # Run JavaScript to get the current URL
        current_url = await page.evaluate("window.location.href")
        return current_url
    except Exception as e:
        logger.error(f"Error fetching the current URL: {e}")
        return None


def sofi_run(orderObj: stockOrder, command=None, botObj=None, loop=None, SOFI_EXTERNAL=None):
    logger.info("Initializing SoFi process...")
    load_dotenv()
    create_creds_folder()
    discord_loop = loop  # Keep the parameter as "loop" for consistency with other init functions
    browser = None

    if not os.getenv("SOFI") and SOFI_EXTERNAL is None:
        logger.error("SoFi environment variable not found.")
        printAndDiscord("SoFi environment variable not found.", discord_loop)
        return None

    logger.info("Loading SoFi accounts...")
    accounts = (
        os.environ["SOFI"].strip().split(",")
        if SOFI_EXTERNAL is None
        else SOFI_EXTERNAL.strip().split(",")
    )
    sofi_obj = Brokerage("SoFi")

    # Get headless flag
    headless = os.getenv("HEADLESS", "true").lower() == "true"

    # Set the functions to be run
    _, second_command = command

    try:
        for account in accounts:
            index = accounts.index(account) + 1
            name = f"SoFi {index}"
            cookie_filename = f"{COOKIES_PATH}/{name}.pkl"
            browser_args = [
                '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
            ]
            if headless:
                browser_args.append("--headless=new")
            browser = sofi_loop.run_until_complete(uc.start(browser_args=browser_args))
            sofi_init(account, name, cookie_filename, botObj, browser, discord_loop, sofi_obj)
            if second_command == "_holdings":
                sofi_holdings(browser, name, sofi_obj, discord_loop)
            else:
                sofi_transaction(browser, orderObj, discord_loop)
    except Exception as e:
        logger.error(f"Error during SoFi init process: {e}")
        return None
    finally:
        if browser:
            try:
                logger.info("Saving Cookies...")
                sofi_loop.run_until_complete(save_cookies_to_pkl(browser, cookie_filename))
                logger.info("Closing the browser...")
                browser.stop()
            except Exception as e:
                logger.error(f"Error closing the browser: {e}")
    return None


def sofi_init(account, name, cookie_filename, botObj, browser, discord_loop, sofi_obj):
    try:
        account = account.split(":")

        # Load cookies
        page = sofi_loop.run_until_complete(browser.get('https://www.sofi.com'))
        cookies_loaded = sofi_loop.run_until_complete(load_cookies_from_pkl(browser, page, cookie_filename))

        if cookies_loaded:
            logger.info(f"Cookies loaded for {name}, checking if login is valid...")
            sofi_loop.run_until_complete(page.get('https://www.sofi.com/wealth/app/'))
            sofi_loop.run_until_complete(browser.sleep(1))
            sofi_loop.run_until_complete(page.select('body'))
            current_url = sofi_loop.run_until_complete(get_current_url(page))

            if current_url and "overview" in current_url:
                logger.info(f"Successfully bypassed login for {name} using cookies.")
                sofi_loop.run_until_complete(save_cookies_to_pkl(browser, cookie_filename))
                return sofi_obj

        # Proceed with login if cookies are invalid or expired
        sofi_loop.run_until_complete(sofi_login_and_account(browser, page, account, name, botObj, discord_loop))
        sofi_obj.set_logged_in_object(name, browser)
    except Exception as e:
        logger.error(f"Error during SoFi init process: {e}")
        return None
    return sofi_obj


async def sofi_login_and_account(browser, page, account, name, botObj, discord_loop):
    try:
        logger.info(f"Navigating to SoFi login page for {name}...")
        page = await browser.get('https://www.sofi.com')
        if not page:
            raise Exception(f"Failed to load SoFi login page for {name}")

        await page.get('https://www.sofi.com/wealth/app')
        logger.info(f"Entering username for {name}...")
        username_input = await page.select("input[id=username]")
        if not username_input:
            raise Exception(f"Unable to locate the username input field for {name}")
        await username_input.send_keys(account[0])

        logger.info(f"Entering password for {name}...")
        password_input = await page.select("input[type=password]")
        if not password_input:
            raise Exception(f"Unable to locate the password input field for {name}")
        await password_input.send_keys(account[1])

        logger.info(f"Clicking login button for {name}...")
        login_button = await page.find("Log In", best_match=True)
        if not login_button:
            raise Exception(f"Unable to locate the login button for {name}")
        await login_button.click()

        await page.select('body')

        current_url = await get_current_url(page)
        if current_url and "overview" in current_url:
            logger.info(f"Successfully logged in without needing 2FA for {name}.")
        else:
            logger.info(f"2FA required for {name}, starting 2FA handling...")
            await handle_2fa(page, account, name, botObj, discord_loop)
    except Exception as e:
        logger.error(f"Error logging into account {name}: {e}")
        await sofi_error(page, discord_loop)
        raise


async def sofi_account_info(browser, discord_loop) -> dict:
    try:
        logger.info("Navigating to SoFi account overview page...")
        await browser.sleep(1)
        page = await browser.get('https://www.sofi.com/wealth/app/overview')

        cookies = await browser.cookies.get_all()

        headers = {
        'accept': 'application/json',
        'accept-language': 'en-US,en;q=0.9',
        'content-type': 'application/json',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest'
        }

        cookies_dict = {cookie.name: cookie.value for cookie in cookies}

        logger.info("Sending request for account information...")
        response = requests.get(
            'https://www.sofi.com/wealth/backend/v1/json/accounts',
            headers=headers,
            cookies=cookies_dict
        )

        if response.status_code != 200:
            raise Exception(f"Failed to fetch account info, status code: {response.status_code}")

        accounts_data = response.json()
        account_dict = {}

        for account in accounts_data:
            account_number = account['apexAccountId']
            account_id = account['id']
            account_type = account['type']['description']
            current_value = account['totalEquityValue']

            account_dict[account_number] = {
                'type': account_type,
                'balance': float(current_value),
                'id': account_id
            }

            logger.info(f"Account Info Retrieved: {account_dict[account_number]}")

        logger.info("Successfully retrieved and parsed account information.")
        return account_dict

    except Exception as e:
        logger.error(f"Error fetching SoFi account information: {e}")
        await sofi_error(page, discord_loop)
        raise


def sofi_holdings(browser, name, sofi_obj, discord_loop):
    logger.info(f"Processing holdings for {name}...")
    account_dict = sofi_loop.run_until_complete(sofi_account_info(browser, discord_loop))
    if not account_dict:
        raise Exception(f"Failed to retrieve account info for {name}")

    for acct, account_info in account_dict.items():
        real_account_number = acct
        sofi_obj.set_account_number(name, real_account_number)
        sofi_obj.set_account_totals(name, real_account_number, account_info["balance"])

        account_id = account_info.get('id')
        cookies = {cookie.name: cookie.value for cookie in sofi_loop.run_until_complete(browser.cookies.get_all())}

        holdings = sofi_loop.run_until_complete(get_holdings_formatted(account_id, cookies))

        for holding in holdings:
            company_name = holding.get('company_name', 'N/A')
            if company_name == '|CASH|':
                continue

            shares = holding.get('shares', 'N/A')
            price = holding.get('price', 'N/A')
            sofi_obj.set_holdings(name, real_account_number, company_name, shares, price)

        logger.info(f"Completed processing holdings for account {real_account_number}")

    # Log info after holdings are processed
    logger.info(f"All holdings processed for {name}.")
    printHoldings(sofi_obj, discord_loop)


async def get_holdings_formatted(account_id, cookies):
    try:
        headers = {
        'accept': 'application/json',
        'accept-language': 'en-US,en;q=0.9',
        'content-type': 'application/json',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest'
        }
        logger.info(f"Retrieving holdings for SOFI account {account_id}...")

        holdings_url = f"https://www.sofi.com/wealth/backend/api/v3/account/{account_id}/holdings?accountDataType=INTERNAL"

        response = requests.get(holdings_url, headers=headers, cookies=cookies)

        if response.status_code != 200:
            raise Exception(f"Failed to fetch holdings, status code: {response.status_code}")

        holdings_data = response.json()

        formatted_holdings = []

        for holding in holdings_data.get('holdings', []):
            company_name = holding.get('symbol', 'N/A')
            shares = holding.get('shares', 'N/A')
            price = holding.get('price', 'N/A')

            formatted_holdings.append({
                'company_name': company_name if company_name else 'N/A',
                'shares': float(shares) if shares is not None else 'N/A',
                'price': float(price) if price is not None else 'N/A',
            })

        logger.info(f"Successfully retrieved and processed holdings for account {account_id}.")
        return formatted_holdings

    except Exception as e:
        logger.error(f"Error fetching holdings for SOFI account {account_id}: {e}")
        raise e


def get_2fa_code(secret):
    totp = pyotp.TOTP(secret)
    return totp.now()


async def handle_2fa(page, account, name, botObj, discord_loop):
    """
    Handle both authenticator app 2FA and SMS-based 2FA.
    """
    try:
        # Authenticator app 2FA handling (if secret exists)
        secret = account[2] if len(account) > 2 else None
        if secret:
            logger.info(f"Handling authenticator app 2FA for {name}...")
            remember = await page.select("input[id=rememberBrowser]")
            if remember:
                await remember.click()

            twofa_input = await page.select("input[id=code]")
            if not twofa_input:
                raise Exception(f"Unable to locate 2FA input field for {name}")

            two_fa_code = get_2fa_code(secret)  # Get the OTP from the authenticator app
            await twofa_input.send_keys(two_fa_code)
            verify_button = await page.find("Verify Code")
            if verify_button:
                await verify_button.click()
            logger.info(f"Authenticator app 2FA completed for {name}.")
        else:
            # Set a timeout duration for finding the SMS 2FA element
            sms_2fa_element = None
            try:
                sms_2fa_element = await asyncio.wait_for(
                    page.find("We've sent a text message to:", best_match=True),
                    timeout=5
                )
            except asyncio.TimeoutError:
                logger.info(f"SMS 2FA text not found for {name}, proceeding to check for authenticator app 2FA...")

            if sms_2fa_element:
                # SMS 2FA handling
                logger.info(f"Waiting for SMS 2FA for {name}...")
                remember = await page.select("input[id=rememberBrowser]")
                if remember:
                    await remember.click()
                sms2fa_input = await page.select("input[id=code]")
                if not sms2fa_input:
                    raise Exception(f"Unable to locate SMS 2FA input field for {name}")

                if botObj is not None and discord_loop is not None:
                    # Directly await the OTP code from Discord without specifying the loop
                    sms_code = asyncio.run_coroutine_threadsafe(
                        getOTPCodeDiscord(botObj, name, loop=discord_loop),
                        discord_loop,
                    ).result()
                    if sms_code is None:
                        raise Exception(f"Sofi {name} SMS code not received in time...")
                else:
                    sms_code = input("Enter code: ")

                await sms2fa_input.send_keys(sms_code)
                verify_button = await page.find("Verify Code")
                if verify_button:
                    await verify_button.click()
                logger.info(f"SMS 2FA completed for {name}.")
            else:
                raise Exception(f"No valid 2FA method found for {name}.")
        
    except Exception as e:
        logger.error(f"Error during 2FA handling for {name}: {e}")
        printAndDiscord(f"Error during 2FA handling for {name}", discord_loop)
        raise e


def sofi_transaction(browser, orderObj: stockOrder, discord_loop):
    for stock in orderObj.get_stocks():
        if orderObj.get_action() == "buy":
            sofi_loop.run_until_complete(sofi_buy(browser, stock, orderObj.get_amount(), discord_loop))
        elif orderObj.get_action() == "sell":
            sofi_loop.run_until_complete(sofi_sell(browser, stock, orderObj.get_amount(), discord_loop))
        else:
            logger.error(f"Unknown action: {orderObj.get_action()}")


async def sofi_buy(browser, symbol, quantity, discord_loop):
    try:
        # Step 1: Navigate to stock page and get valid cookies
        stock_url = f'https://www.sofi.com/wealth/app/stock/{symbol}'
        page = await browser.get(stock_url)
        await page.select('body')

        cookies = {cookie.name: cookie.value for cookie in await browser.cookies.get_all()}
        if not cookies:
            raise Exception("Failed to retrieve valid cookies for the session.")

        csrf_token = cookies.get('SOFI_CSRF_COOKIE') or cookies.get('SOFI_R_CSRF_TOKEN')
        if not csrf_token:
            raise Exception("Failed to retrieve CSRF token from cookies.")

        # Step 2: Get the stock price
        stock_price = await fetch_stock_price(symbol)
        if stock_price is None:
            raise Exception(f"Failed to retrieve stock price for {symbol}")

        # Add a single cent to the stock price
        limit_price = round(stock_price + 0.01, 2)

        logger.info(f"Stock price for {symbol}: {stock_price}, placing order with limit price: {limit_price}")

        # Step 3: Fetch all funded accounts and their buying power
        accounts = await fetch_funded_accounts(cookies)
        if not accounts:
            raise Exception("Failed to retrieve funded accounts or none available.")
        
        # Step 4: Loop through all accounts to check buying power and place the limit order
        for account in accounts:
            account_id = account['accountId']
            buying_power = account['accountBuyingPower']
            account_name = account.get('accountType')

            total_price = limit_price * quantity
            if total_price <= buying_power:
                # Place a limit order using the adjusted limit price
                logger.info(f"Placing limit order for {symbol} in account {account_name} with limit price: {limit_price}")
                await place_order(symbol, quantity, limit_price, account_id, order_type='BUY', cookies=cookies, csrf_token=csrf_token)
            else:
                logger.info(f"Insufficient buying power in {account_name}. Needed: {total_price}, Available: {buying_power}")

    except Exception as e:
        logger.error(f"Error during buy transaction for {symbol}: {e}")
        await printAndDiscord(f"Error during buy transaction for {symbol}: {e}", discord_loop)
        raise


async def sofi_sell(browser, symbol, quantity, discord_loop):
    try:
        # Step 1: Fetch holdings for the stock symbol
        logger.info(f"Checking holdings for symbol: {symbol}")
        cookies = {cookie.name: cookie.value for cookie in await browser.cookies.get_all()}
        if not cookies:
            raise Exception("Failed to retrieve valid cookies for the session.")
        
        csrf_token = cookies.get('SOFI_CSRF_COOKIE') or cookies.get('SOFI_R_CSRF_TOKEN')
        if not csrf_token:
            raise Exception("Failed to retrieve CSRF token from cookies.")
        
        # Fetch holdings for the specific symbol
        holdings_url = f"https://www.sofi.com/wealth/backend/api/v3/customer/holdings/symbol/{symbol}"
        response = requests.get(holdings_url, headers={
            'accept': 'application/json',
            'content-type': 'application/json',
            'x-requested-with': 'XMLHttpRequest',
            'user-agent': 'Mozilla/5.0'
        }, cookies=cookies)
        
        if response.status_code != 200:
            raise Exception(f"Failed to fetch holdings for {symbol}. Status code: {response.status_code}")
        
        holdings_data = response.json()
        account_holding_infos = holdings_data.get("accountHoldingInfos", [])
        
        if not account_holding_infos:
            raise Exception(f"No holdings found for symbol {symbol}. Cannot proceed with the sell order.")
        
        # Step 2: Accumulate total shares and prepare to sell
        total_available_shares = 0
        accounts_to_sell = []
        
        for holding_info in account_holding_infos:
            account_id = holding_info['accountId']
            available_shares = holding_info['salableQuantity']
            if available_shares > 0:
                total_available_shares += available_shares
                accounts_to_sell.append({
                    'account_id': account_id,
                    'available_shares': available_shares
                })
        
        # Step 3: Fail if total shares held are less than the quantity requested
        if total_available_shares < quantity:
            raise Exception(f"Not enough shares to sell. Available: {total_available_shares}, Requested: {quantity}")
        
        # Step 4: Fetch the current stock price and calculate limit price
        stock_price = await fetch_stock_price(symbol)
        if stock_price is None:
            raise Exception(f"Failed to retrieve stock price for {symbol}")
        
        # Subtract a cent from the stock price for a limit sell
        limit_price = round(stock_price - 0.01, 2)
        logger.info(f"Stock price for {symbol}: {stock_price}, placing sell order with limit price: {limit_price}")
        
        # Step 5: Loop through accounts to place the sell orders
        remaining_shares_to_sell = quantity
        
        for account in accounts_to_sell:
            account_id = account['account_id']
            available_shares = account['available_shares']
            
            # Determine the number of shares to sell from this account
            shares_to_sell = min(remaining_shares_to_sell, available_shares)
            remaining_shares_to_sell -= shares_to_sell
            
            logger.info(f"Placing sell order for {shares_to_sell} shares in account {account_id}")
            await place_order(symbol, shares_to_sell, limit_price, account_id, order_type='SELL', cookies=cookies, csrf_token=csrf_token)
            
            # If all required shares have been sold, stop
            if remaining_shares_to_sell <= 0:
                break
        
    except Exception as e:
        logger.error(f"Error during sell transaction for {symbol}: {e}")
        await printAndDiscord(f"Error during sell transaction for {symbol}: {e}", discord_loop)
        raise


async def fetch_funded_accounts(cookies):
    try:
        headers = {
            'accept': 'application/json',
            'content-type': 'application/json',
            'x-requested-with': 'XMLHttpRequest',
            'user-agent': 'Mozilla/5.0'
        }
        url = 'https://www.sofi.com/wealth/backend/api/v1/user/funded-brokerage-accounts'
        response = requests.get(url, headers=headers, cookies=cookies)
        if response.status_code == 200:
            accounts = response.json()
            return accounts
        else:
            logger.error(f"Failed to fetch funded accounts. Status code: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error fetching funded accounts: {e}")
        return None


async def fetch_stock_price(symbol):
    try:
        headers = {
            'accept': 'application/json',
            'x-requested-with': 'XMLHttpRequest',
            'user-agent': 'Mozilla/5.0'
        }
        url = f'https://www.sofi.com/wealth/backend/api/v1/tearsheet/quote?symbol={symbol}&productSubtype=BROKERAGE'
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            price = data.get("price")
            if price:
                # Round the price to the nearest second decimal place
                rounded_price = round(float(price), 2)
                return rounded_price
            else:
                return None
        else:
            logger.error(f"Failed to fetch stock price for {symbol}. Status code: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error fetching stock price for {symbol}: {e}")
        return None


async def place_order(symbol, quantity, limit_price, account_id, order_type, cookies, csrf_token):
    try:
        headers = {
            'accept': 'application/json',
            'content-type': 'application/json',
            'x-requested-with': 'XMLHttpRequest',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
            'csrf-token': csrf_token,
            'origin': 'https://www.sofi.com',
            'referer': 'https://www.sofi.com/',
            'sec-fetch-site': 'same-origin',
            'sec-fetch-mode': 'cors',
            'sec-fetch-dest': 'empty'
        }

        payload = {
            "operation": order_type,
            "quantity": str(quantity),
            "time": "DAY",
            "type": "LIMIT",
            "limitPrice": limit_price,
            "symbol": symbol,
            "accountId": account_id,
            "tradingSession": "CORE_HOURS"
        }

        url = 'https://www.sofi.com/wealth/backend/api/v1/trade/order'
        response = requests.post(url, json=payload, headers=headers, cookies=cookies)
        
        if response.status_code == 200:
            logger.info(f"Limit order placed successfully for {symbol}.")
            return response.json()
        else:
            logger.error(f"Failed to place order for {symbol}. Status code: {response.status_code}")
            logger.error(f"Response text: {response.text}")
            return None
    except Exception as e:
        logger.error(f"Error placing order for {symbol}: {e}")
        return None


if __name__ == '__main__':
    logger.info("Starting SoFi bot...")
    sofi_obj = sofi_init()
    logger.info("SoFi bot finished execution.")
