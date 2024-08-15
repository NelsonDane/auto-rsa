import datetime
import os
import re
import traceback
from time import sleep,time
import logging

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support.ui import Select


from helperAPI import (
    Brokerage,
    check_if_page_loaded,
    getDriver,
    killSeleniumDriver,
    maskString,
    printAndDiscord,
    printHoldings,
    stockOrder,
    type_slowly,
)
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sofi_error(driver,e):
    print("SOFI Error: ", e)
    driver.save_screenshot(f"SOFI-error-{datetime.datetime.now()}.png")
    #printAndDiscord("SOFI Error: " + str(e))
    print(traceback.format_exc())


def sofi_init(SOFI_EXTERNAL=None,DOCKER=False):
    load_dotenv()

    if not os.getenv("SOFI") and SOFI_EXTERNAL is None:
        print("SOFI environment variable not found.")
        return None
    accounts = (
        os.environ["SOFI"].strip().split(",")
        if SOFI_EXTERNAL is None
        else SOFI_EXTERNAL.strip().split(",")
    )
    SOFI_obj = Brokerage("SOFI")
    for account in accounts:
        # DRIVER=getDriver(DOCKER=False)
        index = accounts.index(account) + 1
        name = f"SOFI {index}"
        account = account.split(":")
        try:
            print("Logging into SOFI...")
            # driver=DRIVER
            driver=getDriver(DOCKER=False)
            if driver is None:
                raise Exception("Driver not found.")
            driver.get(
                'https://login.sofi.com/u/login?state=hKFo2SBiMkxuWUxGckdxdVJ0c3BKLTlBdEk1dFgwQnZCcWo0ZKFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIHdDekRxWk81cURTYWVZOVJleEJORE9vMExBVFVjMEw2o2NpZNkgNkxuc0xDc2ZGRUVMbDlTQzBDaWNPdkdlb2JvZXFab2I'
            )
            WebDriverWait(driver, 20).until(check_if_page_loaded)
            # Login
            try:
                print("Username:", account[0], "Password:", (account[1]))
                username_field = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='username']")))
                username_field.send_keys(account[0])

                # Wait for the password field and enter the password
                password_field = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='password']")))
                password_field.send_keys(account[1])
                


                login_button = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='widget_block']/div/div[2]/div/div/main/section/div/div/div/form/div[2]/button")))
                login_button.click()
                #//*[@id="prompt-alert"]/p
                '''
                try:
                    tooManyAttempts=WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//*[@id='prompt-alert']/p")))
                    print("Too many attempts, give it a break and come back later.")
                except TimeoutException:
                    return
                '''
                print("=====================================================\n")
              
                # code2fa=input('Please enter code and press ENTER to continue:')
              
                # code_field = WebDriverWait(driver, 60).until(
                #     EC.element_to_be_clickable((By.XPATH, "//*[@id='code']")))
                # code_field.send_keys(code2fa)



                # code_button = WebDriverWait(driver, 20).until(
                #     EC.element_to_be_clickable((By.XPATH, "//*[@id='widget_block']/div/div[2]/div/div/main/section/div/div/div/div[1]/div/form/div[3]/button")))
                # code_button.click()
                
                max_attempts = 3
                attempts = 0

                while attempts < max_attempts:
                    try:
                        # Prompt the user for the 2FA code
                        code2fa = input('Please enter code and press ENTER to continue:')
                        
                        # Wait for the code field to be clickable and enter the code
                        code_field = WebDriverWait(driver, 60).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='code']")))
                        code_field.send_keys(code2fa)

                        # Click the submit button or the appropriate element to continue
                        code_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='widget_block']/div/div[2]/div/div/main/section/div/div/div/div[1]/div/form/div[3]/button")))
                        code_button.click()

                        # Wait briefly to allow the page to process the input
                        sleep(3)

                        # Check if the 2FA input field is still present
                        if driver.find_elements(By.XPATH, "//*[@id='code']"):
                            attempts += 1
                            print(f"Attempt {attempts} failed. Incorrect code.")
                            
                            # If max attempts are reached, print a message and exit the loop
                            if attempts >= max_attempts:
                                print("Too many attempts. Please try again later.")
                                raise TimeoutException("Max 2FA attempts reached. Exiting...")

                        else:
                            print("2FA code accepted. Proceeding...")
                            break  # Exit the loop if the 2FA code is correct and accepted

                    except TimeoutException:
                        if attempts >= max_attempts:
                            print("Too many attempts. Please try again later.")
                            raise TimeoutException("Max 2FA attempts reached due to timeouts. Exiting...")
            except TimeoutException:
                print("TimeoutException: Login failed.")
                driver.quit()
                continue
            
            SOFI_obj.set_logged_in_object(name, driver)
            # Get account numbers, types, and balances
        
            SOFI_obj.set_account_number(name, account[0])
            print(f"Logged in to {name}!")
            print(" ")

        except Exception as e:
            sofi_error(driver,e)
            driver.close()
            driver.quit()
            return None
    return SOFI_obj


def sofi_transaction(SOFI_o:Brokerage,orderObj:stockOrder,loop=None,DOCKER=False):
    print()
    print("==============================")
    print("SOFI")
    print("==============================")
    print()
    # //*[@id="root"]/div/header/nav/div[2]/a[4] 
    # //*[@id="root"]/div/header/nav/div[3]/a[4]
    for s in orderObj.get_stocks():
        for key in SOFI_o.get_account_numbers():
            driver = SOFI_o.get_logged_in_objects(key)
            driver.get("https://www.sofi.com/wealth/app/overview")
            # investment_button = WebDriverWait(driver, 20).until(
            #     EC.element_to_be_clickable((By.XPATH, "//*[@id='root']/div/header/nav/div[3]/a[4]")))
            # investment_button.click()
            try:
                # search_field = WebDriverWait(driver, 20).until(
                #     EC.element_to_be_clickable((By.XPATH, "//*[@id='page-wrap']/div[1]/div/div/div/div/input")))
                search_field = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.NAME, "search-bar")))
                search_field.send_keys(s)
                # WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located((By.XPATH, "//*[@id='page-wrap']/div[1]/div/div/div/ul/li")))
                # dropdown_items = driver.find_elements(By.XPATH, "//*[@id='page-wrap']/div[1]/div/div/div/ul/li")
                # total_items = len(dropdown_items)
            except TimeoutException:
                try:
                    invest_search_field=WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[1]/div/div/div/input")))
                    invest_search_field.send_keys(s)
                except TimeoutException:
                    print("Search field not found")
                    continue
            WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located((By.XPATH, "//*[@id='page-wrap']/div[1]/div/div/div/ul/li")))
            dropdown_items = driver.find_elements(By.XPATH, "//*[@id='page-wrap']/div[1]/div/div/div/ul/li")
            total_items = len(dropdown_items)
            #//*[@id="mainContent"]/div[2]/div[2]/div[2]/div[1]/div/div/ul/li

            if total_items == 0:
                print("No stock found")
                return
            
            found_stock = False
            for item in dropdown_items:
                ticker_name = item.find_element(By.XPATH, "./a/div/p[1]").text
                if ticker_name == s:
                    found_stock = True
                    item.click()
                    break

            if not found_stock:
                print(f"SOFI DOESN'T HAVE {s}")
                return
            if orderObj.get_action() == "buy":
                clicked_values = set()  # Set to keep track of processed accounts
            
                DRY=orderObj.get_dry()
                QUANTITY=orderObj.get_amount()
                print("DRY MODE:", DRY)
                account_number=1
                sleep(4)
                while True:
                    # Click the buy button
                    sleep(1)
                    buy_button = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[2]/div/button[1]")))
                    driver.execute_script("arguments[0].click();", buy_button)
                    #//*[@id="shares"]
                    sleep(1)
                    try:
                        dropdown = driver.find_element(By.XPATH, "//*[@id='OrderTypedDropDown']")
                        print("Found ordertypedropdown")
        
                        # Check if the dropdown is already set to "Limit price"
                        selected_option = dropdown.find_element(By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[3]/p[2]').text
                        print("selected_option:", selected_option)
                        #//*[@id="OrderTypedDropDown"]
                        if selected_option != "Limit price":
                            print("We're in the dropdown")
                            OrderTypedDropDown=WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='OrderTypedDropDown']")))
                            OrderTypedDropDown.click()
                            #//*[@id="OrderTypedDropDown"]/option[2]
                            OrderTypedDropDown_limit=WebDriverWait(driver, 3).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='OrderTypedDropDown']/option[2]")))
                            OrderTypedDropDown_limit.click()
                    except (NoSuchElementException, TimeoutException):
                        print('We passed')
                        pass


                    # Handle account selection
                    accounts_dropdown = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.NAME, "account")))
                    select = Select(accounts_dropdown)

                    # Find an unclicked account
                    for option in select.options:
                        value = option.get_attribute('value')
                        if value not in clicked_values:
                            select.select_by_value(value)
                            print("Selected account",account_number,":", {value})
                            account_number+=1
                            clicked_values.add(value)
                            break
                    else:
                        print(f"All accounts have been processed for {s}.")
                        try:
                            cancel_button = WebDriverWait(driver, 20).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                            cancel_button.click()
                        except TimeoutException:
                            pass
                        break  # Exit the while loop if all accounts are processed

                    # Input quantity and price
                    sleep(1)
                    # //*[@id="mainContent"]/div[2]/div[2]/div[3]/div/p
                    # Fetch the live price
                    live_price = WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/p")))
                    live_price=live_price.text
                    print("live price presplit:", live_price)
                    live_price = live_price.split('$')[1]
                    
                    quant = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.NAME, "shares")))
                    quant.send_keys(QUANTITY)
                    
                    limit_price = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.NAME, "value")))

                    if float(live_price)<0.11:
                        limit_price.send_keys(str(float(live_price))) 
                    else: 
                        limit_price.send_keys(str(float(live_price) + 0.01))

                    try:
                        #//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/h2
                        available_funds = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/h2"))).text
                        available_funds = available_funds.split('$')[1]
                        order_price=QUANTITY*(float(live_price)+0.01)
                        if order_price > float(available_funds):
                            print(f"Insufficient funds. {s}'s price is {live_price}, Order price ${order_price} Available funds ${available_funds}.")
                            #//*[@id="mainContent"]/div[2]/div[2]/div[3]/a
                            cancel_button = WebDriverWait(driver, 20).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                            cancel_button.click() 
                            continue
                    except TimeoutException:
                        pass

                    # try:
                    #     # Define possible XPaths for the review button
                    #     xpaths = [
                    #         "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[8]/button",
                    #         "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[7]/button",
                    #         "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[6]/button"
                    #     ]

                    #     # Try each XPath until one works
                    #     review_button = None
                    #     for xpath in xpaths:
                    #         try:
                    #             review_button = WebDriverWait(driver, 3).until(
                    #                 EC.element_to_be_clickable((By.XPATH, xpath))
                    #             )
                    #             break  # Exit the loop if the button is found and clickable
                    #         except TimeoutException:
                    #             continue  # Try the next XPath

                    #     if review_button is None:
                    #         raise Exception("Review button not found")

                    #     # Click the review button
                    #     review_button.click()
                    # except:
                    #     continue
                    # review_button = WebDriverWait(driver, 3).until(
                    #                 EC.element_to_be_clickable((By.NAME, "review")))
                    review_button = WebDriverWait(driver, 3).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-mjs='inv-trade-buy-review']")))

                    review_button.click()
                    
                    if DRY is False:
                        submit_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[4]/button[1]")))
                        submit_button.click()
                        if float(live_price)<0.11:
                            print("Order submitted for", QUANTITY, "shares of", s, "at", str(float(live_price)))
                        else:
                            print("Order submitted for", QUANTITY, "shares of", s, "at", str(float(live_price) + 0.01))
                        
                        # Confirm the order
                        done_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[2]/button")))
                        done_button.click()
                        print("Order completed and confirmed.")
                    
                    elif(DRY is True):
                        sleep(3)
                        back_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[4]/button[2]")))
                        back_button.click()
                        sleep(2)
                        print("DRY MODE")
                        print("Submitting order BUY for", QUANTITY, "shares of", s, "at", str(float(live_price) + 0.01))

                        cancel_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                        cancel_button.click() 

            elif orderObj.get_action() == "sell":
                start_time=time()
                clicked_values = set()  # Set to keep track of processed accounts

                DRY=orderObj.get_dry()
                QUANTITY=orderObj.get_amount()
                print("DRY MODE:", DRY)
                account_number=1
                sleep(4)
                while True:
                    sleep(1)
                    # Click sell button
                    try:
                        sell = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[2]/div/button[2]")))
                        sell.click()
                    except:
                        print("Sell button not found for", {s})
                        break
            
                    accounts_dropdown = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.NAME, "account")))
                
                    select=Select(accounts_dropdown)
                    # sleep(3)

                    # Find an unclicked account
                    for option in select.options:
                        value = option.get_attribute('value')
                        if value not in clicked_values:
                            select.select_by_value(value)
                            print("Selected account",account_number,":",{value})
                            account_number+=1
                            clicked_values.add(value)
                            break
                    else:
                        print("All accounts have been processed.")
                        break  # Exit the while loop if all accounts are processed
                    
                    # //*[@id="mainContent"]/div[2]/div[2]/div[3]/div/h2
                    #Check if quantity is less
                    available_shares= WebDriverWait(driver, 20).until(
                                EC.presence_of_element_located((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/h2')))
                    available_shares=available_shares.text
                    print('available shares presplit:', available_shares)
                    available_shares=available_shares.split(' ')[0]
                    print("Available shares:", {available_shares})
                    
                    try:
                        if QUANTITY>float(available_shares):
                            if float(available_shares) > 0:
                                QUANTITY=float(available_shares)
                            else:
                                print("No shares available")
                                cancel_button = WebDriverWait(driver, 20).until(
                                    EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                                cancel_button.click()
                                continue
                    except:
                        pass
                    
                    # Input quantity
                    quant = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.NAME, "shares")))
                    quant.send_keys(QUANTITY)
                    
                    # Fetch the live price
                    sleep(2)
                    try:
                        live_price = WebDriverWait(driver, 20).until(
                            EC.presence_of_element_located((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[4]/div[2]')))
                        live_price=live_price.text
                        print("live price presplit:", live_price)
                        live_price = live_price.split('$')[1]
                        print('Live price:', live_price)
                    except Exception as e:
                        print("live price not found for some reason")
                        sofi_error(driver,e)
                    
                    
                    try:
                        # Locate the dropdown for order type
                        dropdown = WebDriverWait(driver, 3).until(
                            EC.presence_of_element_located((By.NAME, "OrderTypeValue")))
                        
                        # Get the value of the first option in the dropdown
                        first_option_value = dropdown.find_element(By.XPATH, './option[1]').get_attribute("value")
                        print("first_option_value:", first_option_value)
                        if first_option_value == "MARKET":
                            # Handle market order directly, since stock price is over $1
                            review_button = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[7]/button'))
                            )
                            review_button.click()
                        else:
                            # Handle limit order, since stock price is below $1
                            try:
                                # Input limit price
                                limit_price = WebDriverWait(driver, 20).until(
                                    EC.element_to_be_clickable((By.NAME, 'value'))
                                )
                                limit_price.send_keys(str(float(live_price) - 0.01))

                                # Review order: Case limit order
                                review_button = WebDriverWait(driver, 5).until(
                                    EC.element_to_be_clickable((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[8]/button'))
                                )
                                driver.execute_script("arguments[0].click();", review_button)
                            except:
                                print('Limit order review button did not work')
                                continue
                    except:
                        print('Neither order type worked')
                        #//*[@id="mainContent"]/div[2]/div[2]/div[3]/a
                        cancel_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                        cancel_button.click()
                        continue
                        
                    # try:
                    #     #Review order: Case market order
                    #     # //*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[7]/button
                    #     review_button= WebDriverWait(driver, 5).until(
                    #             EC.element_to_be_clickable((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[7]/button')))
                    #     review_button.click()
                    # except:
                    #     try:
                    #         #Input limit price
                    #         # limit_price = WebDriverWait(driver, 20).until(
                    #         #     EC.element_to_be_clickable((By.XPATH, '//*[@id="input-33"]')))
                    #         limit_price = WebDriverWait(driver, 20).until(
                    #             EC.element_to_be_clickable((By.NAME, 'value')))
                    #         limit_price.send_keys(str(float(live_price) - 0.01))

                    #         #Review order: Case limit order
                    #         review_button= WebDriverWait(driver, 5).until(
                    #             EC.element_to_be_clickable((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[8]/button')))
                    #         driver.execute_script("arguments[0].click();", review_button)
                    #     except:
                    #         print('neither review button worked')
                    #         continue
                    
                    # If market price shift warning message
                    try:
                       okay_button= WebDriverWait(driver, 2).until(
                            EC.element_to_be_clickable((By.XPATH, '//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[7]/div/button[1]'))) 
                       okay_button.click()
                    except:
                        pass

                    if(DRY is False):
                        #//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[5]/button[1]
                        # sleep(2)
                        submit_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[5]/button[1]")))
                        submit_button.click()
                        print("LIVE MODE")
                        done=WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[2]/button")))
                        done.click()
                        print("Submitting order SELL for", QUANTITY, "shares of", s, "at", str(float(live_price) - 0.01))
                        
                    elif(DRY is True):   
                        try:
                            sleep(3)
                            # Try to find and click the back_button
                            # //*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[5]/button[2]
                            back_button = WebDriverWait(driver, 10).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[5]/button[2]")))
                            back_button.click()
                        except TimeoutException:
                            try:
                                logger.info('couldnt find back button')
                                # If back_button is not found, try to find and click the Out_of_market_back_button
                                Out_of_market_back_button = WebDriverWait(driver, 20).until(
                                    EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[6]/div/button[2]")))
                                Out_of_market_back_button.click()
                            except TimeoutException:
                                print("Neither button was found.")


                        print("Submitting order SELL for", QUANTITY, "shares of", s, "at", live_price)
                        sleep(1)
                        #//*[@id="mainContent"]/div[2]/div[2]/div[3]/a
                        cancel_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                        cancel_button.click()
                end_time=time()
                elapsed_time= end_time-start_time
                print("Time for stock", {s},"is:", elapsed_time)
 
    print("Completed all transactions, Exiting...")
    driver.close()
    driver.quit()      
