import asyncio
import os
import traceback
from io import BytesIO

from dotenv import load_dotenv
from dspac_invest_api import DSPACAPI

from helperAPI import (
    Brokerage,
    getOTPCodeDiscord,
    getUserInputDiscord,
    maskString,
    printAndDiscord,
    printHoldings,
    send_captcha_to_discord,
    stockOrder
)


def dspac_init(DSPAC_EXTERNAL=None, botObj=None, loop=None):
    load_dotenv()
    dspac_obj = Brokerage("DSPAC")
    if not os.getenv("DSPAC") and DSPAC_EXTERNAL is None:
        print("DSPAC not found, skipping...")
        return None
    DSPAC = (
        os.environ["DSPAC"].strip().split(",")
        if DSPAC_EXTERNAL is None
        else DSPAC_EXTERNAL.strip().split(",")
    )
    print("Logging in to DSPAC...")
    for index, account in enumerate(DSPAC):
        name = f"DSPAC {index + 1}"
        try:
            user, password = account.split(":")[:2]
            use_email = "@" in user
            # Initialize the DSPAC API object
            ds = DSPACAPI(
                user, password, filename=f"DSPAC_{index + 1}.pkl", creds_path="./creds/"
            )
            ds.make_initial_request()
            # All the rest of the requests responsible for getting authenticated
            login(ds, botObj, name, loop, use_email)
            account_assets = ds.get_account_assets()
            account_info = ds.get_account_info()
            account_number = str(account_info["Data"]["accountNumber"])
            # Set account values
            masked_account_number = maskString(account_number)
            dspac_obj.set_account_number(name, masked_account_number)
            dspac_obj.set_account_totals(
                name,
                masked_account_number,
                float(account_assets["Data"]["totalAssets"]),
            )
            dspac_obj.set_logged_in_object(name, ds, "ds")
        except Exception as e:
            print(f"Error logging into DSPAC: {e}")
            print(traceback.format_exc())
            continue
    print("Logged into DSPAC!")
    return dspac_obj


def login(ds: DSPACAPI, botObj, name, loop, use_email):
    try:
        # API call to generate the login ticket
        if use_email:
            ticket_response = ds.generate_login_ticket_email()
        else:
            ticket_response = ds.generate_login_ticket_sms()
        # Ensure "Data" key exists and proceed with verification if necessary
        if ticket_response.get("Data") is None:
            raise Exception("Invalid response from generating login ticket")
        # Check if SMS or CAPTCHA verification are required
        data = ticket_response["Data"]
        if data.get("needSmsVerifyCode", False):
            sms_and_captcha_response = handle_captcha_and_sms(
                ds, botObj, data, loop, name, use_email
            )
            if not sms_and_captcha_response:
                raise Exception("Error solving SMS or Captcha")
            # Get the OTP code from the user
            if botObj is not None and loop is not None:
                otp_code = asyncio.run_coroutine_threadsafe(
                    getOTPCodeDiscord(botObj, name, timeout=300, loop=loop),
                    loop,
                ).result()
            else:
                otp_code = input("Enter security code: ")
            if otp_code is None:
                raise Exception("No OTP code received")
            # Login with the OTP code
            if use_email:
                ticket_response = ds.generate_login_ticket_email(sms_code=otp_code)
            else:
                ticket_response = ds.generate_login_ticket_sms(sms_code=otp_code)
            if ticket_response.get("Message") == "Incorrect verification code.":
                raise Exception("Incorrect OTP code")
        # Handle the login ticket
        if (
            ticket_response.get("Data") is not None
            and ticket_response["Data"].get("ticket") is not None
        ):
            ticket = ticket_response["Data"]["ticket"]
        else:
            raise Exception(
                f"Login failed. No ticket generated. Response: {ticket_response}"
            )
        # Login with the ticket
        login_response = ds.login_with_ticket(ticket)
        if login_response.get("Outcome") != "Success":
            raise Exception(f"Login failed. Response: {login_response}")
        return True
    except Exception as e:
        print(f"Error in OTP login: {e}")
        print(traceback.format_exc())
        return False


def handle_captcha_and_sms(ds: DSPACAPI, botObj, data, loop, name, use_email):
    try:
        # If CAPTCHA is needed it will generate an SMS code as well
        if data.get("needCaptchaCode", False):
            print(f"{name}: CAPTCHA required. Requesting CAPTCHA image...")
            sms_response = solve_captcha(ds, botObj, name, loop, use_email)
            if not sms_response:
                raise Exception("Failure solving CAPTCHA!")
            print(f"{name}: CAPTCHA solved. SMS response is: {sms_response}")
        else:
            print(f"{name}: Requesting code...")
            sms_response = send_sms_code(ds, name, use_email)
            if not sms_response:
                raise Exception("Unable to retrieve sms code!")
            print(f"{name}: SMS response is: {sms_response}")
        return True
    except Exception as e:
        print(f"Error in CAPTCHA or SMS: {e}")
        print(traceback.format_exc())
        return False


def solve_captcha(ds: DSPACAPI, botObj, name, loop, use_email):
    try:
        captcha_image = ds.request_captcha()
        if not captcha_image:
            raise Exception("Unable to request CAPTCHA image, aborting...")
        # Send the CAPTCHA image to Discord for manual input
        print("Sending CAPTCHA to Discord for user input...")
        file = BytesIO()
        captcha_image.save(file, format="PNG")
        file.seek(0)
        # Retrieve input
        if botObj is not None and loop is not None:
            asyncio.run_coroutine_threadsafe(
                send_captcha_to_discord(file),
                loop,
            ).result()
            captcha_input = asyncio.run_coroutine_threadsafe(
                getUserInputDiscord(
                    botObj, f"{name} requires CAPTCHA input", timeout=300, loop=loop
                ),
                loop,
            ).result()
        else:
            captcha_image.save("./captcha.png", format="PNG")
            captcha_input = input(
                "CAPTCHA image saved to ./captcha.png. Please open it and type in the code: "
            )
        if captcha_input is None:
            raise Exception("No CAPTCHA code found")
        # Send the CAPTCHA to the appropriate API based on login type
        if use_email:
            sms_request_response = ds.request_email_code(captcha_input=captcha_input)
        else:
            sms_request_response = ds.request_sms_code(captcha_input=captcha_input)
        if sms_request_response.get("Message") == "Incorrect verification code.":
            raise Exception("Incorrect CAPTCHA code!")
        return sms_request_response
    except Exception as e:
        print(f"{name}: Error solving CAPTCHA code: {e}")
        print(traceback.format_exc())
        return None


def send_sms_code(ds: DSPACAPI, name, use_email, captcha_input=None):
    if use_email:
        sms_code_response = ds.request_email_code(captcha_input=captcha_input)
    else:
        sms_code_response = ds.request_sms_code(captcha_input=captcha_input)
    if sms_code_response.get("Message") == "Incorrect verification code.":
        print(f"{name}: Incorrect CAPTCHA code, retrying...")
        return False
    return sms_code_response


def dspac_holdings(ds: Brokerage, loop=None):
    for key in ds.get_account_numbers():
        for account in ds.get_account_numbers(key):
            obj: DSPACAPI = ds.get_logged_in_objects(key, "ds")
            try:
                positions = obj.get_account_holdings()
                if positions.get("Data") is not None:
                    for holding in positions["Data"]:
                        qty = holding["CurrentAmount"]
                        if float(qty) == 0:
                            continue
                        sym = holding["displaySymbol"]
                        cp = holding["Last"]
                        ds.set_holdings(key, account, sym, qty, cp)
            except Exception as e:
                printAndDiscord(f"Error getting DSPAC holdings: {e}")
                print(traceback.format_exc())
                continue
    printHoldings(ds, loop, False)


def dspac_transaction(ds: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("DSPAC")
    print("==============================")
    print()
    for s in orderObj.get_stocks():
        for key in ds.get_account_numbers():
            action = orderObj.get_action().lower()
            printAndDiscord(
                f"{key}: {action}ing {orderObj.get_amount()} of {s}",
                loop,
            )
            for account in ds.get_account_numbers(key):
                obj: DSPACAPI = ds.get_logged_in_objects(key, "ds")
                try:
                    quantity = orderObj.get_amount()
                    is_dry_run = orderObj.get_dry()
                    # Buy
                    if action == "buy":
                        # Validate the buy transaction
                        validation_response = obj.validate_buy(
                            symbol=s,
                            amount=quantity,
                            order_side=1,
                            account_number=account,
                        )
                        if validation_response["Outcome"] != "Success":
                            printAndDiscord(
                                f"{key} {account}: Validation failed for buying {quantity} of {s}: {validation_response['Message']}",
                                loop,
                            )
                            continue
                        # Proceed to execute the buy if not in dry run mode
                        if not is_dry_run:
                            buy_response = obj.execute_buy(
                                symbol=s,
                                amount=quantity,
                                account_number=account,
                                dry_run=is_dry_run,
                            )
                            message = buy_response["Message"]
                        else:
                            message = "Dry Run Success"
                    # Sell
                    elif action == "sell":
                        # Check stock holdings before attempting to sell
                        holdings_response = obj.check_stock_holdings(
                            symbol=s, account_number=account
                        )
                        if holdings_response["Outcome"] != "Success":
                            printAndDiscord(
                                f"{key} {account}: Error checking holdings: {holdings_response['Message']}",
                                loop,
                            )
                            continue
                        available_amount = float(
                            holdings_response["Data"]["enableAmount"]
                        )
                        # If trying to sell more than available, skip to the next
                        if quantity > available_amount:
                            printAndDiscord(
                                f"{key} {account}: Not enough shares to sell {quantity} of {s}. Available: {available_amount}",
                                loop,
                            )
                            continue
                        # Validate the sell transaction
                        validation_response = obj.validate_sell(
                            symbol=s, amount=quantity, account_number=account
                        )
                        if validation_response["Outcome"] != "Success":
                            printAndDiscord(
                                f"{key} {account}: Validation failed for selling {quantity} of {s}: {validation_response['Message']}",
                                loop,
                            )
                            continue
                        # Proceed to execute the sell if not in dry run mode
                        if not is_dry_run:
                            entrust_price = validation_response["Data"]["entrustPrice"]
                            sell_response = obj.execute_sell(
                                symbol=s,
                                amount=quantity,
                                account_number=account,
                                entrust_price=entrust_price,
                                dry_run=is_dry_run,
                            )
                            message = sell_response["Message"]
                        else:
                            message = "Dry Run Success"
                    printAndDiscord(
                        f"{key}: {orderObj.get_action().capitalize()} {quantity} of {s} in {account}: {message}",
                        loop,
                    )
                except Exception as e:
                    printAndDiscord(f"{key} {account}: Error placing order: {e}", loop)
                    print(traceback.format_exc())
                    continue
