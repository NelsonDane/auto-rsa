# Nelson Dane
# Schwab API

import os
import traceback
from asyncio import AbstractEventLoop
from time import sleep
from typing import cast

from dotenv import load_dotenv
from schwab_api.schwab import Schwab

from src.helper_api import Brokerage, StockOrder, mask_string, print_all_holdings, print_and_discord

# Define known transaction errors
TRANSACTION_ERRORS = {
    "One share buy orders for this security must be phoned into a representative.": "Order failed: One share buy orders must be phoned in.",
    "This order may result in an oversold/overbought position in your account.": "Order failed: This may result in an oversold/overbought position.",
}


def schwab_init() -> Brokerage | None:
    """Initialize Schwab API."""
    # Initialize .env file
    load_dotenv()
    # Import Schwab account
    if not os.getenv("SCHWAB"):
        print("Schwab not found, skipping...")
        return None
    accounts = os.environ["SCHWAB"].strip().split(",")
    # Log in to Schwab account
    print("Logging in to Schwab...")
    schwab_obj = Brokerage("Schwab")
    for acct in accounts:
        index = accounts.index(acct) + 1
        name = f"Schwab {index}"
        try:
            account = acct.split(":")
            schwab = Schwab(session_cache=f"./creds/schwab{index}.json")
            schwab.login(
                username=account[0],
                password=account[1],
                totp_secret=None if account[2] == "NA" else account[2],
            )

            # Use the older get_account_info() function which correctly fetches all accounts
            account_info = schwab.get_account_info()

            if not account_info:
                msg = f"{name}: Failed to retrieve account information from Schwab."
                print_and_discord(msg)
                raise Exception(msg)

            account_list = list(account_info.keys())
            print_accounts = [mask_string(a) for a in account_list]
            print(f"The following Schwab accounts were found: {print_accounts}")
            print("Logged in to Schwab!")
            schwab_obj.set_logged_in_object(name, schwab)
            for acc_id in account_list:
                schwab_obj.set_account_number(name, acc_id)
                schwab_obj.set_account_totals(
                    name,
                    acc_id,
                    account_info[acc_id]["account_value"],
                )
                holdings = account_info[acc_id]["positions"]
                for item in holdings:
                    # The old function returns a simple string for description, not a dict
                    sym = item["symbol"]
                    if not sym:
                        sym = "Unknown"
                    mv = round(float(item["market_value"]), 2)
                    qty = float(item["quantity"])
                    current_price = 0 if qty == 0 else round(mv / qty, 2)
                    schwab_obj.set_holdings(name, acc_id, sym, qty, current_price)

        except Exception as e:
            print(f"Error logging in to Schwab: {e}")
            print(traceback.format_exc())
            return None
    return schwab_obj


def schwab_holdings(schwab_o: Brokerage, loop: AbstractEventLoop | None = None) -> None:
    """Display Schwab account holdings (cached)."""
    print_all_holdings(schwab_o, loop)


def schwab_transaction(schwab_o: Brokerage, order_obj: StockOrder, loop: AbstractEventLoop | None = None) -> None:  # noqa: C901
    """Handle Schwab API transactions."""
    print()
    print("==============================")
    print("Schwab")
    print("==============================")
    print()
    # Use each account (unless specified in .env)
    purchase_accounts = os.getenv("SCHWAB_ACCOUNT_NUMBERS", "").strip().split(":")
    for s in order_obj.get_stocks():
        for key in schwab_o.get_account_numbers():
            print_and_discord(
                f"{key} {order_obj.get_action()}ing {order_obj.get_amount()} {s} @ {order_obj.get_price()}",
                loop,
            )
            obj = cast("Schwab", schwab_o.get_logged_in_objects(key))
            for account in schwab_o.get_account_numbers(key):
                print_account = mask_string(account)
                if purchase_accounts != [""] and order_obj.get_action().lower() != "sell" and str(account) not in purchase_accounts:
                    print(f"Skipping account {print_account}, not in SCHWAB_ACCOUNT_NUMBERS")
                    continue
                # If DRY is True, don't actually make the transaction
                if order_obj.get_dry():
                    print_and_discord("Running in DRY mode. No transactions will be made.", loop)
                try:
                    messages, success = obj.trade_v2(
                        ticker=s,
                        side=order_obj.get_action().capitalize(),
                        qty=order_obj.get_amount(),
                        account_id=account,
                        dry_run=order_obj.get_dry(),
                    )

                    handled = False
                    if not success:
                        for error, friendly_message in TRANSACTION_ERRORS.items():
                            if any(error in str(msg) for msg in messages):
                                print_and_discord(
                                    f"{key} account {print_account}: {friendly_message}",
                                    loop,
                                )
                                handled = True
                                break  # Exit the inner loop once an error is handled

                    if handled:
                        continue  # Skip to the next account or stock

                    print_and_discord(
                        (f"{key} account {print_account}: The order verification was successful" if success else "unsuccessful, retrying with legacy API..."),
                        loop,
                    )

                    if not success:
                        messages, success = obj.trade(
                            ticker=s,
                            side=order_obj.get_action().capitalize(),
                            qty=order_obj.get_amount(),
                            account_id=account,
                            dry_run=order_obj.get_dry(),
                        )
                        print_and_discord(
                            (f"{key} account {print_account}: The order verification was retry successful" if success else "retry unsuccessful"),
                            loop,
                        )
                        if not success:
                            print_and_discord(
                                f"{key} account {print_account}: The order verification produced the following messages: {messages}",
                                loop,
                            )
                except Exception as e:
                    print_and_discord(
                        f"{key} {print_account}: Error submitting order: {e}",
                        loop,
                    )
                    print(traceback.format_exc())
                sleep(1)
