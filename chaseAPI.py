# Donald Ryan Gullett(MaxxRK)
# Chase API

import asyncio
import os
import pprint
import traceback

from chase import account as ch_account
from chase import order, session, symbols
from dotenv import load_dotenv

from helperAPI import (
    Brokerage,
    getOTPCodeDiscord,
    printAndDiscord,
    printHoldings,
    stockOrder,
)


def chase_run(
    orderObj: stockOrder, command=None, botObj=None, loop=None, CHASE_EXTERNAL=None
):
    # Initialize .env file
    load_dotenv()
    # Import Chase account
    if not os.getenv("CHASE") and CHASE_EXTERNAL is None:
        print("Chase not found, skipping...")
        return None
    accounts = (
        os.environ["CHASE"].strip().split(",")
        if CHASE_EXTERNAL is None
        else CHASE_EXTERNAL.strip().split(",")
    )
    # Get headless flag
    headless = os.getenv("HEADLESS", "true").lower() == "true"
    # Set the functions to be run
    _, second_command = command

    # For each set of login info, i.e. seperate chase accounts
    for account in accounts:
        # Start at index 1 and go to how many logins we have
        index = accounts.index(account) + 1
        # Receive the chase broker class object and the AllAccount object related to it
        chase_details = chase_init(
            account=account,
            index=index,
            headless=headless,
            botObj=botObj,
            loop=loop,
        )
        if chase_details is not None:
            orderObj.set_logged_in(chase_details[0], "chase")
            if second_command == "_holdings":
                chase_holdings(chase_details[0], chase_details[1], loop=loop)
            # Only other option is _transaction
            else:
                chase_transaction(
                    chase_details[0], chase_details[1], orderObj, loop=loop
                )
    return None


def get_account_id(account_connectors, value):
    for key, val in account_connectors.items():
        if val[0] == value:
            return key
    return None


def chase_init(account: str, index: int, headless=True, botObj=None, loop=None):
    """
    Logs into chase. Checks for 2FA and gathers details on the chase accounts

    Args:
        account (str): The chase username, password, last 4 of phone #, and possible debug flag, seperated by ':'.
        index (int): The index of this chase account in a list of accounts.
        headless (bool): Whether to run the browser in headless mode.
        botObj (Bot): The discord bot object if used.
        loop (AbstractEventLoop): The event loop to be used
    Raises:
        Exception: Error logging in to Chase
    Returns:
        Brokerage object which represents the chase session and data.
        AllAccounts object which holds account information.
    """
    # Log in to Chase account
    print("Logging in to Chase...")
    # Create brokerage class object and call it chase
    chase_obj = Brokerage("Chase")
    name = f"Chase {index}"
    try:
        # Split the login into into seperate items
        account = account.split(":")
        # If the debug flag is present, use it, else set it to false
        debug = bool(account[3]) if len(account) == 4 else False
        # Create a ChaseSession class object which automatically configures and opens a browser
        ch_session = session.ChaseSession(
            title=f"chase_{index}",
            headless=headless,
            profile_path="./creds",
            debug=debug,
        )
        # Login to chase
        need_second = ch_session.login(account[0], account[1], account[2])
        # If 2FA is present, ask for code
        if need_second:
            if botObj is None and loop is None:
                ch_session.login_two(input("Enter code: "))
            else:
                sms_code = asyncio.run_coroutine_threadsafe(
                    getOTPCodeDiscord(botObj, name, code_len=8, loop=loop), loop
                ).result()
                if sms_code is None:
                    raise Exception(f"Chase {index} code not received in time...", loop)
                ch_session.login_two(sms_code)
        # Create an AllAccounts class object using the current browser session. Holds information about all accounts
        all_accounts = ch_account.AllAccount(ch_session)
        # Get the account IDs and store in a list. The IDs are different than account numbers.
        account_ids = list(all_accounts.account_connectors.keys())
        print("Logged in to Chase!")
        # In the Chase Brokerage object, set the index of "Chase 1" to be its own empty array and append the chase session to the end of this array
        chase_obj.set_logged_in_object(name, ch_session)
        # Create empty array to store account number masks (last 4 digits of each account number)
        print_accounts = []
        for acct in account_ids:
            # Create an AccountDetails Object which organizes the information in the AllAccounts class object
            account = ch_account.AccountDetails(acct, all_accounts)
            # Save account masks
            chase_obj.set_account_number(name, account.mask)
            chase_obj.set_account_totals(name, account.mask, account.account_value)
            print_accounts.append(account.mask)
        print(f"The following Chase accounts were found: {print_accounts}")
    except Exception as e:
        ch_session.close_browser()
        print(f"Error logging in to Chase: {e}")
        print(traceback.format_exc())
        return None
    return [chase_obj, all_accounts]


def chase_holdings(chase_o: Brokerage, all_accounts: ch_account.AllAccount, loop=None):
    """
    Get the holdings of chase account

    Args:
        chase_o (Brokerage): Brokerage object associated with the current session.
        all_accounts (AllAccount): AllAccount object that holds account information.
        loop (AbstractEventLoop): The event loop to be used if present.
    """
    # Get holdings on each account. This loop only ever runs once.
    for key in chase_o.get_account_numbers():
        try:
            # Retrieve account masks and iterate through them
            for _, account in enumerate(chase_o.get_account_numbers(key)):
                # Retrieve the chase session
                ch_session: session.ChaseSession = chase_o.get_logged_in_objects(key)
                # Get the account ID accociated with mask
                account_id = get_account_id(all_accounts.account_connectors, account)
                data = symbols.SymbolHoldings(account_id, ch_session)
                success = data.get_holdings()
                if success:
                    for i, _ in enumerate(data.positions):
                        if (
                            data.positions[i]["instrumentLongName"]
                            == "Cash and Sweep Funds"
                        ):
                            sym = data.positions[i]["instrumentLongName"]
                            current_price = data.positions[i]["marketValue"][
                                "baseValueAmount"
                            ]
                            qty = "1"
                            chase_o.set_holdings(key, account, sym, qty, current_price)
                        elif data.positions[i]["assetCategoryName"] == "EQUITY":
                            try:
                                sym = data.positions[i]["positionComponents"][0][
                                    "securityIdDetail"
                                ][0]["symbolSecurityIdentifier"]
                                current_price = data.positions[i]["marketValue"][
                                    "baseValueAmount"
                                ]
                                qty = data.positions[i]["tradedUnitQuantity"]
                            except KeyError:
                                sym = data.positions[i]["securityIdDetail"][
                                    "cusipIdentifier"
                                ]
                                current_price = data.positions[i]["marketValue"][
                                    "baseValueAmount"
                                ]
                                qty = data.positions[i]["tradedUnitQuantity"]
                            chase_o.set_holdings(key, account, sym, qty, current_price)
        except Exception as e:
            ch_session.close_browser()
            printAndDiscord(f"{key} {account}: Error getting holdings: {e}", loop)
            print(traceback.format_exc())
            continue
        printHoldings(chase_o, loop)
    ch_session.close_browser()


def chase_transaction(
    chase_obj: Brokerage,
    all_accounts: ch_account.AllAccount,
    orderObj: stockOrder,
    loop=None,
):
    """
    Executes transactions on all accounts.

    Args:
        chase_obj (Brokerage): The brokerage class object related to the chase session.
        all_accounts (AllAccount): AllAccount object that holds account information.
        orderObj (stockOrder): The order(s) to be executed.
        loop (AbstractEventLoop): The event loop to be used if present.
    Returns:
        None
    """
    print()
    print("==============================")
    print("Chase")
    print("==============================")
    print()

    # Buy on each account
    for ticker in orderObj.get_stocks():

        # This loop should only run once, but it provides easy access to the chase session by using key to get it back from
        # the chase_obj via get_logged_in_objects
        for key in chase_obj.get_account_numbers():

            # Declare for later
            price_type = order.PriceType.MARKET
            limit_price = 0.0

            # Load the chase session
            ch_session: session.ChaseSession = chase_obj.get_logged_in_objects(key)

            # Determine limit or market for buy orders
            if orderObj.get_action().capitalize() == "Buy":
                account_ids = list(all_accounts.account_connectors.keys())

                # Get the ask price and determine whether to use MARKET or LIMIT order
                symbol_quote = symbols.SymbolQuote(
                    account_id=account_ids[0], session=ch_session, symbol=ticker
                )

                # If it should be limit
                if symbol_quote.ask_price < 1:
                    price_type = order.PriceType.LIMIT
                    # Set limit price
                    limit_price = round(symbol_quote.ask_price + 0.01, 2)

            printAndDiscord(
                f"{key} {orderObj.get_action()}ing {orderObj.get_amount()} {ticker} @ {price_type.value}",
                loop,
            )
            try:
                print(chase_obj.get_account_numbers())
                # For each account number "mask" attached to "Chase_#" complete the order
                for account in chase_obj.get_account_numbers(key):
                    target_account_id = get_account_id(
                        all_accounts.account_connectors, account
                    )
                    # If DRY is True, don't actually make the transaction
                    if orderObj.get_dry():
                        printAndDiscord(
                            "Running in DRY mode. No transactions will be made.", loop
                        )

                    if orderObj.get_action().capitalize() == "Buy":
                        order_type = order.OrderSide.BUY
                    else:
                        # Reset to market for selling
                        price_type = order.PriceType.MARKET
                        order_type = order.OrderSide.SELL
                    chase_order = order.Order(ch_session)
                    messages = chase_order.place_order(
                        account_id=target_account_id,
                        quantity=int(orderObj.get_amount()),
                        price_type=price_type,
                        symbol=ticker,
                        duration=order.Duration.DAY,
                        order_type=order_type,
                        dry_run=orderObj.get_dry(),
                        limit_price=limit_price,
                    )
                    print("The order verification produced the following messages: ")
                    if orderObj.get_dry():
                        pprint.pprint(messages["ORDER PREVIEW"])
                        printAndDiscord(
                            (
                                f"{key} account {account}: The order verification was "
                                + (
                                    "successful"
                                    if messages["ORDER PREVIEW"]
                                    not in ["", "No order preview page found."]
                                    else "unsuccessful"
                                )
                            ),
                            loop,
                        )
                        if (
                            messages["ORDER INVALID"]
                            != "No invalid order message found."
                        ):
                            printAndDiscord(
                                f"{key} account {account}: The order verification produced the following messages: {messages['ORDER INVALID']}",
                                loop,
                            )
                    else:
                        pprint.pprint(messages["ORDER CONFIRMATION"])
                        printAndDiscord(
                            (
                                f"{key} account {account}: The order verification was "
                                + (
                                    "successful"
                                    if messages["ORDER CONFIRMATION"]
                                    not in [
                                        "",
                                        "No order confirmation page found. Order Failed.",
                                    ]
                                    else "unsuccessful"
                                )
                            ),
                            loop,
                        )
                        if (
                            messages["ORDER INVALID"]
                            != "No invalid order message found."
                        ):
                            printAndDiscord(
                                f"{key} account {account}: The order verification produced the following messages: {messages['ORDER INVALID']}",
                                loop,
                            )
            except Exception as e:
                printAndDiscord(f"{key} {account}: Error submitting order: {e}", loop)
                print(traceback.format_exc())
                continue
    ch_session.close_browser()
    printAndDiscord(
        "All Chase transactions complete",
        loop,
    )
