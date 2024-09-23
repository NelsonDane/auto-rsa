import asyncio
import os
import logging
from dotenv import load_dotenv
import pyotp
import nodriver as uc
import requests
import traceback
import datetime

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

async def sofi_error(page, loop=None):
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
        printAndDiscord(error_message, loop, embed=False)
    except Exception as e:
        print(f"Failed to log error: {str(e)}")


def sofi_init(SOFI_EXTERNAL=None, botObj=None, loop=None):
    logger.info("Initializing SoFi process...")
    load_dotenv()

    if not os.getenv("SOFI") and SOFI_EXTERNAL is None:
        logger.error("SoFi environment variable not found.")
        printAndDiscord("SoFi environment variable not found.", loop)
        return None

    logger.info("Loading SoFi accounts...")
    accounts = (
        os.environ["SOFI"].strip().split(",")
        if SOFI_EXTERNAL is None
        else SOFI_EXTERNAL.strip().split(",")
    )
    sofi_obj = Brokerage("SoFi")

    for account in accounts:
        index = accounts.index(account) + 1
        name = f"SoFi {index}"
        account = account.split(":")

        logger.info(f"Starting login process for {name}...")
        try:
            browser = asyncio.run(uc.start(browser_args=[
                "--headless=new", 
                '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'
                ]))

            asyncio.run(sofi_login_and_account(browser, account, name, sofi_obj, loop))

        except Exception as e:
            logger.error(f"Error in {name}: {e}")
            return None

    logger.info("Finished processing all accounts. Printing holdings...")
    printHoldings(sofi_obj, loop)
    return sofi_obj


async def sofi_login_and_account(browser, account, name, sofi_obj, loop):
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

        secret = account[2] if len(account) > 2 else None
        if secret:
            logger.info(f"Handling 2FA for {name}...")
            twofa = await page.select("input[id=code]")
            if not twofa:
                raise Exception(f"Unable to locate 2FA input field for {name}")
            two_fa_code = get_2fa_code(secret)
            await twofa.send_keys(two_fa_code)
            verify_button = await page.find("Verify Code")
            if verify_button:
                await verify_button.click()
        else:
            try:
                logger.info(f"Waiting for SMS 2FA for {name}...")
                await page.wait_for_selector("#code")
                sms_code = input("Enter security code: ")
                await page.find("#code", sms_code)
                await page.click('//*[@id="widget_block"]/div/div[2]/div/div/main/section/div/div/div/form/div[2]')
            except:
                logger.error(f"Error during 2FA handling for {name}")
                printAndDiscord("Error during 2FA handling", loop)

        logger.info(f"Fetching account info for {name}...")
        account_dict = await sofi_account_info(browser, loop)

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
        await sofi_error(page, loop)
        raise


async def sofi_account_info(browser, loop) -> dict:
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
        await sofi_error(page, loop)
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


if __name__ == '__main__':
    logger.info("Starting SoFi bot...")
    sofi_obj = sofi_init()
    logger.info("SoFi bot finished execution.")
