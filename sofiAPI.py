import datetime
import os
import re
import traceback
from time import sleep

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
DRIVER=getDriver(DOCKER=False)
load_dotenv()

def sofi_error(driver,e):
    print("SOFI Error: ", e)
    driver.save_screenshot(f"SOFI-error-{datetime.datetime.now()}.png")
    #printAndDiscord("SOFI Error: " + str(e))
    print(traceback.format_exc())


def sofi_init(SOFI_EXTERNAL=None,DOCKER=False):
    load_dotenv()

    if not os.getenv("SOFI"):
        print("SOFI environment variable not found.")
        return False
    accounts = (
        os.environ["SOFI"].strip().split(",")
        if SOFI_EXTERNAL is None
        else SOFI_EXTERNAL.strip().split(",")
    )
    SOFI_obj = Brokerage("SOFI")
    for account in accounts:
        index = accounts.index(account) + 1
        name = f"SOFI {index}"
        account = account.split(":",1)
        try:
            print("Logging into SOFI...")
            driver=DRIVER
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
                try:
                    tooManyAttempts=WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//*[@id='prompt-alert']/p")))
                    print("Too many attempts, give it a break and come back later.")
                except TimeoutException:
                    return
                print("=====================================================\n")
              
                code2fa=input('Please enter code and press ENTER to continue:')
              
                code_field = WebDriverWait(driver, 60).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='code']")))
                code_field.send_keys(code2fa)



                code_button = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='widget_block']/div/div[2]/div/div/main/section/div/div/div/div[1]/div/form/div[3]/button")))
                code_button.click()
            except TimeoutException:
                print("TimeoutException: Login failed.")
                return False
            SOFI_obj.set_logged_in_object(name, driver)

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
    
    #driver: webdriver = SOFI_o.get_logged_in_objects(key)
    driver=DRIVER
    #print(orderObj.get_stocks())
    investment_button = WebDriverWait(driver, 20).until(
        EC.element_to_be_clickable((By.XPATH, "//*[@id='root']/div/header/nav/div[2]/a[4]")))
    investment_button.click()
    
    for s in orderObj.get_stocks():
        try:
            search_field = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='page-wrap']/div[1]/div/div/div/div/input")))
            search_field.send_keys(s)
            WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located((By.XPATH, "//*[@id='page-wrap']/div[1]/div/div/div/ul/li")))
            dropdown_items = driver.find_elements(By.XPATH, "//*[@id='page-wrap']/div[1]/div/div/div/ul/li")
            total_items = len(dropdown_items)
        except TimeoutException:
            try:
                invest_search_field=WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[1]/div/div/div/input")))
                invest_search_field.send_keys(s)
                WebDriverWait(driver, 20).until(EC.presence_of_all_elements_located((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[1]/div/div/ul/li")))
                dropdown_items = driver.find_elements(By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[1]/div/div/ul/li")
                total_items = len(dropdown_items)
            except TimeoutException:
                print("Search field not found")
                return
        #//*[@id="mainContent"]/div[2]/div[2]/div[2]/div[1]/div/div/ul/li

        if total_items == 0:
            print("No stock found")
            return
        else:
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
        #print(orderObj.get_action())
        if orderObj.get_action() == "buy":
            #print(f"Buying {orderObj.get_quantity(s)} shares of {s} at ${orderObj.get_price(s)}")
            clicked_values = set()  # Set to keep track of processed accounts
           
            DRY=orderObj.get_dry()
            QUANTITY=orderObj.get_amount()
            print("DRY MODE:", DRY)
            while True:
                # Click the buy button
                sleep(5)
                buy_button = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[2]/div/button[1]")))
                driver.execute_script("arguments[0].click();", buy_button)
                #print("BUY BUTTON CLICKED")
                #//*[@id="shares"]
                #//*[@id="shares"]
                try:
                    shares=WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='shares']")))
                    shares.click()
                    #//*[@id="OrderTypedDropDown"]
                    OrderTypedDropDown=WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='OrderTypedDropDown']")))
                    OrderTypedDropDown.click()
                    #//*[@id="OrderTypedDropDown"]/option[2]
                    OrderTypedDropDown_limit=WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='OrderTypedDropDown']/option[2]")))
                    OrderTypedDropDown_limit.click()
                except TimeoutException:
                    #print("Shares field not found")
                    pass
                    

                # Fetch the live price
                live_price = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/p"))).text
                live_price = live_price.split('$')[1]
                #print("LIVE PRICE:", live_price)

                # Handle account selection
                accounts_dropdown = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.NAME, "account")))
                select = Select(accounts_dropdown)

                # Find an unclicked account
                for option in select.options:
                    value = option.get_attribute('value')
                    if value not in clicked_values:
                        select.select_by_value(value)
                        #print("Selected account:", value)
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
                #print("Inputting quantity and price")
                sleep(5)
                quant = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.NAME, "shares")))
                quant.send_keys(QUANTITY)
                sleep(5)
                limit_price = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.NAME, "value")))
                limit_price.send_keys(str(float(live_price) + 0.01))
                #//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[8]/div/p
                try:
                    #//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/h2
                    available_funds = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/h2")))
                    
                    Insufficient_funds=WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[8]/div/p")))
                    print(f"Insufficient funds. {s}'s price is {live_price}, Available funds {available_funds.text}.")
                    #//*[@id="mainContent"]/div[2]/div[2]/div[3]/a
                    cancel_button = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                    cancel_button.click()
                    continue    
                except TimeoutException:
                    pass
                # Review and submit the order
                review_button = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[8]/button")))
                review_button.click()
                if DRY == 'False':
                    submit_button = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[4]/button[1]")))
                    submit_button.click()
                    print("Order submitted for", QUANTITY, "shares of", s, "at", str(float(live_price) + 0.01))
                    
                    # Confirm the order
                    done_button = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[2]/button")))
                    done_button.click()
                    print("Order completed and confirmed.")
                elif(DRY=='True'):
                    #print("testing before back")
                    sleep(5)
                    back_button = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[4]/button[2]")))
                    back_button.click()
                    sleep(3)
                    print("DRY MODE")
                    print("Submitting order BUY for", QUANTITY, "shares of", s, "at", str(float(live_price) + 0.01))
        elif orderObj.get_action() == "sell":
               

            sell = WebDriverWait(driver, 50).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[2]/div/button[2]")))
            sell.click()
    
            accounts_dropdown = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.NAME, "account")))
        
            select=Select(accounts_dropdown)
            #print("select", select)
            Options=select.options
            #print("options", Options)
            Options_length=len(Options)
        

            for index in range(Options_length):
                if index !=0:
                    sell = WebDriverWait(driver, 50).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[2]/div[2]/div/button[2]")))
                    sell.click()
                    quant=WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.NAME, "shares")))
                    quant.send_keys(QUANTITY)
                    #print('Quant sent')
                    #//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[6]/button
                    sell_button_INDEX = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[6]/button")))
                    sell_button_INDEX.click()
                else:
                    wait=WebDriverWait(driver,10)
                    wait.until(EC.presence_of_all_elements_located((By.NAME, "account")))
                    select = Select(WebDriverWait(driver, 20).until(
                                    EC.presence_of_element_located((By.NAME, "account"))))
                    select.select_by_index(index)
                    #print("Selected account index:", index)
                    #time.sleep(3)
                    
                    quant=WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.NAME, "shares")))
                    quant.send_keys(QUANTITY)
                    #print('Quant sent')
                    #//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[6]/button
                    WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[6]/button")))
                    sell_button=driver.find_element(By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[6]/button")
                    driver.execute_script("arguments[0].click();", sell_button)

                #limit_price=WebDriverWait(driver, 20).until(
                # EC.element_to_be_clickable((By.NAME, "value")))
                #limit_price.send_keys(str(float(live_price) + 0.01))
                #print('Limit price sent')
                #time.sleep(3)

                
                #review_button = WebDriverWait(driver, 20).until(
                    #EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[8]/button")))
                #review_button.click()
            
                if(DRY=='False'):
                    #//*[@id="mainContent"]/div[2]/div[2]/div[3]/div/div[4]/button[1]
                    submit_button = WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[4]/button[1]")))
                    submit_button.click()
                    print("LIVE MODE")
                    done=WebDriverWait(driver, 20).until(
                        EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[2]/button")))
                    done.click()
                    print("Submitting order SELL for", QUANTITY, "shares of", s, "at", str(float(live_price) + 0.01))
                    index+=1
                elif(DRY=='True'):
                    
                    #print("testing before back")
                    #time.sleep(5)
                    try:
                        # Try to find and click the back_button
                        back_button = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[4]/button[2]")))
                        back_button.click()
                    except TimeoutException:
                        try:
                            # If back_button is not found, try to find and click the Out_of_market_back_button
                            Out_of_market_back_button = WebDriverWait(driver, 20).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/div/div[6]/div/button[2]")))
                            Out_of_market_back_button.click()
                        except TimeoutException:
                            print("Neither button was found.")
                        #time.sleep(3)
                        print("DRY MODE")
                        print("Submitting order SELL for", QUANTITY, "shares of", s, "at", str(float(live_price) + 0.01))
                        #//*[@id="mainContent"]/div[2]/div[2]/div[3]/a
                        cancel_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@id='mainContent']/div[2]/div[2]/div[3]/a")))
                        cancel_button.click()
                        index+=1
    print("Completed all transactions, Exiting...")
    driver.close()
    driver.quit()
