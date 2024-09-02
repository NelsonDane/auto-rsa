import asyncio
import os
import traceback
from io import BytesIO

from dotenv import load_dotenv

from dspac_investing_API import DSPACAPI
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
            user, password, use_email = account.split(":")
            use_email = use_email.upper()
            ds = DSPACAPI(user, password, filename=f"DSPAC_{index + 1}.txt", creds_path="./creds/")

            # Initial API call to establish session and get initial cookies
            print(f"{name}: Making initial request to establish session...")
            ds.make_initial_request()

            # All the rest of the requests responsible for getting authenticated
            print(f"{name}: Attempting to login...")
            login(ds, botObj, name, loop, use_email)

            print(f"{name}: Retrieving account assets...")
            account_assets = ds.get_account_assets()

            print(f"{name}: Retrieving account information...")
            account_info = ds.get_account_info()

            account_number = str(account_info['Data']['accountNumber'])

            # Mask the account number before printing it
            masked_account_number = maskString(account_number)
            print(f"{name}: Found account {masked_account_number}")

            dspac_obj.set_account_number(name, masked_account_number)
            dspac_obj.set_account_totals(name, masked_account_number, float(account_assets['Data']['totalAssets']))

            dspac_obj.set_logged_in_object(name, ds, "ds")
            print(f"{name}: Logged in with account number {masked_account_number}")
        except Exception as e:
            print(f"Error logging into DSPAC: {e}")
            print(traceback.format_exc())
            continue
    print("Logged into DSPAC!")
    return dspac_obj


def login(ds, botObj, name, loop, use_email):
    try:
        # API call to generate the login ticket
        if use_email == "TRUE":
            print(f"{name}: Generating login ticket (Email)...")
            ticket_response = ds.generate_login_ticket_email()
        else:
            print(f"{name}: Generating login ticket (SMS)...")
            ticket_response = ds.generate_login_ticket_sms()

        # Log the raw response details
        print(f"{name}: Initial ticket response: {ticket_response}")

        # Ensure 'Data' key exists and proceed with verification if necessary
        if 'Data' not in ticket_response:
            raise Exception("Invalid response from generating login ticket")

        # Check if SMS or CAPTCHA verification are required
        data = ticket_response['Data']
        if data.get('needSmsVerifyCode', False):
            # TODO 8/30/24: CAPTCHA should only be needed if SMS is needed. Is this true?
            sms_and_captcha_response = handle_captcha_and_sms(ds, botObj, data, loop, name, use_email)
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
            ticket_response = ds.generate_login_ticket_sms(sms_code=otp_code)

            if "Message" in ticket_response and ticket_response["Message"] == "Incorrect verification code.":
                raise Exception("Incorrect OTP code")

        # Handle the login ticket
        if 'Data' in ticket_response and 'ticket' in ticket_response['Data']:
            ticket = ticket_response['Data']['ticket']
        else:
            print(f"{name}: Raw response object: {ticket_response}")
            raise Exception(f"Login failed. No ticket generated. Response: {ticket_response}")

        print(f"{name}: Logging in with ticket...")
        ds.login_with_ticket(ticket)
        return True
    except Exception as e:
        print(f"Error in SMS login: {e}")
        print(traceback.format_exc())
        return False


def handle_captcha_and_sms(ds, botObj, data, loop, name, use_email):
    try:
        if data.get('needCaptchaCode', False):
            print(f"{name}: CAPTCHA required. Requesting CAPTCHA image...")
            sms_response = solve_captcha(ds, botObj, name, loop, use_email)
            if not sms_response:
                raise Exception("Failure solving CAPTCHA!")
            print(f"{name}: CAPTCHA solved. SMS response is: {sms_response}")
        else:
            print(f"{name}: Requesting SMS code...")
            sms_response = send_sms_code(ds, name, use_email)
            if not sms_response:
                raise Exception("Unable to retrieve sms code!")
            print(f"{name}: SMS response is: {sms_response}")
        return True

    except Exception as e:
        print(f"Error in CAPTCHA or SMS: {e}")
        print(traceback.format_exc())
        return False


def solve_captcha(ds, botObj, name, loop, use_email):
    try:
        captcha_image = ds.request_captcha()
        if not captcha_image:
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
            if use_email == "TRUE":
                sms_request_response = ds.request_email_code(captcha_input=captcha_input)
            else:
                sms_request_response = ds.request_sms_code(captcha_input=captcha_input)

            print(f"{name}: SMS code request response: {sms_request_response}")

            if sms_request_response.get("Message") == "Incorrect verification code.":
                raise Exception("Incorrect CAPTCHA code!")

            return sms_request_response  # Return the response if successful
        return None  # Ensure the function always returns an expression

    except Exception as e:
        print(f"{name}: Error during CAPTCHA code step: {e}")
        print(traceback.format_exc())
        return None


def send_sms_code(ds, name, use_email, captcha_input=None):
    if use_email == "TRUE":
        sms_code_response = ds.request_email_code(captcha_input=captcha_input)
    else:
        sms_code_response = ds.request_sms_code(captcha_input=captcha_input)
    print(f"{name}: SMS code request response: {sms_code_response}")

    if sms_code_response.get("Message") == "Incorrect verification code.":
        print(f"{name}: Incorrect CAPTCHA code, retrying...")
        return False

    return sms_code_response


def dspac_holdings(dso: Brokerage, loop=None):
    for key in dso.get_account_numbers():
        for account in dso.get_account_numbers(key):
            obj: DSPACAPI = dso.get_logged_in_objects(key, "ds")
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
                        dso.set_holdings(key, account, sym, qty, cp)
            except Exception as e:
                printAndDiscord(f"Error getting DSPAC holdings: {e}")
                print(traceback.format_exc())
                continue
    printHoldings(dso, loop, False)


def dspac_transaction(dso: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("DSPAC")
    print("==============================")
    print()
    for s in orderObj.get_stocks():
        for key in dso.get_account_numbers():
            action = orderObj.get_action().lower()
            printAndDiscord(
                f"{key}: {action}ing {orderObj.get_amount()} of {s}",
                loop,
            )
            for account in dso.get_account_numbers(key):
                obj: DSPACAPI = dso.get_logged_in_objects(key, "ds")
                try:
                    quantity = orderObj.get_amount()
                    is_dry_run = orderObj.get_dry()

                    if action == "buy":
                        # Validate the buy transaction
                        validation_response = obj.validate_buy(symbol=s, amount=quantity, order_side=1, account_number=account)
                        print(f"Validate Buy Response: {validation_response}")
                        if validation_response['Outcome'] != 'Success':
                            printAndDiscord(f"{key} {account}: Validation failed for buying {quantity} of {s}: {validation_response['Message']}", loop)
                            continue

                        # Proceed to execute the buy if not in dry run mode
                        if not is_dry_run:
                            buy_response = obj.execute_buy(
                                symbol=s,
                                amount=quantity,
                                account_number=account,
                                dry_run=is_dry_run
                            )
                            print(f"Execute Buy Response: {buy_response}")
                            message = buy_response['Message']
                        else:
                            message = "Dry Run Success"

                    elif action == "sell":
                        # Check stock holdings before attempting to sell
                        holdings_response = obj.check_stock_holdings(symbol=s, account_number=account)
                        print(f"Check Holdings Response: {holdings_response}")
                        if holdings_response["Outcome"] != "Success":
                            printAndDiscord(f"{key} {account}: Error checking holdings: {holdings_response['Message']}", loop)
                            continue

                        available_amount = float(holdings_response["Data"]["enableAmount"])

                        # If trying to sell more than available, skip to the next
                        if quantity > available_amount:
                            printAndDiscord(f"{key} {account}: Not enough shares to sell {quantity} of {s}. Available: {available_amount}", loop)
                            continue

                        # Validate the sell transaction
                        validation_response = obj.validate_sell(symbol=s, amount=quantity, account_number=account)
                        print(f"Validate Sell Response: {validation_response}")
                        if validation_response['Outcome'] != 'Success':
                            printAndDiscord(f"{key} {account}: Validation failed for selling {quantity} of {s}: {validation_response['Message']}", loop)
                            continue

                        # Proceed to execute the sell if not in dry run mode
                        if not is_dry_run:
                            entrust_price = validation_response['Data']['entrustPrice']
                            sell_response = obj.execute_sell(
                                symbol=s,
                                amount=quantity,
                                account_number=account,
                                entrust_price=entrust_price,
                                dry_run=is_dry_run
                            )
                            print(f"Execute Sell Response: {sell_response}")
                            message = sell_response['Message']
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
