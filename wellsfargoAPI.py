import asyncio
import datetime
import os
import re
import traceback
from time import sleep
import json
from bs4 import BeautifulSoup

import zendriver as uc
from zendriver import SpecialKeys, KeyEvents, KeyPressEvent 
from dotenv import load_dotenv

# Assuming helperAPI.py is in the same directory or accessible in PYTHONPATH
from helperAPI import (
    Brokerage,
    getOTPCodeDiscord,
    printAndDiscord,
    printHoldings,
    stockOrder,
    maskString,
)

load_dotenv()

# Controls detailed logging. Set to "true" in your .env file to enable.
DEBUG = os.getenv("WELLSFARGO_DEBUG", "false").lower() == "true"

def log(message):
    """Prints a message to the console if DEBUG is True."""
    if DEBUG:
        print(f"[DEBUG] {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}")

COOKIES_PATH = "creds"
# wf_loop for Wells Fargo specific asyncio operations
try:
    wf_loop = asyncio.get_event_loop()
except RuntimeError:
    wf_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(wf_loop)


def create_creds_folder():
    """Create the 'creds' folder if it doesn't exist."""
    log("Checking if 'creds' folder exists.")
    if not os.path.exists(COOKIES_PATH):
        os.makedirs(COOKIES_PATH)
        log("'creds' folder created.")


async def wellsfargo_error(error: str, page=None, discord_loop=None, browser=None):
    print(f"Wells Fargo Error: {error}")
    log(f"Error encountered: {error}")
    if page:
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_name = f"wells-fargo-error-{timestamp}.png"
            await page.save_screenshot(filename=screenshot_name)
            print(f"Screenshot saved: {screenshot_name}")
            log(f"Screenshot saved to {screenshot_name}")
        except Exception as e:
            print(f"Failed to take screenshot: {e}")
            log(f"Failed to take screenshot: {e}")
    if discord_loop:
        printAndDiscord(f"Wells Fargo Error: {error}\n{traceback.format_exc()}", discord_loop)
    else:
        print(traceback.format_exc())
    if browser:
        try:
            await browser.stop()
            log("Browser stopped due to error.")
        except Exception as e_stop_err:
            print(f"Error trying to stop browser in wellsfargo_error: {e_stop_err}")


async def get_current_url(page, discord_loop):
    """Get the current page URL by evaluating JavaScript."""
    log("Attempting to get current URL.")
    await page.sleep(1)
    await page.select("body")
    try:
        # Run JavaScript to get the current URL
        current_url = await page.evaluate("window.location.href")
        log(f"Current URL is: {current_url}")
        return current_url
    except Exception as e:
        await wellsfargo_error(
            f"Error fetching the current URL {e}", page=page, discord_loop=discord_loop
        )
        return None


def wellsfargo_run(orderObj=None, command=None, botObj=None, loop=None, WELLSFARGO_EXTERNAL=None):
    """
    Main function to run Wells Fargo operations using asyncio.
    This function itself is synchronous and designed to be called from a synchronous context (like autoRSA's fun_run).
    It then runs the async parts using the globally defined wf_loop.
    """
    print("Starting Wells Fargo run process...")
    log("wellsfargo_run initiated.")
    load_dotenv()
    create_creds_folder()
    discord_loop = loop

    if not os.getenv("WELLSFARGO") and WELLSFARGO_EXTERNAL is None:
        errmsg = "WELLSFARGO environment variable not found."
        print(errmsg)
        if discord_loop:
            printAndDiscord(errmsg, discord_loop)
        log("WELLSFARGO environment variable not set. Exiting.")
        return None

    accounts_env_str = os.environ.get("WELLSFARGO", "") if WELLSFARGO_EXTERNAL is None else WELLSFARGO_EXTERNAL
    accounts_env = accounts_env_str.strip().split(",")
    log(f"Found {len(accounts_env)} Wells Fargo account(s) in environment variables.")

    final_wf_brokerage_obj = Brokerage("WELLSFARGO")

    if command is None:
        action_to_perform = "_holdings"
    else:
        _, action_to_perform = command
    log(f"Action to perform: {action_to_perform}")

    try:
        # Run the async process and get the populated object back
        populated_obj = wf_loop.run_until_complete(
            _async_wellsfargo_run_wrapper(
                accounts_env,
                final_wf_brokerage_obj,
                action_to_perform,
                botObj,
                discord_loop,
                orderObj
            )
        )
        
        if populated_obj and orderObj:
            orderObj.set_logged_in(populated_obj, 'wellsfargo')
            log("Populated brokerage object set in main orderObj.")
            
        return populated_obj

    except Exception as e:
        print(f"Critical error in Wells Fargo async run wrapper: {e}")
        log(f"Critical error in async wrapper: {e}\n{traceback.format_exc()}")
        print(traceback.format_exc())
        return final_wf_brokerage_obj


async def handle_wellsfargo_2fa(page: uc.Tab, botObj, discord_loop):
    """Handles the Wells Fargo 2FA 'Verify Your Identity' page."""
    log("2FA page detected. Starting OTP process.")
    try:
        # Step 1: Find and click the 'Mobile' phone number button
        log("Looking for the 'Mobile' phone number option...")
        # We find all list items, then look for the one containing "Mobile" to be robust
        contact_options = await page.select_all('[role="listitem"]', timeout=10)
        mobile_button = None
        for option in contact_options:
            if "Mobile" in option.text_all:
                mobile_button = await option.select("button")
                break
        
        if not mobile_button:
            raise Exception("Could not find the 'Mobile' option for 2FA.")

        await mobile_button.click()
        log("Mobile option selected. Waiting for OTP input page.")
        await asyncio.sleep(5) # Wait for the next page to load

        # Step 2: Get the OTP code from the user via Discord
        log("Requesting OTP code from Discord.")
        otp_code = await getOTPCodeDiscord(botObj, "Wells Fargo", timeout=300, loop=discord_loop)
        if not otp_code:
            raise Exception("Did not receive Wells Fargo OTP code in time.")
        log("OTP code received.")

        # Step 3: Enter the OTP code
        log("Entering OTP code into the input field.")
        otp_input = await page.select("#otp", timeout=10)
        if not otp_input:
            raise Exception("Could not find the OTP input field with id='otp'.")
        await otp_input.send_keys(otp_code)

        # Step 4: Click the 'Continue' button
        log("Clicking the Continue button.")
        continue_button = await page.select('button[type="submit"]', timeout=10)
        if not continue_button:
            raise Exception("Could not find the final 'Continue' submit button.")
        
        await continue_button.click()
        log("2FA process submitted successfully.")
        # Wait for the login to complete and the main page to load
        await asyncio.sleep(5)

    except Exception as e:
        # Re-raise to be caught by the main error handler for screenshots
        raise Exception(f"Error during Wells Fargo 2FA process: {e}")


async def _async_wellsfargo_run_wrapper(accounts_env, wf_brokerage_obj_to_populate: Brokerage, action_to_perform, botObj, discord_loop, orderObj):
    headless = os.getenv("HEADLESS", "true").lower() == "true"
    print(f"Headless mode is {'enabled' if headless else 'disabled'}.")
    log(f"Headless mode: {headless}")

    for acc_idx, account_cred_str in enumerate(accounts_env):
        account_name_key = f"WELLSFARGO {acc_idx + 1}"
        cookie_filename = os.path.join(COOKIES_PATH, f"{account_name_key.replace(' ', '_')}_cookies.pkl")
        browser = None
        page = None
        log(f"Starting process for account: {account_name_key}")

        try:
            browser_args = []
            if headless:
                browser_args.append("--headless=new")
                browser_args.append("--window-size=1920,1080")
                browser_args.append("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")

            log("Starting browser...")
            browser = await uc.start(browser_args=browser_args)
            
            if not browser.tabs:
                page = await browser() 
            else:
                page = browser.tabs[0]
            log("Browser started and page object acquired.")

            await wellsfargo_init(
                account_cred_str,
                account_name_key,
                cookie_filename,
                botObj,
                browser,
                page, 
                wf_brokerage_obj_to_populate,
                discord_loop
            )

            if wf_brokerage_obj_to_populate.get_logged_in_objects(account_name_key):
                log(f"Login successful for {account_name_key}. Proceeding with action.")
                if not page or page.closed: 
                    if browser.tabs: page = browser.tabs[0]
                    else: page = await browser()

                if action_to_perform == "_holdings":
                    await wellsfargo_holdings(
                        wf_brokerage_obj_to_populate,
                        account_name_key,
                        browser,
                        page, 
                        discord_loop
                    )
                elif action_to_perform == "_transaction":
                    log(f"Calling wellsfargo_transaction for {account_name_key}.")
                    await wellsfargo_transaction(
                        wf_brokerage_obj_to_populate,
                        orderObj,
                        account_name_key,
                        browser,
                        page,
                        discord_loop
                    )
                print(f"Async process for account {account_name_key} completed.")

        except Exception as e:
            current_page_for_error = page if page and not page.closed else (browser.tabs[0] if browser and browser.tabs else None)
            await wellsfargo_error(f"Error during async Wells Fargo run for {account_name_key}: {e}", browser=browser, discord_loop=discord_loop, page=current_page_for_error)
        finally:
            if browser:
                try:
                    await browser.stop()
                    print(f"Browser stopped for {account_name_key}.")
                    log(f"Browser stopped for {account_name_key}.")
                except Exception as e_stop:
                    print(f"Error stopping browser for {account_name_key}: {e_stop}")
            browser = None
            page = None
    return wf_brokerage_obj_to_populate


async def wellsfargo_init(account_cred_str: str, account_name_key: str, cookie_filename: str, botObj, browser: uc.Browser, page: uc.Tab, wf_brokerage_obj: Brokerage, discord_loop):
    print(f"Initializing Wells Fargo login for {account_name_key}...")
    log(f"wellsfargo_init started for {account_name_key}.")
    try:
        credentials = account_cred_str.split(":")
        log("Credentials parsed.")

        if len(credentials) < 2:
            raise ValueError(f"Credential string for {account_name_key} is not in the expected format 'username:password[:phone_suffix]' Got: '{account_cred_str}'")

        phone_suffix_for_2fa = credentials[2] if len(credentials) > 2 else None
        log(f"2FA phone suffix: {'Provided' if phone_suffix_for_2fa else 'Not provided'}")

        log("Navigating to Wells Fargo Advisors homepage.")
        await page.get("https://www.wellsfargoadvisors.com/")

        log("Locating and filling username field.")
        username_field = await page.select("input[id=j_username]")
        await username_field.click()
        await username_field.clear_input()
        if not username_field:
            raise Exception(f"Unable to locate the username input field")
        await username_field.send_keys(credentials[0])

        log("Locating and filling password field.")
        password_field = await page.select("input[id=j_password]")
        if not password_field:
            raise Exception(f"Unable to locate the password input field")
        await password_field.send_keys(credentials[1])

        await browser.sleep(2)

        log("Clicking login button.")
        login_button = await page.select(".button.button--login.button--signOn", timeout=10)
        if not login_button: raise Exception("Login button not found.")
        await login_button.click()
        
        # Give the page a moment to redirect after login click
        await browser.sleep(3)
        await page.select("body")

        current_url = await get_current_url(page, discord_loop)

        # Check if we landed on the 2FA / Identity Verification page
        if "dest=INTERDICTION" in current_url:
            await handle_wellsfargo_2fa(page, botObj, discord_loop)
            # After 2FA, get the URL again to confirm we've moved on
            current_url = await get_current_url(page, discord_loop)

        if "login" in current_url.lower() and "brokoverview" not in current_url.lower():

            error_message_on_page = "N/A"
            try: 
                error_element_selectors = [".alert-msg-summary p", "#messagetext", ".messageHyberLinkClass"]
                for selector in error_element_selectors:
                    error_element = await page.select(selector, timeout=1_000)
                    if error_element:
                        error_message_on_page = (await error_element.text_content()).strip()
                        log(f"Found error message on page with selector '{selector}': {error_message_on_page}")
                        break
            except asyncio.TimeoutError:
                log(f"No specific error message element found on page {current_url}.")
            except Exception as e_err_msg:
                log(f"Exception while trying to get error message: {e_err_msg}")

            detailed_error_msg = f"Login failed for {account_name_key}. Ended on URL: {current_url}. Page hint: '{error_message_on_page}'"
            print(f"ERROR: {detailed_error_msg}")
            if discord_loop:
                printAndDiscord(detailed_error_msg, discord_loop)
            
            wf_brokerage_obj.set_logged_in_object(account_name_key, None)
            return

        log("Login appears successful. Setting logged in object.")
        wf_brokerage_obj.set_logged_in_object(account_name_key, browser)
        await fetch_initial_account_data(page, wf_brokerage_obj, account_name_key, discord_loop)

    except Exception as e:
        current_page_for_error = page if page and not page.closed else None
        await wellsfargo_error(f"Error during Wells Fargo init for {account_name_key}: {e}", current_page_for_error, discord_loop, browser=None)
        wf_brokerage_obj.set_logged_in_object(account_name_key, None)

    log(f"wellsfargo_init finished for {account_name_key}.")


async def fetch_initial_account_data(page: uc.Tab, wf_brokerage_obj: Brokerage, account_name_key: str, discord_loop):
    log(f"Fetching initial account data for {account_name_key}.")
    try:
        current_url = await get_current_url(page, discord_loop)
        
        x_param_match = re.search(r'_x=([^&]+)', current_url)
        x_param = f"_x={x_param_match.group(1)}" if x_param_match else ""
        log(f"Extracted x_param: '{x_param}' from URL.")

        content = await page.get_content()
        soup = BeautifulSoup(content, 'html.parser')
        
        account_rows = soup.select('tr[data-p_account]')
        log(f"Found {len(account_rows)} potential account rows on summary page.")
        
        if not account_rows:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_name = f"wells-fargo-no-accounts-found-{timestamp}.png"
            await page.save_screenshot(filename=screenshot_name)
            log(f"Saved screenshot for no-accounts-found case to '{screenshot_name}'")
            
            msg = f"No account rows found for {account_name_key} on summary page. URL: {current_url}"
            printAndDiscord(msg, discord_loop)
            return
        
        for row in account_rows:
            try:
                account_index = row.get('data-p_account', '').strip()
                if account_index == "-1":
                    log("Skipping 'All Accounts' summary row.")
                    continue
                log(f"Processing row for account index: {account_index}")
                    
                account_name_el = row.select_one('[role="rowheader"]')
                if not account_name_el:
                    log("Skipping row, no rowheader found.")
                    continue
                    
                nickname_el = account_name_el.select_one('.ellipsis')
                nickname = nickname_el.get_text(strip=True) if nickname_el else "N/A"
                
                account_number_div = account_name_el.select_one('div:not(.ellipsis-container)')
                account_number = account_number_div.get_text(strip=True).replace('*', '') if account_number_div else "N/A"
                
                balance_cells = row.select('td[data-sort-value]')
                balance_text = balance_cells[-1].get_text(strip=True) if balance_cells else "$0.00"
                balance = float(balance_text.replace("$", "").replace(",", ""))
                
                account_id = f"{nickname} {account_number}"
                log(f"Processed Account: ID='{account_id}', Balance=${balance}")
                
                wf_brokerage_obj.set_account_number(account_name_key, account_id)
                wf_brokerage_obj.set_account_totals(account_name_key, account_id, balance)
                
                if not hasattr(wf_brokerage_obj, '_account_indices'):
                    wf_brokerage_obj._account_indices = {}
                if account_name_key not in wf_brokerage_obj._account_indices:
                    wf_brokerage_obj._account_indices[account_name_key] = {}
                
                wf_brokerage_obj._account_indices[account_name_key][account_id] = {
                    'index': account_index,
                    'x_param': x_param
                }
                log(f"Stored index '{account_index}' and x_param for account '{account_id}'.")
                
            except Exception as e_block:
                await wellsfargo_error(f"Error processing one account row for {account_name_key}: {e_block}", page, discord_loop)
        
        if not wf_brokerage_obj.get_account_numbers(account_name_key):
            printAndDiscord(f"No accounts successfully processed for {account_name_key} from summary.", discord_loop)
            
    except Exception as e:
        await wellsfargo_error(f"Error fetching initial account data for {account_name_key}: {e}", page, discord_loop)

async def wellsfargo_transaction(wf_brokerage_obj: Brokerage, orderObj: stockOrder, account_name_key: str, browser: uc.Browser, page: uc.Tab, discord_loop):
    log("wellsfargo_transaction started.")
    try:
        if not wf_brokerage_obj.get_logged_in_objects(account_name_key):
            printAndDiscord(f"Not logged in for {account_name_key}, cannot perform transaction.", discord_loop)
            log("Transaction aborted: Not logged in.")
            return

        current_url = await get_current_url(page, discord_loop)
        x_param_match = re.search(r'(_x=[^&]+)', current_url)
        if not x_param_match:
            raise Exception("Could not find the dynamic '_x' parameter in the current URL.")
        
        dynamic_x_param = x_param_match.group(1)
        log(f"Captured dynamic parameter for trade URL: {dynamic_x_param}")

        processed_accounts = set()
        account_index = 0

        while True:
            trade_url = f"https://wfawellstrade.wellsfargo.com/BW/equity.do?account={account_index}&symbol=&selectedAction=&{dynamic_x_param}"
            log(f"Navigating to trade URL for account index {account_index}: {trade_url}")
            await page.get(trade_url)
            await asyncio.sleep(3)

            try:
                # This call finds the element(s)
                acct_mask_element_or_list = await page.select(".acctmask", timeout=5)
                
                final_element = None
                if isinstance(acct_mask_element_or_list, list):
                    if acct_mask_element_or_list:
                        final_element = acct_mask_element_or_list[0]
                else:
                    final_element = acct_mask_element_or_list

                if not final_element:
                    log(f"Element '.acctmask' returned None or empty list for index {account_index}. Assuming end of accounts and breaking loop.")
                    break

                full_text = final_element.text_all
                
                account_mask = re.sub(r'Account ending with', '', full_text).strip().replace('*', '')
                log(f"Found account mask on page: *{account_mask}")

            except asyncio.TimeoutError:
                log(f"Timed out waiting for account mask on page for index {account_index}. Assuming end of accounts and breaking loop.")
                break
            
            if account_mask in processed_accounts:
                log(f"Detected repeated account mask: *{account_mask}. Ending transaction loop.")
                printAndDiscord(f"Finished processing all unique accounts for {account_name_key}.", discord_loop)
                break
            
            processed_accounts.add(account_mask)
            log(f"New account found: *{account_mask}. Stored for processing.")

            for stock_symbol in orderObj.get_stocks():

                trade_url = f"https://wfawellstrade.wellsfargo.com/BW/equity.do?account={account_index}&symbol=&selectedAction=&{dynamic_x_param}"
                log(f"Navigating to fresh trade URL for stock '{stock_symbol}': {trade_url}")
                await page.get(trade_url)
                await asyncio.sleep(3)

                log(f"Processing order for stock: {stock_symbol} in account *{account_mask}")
                action = orderObj.get_action().capitalize()
                quantity = orderObj.get_amount()
                is_dry_run = orderObj.get_dry()
                
                printAndDiscord(f"Preparing to {action} {quantity} share(s) of {stock_symbol} for account ending in *{account_mask}.", discord_loop)

                # 1. Select Action
                try:
                    log(f"Clicking Action dropdown and selecting '{action}'.")
                    await (await page.select("#BuySellBtn", timeout=5)).click()
                    await asyncio.sleep(0.5)
                    await (await page.select(f"a[data-val='{action}']", timeout=5)).click()
                    await asyncio.sleep(1)
                except asyncio.TimeoutError:
                    raise Exception("Failed to select Buy/Sell action.")

                # 2. Enter Symbol
                try:
                    log(f"Entering symbol: {stock_symbol}")
                    symbol_input = await page.select("#Symbol", timeout=5)
                    await symbol_input.send_keys(stock_symbol)

                    await symbol_input.send_keys(SpecialKeys.TAB)

                    log("Waiting for quote to load...")
                    await asyncio.sleep(5)
                except asyncio.TimeoutError:
                    raise Exception("Failed to find symbol input field.")

                # 2a. Check Owned Shares for Sell Orders
                if action == "Sell":
                    try:
                        log("Checking number of shares owned.")
                        # Selector for the span containing the number of shares
                        shares_element = await page.select("#currentSharesOwned .numshares", timeout=5)
                        
                        if not shares_element:
                            raise Exception("Could not find the 'shares owned' element on the page.")

                        owned_shares_text = shares_element.text_all.strip()
                        owned_shares = int(owned_shares_text)
                        log(f"Account owns {owned_shares} shares of {stock_symbol}.")

                        # Check if we have enough shares to sell
                        if owned_shares == 0:
                            message = f"Skipped selling {stock_symbol} in account *{account_mask}: You own 0 shares."
                            printAndDiscord(message, discord_loop)
                            log(message)
                            continue # Skip to the next stock
                        
                        if quantity > owned_shares:
                            message = f"Skipped selling {stock_symbol} in account *{account_mask}: Order quantity ({quantity}) exceeds shares owned ({owned_shares})."
                            printAndDiscord(message, discord_loop)
                            log(message)
                            continue # Skip to the next stock

                    except asyncio.TimeoutError:
                        log("Warning: Timed out waiting for the 'shares owned' element. Proceeding with caution.")
                    except Exception as e:
                        # Catch other errors like failing to parse the number
                        error_message = f"An error occurred while checking owned shares for {stock_symbol}: {e}"
                        printAndDiscord(error_message, discord_loop)
                        log(error_message)
                        continue # Skip to the next stock

                # 3. Get Quote & Determine Order Type
                try:
                    # The 'select' method will wait up to 10 seconds for the element to appear.
                    last_price_element = await page.select("#last", timeout=10)

                    # Add a check to ensure the element was actually found before using it.
                    if not last_price_element:
                        raise Exception("Price element #last could not be found after 10 seconds. The page may not have loaded the quote correctly.")
                    
                    last_price_str = last_price_element.get('value')
                    if not last_price_str: 
                        raise Exception("Price element #last was found, but its value is empty.")

                    last_price = float(last_price_str)
                    log(f"Last price for {stock_symbol} is ${last_price}")
                except asyncio.TimeoutError:
                    # This will catch the timeout from page.select and provide a clearer error.
                    raise Exception("Timed out waiting for the last price element (#last) to appear.")

                order_type = "Market" if last_price >= 2.00 else "Limit"
                log(f"Order type determined: {order_type}")

                # 4. Enter Quantity
                try:
                    log(f"Entering quantity: {quantity}")
                    # First, select the input element by its ID
                    quantity_input = await page.select("#OrderQuantity", timeout=5)
                    
                    # Clear any default value (like '0') that might be in the box
                    await quantity_input.clear_input()

                    # Then, type the new quantity into the element
                    payloads = KeyEvents.from_text(str(int(quantity)), KeyPressEvent.DOWN_AND_UP)  
                    await quantity_input.send_keys(payloads)
                    await quantity_input.send_keys(SpecialKeys.TAB)
                    await asyncio.sleep(2)

                except asyncio.TimeoutError:
                    raise Exception("Failed to find the Quantity input field '#OrderQuantity'.")
                
                # 5. Select Order Type
                try:
                    log(f"Clicking Order Type dropdown and selecting '{order_type}'.")
                    await (await page.select("#OrderTypeBtn", timeout=5)).click()
                    await asyncio.sleep(0.5)
                    await (await page.select(f"a[data-val='{order_type}']", timeout=5)).click()
                    await asyncio.sleep(1)
                except asyncio.TimeoutError:
                    raise Exception("Failed to select Order Type.")

                # 6. Enter Limit Price
                if order_type == "Limit":
                    try:
                        limit_price = round(last_price + 0.01, 2) if action == "Buy" else round(last_price - 0.01, 2)
                        log(f"Calculating and entering Limit Price: ${limit_price}")
                        limit_input = await page.select("#Price", timeout=5)
                        await limit_input.send_keys(str(limit_price))
                    except asyncio.TimeoutError:
                        raise Exception("Failed to find Limit Price input field.")
                
                # 7. Select Timing
                try:
                    log("Clicking Timing dropdown and selecting 'Day'.")
                    await (await page.select("#TIFBtn", timeout=5)).click()
                    await asyncio.sleep(0.5)
                    await (await page.select("a[data-val='Day']", timeout=5)).click()
                    await asyncio.sleep(1)
                except asyncio.TimeoutError:
                    raise Exception("Failed to select Timing.")

                # 8. Preview Order
                try:
                    log("Clicking PREVIEW ORDER button.")
                    preview_button = await page.select("#actionbtnContinue", timeout=5)
                    await preview_button.click()
                    log("Preview Order button clicked. Waiting for next page to load.")
                    await asyncio.sleep(5) 
                except asyncio.TimeoutError:
                    raise Exception("Failed to find or click the Preview Order button.")

                # 9. Check for Confirmation Button (Hard Error Path)
                try:
                    # The key check: Can we find the final SUBMIT button?
                    # If we can't, it means we hit a hard error page.
                    confirm_button = await page.select(".btn-wfa-primary.btn-wfa-submit", timeout=5)
                    log("Confirmation button found. The trade is placeable.")
                except asyncio.TimeoutError:
                    # This is the HARD ERROR path. The submit button doesn't exist.
                    log("Confirmation button NOT found. Assuming a hard trade error occurred.")
                    try:
                        # Now, find the error message to report it.
                        error_element = await page.select(".alert-msg-summary p", timeout=2)
                        error_text = error_element.text_all.strip().replace("\n", " ")
                        full_error_message = f"Wells Fargo HARD Error for {stock_symbol}: {error_text}"
                        printAndDiscord(full_error_message, discord_loop)
                    except asyncio.TimeoutError:
                        # Fallback if we can't even find the error text
                        printAndDiscord(f"Wells Fargo HARD Error for {stock_symbol}: Confirmation page did not load, and no specific error message was found.", discord_loop)
                    
                    log(f"Skipping final confirmation for {stock_symbol} due to hard error.")
                    continue # Skip to the next stock

                # 10. Check for Soft Warnings
                try:
                    # If we got here, the trade is placeable. Now we check for non-critical warnings.
                    warning_element = await page.select(".alert-msg-summary p", timeout=2)
                    if warning_element:
                        warning_text = warning_element.text_all.strip().replace("\n", " ")
                        full_warning_message = f"Wells Fargo Warning for {stock_symbol}: {warning_text}"
                        printAndDiscord(full_warning_message, discord_loop)
                        log(full_warning_message)
                except asyncio.TimeoutError:
                    # This is the normal path when no warnings are present.
                    log("No soft warnings found on the page.")

                # 11. Final Confirmation
                if is_dry_run:
                    printAndDiscord(f"[DRY RUN] Successfully previewed order for {action} {quantity} of {stock_symbol}. Final confirmation skipped.", discord_loop)
                    log("Dry run complete. Skipping final confirmation click.")
                else:
                    try:
                        log("Attempting to click the final 'SUBMIT ORDER' button.")
                        # We use the 'confirm_button' element we already found in step 9
                        await confirm_button.click()
                        printAndDiscord(f"Successfully placed order for {action} {quantity} of {stock_symbol}.", discord_loop)
                        log("Final order placed successfully.")
                        await asyncio.sleep(5)
                    except Exception as e:
                        # This catch is for potential errors during the final click itself
                        raise Exception(f"An error occurred while clicking the final 'SUBMIT ORDER' button: {e}")
            
            account_index += 1

    except Exception as e:
        await wellsfargo_error(f"Error during Wells Fargo transaction logic for {account_name_key}: {e}", page, discord_loop, browser)


async def wellsfargo_holdings(wf_brokerage_obj: Brokerage, account_name_key: str, browser: uc.Browser, page: uc.Tab, discord_loop):
    log(f"wellsfargo_holdings started for {account_name_key}.")
    try:
        if not wf_brokerage_obj.get_logged_in_objects(account_name_key):
            printAndDiscord(f"Not logged in for {account_name_key}, cannot fetch holdings.", discord_loop)
            return

        registered_accounts = wf_brokerage_obj.get_account_numbers(account_name_key)
        log(f"Starting holdings check for {len(registered_accounts)} accounts in '{account_name_key}'.")

        if not registered_accounts:
            printAndDiscord(f"No accounts registered for {account_name_key} from init.", discord_loop)
            return

        current_url = await get_current_url(page, discord_loop)
        x_param_match = re.search(r'_x=([^&]+)', current_url)
        current_x_param = f"_x={x_param_match.group(1)}" if x_param_match else ""

        for account_id in registered_accounts:
            try:
                if not hasattr(wf_brokerage_obj, '_account_indices'):
                    log("CRITICAL - _account_indices attribute not found on brokerage object. Cannot look up account index.")
                    continue
                    
                account_data = wf_brokerage_obj._account_indices.get(account_name_key, {}).get(account_id, {})
                account_index = account_data.get('index', '')
                stored_x_param = account_data.get('x_param', '')
                
                log(f"Processing holdings for account '{account_id}'. Stored index: '{account_index}'.")

                if not account_index:
                    log(f"Skipping account '{account_id}' - no account index stored.")
                    continue
                
                x_param_to_use = stored_x_param if stored_x_param else current_x_param
                
                holdings_url = f"https://wfawellstrade.wellsfargo.com/BW/holdings.do?account={account_index}"
                if x_param_to_use:
                    holdings_url += f"&{x_param_to_use}"
                
                log(f"Navigating to holdings URL: {holdings_url}")
                await page.get(holdings_url)
                await asyncio.sleep(5)
                
                await extract_holdings_from_table(page, wf_brokerage_obj, account_name_key, account_id, discord_loop)
                
            except Exception as e_account:
                await wellsfargo_error(f"Error processing account {account_id}: {e_account}", page, discord_loop)
        
        printHoldings(wf_brokerage_obj, discord_loop)
        log("printHoldings called.")
        
    except Exception as e:
        current_page_for_error = page if page and not page.closed else (browser.tabs[0] if browser and browser.tabs else None)
        await wellsfargo_error(f"Error fetching Wells Fargo holdings for {account_name_key}: {e}", current_page_for_error, discord_loop, browser)

async def extract_holdings_from_table(page: uc.Tab, wf_brokerage_obj: Brokerage, login_key: str, current_wf_account_id: str, discord_loop):
    log(f"Extracting holdings from table for account '{current_wf_account_id}'.")
    try:
        content = await page.get_content()
        soup = BeautifulSoup(content, 'html.parser')
        
        holding_rows = soup.select('tbody > tr.level1')
        log(f"Found {len(holding_rows)} holding rows in table.")

        for row in holding_rows:
            try:
                symbol_el = row.select_one('a.navlink.quickquote')
                if not symbol_el:
                    continue 
                symbol = symbol_el.text.replace(",popup", "").strip()
                
                name_el = row.select_one('td[role="rowheader"] .data-content > div:last-child')
                name = name_el.get_text(strip=True) if name_el else "N/A" 

                all_numeric_cells = row.select('td.datanumeric')
                
                quantity = 0.0
                price = 0.0

                if len(all_numeric_cells) > 2:
                    qty_div = all_numeric_cells[1].select_one('div:first-child')
                    if qty_div:
                        quantity_text = qty_div.get_text(strip=True)
                        quantity = float(quantity_text)
                    
                    price_div = all_numeric_cells[2].select_one('div:first-child')
                    if price_div:
                        price_text = price_div.get_text(strip=True).replace('$', '').replace(',', '')
                        price = float(price_text)

                if symbol and quantity > 0:
                    log(f"Found holding: {quantity} of {symbol} @ ${price}")
                    wf_brokerage_obj.set_holdings(login_key, current_wf_account_id, symbol, quantity, price)
                    
            except Exception as e_row:
                await wellsfargo_error(f"Error processing a specific holdings row: {e_row}", page, discord_loop)

    except Exception as e_table:
        await wellsfargo_error(f"Error during main extraction logic: {e_table}", page, discord_loop)
