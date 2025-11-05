import asyncio
import contextlib
import datetime
import os
import re
import traceback
from time import sleep
from typing import cast

from discord.ext.commands import Bot
from dotenv import load_dotenv
from selenium.common.exceptions import (
    ElementNotInteractableException,
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver import Chrome, Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.wait import WebDriverWait

from src.helper_api import Brokerage, StockOrder, check_if_page_loaded, get_local_timezone, get_otp_from_discord, get_selenium_driver, kill_all_selenium_drivers, print_all_holdings, print_and_discord, type_slowly


def _wellsfargo_error(driver: Chrome, error: str) -> None:
    print(f"Wells Fargo Error: {error}")
    driver.save_screenshot(f"wells-fargo-error-{datetime.datetime.now(get_local_timezone())}.png")
    print(traceback.format_exc())


def wellsfargo_init(bot_obj: Bot | None, *, docker_mode: bool = False, loop: asyncio.AbstractEventLoop | None = None) -> Brokerage | None:  # noqa: C901, PLR0912, PLR0914, PLR0915
    """Initialize the Wells Fargo API."""
    load_dotenv()

    if not os.getenv("WELLSFARGO"):
        print("WELLSFARGO environment variable not found.")
        return None
    accounts = os.environ["WELLSFARGO"].strip().split(",")
    wf_obj = Brokerage("WELLSFARGO")
    for wells_account in accounts:
        index = accounts.index(wells_account) + 1
        name = f"WELLSFARGO {index}"
        account = wells_account.split(":")
        try:
            print_and_discord("Logging into WELLS FARGO...", loop)
            driver = get_selenium_driver(docker_mode=docker_mode)
            if driver is None:
                msg = "Driver not found."
                raise Exception(msg)
            driver.get("https://connect.secure.wellsfargo.com/auth/login/present")
            WebDriverWait(driver, 20).until(check_if_page_loaded)
            # Login
            try:
                username_field = driver.find_element(By.XPATH, "//*[@id='j_username']")
                type_slowly(username_field, account[0])
                # Wait for the password field and enter the password
                password_field = driver.find_element(By.XPATH, "//*[@id='j_password']")
                type_slowly(password_field, account[1])

                login_button = WebDriverWait(driver, 20).until(
                    ec.element_to_be_clickable(
                        (By.CSS_SELECTOR, ".Button__modern___cqCp7"),
                    ),
                )
                login_button.click()
                WebDriverWait(driver, 20).until(check_if_page_loaded)
                print("=====================================================\n")
            except TimeoutException:
                print("TimeoutException: Login failed.")
                return None
            wf_obj.set_logged_in_object(name, driver)
            try:
                auth_popup = WebDriverWait(driver, 10).until(
                    ec.presence_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            ".ResponsiveModalContent__modalContent___guT3p",
                        ),
                    ),
                )
                auth_list = auth_popup.find_element(
                    By.CSS_SELECTOR,
                    ".LineItemLinkList__lineItemLinkList___Dj6vb",
                )
                li_elements = auth_list.find_elements(By.TAG_NAME, "li")
                for li in li_elements:
                    if account[2] in li.text:
                        li.click()
                        break
                print("Clicked on phone number")
                # Get the OTP code from the user
                if bot_obj is not None and loop is not None:  # noqa: SIM108
                    code = asyncio.run_coroutine_threadsafe(
                        get_otp_from_discord(bot_obj, name, timeout=300, loop=loop),
                        loop,
                    ).result()
                else:
                    code = input("Enter security code: ")
                code_input = WebDriverWait(driver, 20).until(
                    ec.presence_of_element_located((By.ID, "otp")),
                )
                if code:
                    code_input.send_keys(code)
                WebDriverWait(driver, 10).until(
                    ec.element_to_be_clickable((By.XPATH, "//button[@type='submit']")),
                ).click()
            except TimeoutException:
                pass

            WebDriverWait(driver, 20).until(
                ec.presence_of_element_located((By.LINK_TEXT, "Locations")),
            )

            # TODO: This will not show accounts that do not have settled cash funds  # noqa: FIX002, TD002, TD003
            account_blocks = driver.find_elements(
                By.CSS_SELECTOR,
                'li[data-testid^="WELLSTRADE"]',
            )
            for account_block in account_blocks:
                masked_number_element = account_block.find_element(
                    By.CSS_SELECTOR,
                    '[data-testid$="-masked-number"]',
                )
                masked_number_text = masked_number_element.text.replace(".", "*")
                wf_obj.set_account_number(name, masked_number_text)
                balance_element = account_block.find_element(
                    By.CSS_SELECTOR,
                    '[data-testid$="-balance"]',
                )
                balance = float(balance_element.text.replace("$", "").replace(",", ""))
                wf_obj.set_account_totals(name, masked_number_text, balance)
        except Exception as e:
            if driver:
                _wellsfargo_error(driver, str(e))
                driver.close()
                driver.quit()
            return None
    return wf_obj


def wellsfargo_holdings(wf_obj: Brokerage, loop: asyncio.AbstractEventLoop | None = None) -> None:  # noqa: C901, PLR0912, PLR0914, PLR0915
    """Retrieve and display all Wells Fargo account holdings."""
    for key in wf_obj.get_account_numbers():
        driver = cast("Chrome", wf_obj.get_logged_in_objects(key))
        try:
            brokerage = WebDriverWait(driver, 20).until(
                ec.element_to_be_clickable((By.XPATH, "//*[@id='BROKERAGE_LINK7P']")),
            )
            brokerage.click()

            try:
                more = WebDriverWait(driver, 20).until(
                    ec.element_to_be_clickable((By.LINK_TEXT, "Holdings Snapshot")),
                )
                more.click()
                position = WebDriverWait(driver, 10).until(
                    ec.element_to_be_clickable((By.ID, "btnpositions")),
                )
                position.click()
            except Exception as e:
                _wellsfargo_error(driver, str(e))
                kill_all_selenium_drivers(wf_obj)
                return

            # Check if multi-account dropdown exists
            try:
                WebDriverWait(driver, 5).until(
                    ec.presence_of_element_located((By.XPATH, "//*[@id='dropdown1']")),
                )
                is_multi_account = True
            except TimeoutException:
                is_multi_account = False

            account_masks = wf_obj.get_account_numbers(key)
            if not account_masks:
                print(f"Error: No account masks found stored for {key}")
                kill_all_selenium_drivers(wf_obj)
                return

            if is_multi_account:
                # Original multi-account logic
                open_dropdown = WebDriverWait(driver, 20).until(
                    ec.element_to_be_clickable((By.XPATH, "//*[@id='dropdown1']")),
                )
                open_dropdown.click()

                accounts = driver.execute_script(
                    "return document.getElementById('dropdownlist1').getElementsByTagName('li').length;",
                )
                accounts = int(accounts - 3)  # Adjust based on actual implementation

                for account in range(accounts):
                    if account >= len(account_masks):
                        continue
                    try:
                        open_dropdown = WebDriverWait(driver, 20).until(
                            ec.element_to_be_clickable(
                                (By.XPATH, "//*[@id='dropdown1']"),
                            ),
                        )
                        open_dropdown.click()
                        sleep(1)
                        find_account = """
                            var items = document.getElementById('dropdownlist1').getElementsByTagName('li');
                            for (var i = 0; i < items.length; i++) {
                                if (items[i].innerText.includes(arguments[0])) {
                                    items[i].click();
                                    return i;
                                }
                            }
                            return -1;
                        """
                        select_account = driver.execute_script(
                            find_account,
                            account_masks[account].replace("*", ""),
                        )
                        if select_account == -1:
                            print("Could not find the account with the specified text")
                            continue
                    except Exception:
                        print("Could not change account")
                        kill_all_selenium_drivers(wf_obj)
                        continue

                    sleep(1)
                    rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")

                    for row in rows:
                        cells = row.find_elements(By.CSS_SELECTOR, "td")
                        if len(cells) >= 9:  # noqa: PLR2004
                            name_match = re.search(r"^[^\n]*", cells[1].text)
                            amount_match = re.search(
                                r"-?\d+(\.\d+)?",
                                cells[3].text.replace("\n", ""),
                            )
                            price_match = re.search(
                                r"-?\d+(\.\d+)?",
                                cells[4].text.replace("\n", ""),
                            )
                            name = name_match.group(0) if name_match else cells[1].text
                            amount = amount_match.group(0) if amount_match else "0"
                            price = price_match.group(0) if price_match else "0"

                            wf_obj.set_holdings(
                                key,
                                account_masks[account],
                                name.strip(),
                                float(amount),
                                float(price),
                            )
            else:
                # Single account logic
                current_mask = account_masks[0]
                sleep(1)
                rows = driver.find_elements(By.CSS_SELECTOR, "tbody tr")

                for row in rows:
                    cells = row.find_elements(By.CSS_SELECTOR, "td")
                    if len(cells) >= 9:  # noqa: PLR2004
                        name_match = re.search(r"^[^\n]*", cells[1].text)
                        amount_match = re.search(
                            r"-?\d+(\.\d+)?",
                            cells[3].text.replace("\n", ""),
                        )
                        price_match = re.search(
                            r"-?\d+(\.\d+)?",
                            cells[4].text.replace("\n", ""),
                        )
                        name = name_match.group(0) if name_match else cells[1].text
                        amount = amount_match.group(0) if amount_match else "0"
                        price = price_match.group(0) if price_match else "0"

                        wf_obj.set_holdings(
                            key,
                            current_mask,
                            name.strip(),
                            float(amount),
                            float(price),
                        )

        except TimeoutException:
            print("Could not get to holdings")
            kill_all_selenium_drivers(wf_obj)
            return

        print_all_holdings(wf_obj, loop)
        kill_all_selenium_drivers(wf_obj)


def wellsfargo_transaction(wf_obj: Brokerage, order_obj: StockOrder, loop: asyncio.AbstractEventLoop | None = None) -> None:  # noqa: C901, PLR0912, PLR0914, PLR0915
    """Handle Wells Fargo stock transactions."""
    print()
    print("==============================")
    print("WELLS FARGO")
    print("==============================")
    print()

    for key in wf_obj.get_account_numbers():
        driver = cast("Chrome", wf_obj.get_logged_in_objects(key))

        # Navigate to Trade
        try:
            brokerage = WebDriverWait(driver, 20).until(
                ec.element_to_be_clickable((By.XPATH, "//*[@id='BROKERAGE_LINK7P']")),
            )
            brokerage.click()

            trade = WebDriverWait(driver, 20).until(
                ec.element_to_be_clickable((By.XPATH, "//*[@id='trademenu']/span[1]")),
            )
            trade.click()

            trade_stock = WebDriverWait(driver, 20).until(
                ec.element_to_be_clickable((By.XPATH, "//*[@id='linktradestocks']")),
            )
            trade_stock.click()

            # Find accounts
            open_dropdown = WebDriverWait(driver, 20).until(
                ec.element_to_be_clickable((By.XPATH, "//*[@id='dropdown2']")),
            )
            open_dropdown.click()

            accounts = driver.execute_script(
                "return document.getElementById('dropdownlist2').getElementsByTagName('li').length;",
            )
            accounts = int(accounts)
        except TimeoutException:
            print("could not get to trade")
            kill_all_selenium_drivers(wf_obj)

        account_masks = wf_obj.get_account_numbers(key)
        # Use to keep track of an order to know whether to reset the trading screen
        order_failed = False
        for account in range(accounts):
            WebDriverWait(driver, 20).until(check_if_page_loaded)
            if account >= len(account_masks):
                continue
            try:
                if order_failed and order_obj.get_dry():
                    trade = WebDriverWait(driver, 20).until(
                        ec.element_to_be_clickable(
                            (By.XPATH, "//*[@id='trademenu']/span[1]"),
                        ),
                    )
                    trade.click()
                    trade_stock = WebDriverWait(driver, 20).until(
                        ec.element_to_be_clickable(
                            (By.XPATH, "//*[@id='linktradestocks']"),
                        ),
                    )
                    trade_stock.click()
                    dismiss_prompt = WebDriverWait(driver, 20).until(
                        ec.element_to_be_clickable((By.ID, "btn-continue")),
                    )
                    dismiss_prompt.click()
                # choose account
                open_dropdown = WebDriverWait(driver, 20).until(
                    ec.element_to_be_clickable((By.XPATH, "//*[@id='dropdown2']")),
                )
                open_dropdown.click()
                find_account = """
                    var items = document.getElementById('dropdownlist2').getElementsByTagName('li');
                    for (var i = 0; i < items.length; i++) {
                        if (items[i].innerText.includes(arguments[0])) {
                            items[i].click();
                            return i;
                        }
                    }
                    return -1;
                """
                select_account = driver.execute_script(
                    find_account,
                    account_masks[account].replace("*", ""),
                )
                sleep(2)
                # Check for clear ticket prompt and accept
                with contextlib.suppress(NoSuchElementException, ElementNotInteractableException):
                    driver.find_element(By.ID, "btn-continue").click()
                if select_account == -1:
                    print("Could not find the account with the specified text")
                    continue
            except Exception:
                traceback.print_exc()
                print("Could not change account")
                kill_all_selenium_drivers(wf_obj)
            for s in order_obj.get_stocks():
                WebDriverWait(driver, 20).until(check_if_page_loaded)
                # If an order fails need to sort of reset the tradings screen. Refresh does not work
                if order_failed:
                    trade = WebDriverWait(driver, 20).until(
                        ec.element_to_be_clickable(
                            (By.XPATH, "//*[@id='trademenu']/span[1]"),
                        ),
                    )
                    trade.click()
                    trade_stock = WebDriverWait(driver, 20).until(
                        ec.element_to_be_clickable(
                            (By.XPATH, "//*[@id='linktradestocks']"),
                        ),
                    )
                    trade_stock.click()
                    dismiss_prompt = WebDriverWait(driver, 20).until(
                        ec.element_to_be_clickable((By.ID, "btn-continue")),
                    )
                    dismiss_prompt.click()
                sleep(2)
                # idk why doing it through selenium doesnt work sometimes
                driver.execute_script('document.getElementById("BuySellBtn").click()')
                # Buy or Sell
                if order_obj.get_action().lower() == "buy":
                    action = WebDriverWait(driver, 20).until(
                        ec.element_to_be_clickable((By.LINK_TEXT, "Buy")),
                    )
                elif order_obj.get_action().lower() == "sell":
                    action = WebDriverWait(driver, 20).until(
                        ec.element_to_be_clickable((By.LINK_TEXT, "Sell")),
                    )
                else:
                    print("no buy or sell set")
                action.click()

                review = WebDriverWait(driver, 20).until(
                    ec.element_to_be_clickable((By.ID, "actionbtnContinue")),
                )
                driver.execute_script("arguments[0].scrollIntoView(true);", review)
                sleep(2)
                ticker_box = WebDriverWait(driver, 20).until(
                    ec.element_to_be_clickable((By.ID, "Symbol")),
                )

                ticker_box.send_keys(s)
                ticker_box.send_keys(Keys.ENTER)

                # quantity
                driver.execute_script(
                    "document.querySelector('#OrderQuantity').value =" + str(int(order_obj.get_amount())),
                )

                # get price
                WebDriverWait(driver, 20).until(
                    ec.presence_of_element_located((By.CLASS_NAME, "qeval")),
                )

                price = float(driver.find_element(By.CLASS_NAME, "qeval").text)
                price_cuttoff = 2
                if order_obj.get_action().lower() == "buy" and price < price_cuttoff:
                    price_type = "Limit"
                    price += 0.01
                elif order_obj.get_action().lower() == "sell" and price < price_cuttoff:
                    price_type = "Limit"
                    price -= 0.01
                else:
                    price_type = "Market"

                # order type
                driver.execute_script(
                    "document.getElementById('OrderTypeBtnText').click()",
                )

                # limit price
                order = driver.find_element(By.LINK_TEXT, price_type)
                order.click()
                if price_type == "Limit":
                    ticker_box = driver.find_element(By.ID, "Price")
                    ticker_box.send_keys(str(price))
                    ticker_box.send_keys(Keys.ENTER)

                    # timing
                    driver.execute_script("document.getElementById('TIFBtn').click()")
                    sleep(1)
                    day = driver.find_element(By.LINK_TEXT, "Day")
                    day.click()

                # preview
                driver.execute_script("arguments[0].click();", review)
                try:
                    if not order_obj.get_dry():
                        # submit
                        submit = WebDriverWait(driver, 10).until(
                            ec.element_to_be_clickable(
                                (By.CSS_SELECTOR, ".btn-wfa-submit"),
                            ),
                        )
                        driver.execute_script(
                            "arguments[0].click();",
                            submit,
                        )  # Was getting visibility issues even though scrolling to it
                        # Send confirmation
                        print_and_discord(
                            f"{key} {wf_obj.get_account_numbers(key)[account]}: {order_obj.get_action()} {order_obj.get_amount()} shares of {s}",
                            loop,
                        )
                        # buy next
                        buy_next = driver.find_element(
                            By.CSS_SELECTOR,
                            ".btn-wfa-primary",
                        )
                        driver.execute_script("arguments[0].click();", buy_next)
                        order_failed = False
                    elif order_obj.get_dry():
                        print_and_discord(
                            f"DRY: {key} account {wf_obj.get_account_numbers(key)[account]}: {order_obj.get_action()} {order_obj.get_amount()} shares of {s}",
                            loop,
                        )
                        order_failed = True
                except TimeoutException:
                    error_text = driver.find_element(
                        By.XPATH,
                        "//div[@class='alert-msg-summary']//p[1]",
                    ).text
                    order_failed = True
                    print_and_discord(
                        f"{key} {wf_obj.get_account_numbers(key)[account]}: {order_obj.get_action()} {order_obj.get_amount()} shares of {s}. FAILED! \n{error_text}",
                        loop,
                    )
                    # Cancel the trade
                    cancel_button = WebDriverWait(driver, 3).until(
                        ec.element_to_be_clickable(
                            (By.CSS_SELECTOR, "#actionbtnCancel"),
                        ),
                    )
                    driver.execute_script(
                        "arguments[0].click();",
                        cancel_button,
                    )  # Must be clicked with js since it's out of view
                    WebDriverWait(driver, 3).until(
                        ec.element_to_be_clickable((By.CSS_SELECTOR, "#btn-continue")),
                    ).click()
        kill_all_selenium_drivers(wf_obj)
