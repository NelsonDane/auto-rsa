import os
import traceback
import uuid
from asyncio import AbstractEventLoop
from typing import cast

from dotenv import load_dotenv
from email_validator import EmailNotValidError, validate_email
from public_api_sdk import AccountType, InstrumentType, OrderExpirationRequest, OrderInstrument, OrderRequest, OrderSide, OrderType, PreflightRequest, PublicApiClient, TimeInForce
from public_api_sdk.auth_config import ApiKeyAuthConfig

from src.helper_api import Brokerage, StockOrder, mask_string, print_all_holdings, print_and_discord

TRADABLE_ACCOUNT_TYPES = [
    AccountType.BROKERAGE,
    AccountType.ROTH_IRA,
    AccountType.TRADITIONAL_IRA,
]


def public_init(loop: AbstractEventLoop | None = None) -> Brokerage | None:
    """Initialize Public API."""
    # Initialize .env file
    load_dotenv()
    # Import Public account
    public_obj = Brokerage("Public")
    if not os.getenv("PUBLIC_BROKER"):
        print("Public not found, skipping...")
        return None
    big_public = os.environ["PUBLIC_BROKER"].strip().split(",")
    # Log in to Public account
    print("Logging in to Public...")
    for index, account in enumerate(big_public):
        name = f"Public {index + 1}"
        try:
            # Check if using old login method (email/password)
            test_account = account.split(":")[0]  # old email
            try:
                validate_email(test_account)
                print_and_discord(
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
                print(f"{name}: Found account {mask_string(pub_account.account_id)}")
                public_obj.set_account_type(name, pub_account.account_id, pub_account.account_type)
                cash = pb.get_portfolio(account_id=pub_account.account_id)
                public_obj.set_account_totals(name, pub_account.account_id, float(cash.buying_power.cash_only_buying_power))
        except Exception as e:
            print(f"Error logging in to Public: {e}")
            print(traceback.format_exc())
            continue
    print("Logged in to Public!")
    return public_obj


def public_holdings(pbo: Brokerage, loop: AbstractEventLoop | None = None) -> None:
    """Retrieve and display all Public account holdings."""
    for key in pbo.get_account_numbers():
        obj = cast("PublicApiClient", pbo.get_logged_in_objects(key, "pb"))
        for account in pbo.get_account_numbers(key):
            try:
                # Get account holdings
                positions = obj.get_portfolio(account_id=account).positions
                if positions:
                    for holding in positions:
                        # Get symbol, quantity, and total value
                        current_price = float(holding.last_price.last_price) if holding.last_price is not None and holding.last_price.last_price is not None else "N/A"
                        pbo.set_holdings(key, account, holding.instrument.symbol, float(holding.quantity), current_price)
            except Exception as e:
                print_and_discord(f"{key}: Error getting account holdings: {e}", loop)
                print(traceback.format_exc())
                continue
    print_all_holdings(pbo, loop)


def public_transaction(pbo: Brokerage, order_obj: StockOrder, loop: AbstractEventLoop | None = None) -> None:
    """Handle Public API transactions."""
    print()
    print("==============================")
    print("Public")
    print("==============================")
    print()
    for s in order_obj.get_stocks():
        for key in pbo.get_account_numbers():
            print_and_discord(
                f"{key}: {order_obj.get_action()}ing {order_obj.get_amount()} of {s}",
                loop,
            )
            for account in pbo.get_account_numbers(key):
                # Check to only trade on brokerage accounts not HYSA
                account_type = pbo.get_account_types(key, account)
                if account_type not in TRADABLE_ACCOUNT_TYPES:
                    print_and_discord(f"{mask_string(account)}: Skipping non-tradable account type: {account_type}")
                    continue
                # Get Public API object
                obj = cast("PublicApiClient", pbo.get_logged_in_objects(key, "pb"))
                print_account = mask_string(account)
                # Dry run
                if order_obj.get_dry():
                    try:
                        preflight_request = PreflightRequest(
                            instrument=OrderInstrument(symbol=s, type=InstrumentType.EQUITY),
                            order_side=OrderSide(order_obj.get_action().upper()),
                            order_type=OrderType.MARKET,
                            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY, expiration_time=None),
                            quantity=int(order_obj.get_amount()),
                            amount=None,
                            limit_price=None,
                            stop_price=None,
                            open_close_indicator=None,
                        )
                        obj.perform_preflight_calculation(preflight_request, account_id=account)
                        print_and_discord(
                            f"DRY RUN: {order_obj.get_action()} {order_obj.get_amount()} of {s} in {print_account}: Preflight check successful",
                            loop,
                        )
                    except Exception as e:
                        print_and_discord(f"DRY RUN: {print_account}: Preflight check failed: {e}", loop)
                        traceback.print_exc()
                else:
                    try:
                        order_request = OrderRequest(
                            order_id=str(uuid.uuid4()),
                            instrument=OrderInstrument(symbol=s, type=InstrumentType.EQUITY),
                            order_side=OrderSide(order_obj.get_action().upper()),
                            order_type=OrderType.MARKET,
                            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY, expiration_time=None),
                            quantity=int(order_obj.get_amount()),
                            amount=None,
                            limit_price=None,
                            stop_price=None,
                            open_close_indicator=None,
                        )
                        obj.place_order(order_request, account_id=account)
                        print_and_discord(
                            f"{order_obj.get_action()} {order_obj.get_amount()} of {s} in {print_account}: Success",
                            loop,
                        )
                    except Exception as e:
                        print_and_discord(f"{print_account}: Error placing order: {e}", loop)
                        traceback.print_exc()
                        continue
