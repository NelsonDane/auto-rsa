import datetime
import os
import traceback
from asyncio import AbstractEventLoop
from time import sleep
from typing import cast

from dotenv import load_dotenv
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver import Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.wait import WebDriverWait

from src.helper_api import Brokerage, StockOrder, check_if_page_loaded, get_local_timezone, get_selenium_driver, kill_all_selenium_drivers, print_all_holdings, print_and_discord

load_dotenv()


def tornado_error(driver: Chrome, loop: AbstractEventLoop | None = None) -> None:
    """Handle errors that occur during Tornado API interactions."""
    driver.save_screenshot(f"Tornado-error-{datetime.datetime.now(get_local_timezone())}.png")
    print_and_discord(f"Tornado Error: {traceback.format_exc()}", loop, embed=False)


def tornado_init(*, docker_mode: bool = False, loop: AbstractEventLoop | None = None) -> Brokerage | None:
    """Initialize the Tornado API."""
    load_dotenv()

    if not os.getenv("TORNADO"):
        print("Tornado not found, skipping...")
        return None
    accounts = os.environ["TORNADO"].strip().split(",")

    tornado_obj = Brokerage("Tornado")

    for index, account in enumerate(accounts):
        account_name = f"Tornado {index + 1}"
        try:
            driver = get_selenium_driver(docker_mode=docker_mode)
            if driver is None:
                msg = "Driver not found."
                raise Exception(msg)
            driver.get("https://tornado.com/app/login")
            WebDriverWait(driver, 30).until(check_if_page_loaded)

            # Log in with email and password
            try:
                email_field = WebDriverWait(driver, 30).until(
                    ec.element_to_be_clickable((By.ID, "email-field")),
                )
                email_field.send_keys(account.split(":")[0])

                password_field = WebDriverWait(driver, 30).until(
                    ec.element_to_be_clickable((By.ID, "password-field")),
                )
                password_field.send_keys(account.split(":")[1])

                login_button = WebDriverWait(driver, 30).until(
                    ec.element_to_be_clickable(
                        (
                            By.CSS_SELECTOR,
                            "#root > div > div > div > div:nth-child(2) > div > div > div > div > form > div.sc-WZYut.ZaYjk > button",
                        ),
                    ),
                )
                login_button.click()

                # Check for the element after logging in to ensure the page is fully loaded
                WebDriverWait(driver, 60).until(
                    ec.presence_of_element_located(
                        (
                            By.XPATH,
                            "//*[@id='main-router']/div/div/div/div[1]/div/div/div/div[1]/div[1]/div/span",
                        ),
                    ),
                )

                tornado_obj.set_logged_in_object(account_name, driver)

                # Set the account name
                tornado_obj.set_account_number(account_name, account_name)

            except TimeoutException:
                print_and_discord(
                    f"TimeoutException: Login failed for {account_name}.",
                    loop,
                )
                return None

        except Exception:
            if driver:
                tornado_error(driver, loop)
                driver.close()
                driver.quit()
            return None
    return tornado_obj


def tornado_extract_holdings(driver: Chrome) -> list[dict[str, str | float]]:
    """Extract stock holdings from the Tornado platform."""
    holdings_data: list[dict[str, str | float]] = []
    try:
        # Locate all the individual stock holdings elements
        holdings_elements = driver.find_elements(
            By.XPATH,
            ".//div[@class='sc-jEWLvH evXkie']",
        )

        if len(holdings_elements) == 0:
            return holdings_data

        for holding_element in holdings_elements:
            try:
                # Extract the stock ticker
                stock_ticker = holding_element.find_element(
                    By.XPATH,
                    ".//a[1]/div[1]/span",
                ).text.strip()

                # Extract the number of shares available
                shares = holding_element.find_element(
                    By.XPATH,
                    ".//a[4]/div/div/span/span",
                ).text.strip()
                shares_float = float(shares.replace(" sh", ""))

                # Corrected XPath to extract the actual stock price
                price = holding_element.find_element(
                    By.XPATH,
                    ".//a[1]/div[3]/span/div/div[1]/span",
                ).text.strip()
                price_float = float(price.replace("$", "").replace(",", ""))

                # Store the extracted data in a dictionary
                holdings_data.append(
                    {
                        "stock_ticker": stock_ticker,
                        "shares": shares_float,
                        "price": price_float,
                    },
                )

            except Exception:
                tornado_error(driver)
                continue

    except Exception:
        tornado_error(driver)
        return []

    return holdings_data


def tornado_holdings(tornado_obj: Brokerage, loop: AbstractEventLoop | None = None) -> None:
    """Retrieve and display all Tornado account holdings."""
    try:
        # Ensure we are using the correct account name
        account_names = tornado_obj.get_account_numbers()
        for account_name in account_names:
            driver = cast("Chrome", tornado_obj.get_logged_in_objects(account_name))

            print(f"Processing holdings for {account_name}")

            # Fetch the total account value
            account_value_element = WebDriverWait(driver, 60).until(
                ec.presence_of_element_located(
                    (
                        By.XPATH,
                        "//*[@id='main-router']/div/div/div/div[1]/div/div/div[1]/div[1]/div[1]/div/span",
                    ),
                ),
            )
            account_value = account_value_element.text.strip()
            account_value_float = float(account_value.replace("$", "").replace(",", ""))

            # Extract holdings data
            holdings_data = tornado_extract_holdings(driver)

            if not holdings_data:
                print(f"No holdings found for {account_name}. Skipping account.")
                continue  # Skip to the next account

            for holding in holdings_data:
                tornado_obj.set_holdings(
                    account_name,
                    account_name,
                    str(holding["stock_ticker"]),
                    holding["shares"],
                    holding["price"],
                )

            # Set the account total using the fetched account value
            tornado_obj.set_account_totals(
                account_name,
                account_name,
                account_value_float,
            )

    except Exception as e:
        tornado_error(driver, loop)
        print_and_discord(f"Tornado Account: Error processing holdings: {e}", loop)

    print_all_holdings(tornado_obj, loop)  # Send the holdings to Discord
    kill_all_selenium_drivers(tornado_obj)  # Close the browser after processing


def tornado_transaction(tornado_obj: Brokerage, order_obj: StockOrder, loop: AbstractEventLoop | None = None) -> None:  # noqa: C901, PLR0912, PLR0915
    """Handle Tornado API transactions."""
    print("\n==============================")
    print("Tornado")
    print("==============================\n")
    for s in order_obj.get_stocks():
        for key in tornado_obj.get_account_numbers():
            driver = cast("Chrome", tornado_obj.get_logged_in_objects(key))

            # Ensure we are on the Tornado dashboard or navigate to it
            try:
                current_url = driver.current_url
                if "app" not in current_url:
                    driver.get("https://tornado.com/app/")
                    WebDriverWait(driver, 30).until(check_if_page_loaded)
            except Exception as e:
                tornado_error(driver, loop)
                print_and_discord(f"Failed to navigate to dashboard for {key}: {e}", loop)
                continue

            try:
                # Interact with the search bar
                search_field = WebDriverWait(driver, 20).until(
                    ec.element_to_be_clickable(
                        (By.CSS_SELECTOR, "#nav_securities_search"),
                    ),
                )
                search_field.click()
                sleep(1)
                search_field.send_keys(s)
            except TimeoutException:
                tornado_error(driver, loop)
                print_and_discord(f"Tornado search field not found for {s}.", loop)
                continue

            try:
                # Wait for and process search results
                WebDriverWait(driver, 10).until(
                    ec.presence_of_all_elements_located(
                        (
                            By.XPATH,
                            '//*[@id="nav_securities_search_container"]/div[2]/ul/li',
                        ),
                    ),
                )
                dropdown_items = driver.find_elements(
                    By.XPATH,
                    '//*[@id="nav_securities_search_container"]/div[2]/ul/li',
                )
                total_items = len(dropdown_items)
                sleep(2)

                if total_items == 0:
                    print_and_discord(f"Tornado doesn't have {s}.", loop)
                    continue

                found_stock = False
                for item in dropdown_items:
                    ticker_name = item.find_element(By.CLASS_NAME, "bold").text.strip()
                    if ticker_name == s:
                        found_stock = True
                        sleep(1)
                        item.click()
                        break

                if not found_stock:
                    print_and_discord(f"Tornado doesn't have {s}.", loop)
                    continue
            except TimeoutException:
                tornado_error(driver, loop)
                print_and_discord(f"Tornado search results did not appear for {s}.", loop)
                continue

            # Proceed with the transaction based on the action (buy/sell)
            if order_obj.get_action() == "buy":
                handle_buy(driver, s, order_obj, loop)
            elif order_obj.get_action() == "sell":
                handle_sell(driver, s, order_obj, loop)

            # Ensure to return to the dashboard after every transaction
            try:
                dashboard_link = WebDriverWait(driver, 30).until(
                    ec.element_to_be_clickable(
                        (
                            By.XPATH,
                            '//*[@id="root"]/div/div/div[4]/div/div[1]/div/div/div[2]/div[1]/div[2]/span[1]/a/span',
                        ),
                    ),
                )
                dashboard_link.click()
                WebDriverWait(driver, 60).until(
                    ec.presence_of_element_located(
                        (
                            By.XPATH,
                            '//*[@id="main-router"]/div/div/div/div[1]/div/div/div/div[1]/div[1]/div/span',
                        ),
                    ),
                )
            except TimeoutException:
                tornado_error(driver, loop)
                print_and_discord(
                    f"Tornado failed to return to dashboard after processing {s}.",
                    loop,
                )

    print("Completed all transactions, Exiting...")
    kill_all_selenium_drivers(tornado_obj)


def handle_buy(driver: Chrome, stock: str, order_obj: StockOrder, loop: AbstractEventLoop | None) -> None:  # noqa: C901, PLR0911, PLR0914, PLR0915
    """Handle the buy action for a stock order."""
    dry_mode = order_obj.get_dry()
    quantity = order_obj.get_amount()
    print("DRY MODE:", dry_mode)

    try:
        buy_button = WebDriverWait(driver, 20).until(
            ec.element_to_be_clickable((By.XPATH, '//*[@id="buy-button"]')),
        )
        driver.execute_script("arguments[0].click();", buy_button)
    except TimeoutException:
        tornado_error(driver, loop)
        print_and_discord(f"Tornado buy button not found for {stock}.", loop)
        return

    try:
        quant = WebDriverWait(driver, 20).until(
            ec.element_to_be_clickable(
                (By.XPATH, '//*[@id="main-router"]/div[1]/div/div[3]/input'),
            ),
        )
        quant.clear()
        quant.send_keys(str(quantity))
    except TimeoutException:
        tornado_error(driver, loop)
        print_and_discord(f"Tornado failed to enter quantity for {stock}.", loop)
        return

    try:
        current_shares_element = driver.find_element(
            By.XPATH,
            '//*[@id="main-router"]/div[1]/div/div[4]/div',
        )
        has_current_shares = bool("sh" in current_shares_element.text.strip())
    except NoSuchElementException:
        has_current_shares = False

    market_order_xpath = '//*[@id="main-router"]/div[1]/div/div[5]/select/option[1]' if has_current_shares else '//*[@id="main-router"]/div[1]/div/div[4]/select/option[1]'
    current_price_xpath = '//*[@id="main-router"]/div[1]/div/div[6]/div[contains(text(), "$")]' if has_current_shares else '//*[@id="main-router"]/div[1]/div/div[5]/div[contains(text(), "$")]'
    buy_power_xpath = '//*[@id="main-router"]/div[1]/div/div[8]/div[contains(text(), "$")]' if has_current_shares else '//*[@id="main-router"]/div[1]/div/div[7]/div[contains(text(), "$")]'

    try:
        market_order_option = WebDriverWait(driver, 20).until(
            ec.presence_of_element_located((By.XPATH, market_order_xpath)),
        )
        market_order_option.click()
    except TimeoutException:
        tornado_error(driver, loop)
        print_and_discord(f"Tornado failed to select market order for {stock}.", loop)
        return

    try:
        sleep(3)
        buy_power = driver.find_element(By.XPATH, buy_power_xpath).text.strip()
        cost = driver.find_element(By.XPATH, current_price_xpath).text.strip()

        # Validate and convert buy power
        buy_power_float = float(buy_power.replace("$", "").replace(",", ""))

        # Validate and convert cost, ensuring it's a valid price
        if "$" in cost:
            try:
                cost_float = float(cost.replace("$", "").replace(",", ""))
            except ValueError:
                print_and_discord(
                    f"Tornado: Invalid price format for {stock}: {cost}",
                    loop,
                )
                return
        else:
            print_and_discord(
                f"Tornado: Price not available or in an unexpected format for {stock}: {cost}",
                loop,
            )
            return

        # Check if the available buying power is enough
        if buy_power_float < cost_float:
            tornado_error(driver, loop)
            print_and_discord(
                f"Tornado insufficient funds to buy {stock}. Required: ${cost_float}, Available: ${buy_power_float}",
                loop,
            )
            return

    except TimeoutException:
        tornado_error(driver, loop)
        print_and_discord(
            f"Tornado failed to fetch buying power or cost for {stock}.",
            loop,
        )
        return

    if not dry_mode:
        try:
            submit_button = WebDriverWait(driver, 20).until(
                ec.element_to_be_clickable(
                    (
                        By.XPATH,
                        '//*[@id="main-router"]/div[1]/div/div[10]/div/button | //*[@id="main-router"]/div[1]/div/div[9]/div/button',
                    ),
                ),
            )
            submit_button.click()
            print_and_discord(
                f"Tornado account: buy {quantity} shares of {stock} at {cost}",
                loop,
            )

            # Click the "Continue" button after placing the order
            continue_button = WebDriverWait(driver, 20).until(
                ec.element_to_be_clickable(
                    (By.XPATH, '//*[@id="main-router"]/div[1]/div/div[2]/div/button'),
                ),
            )
            continue_button.click()
        except TimeoutException:
            tornado_error(driver, loop)
            print_and_discord(
                f"Tornado failed to submit buy order for {stock} or click Continue.",
                loop,
            )
    else:
        sleep(5)
        print_and_discord(
            f"DRY MODE: Simulated order BUY for {quantity} shares of {stock} at {cost}",
            loop,
        )


def handle_sell(driver: Chrome, stock: str, order_obj: StockOrder, loop: AbstractEventLoop | None) -> None:
    """Handle the sell action for a stock order."""
    dry_mode = order_obj.get_dry()
    quantity = order_obj.get_amount()

    try:
        sell_button = WebDriverWait(driver, 20).until(
            ec.element_to_be_clickable((By.XPATH, '//*[@id="sell-button"]')),
        )
        driver.execute_script("arguments[0].click();", sell_button)
    except TimeoutException:
        tornado_error(driver, loop)
        print_and_discord(f"Tornado sell button not found for {stock}.", loop)
        return

    try:
        current_shares_element = driver.find_element(
            By.XPATH,
            '//*[@id="main-router"]/div[1]/div/div[4]/div',
        )
        current_shares = float(current_shares_element.text.strip().replace(" sh", ""))
    except NoSuchElementException:
        print_and_discord(f"Tornado no current shares to sell for {stock}.", loop)
        return

    if current_shares < quantity:
        print_and_discord(
            f"Tornado not enough shares to sell {stock}. Available: {current_shares}",
            loop,
        )
        return

    try:
        quant = WebDriverWait(driver, 20).until(
            ec.element_to_be_clickable(
                (By.XPATH, '//*[@id="main-router"]/div[1]/div/div[3]/input'),
            ),
        )
        quant.clear()
        quant.send_keys(str(quantity))
    except TimeoutException:
        tornado_error(driver, loop)
        print_and_discord(f"Tornado failed to enter quantity for {stock}.", loop)
        return

    try:
        market_order_option = WebDriverWait(driver, 20).until(
            ec.presence_of_element_located(
                (By.XPATH, '//*[@id="main-router"]/div[1]/div/div[6]/select/option[1]'),
            ),
        )
        market_order_option.click()
    except TimeoutException:
        tornado_error(driver, loop)
        print_and_discord(f"Tornado failed to select market order for {stock}.", loop)
        return

    try:
        sell_price = driver.find_element(
            By.XPATH,
            '//*[@id="main-router"]/div[1]/div/div[7]/div',
        ).text.strip()
    except TimeoutException:
        tornado_error(driver, loop)
        print_and_discord(f"Tornado failed to fetch sell price for {stock}.", loop)
        return

    if not dry_mode:
        try:
            submit_button = WebDriverWait(driver, 20).until(
                ec.element_to_be_clickable(
                    (By.XPATH, '//*[@id="main-router"]/div[1]/div/div[11]/div/button'),
                ),
            )
            submit_button.click()
            print_and_discord(
                f"Tornado account: sell {quantity} shares of {stock} at {sell_price}",
                loop,
            )

            # Click the "Continue" button after placing the order
            continue_button = WebDriverWait(driver, 20).until(
                ec.element_to_be_clickable(
                    (By.XPATH, '//*[@id="main-router"]/div[1]/div/div[2]/div/button'),
                ),
            )
            continue_button.click()
        except TimeoutException:
            tornado_error(driver, loop)
            print_and_discord(
                f"Tornado failed to submit sell order for {stock} or click Continue.",
                loop,
            )
    else:
        print_and_discord(
            f"DRY MODE: Simulated order SELL for {quantity} shares of {stock} at {sell_price}",
            loop,
        )
