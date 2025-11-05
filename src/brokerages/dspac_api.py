import asyncio
import os
import traceback
from io import BytesIO
from typing import cast

from discord.ext.commands import Bot
from dotenv import load_dotenv
from dspac_invest_api import DSPACAPI

from src.helper_api import Brokerage, StockOrder, get_input_from_discord, get_otp_from_discord, mask_string, print_all_holdings, print_and_discord, send_captcha_to_discord


def dspac_init(bot_obj: Bot | None = None, loop: asyncio.AbstractEventLoop | None = None) -> Brokerage | None:
    """Initialize the DSPAC API."""
    load_dotenv()
    dspac_obj = Brokerage("DSPAC")
    if not os.getenv("DSPAC"):
        print("DSPAC not found, skipping...")
        return None
    big_dspac = os.environ["DSPAC"].strip().split(",")
    print("Logging in to DSPAC...")
    for index, account in enumerate(big_dspac):
        name = f"DSPAC {index + 1}"
        try:
            user, password = account.split(":")[:2]
            use_email = "@" in user
            # Initialize the DSPAC API object
            ds = DSPACAPI(
                user,
                password,
                filename=f"DSPAC_{index + 1}.pkl",
                creds_path="./creds/",
            )
            ds.make_initial_request()
            # All the rest of the requests responsible for getting authenticated
            login(ds, bot_obj, name, loop, use_email=use_email)
            account_assets = ds.get_account_assets()
            account_info = ds.get_account_info()
            account_number = str(account_info["Data"]["accountNumber"])
            # Set account values
            masked_account_number = mask_string(account_number)
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


def login(ds: DSPACAPI, bot_obj: Bot | None, name: str, loop: asyncio.AbstractEventLoop | None, *, use_email: bool) -> bool:  # noqa: C901, PLR0912
    """Login to DSPAC."""
    try:
        # API call to generate the login ticket
        ticket_response = cast("dict[str, dict[str, str]]", ds.generate_login_ticket_email() if use_email else ds.generate_login_ticket_sms())
        # Ensure "Data" key exists and proceed with verification if necessary
        if ticket_response.get("Data") is None:
            msg = f"{name}: Invalid response from generating login ticket"
            raise Exception(msg)
        # Check if SMS or CAPTCHA verification are required
        data = ticket_response["Data"]
        if data.get("needSmsVerifyCode"):
            sms_and_captcha_response = handle_captcha_and_sms(ds, bot_obj, data, loop, name, use_email=use_email)
            if not sms_and_captcha_response:
                msg = f"{name}: Error solving SMS or Captcha"
                raise Exception(msg)
            # Get the OTP code from the user
            if bot_obj is not None and loop is not None:  # noqa: SIM108
                otp_code = asyncio.run_coroutine_threadsafe(
                    get_otp_from_discord(bot_obj, name, timeout=300, loop=loop),
                    loop,
                ).result()
            else:
                otp_code = input("Enter security code: ")
            if otp_code is None:
                msg = f"{name}: No OTP code received"
                raise Exception(msg)
            # Login with the OTP code
            if use_email:  # noqa: SIM108
                ticket_response = ds.generate_login_ticket_email(sms_code=otp_code)
            else:
                ticket_response = ds.generate_login_ticket_sms(sms_code=otp_code)
            if ticket_response.get("Message") == "Incorrect verification code.":
                msg = f"{name}: Incorrect OTP code"
                raise Exception(msg)
        # Handle the login ticket
        if ticket_response.get("Data") is not None and ticket_response["Data"].get("ticket") is not None:
            ticket = ticket_response["Data"]["ticket"]
        else:
            msg = f"{name}: Login failed. No ticket generated. Response: {ticket_response}"
            raise Exception(msg)
        # Login with the ticket
        login_response = ds.login_with_ticket(ticket)
        if login_response.get("Outcome") != "Success":
            msg = f"{name}: Login failed. Response: {login_response}"
            raise Exception(msg)
    except Exception as e:
        print(f"Error in OTP login: {e}")
        print(traceback.format_exc())
        return False
    else:
        return True


def handle_captcha_and_sms(ds: DSPACAPI, bot_obj: Bot | None, data: dict[str, str], loop: asyncio.AbstractEventLoop | None, name: str, *, use_email: bool) -> bool:
    """Handle CAPTCHA and SMS verification."""
    try:
        # If CAPTCHA is needed it will generate an SMS code as well
        if data.get("needCaptchaCode"):
            print(f"{name}: CAPTCHA required. Requesting CAPTCHA image...")
            captcha_response = solve_captcha(ds, bot_obj, name, loop, use_email=use_email)
            if not captcha_response:
                msg = f"{name}: Failure solving CAPTCHA!"
                raise Exception(msg)
            print(f"{name}: CAPTCHA solved. SMS response is: {captcha_response}")
        else:
            print(f"{name}: Requesting code...")
            sms_response = send_sms_code(ds, name, use_email=use_email)
            if not sms_response:
                msg = f"{name}: Unable to retrieve SMS code!"
                raise Exception(msg)
            print(f"{name}: SMS response is: {sms_response}")
    except Exception as e:
        print(f"Error in CAPTCHA or SMS: {e}")
        print(traceback.format_exc())
        return False
    else:
        return True


def solve_captcha(ds: DSPACAPI, bot_obj: Bot | None, name: str, loop: asyncio.AbstractEventLoop | None, *, use_email: bool) -> dict[str, str] | None:
    """Solve CAPTCHA and request SMS code."""
    try:
        captcha_image = ds.request_captcha()
        if not captcha_image:
            msg = f"{name}: Unable to request CAPTCHA image, aborting..."
            raise Exception(msg)
        # Send the CAPTCHA image to Discord for manual input
        print("Sending CAPTCHA to Discord for user input...")
        file = BytesIO()
        captcha_image.save(file, format="PNG")
        file.seek(0)
        # Retrieve input
        if bot_obj is not None and loop is not None:
            asyncio.run_coroutine_threadsafe(
                send_captcha_to_discord(file),
                loop,
            ).result()
            captcha_input = asyncio.run_coroutine_threadsafe(
                get_input_from_discord(
                    bot_obj,
                    f"{name} requires CAPTCHA input",
                    timeout=300,
                    loop=loop,
                ),
                loop,
            ).result()
        else:
            captcha_image.save("./captcha.png", format="PNG")
            captcha_input = input(
                "CAPTCHA image saved to ./captcha.png. Please open it and type in the code: ",
            )
        if captcha_input is None:
            msg = f"{name}: No CAPTCHA code found"
            raise Exception(msg)
        # Send the CAPTCHA to the appropriate API based on login type
        sms_request_response = cast("dict[str, str]", ds.request_email_code(captcha_input=captcha_input) if use_email else ds.request_sms_code(captcha_input=captcha_input))
        if sms_request_response.get("Message") == "Incorrect verification code.":
            msg = f"{name}: Incorrect CAPTCHA code!"
            raise Exception(msg)
    except Exception as e:
        print(f"{name}: Error solving CAPTCHA code: {e}")
        print(traceback.format_exc())
        return None
    else:
        return sms_request_response


def send_sms_code(ds: DSPACAPI, name: str, *, use_email: bool, captcha_input: str | None = None) -> dict[str, str] | bool:
    """Send SMS code."""
    sms_code_response = cast("dict[str, str]", ds.request_email_code(captcha_input=captcha_input) if use_email else ds.request_sms_code(captcha_input=captcha_input))
    if sms_code_response.get("Message") == "Incorrect verification code.":
        print(f"{name}: Incorrect CAPTCHA code, retrying...")
        return False
    return sms_code_response


def dspac_holdings(ds: Brokerage, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Retrieve and display all DSPAC account holdings."""
    for key in ds.get_account_numbers():
        for account in ds.get_account_numbers(key):
            obj = cast("DSPACAPI", ds.get_logged_in_objects(key, "ds"))
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
                print_and_discord(f"Error getting DSPAC holdings: {e}")
                print(traceback.format_exc())
                continue
    print_all_holdings(ds, loop, mask_account_number=False)


def dspac_transaction(ds: Brokerage, order_obj: StockOrder, loop: asyncio.AbstractEventLoop | None = None) -> None:  # noqa: C901, PLR0912
    """Handle Fennel DSPAC transactions."""
    print()
    print("==============================")
    print("DSPAC")
    print("==============================")
    print()
    for s in order_obj.get_stocks():
        for key in ds.get_account_numbers():
            action = order_obj.get_action().lower()
            print_and_discord(
                f"{key}: {action}ing {order_obj.get_amount()} of {s}",
                loop,
            )
            for account in ds.get_account_numbers(key):
                obj = cast("DSPACAPI", ds.get_logged_in_objects(key, "ds"))
                try:
                    quantity = order_obj.get_amount()
                    is_dry_run = order_obj.get_dry()
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
                            print_and_discord(
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
                            symbol=s,
                            account_number=account,
                        )
                        if holdings_response["Outcome"] != "Success":
                            print_and_discord(
                                f"{key} {account}: Error checking holdings: {holdings_response['Message']}",
                                loop,
                            )
                            continue
                        available_amount = float(
                            holdings_response["Data"]["enableAmount"],
                        )
                        # If trying to sell more than available, skip to the next
                        if quantity > available_amount:
                            print_and_discord(
                                f"{key} {account}: Not enough shares to sell {quantity} of {s}. Available: {available_amount}",
                                loop,
                            )
                            continue
                        # Validate the sell transaction
                        validation_response = obj.validate_sell(
                            symbol=s,
                            amount=quantity,
                            account_number=account,
                        )
                        if validation_response["Outcome"] != "Success":
                            print_and_discord(
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
                    print_and_discord(
                        f"{key}: {order_obj.get_action().capitalize()} {quantity} of {s} in {account}: {message}",
                        loop,
                    )
                except Exception as e:
                    print_and_discord(f"{key} {account}: Error placing order: {e}", loop)
                    print(traceback.format_exc())
                    continue
