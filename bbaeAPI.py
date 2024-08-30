import asyncio
import os
import traceback
from helperAPI import (
    Brokerage,
    printAndDiscord,
    printHoldings,
    getOTPCodeDiscord,
    maskString,
    stockOrder,
    send_captcha_to_discord,
    getUserInputDiscord,
)
from bbae_investing_API import BBAEAPI
from dotenv import load_dotenv
from io import BytesIO

load_dotenv()


def bbae_init(BBAE_EXTERNAL=None, botObj=None, loop=None):
    load_dotenv()
    bbae_obj = Brokerage("BBAE")
    if not os.getenv("BBAE") and BBAE_EXTERNAL is None:
        print("BBAE not found, skipping...")
        return None

    # Determine if SMS or Email login should be used
    login_method = os.getenv("BBAE_LOGIN_METHOD", "SMS").upper()

    BBAE = (
        os.environ["BBAE"].strip().split(",")
        if BBAE_EXTERNAL is None
        else BBAE_EXTERNAL.strip().split(",")
    )
    print("Logging in to BBAE...")
    for index, account in enumerate(BBAE):
        name = f"BBAE {index + 1}"
        try:
            user, password = account.split(":")
            bb = BBAEAPI(user, password, creds_path="./creds/")
            
            # Initial API call to establish session and get initial cookies
            print(f"{name}: Making initial request to establish session...")
            bb.make_initial_request()

            if login_method == "SMS":
                login_with_sms(bb, botObj, name, loop)
            elif login_method == "EMAIL":
                login_with_email(bb, botObj, name, loop)
            else:
                raise Exception(f"Invalid login method specified: {login_method}")

            print(f"{name}: Retrieving account assets...")
            account_assets = bb.get_account_assets()

            print(f"{name}: Retrieving account information...")
            account_info = bb.get_account_info()

            account_number = str(account_info['Data']['accountNumber'])

            # Mask the account number before printing it
            masked_account_number = maskString(account_number)
            print(f"{name}: Found account {masked_account_number}")

            bbae_obj.set_account_number(name, masked_account_number)
            bbae_obj.set_account_totals(name, masked_account_number, float(account_assets['Data']['totalAssets']))

            bbae_obj.set_logged_in_object(name, bb, "bb")
            print(f"{name}: Logged in with account number {masked_account_number}")
        except Exception as e:
            print(f"Error logging into BBAE: {e}")
            print(traceback.format_exc())
            continue
    print("Logged into BBAE!")
    return bbae_obj



def login_with_sms(bb, botObj, name, loop):
    try:
        # API call to generate the login ticket (SMS)
        print(f"{name}: Generating login ticket (SMS)...")
        ticket_response = bb.generate_login_ticket_sms()

        # Log the raw response details
        print(f"{name}: Initial ticket response: {ticket_response}")

        # Ensure 'Data' key exists and proceed with verification if necessary
        if 'Data' in ticket_response:
            data = ticket_response['Data']

            # Check if CAPTCHA and SMS verification are required
            if data.get('needCaptchaCode', False):
                print(f"{name}: CAPTCHA required. Requesting CAPTCHA image...")
                captcha_input = solve_captcha(bb, botObj, name, loop, login_type="sms")
                if not captcha_input:
                    raise Exception("CAPTCHA input timed out or was canceled.")
                print(f"{name}: CAPTCHA solved. Input: {captcha_input}")

            if data.get('needSmsVerifyCode', False):
                print(f"{name}: Requesting SMS code after CAPTCHA is solved...")
                sms_code_response = bb.request_sms_code(captcha_input=captcha_input)
                print(f"{name}: SMS code request response: {sms_code_response}")

                if sms_code_response.get("Message") == "Incorrect verification code.":
                    print(f"{name}: Incorrect CAPTCHA code, retrying...")
                    return False

                print(f"{name}: Waiting for OTP code from user...")
                otp_code = asyncio.run_coroutine_threadsafe(
                    getOTPCodeDiscord(botObj, name, timeout=300, loop=loop),
                    loop,
                ).result()
                if otp_code is None:
                    raise Exception("No SMS code received.")
                print(f"{name}: OTP code received: {otp_code}")

                print(f"{name}: Generating login ticket with SMS code...")
                ticket_response = bb.generate_login_ticket_sms(captcha_input=captcha_input, sms_code=otp_code)
                print(f"{name}: Ticket response after SMS code: {ticket_response}")

                if "Message" in ticket_response and ticket_response["Message"] == "Incorrect verification code.":
                    print(f"{name}: Incorrect OTP code, retrying...")
                    return False

        # Handle the login ticket
        if 'Data' in ticket_response and 'ticket' in ticket_response['Data']:
            ticket = ticket_response['Data']['ticket']
        else:
            print(f"{name}: Raw response object: {ticket_response}")
            raise Exception(f"Login failed. No ticket generated. Response: {ticket_response}")

        print(f"{name}: Logging in with ticket...")
        bb.login_with_ticket(ticket)
        return True
    except Exception as e:
        print(f"Error in SMS login: {e}")
        print(traceback.format_exc())
        return False


def login_with_email(name):
    try:
        # Implement the email login logic here
        print(f"{name}: Generating login ticket (Email)...")
        # Call relevant methods for email login process
        # Handle CAPTCHA, OTP, and ticket generation similarly to SMS login
        raise NotImplementedError("Email login functionality is not yet implemented.")
    except Exception as e:
        print(f"Error in Email login: {e}")
        print(traceback.format_exc())
        return False


def solve_captcha(bb, botObj, name, loop, login_type="sms"):
    while True:
        captcha_image = bb.request_captcha()
        if captcha_image:
            print("Sending CAPTCHA to Discord for user input...")
            file = BytesIO()
            captcha_image.save(file, format="PNG")
            file.seek(0)

            asyncio.run_coroutine_threadsafe(
                send_captcha_to_discord(botObj, file, loop),
                loop,
            ).result()

            captcha_input = asyncio.run_coroutine_threadsafe(
                getUserInputDiscord(botObj, f"{name} requires CAPTCHA input", timeout=60, loop=loop),
                loop,
            ).result()

            if captcha_input:
                # Send the CAPTCHA to the appropriate API based on login type
                if login_type == "email":
                    ticket_response = bb.generate_login_ticket_email(captcha_input=captcha_input)
                else:
                    ticket_response = bb.generate_login_ticket_sms(captcha_input=captcha_input)

                # If the CAPTCHA was incorrect, request a new one
                if ticket_response.get("Message") == "Incorrect verification code.":
                    print("Incorrect CAPTCHA, requesting a new one...")
                    continue
                else:
                    return captcha_input  # CAPTCHA was correct, return the input
        else:
            print("Failed to get CAPTCHA image, retrying...")

        # If timeout, abort
        print("CAPTCHA input timed out, aborting...")
        return None


def bbae_holdings(bbo: Brokerage, loop=None):
    for key in bbo.get_account_numbers():
        for account in bbo.get_account_numbers(key):
            obj: BBAEAPI = bbo.get_logged_in_objects(key, "bb")
            try:
                positions = obj.get_account_holdings()
                print(f"Raw holdings data: {positions}")

                if 'Data' in positions:
                    for holding in positions['Data']:
                        qty = holding["CurrentAmount"]
                        if float(qty) == 0:
                            continue
                        sym = holding["displaySymbol"]
                        cp = holding["Last"]
                        print(f"Stock Ticker: {sym}, Amount: {qty}, Current Price: {cp}")
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
            printAndDiscord(
                f"{key}: {orderObj.get_action()}ing {orderObj.get_amount()} of {s}",
                loop,
            )
            for account in bbo.get_account_numbers(key):
                obj: BBAEAPI = bbo.get_logged_in_objects(key, "bb")
                try:
                    quantity = orderObj.get_amount()
                    is_dry_run = orderObj.get_dry()

                    # Execute the buy/sell transaction
                    response = obj.execute_buy(
                        symbol=s,
                        amount=quantity,
                        account_number=account,
                        dry_run=is_dry_run
                    )

                    # Handle the result
                    if is_dry_run:
                        message = "Dry Run Success"
                        if not response.get("Outcome") == "Success":
                            message = f"Dry Run Failed: {response.get('Message')}"
                    else:
                        message = response.get('Message', "Success")

                    printAndDiscord(
                        f"{key}: {orderObj.get_action().capitalize()} {quantity} of {s} in {account}: {message}",
                        loop,
                    )

                except Exception as e:
                    printAndDiscord(f"{key} {account}: Error placing order: {e}", loop)
                    print(traceback.format_exc())
                    continue
