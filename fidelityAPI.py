# Nelson Dane
# API to Interface with Fidelity
# Uses headless Selenium

import os
import sys
import traceback
from time import sleep
from dotenv import load_dotenv
from seleniumAPI import *
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions

def fidelity_init(DOCKER=False):
    try:
        # Initialize .env file
        load_dotenv()
        # Import Fidelity account
        if not os.getenv("FIDELITY_USERNAME") or not os.getenv("FIDELITY_PASSWORD"):
            print("Fidelity not found, skipping...")
            return None
        FIDELITY_USERNAME = os.environ["FIDELITY_USERNAME"]
        FIDELITY_PASSWORD = os.environ["FIDELITY_PASSWORD"]
        # Init webdriver
        print("Logging in to Fidelity...")
        driver = getDriver(DOCKER)
        # Log in to Fidelity account
        driver.get("https://digital.fidelity.com/prgw/digital/login/full-page?AuthRedUrl=https://digital.fidelity.com/ftgw/digital/portfolio/summary")
        # Wait for page load
        WebDriverWait(driver, 10).until(check_if_page_loaded)
        # Type in username and password   
        username_field = driver.find_element(by=By.CSS_SELECTOR, value="#userId-input")
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable(username_field)
        )
        username_field.send_keys(FIDELITY_USERNAME)
        password_field = driver.find_element(by=By.CSS_SELECTOR, value="#password")
        WebDriverWait(driver, 10).until(
            expected_conditions.element_to_be_clickable(password_field)
        )
        password_field.send_keys(FIDELITY_PASSWORD)
        driver.find_element(by=By.CSS_SELECTOR, value="#fs-login-button").click()
        # Wait for page to load to summary page
        if not driver.current_url == "https://oltx.fidelity.com/ftgw/fbc/oftop/portfolio#summary":
            WebDriverWait(driver, 60).until(
                expected_conditions.url_to_be("https://oltx.fidelity.com/ftgw/fbc/oftop/portfolio#summary")
            )
        # Wait for page to load
        WebDriverWait(driver, 10).until(check_if_page_loaded)
        sleep(3)
        print("Logged in to Fidelity!")
    except Exception as e:
        print(f'Error logging in: "{e}"')
        print(traceback.print_exc())
        return None
    return driver
    
async def fidelity_holdings(driver, ctx):
    print()
    print("==============================")
    print("Fidelity Holdings")
    print("==============================")
    print()
    # Make sure init didn't return None
    if driver is None:
        print("Error: No Fidelity account")
        return None
    try:
        # Get account holdings
        driver.get("https://oltx.fidelity.com/ftgw/fbc/oftop/portfolio#positions")
        # Wait for page load
        WebDriverWait(driver, 10).until(check_if_page_loaded)
        sleep(5)
        # Get total account value
        total_value = driver.find_elements(by=By.CSS_SELECTOR, value='body > div.fidgrid.fidgrid--shadow.fidgrid--nogutter > div.full-page--container > div.fidgrid--row.port-summary-container > div.port-summary-content.clearfix > div > div.fidgrid--content > div > div.account-selector-wrapper.port-nav.account-selector--reveal > div.account-selector.account-selector--normal-mode.clearfix > div.account-selector--main-wrapper > div.account-selector--accounts-wrapper > div.account-selector--tab.account-selector--tab-all.js-portfolio.account-selector--target-tab.js-selected > span.account-selector--tab-row.account-selector--all-accounts-balance.js-portfolio-balance')
        print(f'Total Fidelity account value: {total_value[0].text}')
        if ctx:
            await ctx.send(f'Total Fidelity account value: {total_value[0].text}')
        # Get value of individual and retirement accounts
        ind_accounts = driver.find_elements(by=By.CSS_SELECTOR, value='[data-group-id="IA"]')
        ret_accounts = driver.find_elements(by=By.CSS_SELECTOR, value='[data-group-id="RA"]')
        # Get text from elements
        test = ind_accounts[0].text
        test2 = ret_accounts[0].text
        # Split by new line
        info = test.splitlines()
        info2 = test2.splitlines()
        # Get every 4th element in the list, starting at the 3rd element
        # This is the account number
        ind_num = []
        ret_num = []
        for x in info[3::4]:
            ind_num.append(x)
        for x in info2[2::4]:
            ret_num.append(x)
        # Get every 4th element in the list, starting at the 4th element
        # This is the account value
        ind_val = []
        ret_val = []
        for x in info[4::4]:
            ind_val.append(x)
        for x in info2[3::4]:
            ret_val.append(x)
        # Print out account numbers and values
        print("Individual accounts:")
        if ctx:
            print("Individual accounts:")
        for x in range(len(ind_num)):
            print(f'{ind_num[x]} value: {ind_val[x]}')
            if ctx:
                await ctx.send(f'{ind_num[x]} value: {ind_val[x]}')
        print("Retirement accounts:")
        if ctx:
            print("Retirement accounts:")
        for x in range(len(ret_num)):
            print(f'{ret_num[x]} value: {ret_val[x]}')
            if ctx:
                await ctx.send(f'{ret_num[x]} value: {ret_val[x]}')
        # We'll add positions later since that will be hard
    except Exception as e:
        print(f'Error getting holdings: {e}')
        print(traceback.format_exc())

async def fidelity_transaction(driver, action, stock, amount, price, time, DRY=True, ctx=None):
    # Make sure init didn't return None
    if driver is None:
        print("Error: No Fidelity account")
        return None
    print()
    print("==============================")
    print("Fidelity")
    print("==============================")
    print()
    action = action.lower()
    stock = stock.upper()
    amount = int(amount)
    # Go to trade page
    driver.get("https://digital.fidelity.com/ftgw/digital/trade-equity/index/orderEntry")
    # Wait for page to load
    WebDriverWait(driver, 20).until(check_if_page_loaded)
    sleep(3)
    # Get number of accounts
    try:
        accounts_dropdown = driver.find_element(by=By.CSS_SELECTOR, value="#dest-acct-dropdown > div")
        accounts_dropdown.click()
        sleep(0.5)
        test = driver.find_element(by=By.CSS_SELECTOR, value="#ett-acct-sel-list")
        accounts_dropdown = test.find_elements(by=By.CSS_SELECTOR, value="li")
        print(f'Number of accounts: {len(accounts_dropdown)}')
        number_of_accounts = len(accounts_dropdown)
        # # Print all account numbers
        # for x in range(len(accounts_dropdown)):
        #     print(f'Account {x+1}: {accounts_dropdown[x].text}')
        # return None
    except:
        print("Error: No accounts found")
        return None
    # Complete on each account
    # Because of stale elements, we need to re-find the elements each time
    for x in range(number_of_accounts):
        try:
            # Select account
            accounts_dropdown_in = driver.find_element(by=By.CSS_SELECTOR, value="#dest-acct-dropdown > div")
            accounts_dropdown_in.click()
            sleep(0.5)
            test = driver.find_element(by=By.CSS_SELECTOR, value="#ett-acct-sel-list")
            accounts_dropdown_in = test.find_elements(by=By.CSS_SELECTOR, value="li")
            account_label = accounts_dropdown_in[x].text
            accounts_dropdown_in[x].click()
            sleep(1)
            # Type in ticker
            ticker_box = driver.find_element(by=By.CSS_SELECTOR, value="#eq-ticket-dest-symbol")
            WebDriverWait(driver, 10).until(
                expected_conditions.element_to_be_clickable(ticker_box)
            )
            ticker_box.send_keys(stock)
            ticker_box.send_keys(Keys.RETURN)
            sleep(1)
            # Check if symbol not found is displayed
            try:
                symbol_not_found = driver.find_element(by=By.CSS_SELECTOR, value="body > div.app-body > ap122489-ett-component > div > order-entry > div.eq-ticket.order-entry__container-height > div > div > form > div.order-entry__container-content.scroll > div:nth-child(2) > symbol-search > div > div.eq-ticket--border-top > div > div:nth-child(2) > div > div > div > pvd3-inline-alert > s-root > div > div.pvd-inline-alert__content > s-slot > s-assigned-wrapper")
                print(f"Error: Symbol {stock} not found")
                return None
            except:
                pass
            # Get ask price
            ask_price = driver.find_element(by=By.CSS_SELECTOR, value="#quote-panel > div > div.eq-ticket__quote--blocks-container > div:nth-child(2) > div > span > span")
            ask_price = ask_price.text
            # If price is under $1, then we have to use a limit order
            if float(ask_price) < 1:
                LIMIT = True
            else:
                LIMIT = False
            # Set buy/sell
            if action == "buy":
                buy_button = driver.find_element(by=By.CSS_SELECTOR, value="#action-buy > s-root > div > label > s-slot > s-assigned-wrapper")
                buy_button.click()
            elif action == "sell":
                sell_button = driver.find_element(by=By.CSS_SELECTOR, value="#action-sell > s-root > div > label > s-slot > s-assigned-wrapper")
                sell_button.click()
            else:
                print(f"Error: Invalid action {action}")
                return None
            # Set amount (and clear previous amount)
            amount_box = driver.find_element(by=By.CSS_SELECTOR, value="#eqt-shared-quantity")
            amount_box.clear()
            amount_box.send_keys(amount)
            # Set market/limit
            if not LIMIT:
                market_button = driver.find_element(by=By.CSS_SELECTOR, value="#market-yes > s-root > div > label > s-slot > s-assigned-wrapper")
                market_button.click()
            else:
                limit_button = driver.find_element(by=By.CSS_SELECTOR, value="#market-no > s-root > div > label > s-slot > s-assigned-wrapper")
                limit_button.click()
                # Set price
                wanted_price = float(ask_price) + 0.01
                price_box = driver.find_element(by=By.CSS_SELECTOR, value="#eqt-ordsel-limit-price-field")
                price_box.send_keys(wanted_price)
            # Preview order
            preview_button = driver.find_element(by=By.CSS_SELECTOR, value="#previewOrderBtn > s-root > button > div > span > s-slot > s-assigned-wrapper")
            preview_button.click()
            # Wait for page to load
            WebDriverWait(driver, 10).until(check_if_page_loaded)
            sleep(1)
            # Place order
            if not DRY:
                place_button = driver.find_element(by=By.CSS_SELECTOR, value="#placeOrderBtn > span")
                place_button.click()
                # Wait for page to load
                WebDriverWait(driver, 10).until(check_if_page_loaded)
                sleep(1)
                # Check for error
                try:
                    error = driver.find_element(by=By.CSS_SELECTOR, value="#pvd-modal-body-id-638525840682 > s-slot > s-assigned-wrapper > pvd3-inline-alert > s-root > div > div.pvd-inline-alert__content > s-slot > s-assigned-wrapper > div")
                    print(f"Error: {error.text}")
                    continue
                except:
                    pass
                # Send confirmation
                message = f"Fidelity {account_label}: {action} {amount} shares of {stock}"
                print(message)
                if ctx:
                    await ctx.send(message)
            else:
                message = f"DRY: Fidelity {account_label}: {action} {amount} shares of {stock}"
                print(message)
                if ctx:
                    await ctx.send(message)
            sleep(3)
        except Exception as e:
            print(e)
            continue

# fidelity = fidelity_init()
# #     #input("Press enter to continue to holdings...")
# #     fidelity_holdings(fidelity)
# fidelity_transaction(fidelity, "buy", "AAPL", 1, 0, 0, DRY=True)
# input("Press enter to quit...")
# fidelity.close()
# fidelity.quit()
# sys.exit(0)
# # Catch any errors
# except KeyboardInterrupt:
#     print("Quitting...")
#     sys.exit(1)
# except Exception as e:
#     print(e)
