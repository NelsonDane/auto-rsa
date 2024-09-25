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


def create_creds_folder():
    """Create the 'creds' folder if it doesn't exist."""
    if not os.path.exists(COOKIES_PATH):
        os.makedirs(COOKIES_PATH)
        logger.info(f"Created '{COOKIES_PATH}' folder.")


async def save_cookies_to_pkl(browser, filename):
    try:
        await browser.cookies.save(filename)
        print("Cookies saved.")
    except Exception as e:
        print(f"Failed to save cookies: {e}")


async def load_cookies_from_pkl(browser, page, filename):
    try:
        await browser.cookies.load(filename)
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
    try:
        # Wait for the page to fully load
        await page.reload()  # This ensures the page has fully loaded
        # Run JavaScript to get the current URL
        current_url = await page.evaluate("window.location.href")
        return current_url
    except Exception as e:
        logger.error(f"Error fetching the current URL: {e}")
        return None


def sofi_init(SOFI_EXTERNAL=None, botObj=None, loop=None):
    logger.info("Initializing SoFi process...")
    load_dotenv()
    create_creds_folder()
    discord_loop = loop  # Keep the parameter as "loop" for consistency with other init functions

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

    browser = None
    try:
        # Get or create the event loop
        try:
            sofi_loop = asyncio.get_event_loop()
        except RuntimeError:
            sofi_loop = asyncio.new_event_loop()

        # Start the browser once and use it for all accounts
        browser_args = [
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
        ]
        if headless:
            browser_args.append("--headless=new")
        browser = sofi_loop.run_until_complete(uc.start(browser_args=browser_args))

        for account in accounts:
            index = accounts.index(account) + 1
            name = f"SoFi {index}"
            account = account.split(":")
            cookie_filename = f"{COOKIES_PATH}/sofi_{index}.pkl"  # Save in creds folder with .pkl extension

            # Load cookies
            page = sofi_loop.run_until_complete(browser.get('https://www.sofi.com'))
            cookies_loaded = sofi_loop.run_until_complete(load_cookies_from_pkl(browser, page, cookie_filename))
            
            if cookies_loaded:
                logger.info(f"Cookies loaded for {name}, checking if login is valid...")
                sofi_loop.run_until_complete(page.get('https://www.sofi.com/wealth/app/overview'))
                current_url = sofi_loop.run_until_complete(get_current_url(page))

                if current_url and "overview" in current_url:
                    logger.info(f"Successfully bypassed login for {name} using cookies.")
                    sofi_loop.run_until_complete(save_cookies_to_pkl(browser, cookie_filename))
                    sofi_loop.run_until_complete(fetch_account_info_and_holdings(browser, name, sofi_obj,
                                                                                 discord_loop))
                    continue  # Skip to the next account if successfully logged in

            # Proceed with login if cookies are invalid or expired
            sofi_loop.run_until_complete(sofi_login_and_account(browser, account, name, botObj, sofi_obj, discord_loop))
            sofi_loop.run_until_complete(save_cookies_to_pkl(browser, cookie_filename))
        logger.info("Finished processing all accounts. Printing holdings...")
        printHoldings(sofi_obj, discord_loop)
    except Exception as e:
        logger.error(f"Error during SoFi process: {e}")
    finally:
        if browser:
            try:
                logger.info("Closing the browser...")
                browser.stop()
            except Exception as e:
                logger.error(f"Error closing the browser: {e}")

    return sofi_obj


async def fetch_account_info_and_holdings(browser, name, sofi_obj, discord_loop):
    """Fetch account info and holdings without logging in."""
    logger.info(f"Fetching account info for {name}...")
    account_dict = await sofi_account_info(browser, discord_loop)

    if not account_dict:
        raise Exception(f"Failed to retrieve account info for {name}")

    logger.info(f"Processing holdings for {name}...")
    for acct, account_info in account_dict.items():
        real_account_number = acct
        sofi_obj.set_account_number(name, real_account_number)
        sofi_obj.set_account_totals(name, real_account_number, account_info["balance"])

        account_id = account_info.get('id')
        cookies = {cookie.name: cookie.value for cookie in await browser.cookies.get_all()}

        holdings = await sofi_holdings(account_id, cookies)

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


async def sofi_login_and_account(browser, account, name, botObj, sofi_obj, discord_loop):
    try:
        logger.info(f"Navigating to SoFi login page for {name}...")
        page = await browser.get('https://www.sofi.com')
        if not page:
            raise Exception(f"Failed to load SoFi login page for {name}")

        await page.get('https://www.sofi.com/login')
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

        await handle_2fa(page, account, name, botObj, discord_loop)

        logger.info(f"Fetching account info for {name}...")
        account_dict = await sofi_account_info(browser, discord_loop)

        if not account_dict:
            raise Exception(f"Failed to retrieve account info for {name}")

        logger.info(f"Processing holdings for {name}...")
        for acct, account_info in account_dict.items():
            real_account_number = acct
            sofi_obj.set_account_number(name, real_account_number)
            sofi_obj.set_account_totals(name, real_account_number, account_info["balance"])

            account_id = account_info.get('id')
            cookies = {cookie.name: cookie.value for cookie in await browser.cookies.get_all()}

            holdings = await sofi_holdings(account_id, cookies)

            for holding in holdings:
                company_name = holding.get('company_name', 'N/A')
                if company_name == '|CASH|':
                    continue

                shares = holding.get('shares', 'N/A')
                price = holding.get('price', 'N/A')
                sofi_obj.set_holdings(name, real_account_number, company_name, shares, price)

            logger.info(f"Completed processing holdings for account {real_account_number}")

        sofi_obj.set_logged_in_object(name, browser)

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


async def sofi_holdings(account_id, cookies):
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
        return []


def get_2fa_code(secret):
    totp = pyotp.TOTP(secret)
    return totp.now()


async def handle_2fa(page, account, name, botObj, discord_loop):
    """
    Handle both authenticator app 2FA and SMS-based 2FA.
    """
    try:
        # Set a timeout duration for finding the SMS 2FA element
        sms_2fa_element = None
        try:
            # Try to find the SMS text message element with a timeout
            sms_2fa_element = await asyncio.wait_for(
                page.find("We've sent a text message to:", best_match=True),
                timeout=5  # Adjust this timeout as needed
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
                sms_code = await getOTPCodeDiscord(botObj, name, loop=discord_loop)
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
                raise Exception(f"No valid 2FA method found for {name}.")
        
    except Exception as e:
        logger.error(f"Error during 2FA handling for {name}: {e}")
        printAndDiscord(f"Error during 2FA handling for {name}", discord_loop)
        raise



if __name__ == '__main__':
    logger.info("Starting SoFi bot...")
    sofi_obj = sofi_init()
    logger.info("SoFi bot finished execution.")
