import datetime
import os
import traceback
from time import sleep
import logging

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from helperAPI import (
    Brokerage,
    check_if_page_loaded,
    getDriver,
    killSeleniumDriver,
    printAndDiscord,
    printHoldings,
    stockOrder,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def tornado_error(driver, loop=None):
    driver.save_screenshot(f"Tornado-error-{datetime.datetime.now()}.png")
    printAndDiscord(f"Tornado Error: {traceback.format_exc()}", loop, embed=False)


def tornado_init(TORNADO_EXTERNAL=None, loop=None):
    load_dotenv()

    if not os.getenv("TORNADO") and TORNADO_EXTERNAL is None:
        printAndDiscord("TORNADO environment variable not found.", loop)
        return None

    accounts = (
        os.environ["TORNADO"].strip().split(",")
        if TORNADO_EXTERNAL is None
        else TORNADO_EXTERNAL.strip().split(",")
    )
    TORNADO_obj = Brokerage("TORNADO")

    for index, account in enumerate(accounts):
        account_name = f"Tornado {index + 1}"
        try:
            driver = getDriver()
            if driver is None:
                raise Exception("Driver not found.")
            driver.get('https://tornado.com/app/login')
            WebDriverWait(driver, 30).until(check_if_page_loaded)

            # Log in with email and password
            try:
                email_field = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.ID, "email-field")))
                email_field.send_keys(account.split(":")[0])

                password_field = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.ID, "password-field")))
                password_field.send_keys(account.split(":")[1])

                login_button = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "#root > div > div > div > div:nth-child(2) > div > div > div > div > form > div.sc-WZYut.ZaYjk > button")))
                login_button.click()

                # Check for the element after logging in to ensure the page is fully loaded
                WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located((By.XPATH, "//*[@id='main-router']/div/div/div/div[1]/div/div/div/div[1]/div[1]/div/span"))
                )

                TORNADO_obj.set_logged_in_object(account_name, driver)

                # Set the account name
                TORNADO_obj.set_account_number(account_name, account_name)
                logger.info("Set account name for %s", account_name)

            except TimeoutException:
                printAndDiscord(f"TimeoutException: Login failed for {account_name}.", loop)
                return False

        except Exception:
            tornado_error(driver, loop)
            driver.close()
            driver.quit()
            return None
    return TORNADO_obj


def tornado_extract_holdings(driver):
    holdings_data = []
    try:
        # Locate all the individual stock holdings elements
        holdings_elements = driver.find_elements(By.XPATH, ".//div[@class='sc-jEWLvH evXkie']")

        if len(holdings_elements) == 0:
            logger.warning("No holdings found in the account.")
            return holdings_data

        logger.info("Found %d holdings elements to process.", len(holdings_elements))

        for holding_element in holdings_elements:
            try:
                # Extract the stock ticker
                stock_ticker = holding_element.find_element(By.XPATH, ".//a[1]/div[1]/span").text.strip()

                # Extract the number of shares available
                shares = holding_element.find_element(By.XPATH, ".//a[4]/div/div/span/span").text.strip()
                shares_float = float(shares.replace(" sh", ""))

                # Corrected XPath to extract the actual stock price
                price = holding_element.find_element(By.XPATH, ".//a[1]/div[3]/span/div/div[1]/span").text.strip()
                price_float = float(price.replace('$', '').replace(',', ''))

                logger.info("Scraped holding: %s, Shares: %s, Price: %s", stock_ticker, shares_float, price_float)

                # Store the extracted data in a dictionary
                holdings_data.append({
                    'stock_ticker': stock_ticker,
                    'shares': shares_float,
                    'price': price_float
                })

            except Exception as e:
                logger.error("Error scraping a holding element: %s", e)
                continue

    except Exception as e:
        logger.error("Error extracting holdings: %s", e)
        return []

    return holdings_data


def tornado_holdings(TORNADO_o: Brokerage, loop=None):
    try:
        # Ensure we are using the correct account name
        account_names = TORNADO_o.get_account_numbers()
        for account_name in account_names:
            driver: webdriver = TORNADO_o.get_logged_in_objects(account_name)

            logger.info("Processing holdings for %s", account_name)

            # Fetch the total account value
            account_value_element = WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.XPATH, "//*[@id='main-router']/div/div/div/div[1]/div/div/div[1]/div[1]/div[1]/div/span"))
            )
            account_value = account_value_element.text.strip()
            account_value_float = float(account_value.replace('$', '').replace(',', ''))

            # Extract holdings data
            holdings_data = tornado_extract_holdings(driver)

            if not holdings_data:
                logger.warning("No holdings found for %s. Skipping account.", account_name)
                continue  # Skip to the next account

            for holding in holdings_data:
                TORNADO_o.set_holdings(account_name, account_name, holding['stock_ticker'], holding['shares'], holding['price'])

            # Set the account total using the fetched account value
            TORNADO_o.set_account_totals(account_name, account_name, account_value_float)

    except Exception as e:
        logger.error("Error processing Tornado holdings: %s", e)
        printAndDiscord(f"Tornado Account: Error processing holdings: {e}", loop)

    logger.info("Finished processing Tornado account, sending holdings to Discord.")
    printHoldings(TORNADO_o, loop)  # Send the holdings to Discord
    killSeleniumDriver(TORNADO_o)  # Close the browser after processing
    logger.info("Completed Tornado holdings processing.")


def tornado_transaction(TORNADO_o: Brokerage, orderObj: stockOrder, loop=None):
    print("\n==============================")
    print("TORNADO")
    print("==============================\n")

    for s in orderObj.get_stocks():
        for key in TORNADO_o.get_account_numbers():
            driver = TORNADO_o.get_logged_in_objects(key)

            # Ensure we are on the Tornado dashboard or navigate to it
            try:
                current_url = driver.current_url
                if "app" not in current_url:
                    driver.get("https://tornado.com/app/")
                    print(f"Navigated to Tornado dashboard page for account {key}")
                    WebDriverWait(driver, 30).until(check_if_page_loaded)
                else:
                    print(f"Already on the Tornado dashboard page for account {key}")
            except Exception as e:
                print(f"Failed to navigate to dashboard for {key}: {e}")
                continue

            try:
                # Interact with the search bar
                search_field = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, '#nav_securities_search')))
                search_field.click()
                sleep(1)
                search_field.send_keys(s)
                print(f"Entered stock symbol {s} into the search bar")
            except TimeoutException:
                print(f"Search field for {s} not found.")
                printAndDiscord(f"Tornado search field not found for {s}.", loop)
                continue

            try:
                # Wait for and process search results
                WebDriverWait(driver, 10).until(
                    EC.presence_of_all_elements_located((By.XPATH, '//*[@id="nav_securities_search_container"]/div[2]/ul/li'))
                )
                dropdown_items = driver.find_elements(By.XPATH, '//*[@id="nav_securities_search_container"]/div[2]/ul/li')
                total_items = len(dropdown_items)
                print(f"Found {total_items} search results for {s}")
                sleep(2)

                if total_items == 0:
                    print(f"No stock found for {s}. Moving to next stock.")
                    printAndDiscord(f"Tornado doesn't have {s}.", loop)
                    continue

                found_stock = False
                for item in dropdown_items:
                    ticker_name = item.find_element(By.CLASS_NAME, 'bold').text.strip()
                    if ticker_name == s:
                        found_stock = True
                        sleep(1)
                        item.click()
                        print(f"Found and selected stock {s}")
                        break

                if not found_stock:
                    print(f"Tornado doesn't have {s}. Moving to next stock.")
                    printAndDiscord(f"Tornado doesn't have {s}.", loop)
                    continue
            except TimeoutException:
                print(f"Search results did not appear for {s}. Moving to next stock.")
                printAndDiscord(f"Tornado search results did not appear for {s}.", loop)
                continue

            # Proceed with the transaction based on the action (buy/sell)
            if orderObj.get_action() == "buy":
                handle_buy(driver, s, orderObj, loop)
            elif orderObj.get_action() == "sell":
                handle_sell(driver, s, orderObj, loop)

            # Ensure to return to the dashboard after every transaction
            try:
                dashboard_link = WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.XPATH, '//*[@id="root"]/div/div/div[4]/div/div[1]/div/div/div[2]/div[1]/div[2]/span[1]/a/span')))
                dashboard_link.click()
                WebDriverWait(driver, 60).until(
                    EC.presence_of_element_located((By.XPATH, '//*[@id="main-router"]/div/div/div/div[1]/div/div/div/div[1]/div[1]/div/span'))
                )
                print(f"Returned to dashboard after processing {s}")
            except TimeoutException:
                print(f"Failed to return to dashboard after processing {s}.")
                printAndDiscord(f"Tornado failed to return to dashboard after processing {s}.", loop)

    print("Completed all transactions, Exiting...")
    driver.close()
    driver.quit()


def handle_buy(driver, stock, orderObj, loop):
    DRY = orderObj.get_dry()
    QUANTITY = orderObj.get_amount()
    print("DRY MODE:", DRY)

    try:
        buy_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="buy-button"]')))
        driver.execute_script("arguments[0].click();", buy_button)
        print("Buy button clicked")
    except TimeoutException:
        print(f"Buy button not found for {stock}. Moving to next stock.")
        printAndDiscord(f"Tornado buy button not found for {stock}.", loop)
        return

    try:
        print(f"Entering quantity {QUANTITY}")
        quant = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="main-router"]/div[1]/div/div[3]/input')))
        quant.clear()
        quant.send_keys(str(QUANTITY))
        print(f"Quantity {QUANTITY} entered")
    except TimeoutException:
        print(f"Failed to enter quantity for {stock}. Moving to next stock.")
        printAndDiscord(f"Tornado failed to enter quantity for {stock}.", loop)
        return

    # Now check for current shares and adjust XPaths accordingly
    try:
        current_shares_element = driver.find_element(By.XPATH, '//*[@id="main-router"]/div[1]/div/div[4]/div')
        current_shares_text = current_shares_element.text.strip()
        print(f"Current shares for {stock}: {current_shares_text}")
        has_current_shares = True
    except NoSuchElementException:
        print(f"No current shares for {stock}.")
        has_current_shares = False

    market_order_xpath = '//*[@id="main-router"]/div[1]/div/div[5]/select' if has_current_shares else '//*[@id="main-router"]/div[1]/div/div[4]/select'
    current_price_xpath = '//*[@id="main-router"]/div[1]/div/div[6]/div' if has_current_shares else '//*[@id="main-router"]/div[1]/div/div[5]/div'
    buy_power_xpath = '//*[@id="main-router"]/div[1]/div/div[8]/div' if has_current_shares else '//*[@id="main-router"]/div[1]/div/div[7]/div'

    try:
        market_order_option = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, market_order_xpath))
        )
        market_order_option.click()
        print("Market order selected")
    except TimeoutException:
        print(f"Failed to select market order for {stock}. Moving to next stock.")
        printAndDiscord(f"Tornado failed to select market order for {stock}.", loop)
        return

    try:
        buy_power = driver.find_element(By.XPATH, buy_power_xpath).text.strip()
        cost = driver.find_element(By.XPATH, current_price_xpath).text.strip()

        buy_power_float = float(buy_power.replace('$', '').replace(',', ''))
        cost_float = float(cost.replace('$', '').replace(',', ''))

        if buy_power_float < cost_float:
            print(f"Insufficient funds to complete the purchase for {stock}.")
            printAndDiscord(f"Tornado insufficient funds to buy {stock}. Required: ${cost_float}, Available: ${buy_power_float}", loop)
            return

        print(f"Buying power: ${buy_power_float}, Cost: ${cost_float}")
    except TimeoutException:
        print(f"Failed to fetch buying power or cost for {stock}. Moving to next stock.")
        printAndDiscord(f"Tornado failed to fetch buying power or cost for {stock}.", loop)
        return

    if not DRY:
        try:
            submit_button = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="main-router"]/div[1]/div/div[10]/div/button | //*[@id="main-router"]/div[1]/div/div[9]/div/button')))
            submit_button.click()
            print(f"Successfully bought {QUANTITY} shares of {stock}")
            printAndDiscord(f"Tornado account: buy {QUANTITY} shares of {stock} at {cost}", loop)
            
            # Click the "Continue" button after placing the order
            continue_button = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="main-router"]/div[1]/div/div[2]/div/button')))
            continue_button.click()
            print("Clicked the Continue button after placing the order.")
        except TimeoutException:
            print(f"Failed to submit buy order for {stock} or click Continue. Moving to next stock.")
            printAndDiscord(f"Tornado failed to submit buy order for {stock} or click Continue.", loop)
    else:
        sleep(5)
        print(f"DRY MODE: Simulated order BUY for {QUANTITY} shares of {stock} at {cost}")
        printAndDiscord(f"Tornado account: dry run buy {QUANTITY} shares of {stock} at {cost}", loop)


def handle_sell(driver, stock, orderObj, loop):
    DRY = orderObj.get_dry()
    QUANTITY = orderObj.get_amount()
    print("DRY MODE:", DRY)

    try:
        sell_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="sell-button"]')))
        driver.execute_script("arguments[0].click();", sell_button)
        print("Sell button clicked")
    except TimeoutException:
        print(f"Sell button not found for {stock}. Moving to next stock.")
        printAndDiscord(f"Tornado sell button not found for {stock}.", loop)
        return

    try:
        current_shares_element = driver.find_element(By.XPATH, '//*[@id="main-router"]/div[1]/div/div[4]/div')
        current_shares = float(current_shares_element.text.strip().replace(" sh", ""))
        print(f"Current shares for {stock}: {current_shares}")
    except NoSuchElementException:
        print(f"No current shares found for {stock}. Unable to sell.")
        printAndDiscord(f"Tornado no current shares to sell for {stock}.", loop)
        return

    if QUANTITY > current_shares:
        print(f"Not enough shares to sell for {stock}. Available: {current_shares}")
        printAndDiscord(f"Tornado not enough shares to sell {stock}. Available: {current_shares}", loop)
        return

    try:
        quant = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="main-router"]/div[1]/div/div[3]/input')))
        quant.clear()
        quant.send_keys(str(QUANTITY))
        print(f"Quantity {QUANTITY} entered")
    except TimeoutException:
        print(f"Failed to enter quantity for {stock}. Moving to next stock.")
        printAndDiscord(f"Tornado failed to enter quantity for {stock}.", loop)
        return

    try:
        market_order_option = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="main-router"]/div[1]/div/div[6]/select/option[1]'))
        )
        market_order_option.click()
        print("Market order selected")
    except TimeoutException:
        print(f"Failed to select market order for {stock}. Moving to next stock.")
        printAndDiscord(f"Tornado failed to select market order for {stock}.", loop)
        return

    try:
        sell_price = driver.find_element(By.XPATH, '//*[@id="main-router"]/div[1]/div/div[7]/div').text.strip()
        print(f"Sell price for {stock}: {sell_price}")
    except TimeoutException:
        print(f"Failed to fetch sell price for {stock}. Moving to next stock.")
        printAndDiscord(f"Tornado failed to fetch sell price for {stock}.", loop)
        return

    if not DRY:
        try:
            submit_button = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="main-router"]/div[1]/div/div[11]/div/button')))
            submit_button.click()
            print(f"Successfully sold {QUANTITY} shares of {stock}")
            printAndDiscord(f"Tornado account: sell {QUANTITY} shares of {stock} at {sell_price}", loop)
            
            # Click the "Continue" button after placing the order
            continue_button = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="main-router"]/div[1]/div/div[2]/div/button')))
            continue_button.click()
            print("Clicked the Continue button after placing the order.")
        except TimeoutException:
            print(f"Failed to submit sell order for {stock} or click Continue. Moving to next stock.")
            printAndDiscord(f"Tornado failed to submit sell order for {stock} or click Continue.", loop)
    else:
        print(f"DRY MODE: Simulated order SELL for {QUANTITY} shares of {stock} at {sell_price}")
        printAndDiscord(f"Tornado account: dry run sell {QUANTITY} shares of {stock} at {sell_price}", loop)
