import os
import traceback
import uuid

from dotenv import load_dotenv
from public_api_sdk import InstrumentType, OrderExpirationRequest, OrderInstrument, OrderRequest, PublicApiClient
from public_api_sdk.auth_config import ApiKeyAuthConfig
from email_validator import validate_email, EmailNotValidError
from public_api_sdk import PreflightRequest, OrderSide, OrderType, TimeInForce

from helperAPI import (
    Brokerage,
    maskString,
    printAndDiscord,
    printHoldings,
    stockOrder,
)


def public_init(PUBLIC_EXTERNAL: str | None = None, botObj=None, loop=None):
    # Initialize .env file
    load_dotenv()
    # Import Public account
    public_obj = Brokerage("Public")
    if not os.getenv("PUBLIC_BROKER") and PUBLIC_EXTERNAL is None:
        print("Public not found, skipping...")
        return None
    PUBLIC = (
        os.environ["PUBLIC_BROKER"].strip().split(",")
        if PUBLIC_EXTERNAL is None
        else PUBLIC_EXTERNAL.strip().split(",")
    )
    # Log in to Public account
    print("Logging in to Public...")
    for index, account in enumerate(PUBLIC):
        name = f"Public {index + 1}"
        try:
            # Check if using old login method (email/password)
            test_account = account.split(":")[0] # old email
            try:
                validate_email(test_account)
                printAndDiscord(
                    f"{name}: Public no longer supports email login. Please switch to API tokens. See README for more info.",
                    loop,
                )
                continue
            except EmailNotValidError:
                pass
            pb = PublicApiClient(ApiKeyAuthConfig(api_secret_key=account))
            public_obj.set_logged_in_object(name, pb, "pb")
            accounts = pb.get_accounts().accounts
            for pub_account in accounts:
                public_obj.set_account_number(name, pub_account.account_id)
                print(f"{name}: Found account {maskString(pub_account.account_id)}")
                public_obj.set_account_type(name, pub_account.account_id, pub_account.account_type)
                cash = pb.get_portfolio(account_id=pub_account.account_id)
                public_obj.set_account_totals(name, pub_account.account_id, float(cash.buying_power.cash_only_buying_power))
        except Exception as e:
            print(f"Error logging in to Public: {e}")
            print(traceback.format_exc())
            continue
    print("Logged in to Public!")
    return public_obj


def public_holdings(pbo: Brokerage, loop=None):
    for key in pbo.get_account_numbers():
        for account in pbo.get_account_numbers(key):
            obj: PublicApiClient = pbo.get_logged_in_objects(key, "pb") # pyright: ignore[reportAssignmentType]
            try:
                # Get account holdings
                positions = obj.get_portfolio(account_id=account).positions
                if positions != []:
                    for holding in positions:
                        # Get symbol, quantity, and total value
                        sym = holding.instrument.symbol
                        qty = float(holding.quantity)
                        current_price = holding.last_price
                        if current_price is not None and current_price.last_price is not None:
                            current_price = float(current_price.last_price)
                        else:
                            current_price = "N/A"
                        pbo.set_holdings(key, account, sym, qty, current_price)
            except Exception as e:
                printAndDiscord(f"{key}: Error getting account holdings: {e}", loop)
                traceback.format_exc()
                continue
    printHoldings(pbo, loop)


def public_transaction(pbo: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Public")
    print("==============================")
    print()
    for s in orderObj.get_stocks():
        for key in pbo.get_account_numbers():
            printAndDiscord(
                f"{key}: {orderObj.get_action()}ing {orderObj.get_amount()} of {s}",
                loop,
            )
            for account in pbo.get_account_numbers(key):
                obj: PublicApiClient = pbo.get_logged_in_objects(key, "pb") # pyright: ignore[reportAssignmentType]
                print_account = maskString(account)
                # Dry run
                if orderObj.get_dry():
                    try:
                        preflight_request = PreflightRequest(
                            instrument=OrderInstrument(symbol=s, type=InstrumentType.EQUITY),
                            order_side=OrderSide(orderObj.get_action().upper()),
                            order_type=OrderType.MARKET,
                            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY, expiration_time=None),
                            quantity=int(orderObj.get_amount()),
                            amount=None,
                            limit_price=None,
                            stop_price=None,
                            open_close_indicator=None,
                        )
                        obj.perform_preflight_calculation(preflight_request, account_id=account)
                        printAndDiscord(
                            f"DRY RUN: {orderObj.get_action()} {orderObj.get_amount()} of {s} in {print_account}: Preflight check successful",
                            loop,
                        )
                    except Exception as e:
                        printAndDiscord(f"DRY RUN: {print_account}: Preflight check failed: {e}", loop)
                        traceback.print_exc()
                else:
                    try:
                        order_request = OrderRequest(
                            order_id=str(uuid.uuid4()),
                            instrument=OrderInstrument(symbol=s, type=InstrumentType.EQUITY),
                            order_side=OrderSide(orderObj.get_action().upper()),
                            order_type=OrderType.MARKET,
                            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY, expiration_time=None),
                            quantity=int(orderObj.get_amount()),
                            amount=None,
                            limit_price=None,
                            stop_price=None,
                            open_close_indicator=None,
                        )
                        obj.place_order(order_request, account_id=account)
                        printAndDiscord(
                            f"{orderObj.get_action()} {orderObj.get_amount()} of {s} in {print_account}: Success",
                            loop,
                        )
                    except Exception as e:
                        printAndDiscord(f"{print_account}: Error placing order: {e}", loop)
                        traceback.print_exc()
                        continue
