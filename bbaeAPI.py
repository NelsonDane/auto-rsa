import asyncio
import os
import traceback
from io import BytesIO

from dotenv import load_dotenv

from bbae_investing_API import BBAEAPI
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

load_dotenv()


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
            user, password, use_email = account.split(":")
            use_email = use_email.upper()
            bb = BBAEAPI(user, password, filename=f"BBAE_{index + 1}.txt", creds_path="./creds/")

            # Initial API call to establish session and get initial cookies
            print(f"{name}: Making initial request to establish session...")
            bb.make_initial_request()

            # All the rest of the requests responsible for getting authenticated
            print(f"{name}: Attempting to login...")
            login(bb, botObj, name, loop, use_email)

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


def login(bb, botObj, name, loop, use_email):
    try:
        # API call to generate the login ticket
        if use_email == "TRUE":
            print(f"{name}: Generating login ticket (Email)...")
            ticket_response = bb.generate_login_ticket_email()
        else:
            print(f"{name}: Generating login ticket (SMS)...")
            ticket_response = bb.generate_login_ticket_sms()

        # Log the raw response details
        print(f"{name}: Initial ticket response: {ticket_response}")

        # Ensure 'Data' key exists and proceed with verification if necessary
        if 'Data' not in ticket_response:
            raise Exception("Invalid response from generating login ticket")

        # Check if SMS or CAPTCHA verification are required
        data = ticket_response['Data']
        if data.get('needSmsVerifyCode', False):
            # TODO 8/30/24: CAPTCHA should only be needed if SMS is needed. Is this true?
            sms_and_captcha_response = handle_captcha_and_sms(bb, botObj, data, loop, name, use_email)
            if not sms_and_captcha_response:
                raise Exception("Error solving SMS or Captcha")

            print(f"{name}: Waiting for OTP code from user...")
            otp_code = asyncio.run_coroutine_threadsafe(
                getOTPCodeDiscord(botObj, name, timeout=300, loop=loop),
                loop,
            ).result()
            if otp_code is None:
                raise Exception("No SMS code received")

            print(f"{name}: OTP code received: {otp_code}")
            ticket_response = bb.generate_login_ticket_sms(sms_code=otp_code)

            if "Message" in ticket_response and ticket_response["Message"] == "Incorrect verification code.":
                raise Exception("Incorrect OTP code")

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


def handle_captcha_and_sms(bb, botObj, data, loop, name, use_email):
    try:
        # If CAPTCHA is needed it will generate an SMS code as well
        if data.get('needCaptchaCode', False):
            print(f"{name}: CAPTCHA required. Requesting CAPTCHA image...")
            sms_response = solve_captcha(bb, botObj, name, loop, use_email)
            if not sms_response:
                raise Exception("Failure solving CAPTCHA!")
            print(f"{name}: CAPTCHA solved. SMS response is: {sms_response}")
        else:
            print(f"{name}: Requesting SMS code...")
            sms_response = send_sms_code(bb, name, use_email)
            if not sms_response:
                raise Exception("Unable to retrieve sms code!")
            print(f"{name}: SMS response is: {sms_response}")
        return True
    except Exception as e:
        print(f"Error in CAPTCHA or SMS: {e}")
        print(traceback.format_exc())
        return False


def solve_captcha(bb, botObj, name, loop, use_email):
    try:
        captcha_image = bb.request_captcha()
        if not captcha_image:
            # Unable to get Image
            raise Exception("Unable to request CAPTCHA image, aborting...")

        print("Sending CAPTCHA to Discord for user input...")
        file = BytesIO()
        captcha_image.save(file, format="PNG")
        file.seek(0)

        asyncio.run_coroutine_threadsafe(
            send_captcha_to_discord(file),
            loop,
        ).result()

        captcha_input = asyncio.run_coroutine_threadsafe(
            getUserInputDiscord(botObj, f"{name} requires CAPTCHA input", timeout=300, loop=loop),
            loop,
        ).result()

        if captcha_input:
            # Send the CAPTCHA to the appropriate API based on login type
            if use_email == "TRUE":
                sms_request_response = bb.request_email_code(captcha_input=captcha_input)
            else:
                sms_request_response = bb.request_sms_code(captcha_input=captcha_input)

            print(f"{name}: SMS code request response: {sms_request_response}")

            if sms_request_response.get("Message") == "Incorrect verification code.":
                raise Exception("Incorrect CAPTCHA code!")

            return sms_request_response  # CAPTCHA was correct, return the response
    except Exception as e:
        print(f"{name}: Error during CAPTCHA code step: {e}")
        print(traceback.format_exc())
        return None


def send_sms_code(bb, name, use_email, captcha_input=None):
    if use_email == "TRUE":
        sms_code_response = bb.request_email_code(captcha_input=captcha_input)
    else:
        sms_code_response = bb.request_sms_code(captcha_input=captcha_input)
    print(f"{name}: SMS code request response: {sms_code_response}")

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
