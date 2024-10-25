import asyncio
import os
import traceback
from io import BytesIO

from bbae_invest_api import BBAEAPI
from dotenv import load_dotenv

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


def bbae_init(BBAE_EXTERNAL=None, botObj=None, loop=None):
    load_dotenv()
    bbae_obj = Brokerage("BBAE")
    if not os.getenv("BBAE") and BBAE_EXTERNAL is None:
        print("BBAE not found, skipping...")
        return None
    BBAE = (
        os.environ["BBAE"].strip().split(",")
        if BBAE_EXTERNAL is None
        else BBAE_EXTERNAL.strip().split(",")
    )
    print("Logging in to BBAE...")
    for index, account in enumerate(BBAE):
        name = f"BBAE {index + 1}"
        try:
            user, password = account.split(":")[:2]
            use_email = "@" in user
            # Initialize the BBAE API object
            bb = BBAEAPI(
                user, password, filename=f"BBAE_{index + 1}.pkl", creds_path="./creds/"
            )
            bb.make_initial_request()
            # All the rest of the requests responsible for getting authenticated
            login(bb, botObj, name, loop, use_email)
            account_assets = bb.get_account_assets()
            account_info = bb.get_account_info()
            account_number = str(account_info["Data"]["accountNumber"])
            # Set account values
            masked_account_number = maskString(account_number)
            bbae_obj.set_account_number(name, masked_account_number)
            bbae_obj.set_account_totals(
                name,
                masked_account_number,
                float(account_assets["Data"]["totalAssets"]),
            )
            bbae_obj.set_logged_in_object(name, bb, "bb")
        except Exception as e:
            print(f"Error logging into BBAE: {e}")
            print(traceback.format_exc())
            continue
    print("Logged into BBAE!")
    return bbae_obj


def login(bb: BBAEAPI, botObj, name, loop, use_email):
    try:
        # API call to generate the login ticket
        if use_email:
            ticket_response = bb.generate_login_ticket_email()
        else:
            ticket_response = bb.generate_login_ticket_sms()
        # Ensure "Data" key exists and proceed with verification if necessary
        if ticket_response.get("Data") is None:
            raise Exception("Invalid response from generating login ticket")
        # Check if SMS or CAPTCHA verification are required
        data = ticket_response["Data"]
        if data.get("needSmsVerifyCode", False):
            sms_and_captcha_response = handle_captcha_and_sms(
                bb, botObj, data, loop, name, use_email
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
                raise Exception("No SMS code received")
            # Login with the OTP code
            if use_email:
                ticket_response = bb.generate_login_ticket_email(sms_code=otp_code)
            else:
                ticket_response = bb.generate_login_ticket_sms(sms_code=otp_code)
            if ticket_response.get("Message") == "Incorrect verification code.":
                raise Exception("Incorrect OTP code")
        # Handle the login ticket
        if (
            ticket_response.get("Data") is not None
            and ticket_response.get("Data").get("ticket") is not None
        ):
            ticket = ticket_response["Data"]["ticket"]
        else:
            print(f"{name}: Raw response object: {ticket_response}")
            raise Exception(
                f"Login failed. No ticket generated. Response: {ticket_response}"
            )
        # Login with the ticket
        login_response = bb.login_with_ticket(ticket)
        if login_response.get("Outcome") != "Success":
            raise Exception(f"Login failed. Response: {login_response}")
        return True
    except Exception as e:
        print(f"Error in SMS login: {e}")
        print(traceback.format_exc())
        return False


def handle_captcha_and_sms(bb: BBAEAPI, botObj, data, loop, name, use_email):
    try:
        # If CAPTCHA is needed it will generate an SMS code as well
        if data.get("needCaptchaCode", False):
            print(f"{name}: CAPTCHA required. Requesting CAPTCHA image...")
            sms_response = solve_captcha(bb, botObj, name, loop, use_email)
            if not sms_response:
                raise Exception("Failure solving CAPTCHA!")
        else:
            print(f"{name}: Requesting code...")
            sms_response = send_sms_code(bb, name, use_email)
            if not sms_response:
                raise Exception("Unable to retrieve sms code!")
        return True
    except Exception as e:
        print(f"Error in CAPTCHA or SMS: {e}")
        print(traceback.format_exc())
        return False


def solve_captcha(bb: BBAEAPI, botObj, name, loop, use_email):
    try:
        captcha_image = bb.request_captcha()
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
            sms_request_response = bb.request_email_code(captcha_input=captcha_input)
        else:
            sms_request_response = bb.request_sms_code(captcha_input=captcha_input)
        if sms_request_response.get("Message") == "Incorrect verification code.":
            raise Exception("Incorrect CAPTCHA code!")
        return sms_request_response
    except Exception as e:
        print(f"{name}: Error solving CAPTCHA code: {e}")
        print(traceback.format_exc())
        return None


def send_sms_code(bb: BBAEAPI, name, use_email, captcha_input=None):
    if use_email:
        sms_code_response = bb.request_email_code(captcha_input=captcha_input)
    else:
        sms_code_response = bb.request_sms_code(captcha_input=captcha_input)
    if sms_code_response.get("Message") == "Incorrect verification code.":
        print(f"{name}: Incorrect CAPTCHA code, retrying...")
        return False
    return sms_code_response


def bbae_holdings(bbo: Brokerage, loop=None):
    for key in bbo.get_account_numbers():
        for account in bbo.get_account_numbers(key):
            obj: BBAEAPI = bbo.get_logged_in_objects(key, "bb")
            try:
                positions = obj.get_account_holdings()
                if positions.get("Data") is not None:
                    for holding in positions["Data"]:
                        qty = holding["CurrentAmount"]
                        if float(qty) == 0:
                            continue
                        sym = holding["displaySymbol"]
                        cp = holding["Last"]
                        bbo.set_holdings(key, account, sym, qty, cp)
            except Exception as e:
                printAndDiscord(f"Error getting BBAE holdings: {e}")
                print(traceback.format_exc())
                continue
    printHoldings(bbo, loop, False)


def bbae_transaction(bbo: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("BBAE")
    print("==============================")
    print()
    for s in orderObj.get_stocks():
        for key in bbo.get_account_numbers():
            action = orderObj.get_action().lower()
            printAndDiscord(
                f"{key}: {action}ing {orderObj.get_amount()} of {s}",
                loop,
            )
            for account in bbo.get_account_numbers(key):
                obj: BBAEAPI = bbo.get_logged_in_objects(key, "bb")
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
