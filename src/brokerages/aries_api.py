# Nelson Dane
# Aries API

import os
import traceback
from asyncio import AbstractEventLoop
from typing import cast

from dotenv import load_dotenv
from finance_dev import FinanceDev, models

from src.helper_api import Brokerage, StockOrder, mask_string, print_all_holdings, print_and_discord


def aries_init() -> Brokerage | None:
    """Initialize Aries API client."""
    # Initialize .env file
    load_dotenv()
    # Import Aries accounts
    if not os.getenv("ARIES"):
        print("Aries not found, skipping...")
        return None
    # Get client_id:client_secret pairs and split into list
    credentials = os.environ["ARIES"].strip().split(",")
    # Login to each account
    aries_obj = Brokerage("Aries")
    print("Logging in to Aries...")
    for idx, credential in enumerate(credentials):
        name = f"Aries {idx + 1}"
        try:
            client_id, client_secret = credential.split(":")
        except ValueError:
            print(f"{name}: Error: Invalid credential format, expected 'client_id:client_secret'")
            continue
        try:
            client = FinanceDev(
                security=models.Security(
                    client_id=client_id,
                    client_secret=client_secret,
                ),
            )
            accounts_response = client.accounts.get_user_accounts()
        except Exception as e:
            print(f"{name}: Error logging in: {e}")
            print(traceback.format_exc())
            continue
        if accounts_response is None or accounts_response.get_accounts_response is None:
            print(f"{name}: Error: No accounts response from Aries")
            continue
        accounts = accounts_response.get_accounts_response.accounts
        print(f"Aries accounts found: {len(accounts)}")
        for account in accounts:
            if account.status != models.AccountItemStatus.OPEN:
                print(f"Ignoring {mask_string(account.trading_account_id)}: {account.status}")
                continue
            an = account.trading_account_id
            print(mask_string(an))
            aries_obj.set_account_number(name, an)
            aries_obj.set_account_type(name, an, account.account_type)
            # Get balance
            try:
                balance_response = client.accounts.get_account_balance(id=an)
                if balance_response is None or balance_response.account_balance_v2 is None:
                    aries_obj.set_account_totals(name, an, 0)
                    continue
                aries_obj.set_account_totals(
                    name,
                    an,
                    balance_response.account_balance_v2.balance,
                )
            except Exception as e:
                print(f"{name}: Error getting balance for {mask_string(an)}: {e}")
                print(traceback.format_exc())
                aries_obj.set_account_totals(name, an, 0)
        # Store the SDK client itself; it manages its own token refresh
        aries_obj.set_logged_in_object(name, client)
    print("Logged in to Aries!")
    return aries_obj


def aries_holdings(aries_o: Brokerage, loop: AbstractEventLoop | None = None) -> None:
    """Retrieve and display all Aries account holdings."""
    for key in aries_o.get_account_numbers():
        client = cast("FinanceDev", aries_o.get_logged_in_objects(key))
        for account_number in aries_o.get_account_numbers(key):
            try:
                positions_response = client.accounts.get_account_positions(id=account_number)
                if positions_response is None or positions_response.get_positions_response is None:
                    continue
                positions = positions_response.get_positions_response.positions
                for position in positions:
                    aries_o.set_holdings(
                        key,
                        account_number,
                        position.symbol,
                        position.quantity,
                        position.price,
                    )
            except Exception as e:
                print_and_discord(f"{key}: Error getting holdings: {e}", loop=loop)
                print(traceback.format_exc())
                continue
    print_all_holdings(aries_o, loop=loop)


def aries_transaction(aries_o: Brokerage, order_obj: StockOrder, loop: AbstractEventLoop | None = None) -> None:
    """Handle Aries API transactions."""
    print()
    print("==============================")
    print("Aries")
    print("==============================")
    print()
    for s in order_obj.get_stocks():
        for key in aries_o.get_account_numbers():
            print_and_discord(
                f"{key}: {order_obj.get_action()}ing {order_obj.get_amount()} of {s}",
                loop=loop,
            )
            client = cast("FinanceDev", aries_o.get_logged_in_objects(key))
            for account_number in aries_o.get_account_numbers(key):
                print_account = mask_string(account_number)
                # Aries market orders don't support fractional shares
                if not order_obj.get_amount().is_integer():
                    print_and_discord(
                        f"Aries account {print_account} Error: Fractional share {order_obj.get_amount()} not supported",
                        loop=loop,
                    )
                    continue
                if not order_obj.get_dry():
                    try:
                        side = models.OrderSideEnum.BUY if order_obj.get_action() == "buy" else models.OrderSideEnum.SELL
                        response = client.orders.place_order(
                            request={
                                "qty": str(int(order_obj.get_amount())),
                                "side": side,
                                "symbol": s,
                                "time_in_force": models.OrderRequestTimeInForceEnum.DAY,
                                "trading_account_id": account_number,
                                "type": models.OrderTypeEnum.MARKET,
                            },
                        )
                        if response is None or response.ord_response is None:
                            print_and_discord(
                                f"Aries account {print_account} Error: No order response from Aries",
                                loop=loop,
                            )
                            continue
                        print_and_discord(
                            f"Aries account {print_account}: {order_obj.get_action()} {order_obj.get_amount()} of {s}: {response.ord_response.status}",
                            loop=loop,
                        )
                    except Exception as e:
                        print_and_discord(
                            f"Aries account {print_account} Error: {e}",
                            loop=loop,
                        )
                        print(traceback.format_exc())
                        continue
                else:
                    print_and_discord(
                        f"Aries account {print_account}: Running in DRY mode. Transaction would've been: {order_obj.get_action()} {order_obj.get_amount()} of {s}",
                        loop=loop,
                    )
