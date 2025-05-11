import asyncio
import datetime
import os
import traceback
from time import sleep

import nodriver as uc
import pyotp
from curl_cffi import requests
from dotenv import load_dotenv

from helperAPI import (
    Brokerage,
    getOTPCodeDiscord,
    maskString,
    printAndDiscord,
    printHoldings,
    stockOrder,
)

load_dotenv()

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


def build_headers(csrf_token=None):
    headers = {
        "accept": "application/json",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "x-requested-with": "XMLHttpRequest",
    }
    if csrf_token is not None:
        headers["csrf-token"] = csrf_token
        headers["origin"] = "https://www.sofi.com"
        headers["referer"] = "https://www.sofi.com/"
        headers["sec-fetch-site"] = "same-origin"
        headers["sec-fetch-mode"] = "cors"
        headers["sec-fetch-dest"] = "empty"
    return headers


async def save_cookies_to_pkl(browser, cookie_filename):
    try:
        await browser.cookies.save(cookie_filename)
    except Exception as e:
        print(f"Failed to save cookies: {e}")


async def load_cookies_from_pkl(browser, page, cookie_filename):
    try:
        await browser.cookies.load(cookie_filename)
        await page.reload()
        return True
    except ValueError as e:
        print(f"Failed to load cookies: {e}")
    except FileNotFoundError:
        print("Cookie file does not exist.")
    return False


async def sofi_error(error: str, page=None, discord_loop=None):
    if page is not None:
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_name = f"SoFi-error-{timestamp}.png"
            await page.save_screenshot(filename=screenshot_name, full_page=True)
        except Exception as e:
            print(f"Failed to take screenshot: {e}")
    try:
        printAndDiscord(f"Sofi error: {error}", discord_loop)
        print(f"SoFi Error: {traceback.format_exc()}")
    except Exception as e:
        print(f"Failed to log error: {e}")


async def get_current_url(page, discord_loop):
    """Get the current page URL by evaluating JavaScript."""
    await page.sleep(1)
    await page.select("body")
    try:
        # Run JavaScript to get the current URL
        current_url = await page.evaluate("window.location.href")
        return current_url
    except Exception as e:
        await sofi_error(
            f"Error fetching the current URL {e}", page=page, discord_loop=discord_loop
        )
        return None


def sofi_run(
    orderObj: stockOrder, command=None, botObj=None, loop=None, SOFI_EXTERNAL=None
):
    print("Initializing SoFi process...")
    load_dotenv()
    create_creds_folder()
    discord_loop = (
        loop  # Keep the parameter as "loop" for consistency with other init functions
    )
    browser = None

    if not os.getenv("SOFI") and SOFI_EXTERNAL is None:
        return None

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

    cookie_filename = None
    try:
        for account in accounts:
            index = accounts.index(account) + 1
            name = f"SoFi {index}"
            cookie_filename = f"{COOKIES_PATH}/{name}.pkl"
            browser_args = [
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
            ]
            if headless:
                browser_args.append("--headless=new")
            browser = sofi_loop.run_until_complete(uc.start(browser_args=browser_args))
            print(f"Logging into {name}...")
            sofi_init(
                account, name, cookie_filename, botObj, browser, discord_loop, sofi_obj
            )
            sofi_loop.run_until_complete(browser.sleep(5))
            print(f"Logged in to {name}!")
            if second_command == "_holdings":
                sofi_holdings(browser, name, sofi_obj, discord_loop)
            else:
                sofi_transaction(browser, orderObj, discord_loop)
    except Exception as e:
        sofi_loop.run_until_complete(
            sofi_error(
                f"Error during SoFi init process: {e}", discord_loop=discord_loop
            )
        )
        return None
    finally:
        if browser:
            try:
                sofi_loop.run_until_complete(
                    save_cookies_to_pkl(browser, cookie_filename)
                )
                browser.stop()
            except Exception as e:
                sofi_loop.run_until_complete(
                    sofi_error(
                        f"Error closing the browser: {e}", discord_loop=discord_loop
                    )
                )
    return None


def sofi_init(
    account, name, cookie_filename, botObj, browser, discord_loop, sofi_obj: Brokerage
):
    page = None
    try:
        sleep(5)
        account = account.split(":")

        # The page sometimes doesn't load until after retrying
        max_attempts = 5
        attempts = 0
        while attempts < max_attempts:
            page = sofi_loop.run_until_complete(browser.get("https://www.sofi.com/"))
            sofi_loop.run_until_complete(page)  # Wait for events to be processed
            current_url = sofi_loop.run_until_complete(
                get_current_url(page, discord_loop)
            )
            if current_url == "https://www.sofi.com/":
                break

            attempts += 1

        # Load cookies
        sofi_loop.run_until_complete(page)  # Wait for events to be processed
        page = sofi_loop.run_until_complete(browser.get("https://www.sofi.com"))
        sofi_loop.run_until_complete(browser.sleep(5))
        cookies_loaded = sofi_loop.run_until_complete(
            load_cookies_from_pkl(browser, page, cookie_filename)
        )

        if cookies_loaded:
            sofi_loop.run_until_complete(page.get("https://www.sofi.com/wealth/app/"))
            sofi_loop.run_until_complete(browser.sleep(5))
            sofi_loop.run_until_complete(page.select("body"))
            current_url = sofi_loop.run_until_complete(
                get_current_url(page, discord_loop)
            )

            if current_url and "overview" in current_url:
                sofi_loop.run_until_complete(
                    save_cookies_to_pkl(browser, cookie_filename)
                )
                return sofi_obj

        # Proceed with login if cookies are invalid or expired
        sofi_loop.run_until_complete(
            sofi_login_and_account(browser, page, account, name, botObj, discord_loop)
        )
        sofi_obj.set_logged_in_object(name, browser)
    except Exception as e:
        sofi_loop.run_until_complete(
            sofi_error(
                f"Error during SoFi init process: {e}",
                page=page,
                discord_loop=discord_loop,
            )
        )
        return None
    return sofi_obj


async def sofi_login_and_account(browser, page, account, name, botObj, discord_loop):
    try:
        sleep(5)
        page = await browser.get("https://www.sofi.com")
        if not page:
            raise Exception(f"Failed to load SoFi login page for {name}")

        await page.get("https://www.sofi.com/wealth/app")
        sleep(2)
        username_input = await page.select("input[id=username]")
        if not username_input:
            raise Exception(f"Unable to locate the username input field for {name}")
        await username_input.send_keys(account[0])

        password_input = await page.select("input[type=password]")
        if not password_input:
            raise Exception(f"Unable to locate the password input field for {name}")
        await password_input.send_keys(account[1])

        login_button = await page.find("Log In", best_match=True)
        if not login_button:
            raise Exception(f"Unable to locate the login button for {name}")
        await login_button.click()

        await page.select("body")

        current_url = await get_current_url(page, discord_loop)
        if current_url is not None and "overview" not in current_url:
            await handle_2fa(page, account, name, botObj, discord_loop)
    except Exception as e:
        await sofi_error(
            f"Error logging into account {name}: {e}",
            page=page,
            discord_loop=discord_loop,
        )


async def sofi_account_info(browser, discord_loop):
    try:
        await browser.sleep(1)
        await browser.get("https://www.sofi.com/wealth/app/overview")
        await browser.sleep(5)

        cookies = await browser.cookies.get_all()
        cookies_dict = {cookie.name: cookie.value for cookie in cookies}
        response = requests.get(
            "https://www.sofi.com/wealth/backend/v1/json/accounts",
            impersonate="chrome",
            headers=build_headers(),
            cookies=cookies_dict,
        )

        if response.status_code != 200:
            raise Exception(
                f"Failed to fetch account info, status code: {response.status_code}"
            )

        accounts_data = response.json()
        account_dict = {}

        for account in accounts_data:
            account_number = account["apexAccountId"]
            account_id = account["id"]
            account_type = account["type"]["description"]
            current_value = account["totalEquityValue"]

            account_dict[account_number] = {
                "type": account_type,
                "balance": float(current_value),
                "id": account_id,
            }
        return account_dict
    except Exception as e:
        await sofi_error(
            f"Error fetching SoFi account information: {e}", discord_loop=discord_loop
        )
        return None


def sofi_holdings(browser, name, sofi_obj: Brokerage, discord_loop):
    account_dict: dict = sofi_loop.run_until_complete(
        sofi_account_info(browser, discord_loop)
    )
    if not account_dict:
        raise Exception(f"Failed to retrieve account info for {name}")

    for acct, account_info in account_dict.items():
        real_account_number = acct
        sofi_obj.set_account_number(name, real_account_number)
        sofi_obj.set_account_totals(name, real_account_number, account_info["balance"])

        account_id = account_info.get("id")
        cookies = {
            cookie.name: cookie.value
            for cookie in sofi_loop.run_until_complete(browser.cookies.get_all())
        }

        try:
            holdings = sofi_loop.run_until_complete(
                get_holdings_formatted(account_id, cookies)
            )
        except Exception as e:
            sofi_loop.run_until_complete(
                sofi_error(
                    f"Error fetching holdings for SOFI account {maskString(account_id)}: {e}",
                    discord_loop=discord_loop,
                )
            )
            continue

        for holding in holdings:
            company_name = holding.get("company_name", "N/A")
            if company_name == "|CASH|":
                continue

            shares = holding.get("shares", "N/A")
            price = holding.get("price", "N/A")
            sofi_obj.set_holdings(
                name, real_account_number, company_name, shares, price
            )

    # Log info after holdings are processed
    print(f"All holdings processed for {name}.")
    printHoldings(sofi_obj, discord_loop)


async def get_holdings_formatted(account_id, cookies):
    holdings_url = f"https://www.sofi.com/wealth/backend/api/v3/account/{account_id}/holdings?accountDataType=INTERNAL"
    response = requests.get(
        holdings_url, impersonate="chrome", headers=build_headers(), cookies=cookies
    )

    if response.status_code != 200:
        raise Exception(
            f"Failed to fetch holdings, status code: {response.status_code}"
        )

    holdings_data = response.json()

    formatted_holdings = []

    for holding in holdings_data.get("holdings", []):
        company_name = holding.get("symbol", "N/A")
        shares = holding.get("shares", "N/A")
        price = holding.get("price", "N/A")

        formatted_holdings.append(
            {
                "company_name": company_name if company_name else "N/A",
                "shares": float(shares) if shares is not None else "N/A",
                "price": float(price) if price is not None else "N/A",
            }
        )

    return formatted_holdings


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
        # Checks for people that don't read the README
        if isinstance(secret, str) and (
            secret.lower() == "none" or secret.lower() == "false"
        ):
            secret = None
        if secret is not None:
            try:
                remember = await asyncio.wait_for(
                    page.select("input[id=rememberBrowser]"), timeout=5
                )
                if remember:
                    await remember.click()
            except asyncio.TimeoutError:
                print(
                    f"'rememberBrowser' checkbox not found for {name}. Continuing without it..."
                )

            # Continue with 2FA input
            twofa_input = await page.select("input[id=code]")
            if not twofa_input:
                raise Exception(f"Unable to locate 2FA input field for {name}")

            two_fa_code = get_2fa_code(secret)  # Get the OTP from the authenticator app
            await twofa_input.send_keys(two_fa_code)
            verify_button = await page.find("Verify Code")
            if verify_button:
                await verify_button.click()
        else:
            # Set a timeout duration for finding the SMS 2FA element
            sms_2fa_element = None
            try:
                sms_2fa_element = await asyncio.wait_for(
                    page.find("We've sent a text message to:", best_match=True),
                    timeout=5,
                )
            except asyncio.TimeoutError:
                print(
                    f"SMS 2FA text not found for {name}, proceeding to check for authenticator app 2FA..."
                )

            if sms_2fa_element:
                # SMS 2FA handling
                try:
                    remember = await asyncio.wait_for(
                        page.select("input[id=rememberBrowser]"), timeout=5
                    )
                    if remember:
                        await remember.click()
                except asyncio.TimeoutError:
                    print(
                        f"'rememberBrowser' checkbox not found for {name}. Continuing without it..."
                    )

                sms2fa_input = await page.select("input[id=code]")
                if not sms2fa_input:
                    raise Exception(f"Unable to locate SMS 2FA input field for {name}")

                if botObj is not None and discord_loop is not None:
                    sms_code = asyncio.run_coroutine_threadsafe(
                        getOTPCodeDiscord(botObj, name, timeout=300, loop=discord_loop),
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
            else:
                raise Exception(f"No valid 2FA method found for {name}.")

    except Exception as e:
        await sofi_error(
            f"Error during 2FA handling for {name}: {e}",
            page=page,
            discord_loop=discord_loop,
        )


def sofi_transaction(browser, orderObj: stockOrder, discord_loop):
    dry_mode = orderObj.get_dry()
    for stock in orderObj.get_stocks():
        if orderObj.get_action() == "buy":
            sofi_loop.run_until_complete(
                sofi_buy(browser, stock, orderObj.get_amount(), discord_loop, dry_mode)
            )
        elif orderObj.get_action() == "sell":
            sofi_loop.run_until_complete(
                sofi_sell(browser, stock, orderObj.get_amount(), discord_loop, dry_mode)
            )
        else:
            print(f"Unknown action: {orderObj.get_action()}")


async def sofi_buy(browser, symbol, quantity, discord_loop, dry_mode=False):
    page = None
    try:
        # Step 1: Navigate to stock page and get valid cookies
        stock_url = f"https://www.sofi.com/wealth/app/stock/{symbol}"
        page = await browser.get(stock_url)
        await page.select("body")

        cookies = {
            cookie.name: cookie.value for cookie in await browser.cookies.get_all()
        }
        if not cookies:
            raise Exception("Failed to retrieve valid cookies for the session.")

        csrf_token = cookies.get("SOFI_CSRF_COOKIE") or cookies.get("SOFI_R_CSRF_TOKEN")
        if not csrf_token:
            raise Exception("Failed to retrieve CSRF token from cookies.")

        # Step 2: Get the stock price
        stock_price = await fetch_stock_price(symbol)
        if stock_price is None:
            raise Exception(f"Failed to retrieve stock price for {symbol}")

        limit_price = stock_price

        # Step 3: Fetch all funded accounts and their buying power
        accounts = await fetch_funded_accounts(cookies)
        if not accounts:
            raise Exception("Failed to retrieve funded accounts or none available.")

        # Step 4: Loop through all accounts to check buying power and place the limit order
        for account in accounts:
            account_id = account["accountId"]
            buying_power = account["accountBuyingPower"]
            account_name = account.get("accountType")

            total_price = limit_price * quantity
            if total_price <= buying_power:
                if dry_mode:
                    # Dry mode: Log what would have been done
                    printAndDiscord(
                        f"[DRY MODE] Would place limit order for {symbol} in account {account_name} with limit price: {limit_price}",
                        discord_loop,
                    )
                    continue

                if quantity < 1:
                    result = await place_fractional_order(
                        symbol,
                        quantity,
                        account_id,
                        order_type="BUY",
                        cookies=cookies,
                        csrf_token=csrf_token,
                        discord_loop=discord_loop,
                    )
                else:
                    result = await place_order(
                        symbol,
                        quantity,
                        limit_price,
                        account_id,
                        order_type="BUY",
                        cookies=cookies,
                        csrf_token=csrf_token,
                        discord_loop=discord_loop,
                    )
                if result["header"] == "Your order is placed.":  # Success
                    printAndDiscord(
                        f"Successfully bought {quantity} of {symbol} in account {maskString(account_id)}",
                        discord_loop,
                    )
            else:
                printAndDiscord(
                    f"Insufficient buying power in {account_name}. Needed: {total_price}, Available: {buying_power}",
                    discord_loop,
                )
    except Exception as e:
        await sofi_error(
            f"Error during buy transaction for {symbol}: {e}",
            page=page,
            discord_loop=discord_loop,
        )


async def sofi_sell(browser, symbol, quantity, discord_loop, dry_mode=False):
    try:
        # Step 1: Fetch holdings for the stock symbol
        cookies = {
            cookie.name: cookie.value for cookie in await browser.cookies.get_all()
        }
        if not cookies:
            raise Exception("Failed to retrieve valid cookies for the session.")

        csrf_token = cookies.get("SOFI_CSRF_COOKIE") or cookies.get("SOFI_R_CSRF_TOKEN")
        if not csrf_token:
            raise Exception("Failed to retrieve CSRF token from cookies.")

        # Fetch holdings for the specific symbol
        holdings_url = f"https://www.sofi.com/wealth/backend/api/v3/customer/holdings/symbol/{symbol}"
        response = requests.get(
            holdings_url, impersonate="chrome", headers=build_headers(), cookies=cookies
        )

        if response.status_code != 200:
            raise Exception(
                f"Failed to fetch holdings for {symbol}. Status code: {response.status_code}"
            )

        holdings_data = response.json()
        account_holding_infos = holdings_data.get("accountHoldingInfos", [])

        if not account_holding_infos:
            raise Exception(
                f"No holdings found for symbol {symbol}. Cannot proceed with the sell order."
            )

        total_available_shares = sum(
            info["salableQuantity"] for info in account_holding_infos
        )

        if total_available_shares < quantity:
            raise Exception(
                f"Not enough shares to sell. Available: {total_available_shares}, Requested: {quantity}"
            )

        stock_price = await fetch_stock_price(symbol)
        if stock_price is None:
            raise Exception(f"Failed to retrieve stock price for {symbol}")

        limit_price = round(stock_price - 0.01, 2)

        # Loop through all accounts holding the stock
        for account in account_holding_infos:
            account_id = account["accountId"]
            available_shares = account["salableQuantity"]

            # Skip accounts where available shares are less than the quantity to sell
            if available_shares < quantity:
                printAndDiscord(
                    f"Not enough shares to sell {quantity} of {symbol} in account {maskString(account_id)}. Only {available_shares} available.",
                    discord_loop,
                )
                continue  # Move to the next account

            if dry_mode:
                # Dry mode: Log what would have been done
                printAndDiscord(
                    f"[DRY MODE] Would place sell order for {quantity} shares of {symbol} in account {maskString(account_id)}",
                    discord_loop,
                )
                continue

            if quantity < 1:
                result = await place_fractional_order(
                    symbol,
                    quantity,
                    account_id,
                    order_type="SELL",
                    cookies=cookies,
                    csrf_token=csrf_token,
                    discord_loop=discord_loop,
                )
            else:
                # Place the sell order
                result = await place_order(
                    symbol,
                    quantity,
                    limit_price,
                    account_id,
                    order_type="SELL",
                    cookies=cookies,
                    csrf_token=csrf_token,
                    discord_loop=discord_loop,
                )
            if result["header"] == "Your order is placed.":  # Success
                printAndDiscord(
                    f"Successfully sold {quantity} of {symbol} in account {maskString(account_id)}",
                    discord_loop,
                )
    except Exception as e:
        await sofi_error(
            f"Error during sell transaction for {symbol}: {e}",
            discord_loop=discord_loop,
        )


async def fetch_funded_accounts(cookies):
    try:
        url = (
            "https://www.sofi.com/wealth/backend/api/v1/user/funded-brokerage-accounts"
        )
        response = requests.get(
            url, impersonate="chrome", headers=build_headers(), cookies=cookies
        )
        if response.status_code == 200:
            accounts = response.json()
            return accounts
        print(f"Failed to fetch funded accounts. Status code: {response.status_code}")
        return None
    except Exception as e:
        await sofi_error(f"Error fetching funded accounts: {e}")
        return None


async def fetch_stock_price(symbol):
    try:
        url = f"https://www.sofi.com/wealth/backend/api/v1/tearsheet/quote?symbol={symbol}&productSubtype=BROKERAGE"
        response = requests.get(url, impersonate="chrome", headers=build_headers())
        if response.status_code == 200:
            data = response.json()
            price = data.get("price")
            if price:
                # Round the price to the nearest second decimal place
                rounded_price = round(float(price), 2)
                return rounded_price
            return None
        print(
            f"Failed to fetch stock price for {symbol}. Status code: {response.status_code}"
        )
        return None
    except Exception as e:
        await sofi_error(f"Error fetching stock price for {symbol}: {e}")
        return None


async def place_order(
    symbol,
    quantity,
    limit_price,
    account_id,
    order_type,
    cookies,
    csrf_token,
    discord_loop=None,
):
    try:
        payload = {
            "operation": order_type,
            "quantity": str(quantity),
            "time": "DAY",
            "type": "LIMIT",
            "limitPrice": limit_price,
            "symbol": symbol,
            "accountId": account_id,
            "tradingSession": "CORE_HOURS",
        }

        url = "https://www.sofi.com/wealth/backend/api/v1/trade/order"
        response = requests.post(
            url,
            impersonate="chrome",
            json=payload,
            headers=build_headers(csrf_token),
            cookies=cookies,
        )

        if response.status_code == 200:
            return response.json()

        print(
            f"Failed to place order for {symbol}. Status code: {response.status_code}"
        )
        print(f"Response text: {response.text}")
        if "cannot be traded" in response.text.lower():
            raise Exception(f"{symbol} cannot traded")
        return None
    except Exception as e:
        await sofi_error(
            f"Error placing order for {symbol}: {e}", discord_loop=discord_loop
        )
        return None


async def place_fractional_order(
    symbol, quantity, account_id, order_type, cookies, csrf_token, discord_loop=None
):
    try:
        # Step 1: Fetch the current stock price to calculate cashAmount
        stock_price = await fetch_stock_price(symbol)
        if stock_price is None:
            raise Exception(f"Failed to retrieve stock price for {symbol}")

        # Calculate the cash amount based on the quantity of fractional shares
        cash_amount = round(
            stock_price * quantity, 2
        )  # Round to 2 decimal places for currency

        # Step 2: Prepare payload for the fractional sell order
        payload = {
            "operation": order_type,
            "cashAmount": cash_amount,  # Calculated cash amount based on stock price and quantity
            "quantity": quantity,
            "symbol": symbol,
            "accountId": account_id,
            "time": "DAY",
            "type": "MARKET",
            "tradingSession": "CORE_HOURS",
            "sellAll": False,
        }

        # Step 3: Send the request to sell fractional shares
        url = "https://www.sofi.com/wealth/backend/api/v1/trade/order-fractional"
        response = requests.post(
            url,
            impersonate="chrome",
            json=payload,
            headers=build_headers(csrf_token),
            cookies=cookies,
        )

        if response.status_code == 200:
            return response.json()

        print(
            f"Failed to place fractional sell order for {symbol}. Status code: {response.status_code}"
        )
        print(f"Response text: {response.text}")
        if "cannot be traded" in response.text.lower():
            raise Exception(f"{symbol} cannot traded")
        return None
    except Exception as e:
        await sofi_error(
            f"Error placing fractional order for {symbol}: {e}",
            discord_loop=discord_loop,
        )
        return None
