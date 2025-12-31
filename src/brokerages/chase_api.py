# Donald Ryan Gullett(MaxxRK)
# Chase API

import asyncio
import os
import pprint
import traceback
from typing import cast

from chase import account as ch_account
from chase import order, session, symbols
from discord.ext.commands import Bot
from dotenv import load_dotenv

from src.helper_api import Brokerage, StockOrder, get_otp_from_discord, print_all_holdings, print_and_discord


def chase_run(order_obj: StockOrder, bot_obj: Bot | None = None, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Run all of the Chase API commands in a single function."""
    # Initialize .env file
    load_dotenv()
    # Import Chase account
    if not os.getenv("CHASE"):
        print("Chase not found, skipping...")
        return
    accounts = os.environ["CHASE"].strip().split(",")
    # Get headless flag
    headless = os.getenv("HEADLESS", "true").lower() == "true"

    # For each set of login info, i.e. seperate chase accounts
    for account in accounts:
        # Start at index 1 and go to how many logins we have
        index = accounts.index(account) + 1
        # Receive the chase broker class object and the AllAccount object related to it
        chase_details = chase_init(
            account=account,
            index=index,
            headless=headless,
            bot_obj=bot_obj,
            loop=loop,
        )
        if chase_details is not None:
            order_obj.set_logged_in(chase_details[0], "chase")
            if order_obj.get_holdings():
                chase_holdings(chase_details[0], chase_details[1], loop=loop)
            # Only other option is _transaction
            else:
                chase_transaction(
                    chase_details[0],
                    chase_details[1],
                    order_obj,
                    loop=loop,
                )
    return


def get_account_id(account_connectors: dict[str, str] | None, value: str) -> str | None:
    """Retrieve the account ID associated with a given value."""
    if account_connectors is None:
        return None
    for key, val in account_connectors.items():
        if val[0] == value:
            return str(key)
    return None


def chase_init(account: str, index: int, *, headless: bool = True, bot_obj: Bot | None = None, loop: asyncio.AbstractEventLoop | None = None) -> tuple[Brokerage, ch_account.AllAccount] | None:
    """Log into chase. Checks for 2FA and gathers details on the chase accounts."""
    # Log in to Chase account
    print("Logging in to Chase...")
    # Create brokerage class object and call it chase_obj
    chase_obj = Brokerage("Chase")
    name = f"Chase {index}"
    ch_session: session.ChaseSession | None = None
    try:
        # Split the login into into seperate items
        user_pass = account.split(":")
        # If the debug flag is present, use it, else set it to false
        debug = bool(user_pass[3]) if len(user_pass) == 4 else False  # noqa: PLR2004
        # Create a ChaseSession class object which automatically configures and opens a browser
        ch_session = session.ChaseSession(
            title=f"chase_{index}",
            headless=headless,
            profile_path="./creds",
            debug=debug,
        )
        # Login to chase
        need_second = ch_session.login(user_pass[0], user_pass[1], user_pass[2])
        # If 2FA is present, ask for code
        if need_second:
            if bot_obj is None and loop is None:
                ch_session.login_two(input("Enter code: "))
            elif bot_obj is not None and loop is not None:
                sms_code = asyncio.run_coroutine_threadsafe(
                    get_otp_from_discord(bot_obj, name, code_len=8, loop=loop),
                    loop,
                ).result()
                if sms_code is None:
                    msg = f"Chase {index} code not received in time..."
                    raise Exception(msg, loop)
                ch_session.login_two(sms_code)
        # Create an AllAccounts class object using the current browser session. Holds information about all accounts
        all_accounts = ch_account.AllAccount(ch_session)
        # Get the account IDs and store in a list. The IDs are different than account numbers.
        account_ids = list([] if all_accounts.account_connectors is None else all_accounts.account_connectors.keys())
        print("Logged in to Chase!")
        # In the Chase Brokerage object, set the index of "Chase 1" to be its own empty array and append the chase session to the end of this array
        chase_obj.set_logged_in_object(name, ch_session)
        # Create empty array to store account number masks (last 4 digits of each account number)
        print_accounts = []
        for acct in account_ids:
            # Create an AccountDetails Object which organizes the information in the AllAccounts class object
            chase_account = ch_account.AccountDetails(acct, all_accounts)
            # Save account masks
            chase_obj.set_account_number(name, chase_account.mask)
            chase_obj.set_account_totals(name, chase_account.mask, chase_account.account_value)
            print_accounts.append(chase_account.mask)
        print(f"The following Chase accounts were found: {print_accounts}")
    except Exception as e:
        if ch_session:
            ch_session.close_browser()
        print(f"Error logging in to Chase: {e}")
        print(traceback.format_exc())
        return None
    return (chase_obj, all_accounts)


def _process_position(position: dict, chase_o: Brokerage, key: str, account: str) -> None:
    """Process a single position and add it to holdings."""
    if position["instrumentLongName"] == "Cash and Sweep Funds":
        sym = position["instrumentLongName"]
        current_price = position["marketValue"]["baseValueAmount"]
        qty = "1"
        chase_o.set_holdings(key, account, sym, qty, current_price)
    elif position["assetCategoryName"] == "EQUITY":
        try:
            sym = position["positionComponents"][0]["securityIdDetail"][0]["symbolSecurityIdentifier"]
            current_price = position["marketValue"]["baseValueAmount"]
            qty = position["tradedUnitQuantity"]
        except KeyError:
            sym = position["securityIdDetail"]["cusipIdentifier"]
            current_price = position["marketValue"]["baseValueAmount"]
            qty = position["tradedUnitQuantity"]
        chase_o.set_holdings(key, account, sym, qty, current_price)


def _process_account_holdings(chase_o: Brokerage, all_accounts: ch_account.AllAccount, key: str, account: str) -> None:
    """Process holdings for a single account."""
    ch_session = cast("session.ChaseSession", chase_o.get_logged_in_objects(key))
    account_id = get_account_id(all_accounts.account_connectors, account)
    data = symbols.SymbolHoldings(account_id, ch_session)
    success = data.get_holdings()

    if success:
        for position in data.positions:
            _process_position(position, chase_o, key, account)


def chase_holdings(chase_o: Brokerage, all_accounts: ch_account.AllAccount, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Retrieve and display all Chase account holdings."""
    # Get holdings on each account. This loop only ever runs once.
    ch_session: session.ChaseSession | None = None
    # Get the session object
    account = ""
    for key in chase_o.get_account_numbers():
        try:
            ch_session = cast("session.ChaseSession", chase_o.get_logged_in_objects(key))
            # Retrieve account masks and iterate through them
            for _, account in enumerate(chase_o.get_account_numbers(key)):
                _process_account_holdings(chase_o, all_accounts, key, account)
        except Exception as e:
            if ch_session:
                ch_session.close_browser()
            print_and_discord(f"{key} {account}: Error getting holdings: {e}", loop)
            print(traceback.format_exc())
            continue
        print_all_holdings(chase_o, loop)
    if ch_session:
        print_and_discord("Closing Chase browser...", loop)
        ch_session.close_browser()


def _calculate_limit_price(symbol_quote: symbols.SymbolQuote, action: str) -> tuple[order.PriceType, float]:
    """Calculate limit price for buy orders."""
    current_price = symbol_quote.ask_price

    if current_price >= 1.00:
        return order.PriceType.MARKET, 0.0
    if action.upper() == "BUY":
        # For buys, always round UP to ensure fill
        limit_price = round(current_price + 0.01, 2)
    else:  # SELL
        # For sells, always round DOWN to ensure fill
        limit_price = round(current_price - 0.01, 2)
        limit_price = max(limit_price, 0.01)
    return order.PriceType.LIMIT, limit_price


def _process_order_messages(messages: dict, order_obj: StockOrder, key: str, account: str, loop: asyncio.AbstractEventLoop | None) -> None:
    """Process and print order messages."""
    if order_obj.get_dry():
        pprint.pprint(messages["ORDER VALIDATION"])  # noqa: T203
        print_and_discord(
            (f"{key} account {account}: The order verification was " + ("successful" if messages["ORDER VALIDATION"] else "unsuccessful")),
            loop,
        )
        if messages["ORDER INVALID"]:
            print_and_discord(
                f"{key} account {account}: The order verification produced the following messages: {messages['ORDER INVALID']}",
                loop,
            )
    else:
        pprint.pprint(messages["ORDER CONFIRMATION"])  # noqa: T203

        # Check if ORDER CONFIRMATION is a dict or string
        order_confirmation = messages["ORDER CONFIRMATION"]
        is_successful = bool(order_confirmation.get("orderIdentifier")) if isinstance(order_confirmation, dict) else isinstance(order_confirmation, str) and len(order_confirmation) > 0
        print_and_discord(
            (f"{key} account {account}: The order was " + ("successful" if is_successful else "unsuccessful")),
            loop,
        )

        if messages["ORDER INVALID"]:
            print_and_discord(
                f"{key} account {account}: The order produced the following messages: {messages['ORDER INVALID']}",
                loop,
            )


def _execute_single_order(ch_session: session.ChaseSession, all_accounts: ch_account.AllAccount, order_obj: StockOrder, ticker: str, account: str, price_type: order.PriceType, limit_price: float, key: str, loop: asyncio.AbstractEventLoop | None) -> None:  # noqa: PLR0913, PLR0917
    """Execute a single order for one account."""
    target_account_id = get_account_id(all_accounts.account_connectors, account)

    if order_obj.get_dry():
        print_and_discord("Running in DRY mode. No transactions will be made.", loop)

    if order_obj.get_action().capitalize() == "Buy":
        order_type = order.OrderSide.BUY
    else:
        # Reset to market for selling
        price_type = order.PriceType.MARKET
        order_type = order.OrderSide.SELL

    chase_order = order.Order(ch_session)
    messages = chase_order.place_order(
        account_id=target_account_id,
        quantity=int(order_obj.get_amount()),
        price_type=price_type,
        symbol=ticker,
        duration=order.Duration.DAY,
        order_type=order_type,
        dry_run=order_obj.get_dry(),
        limit_price=limit_price,
    )

    print("The order verification produced the following messages: ")
    _process_order_messages(messages, order_obj, key, account, loop)


def _process_ticker_orders(chase_obj: Brokerage, all_accounts: ch_account.AllAccount, order_obj: StockOrder, ticker: str, loop: asyncio.AbstractEventLoop | None) -> session.ChaseSession | None:
    """Process orders for a single ticker across all accounts."""
    ch_session = None

    for key in chase_obj.get_account_numbers():
        price_type = order.PriceType.MARKET
        limit_price = 0.0

        ch_session = cast("session.ChaseSession", chase_obj.get_logged_in_objects(key))

        # Determine limit or market for buy orders
        if order_obj.get_action().capitalize() == "Buy":
            account_ids = list([] if all_accounts.account_connectors is None else all_accounts.account_connectors.keys())
            symbol_quote = symbols.SymbolQuote(
                account_id=account_ids[0],
                session=ch_session,
                symbol=ticker,
            )
            price_type, limit_price = _calculate_limit_price(symbol_quote, order_obj.get_action())

        print_and_discord(
            f"{key} {order_obj.get_action()}ing {order_obj.get_amount()} {ticker} @ {price_type.value}",
            loop,
        )

        try:
            print(chase_obj.get_account_numbers())
            for account in chase_obj.get_account_numbers(key):
                _execute_single_order(ch_session, all_accounts, order_obj, ticker, account, price_type, limit_price, key, loop)
        except Exception as e:
            print_and_discord(f"{key} {account}: Error submitting order: {e}", loop)
            print(traceback.format_exc())
            continue

    return ch_session


def chase_transaction(chase_obj: Brokerage, all_accounts: ch_account.AllAccount, order_obj: StockOrder, loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Handle Chase API transactions."""
    print()
    print("==============================")
    print("Chase")
    print("==============================")
    print()

    ch_session: session.ChaseSession | None = None

    for ticker in order_obj.get_stocks():
        ch_session = _process_ticker_orders(chase_obj, all_accounts, order_obj, ticker, loop)

    if ch_session:
        print_and_discord("Closing Chase browser...", loop)
        ch_session.close_browser()

    print_and_discord("All Chase transactions complete", loop)
