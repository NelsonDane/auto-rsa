# Donald Ryan Gullett
# TastyTrade API

import asyncio
import os
import traceback
from decimal import Decimal as D

from dotenv import load_dotenv
from tastytrade import Session
from tastytrade.account import Account
from tastytrade.dxfeed import Profile, Quote
from tastytrade.instruments import Equity
from tastytrade.order import NewOrder, OrderAction, OrderTimeInForce, OrderType
from tastytrade.streamer import DXLinkStreamer
from tastytrade.utils import TastytradeError

from helperAPI import Brokerage, maskString, printAndDiscord, printHoldings, stockOrder


def order_setup(tt: Session, order_type, stock_price, stock, amount):
    symbol = Equity.get_equity(tt, stock)
    if order_type[2] == "Buy to Open":
        leg = symbol.build_leg(D(amount), OrderAction.BUY_TO_OPEN)
    elif order_type[2] == "Sell to Close":
        leg = symbol.build_leg(D(amount), OrderAction.SELL_TO_CLOSE)
    else:
        raise ValueError("Invalid order type")
    new_order = NewOrder(
        time_in_force=OrderTimeInForce.DAY,
        order_type=OrderType.MARKET,
        legs=[leg],
        price=stock_price if order_type[0] == "Limit" else None,
    )
    return new_order


def tastytrade_init(TASTYTRADE_EXTERNAL=None):
    # Initialize .env file
    load_dotenv()
    # Import Tastytrade account
    if not os.getenv("TASTYTRADE") and TASTYTRADE_EXTERNAL is None:
        print("Tastytrade not found, skipping...")
        return None
    accounts = (
        os.environ["TASTYTRADE"].strip().split(",")
        if TASTYTRADE_EXTERNAL is None
        else TASTYTRADE_EXTERNAL.strip().split(",")
    )
    tasty_obj = Brokerage("Tastytrade")
    # Log in to Tastytrade account
    print("Logging in to Tastytrade...")
    for account in accounts:
        index = accounts.index(account) + 1
        account = account.strip().split(":")
        name = f"Tastytrade {index}"
        try:
            tasty = Session(account[0], account[1])
            tasty_obj.set_logged_in_object(name, tasty, "session")
            an = Account.get_accounts(tasty)
            tasty_obj.set_logged_in_object(name, an, "accounts")
            for acct in an:
                tasty_obj.set_account_number(name, acct.account_number)
                tasty_obj.set_account_totals(
                    name, acct.account_number, acct.get_balances(tasty).cash_balance
                )
            print("Logged in to Tastytrade!")
        except Exception as e:
            traceback.print_exc()
            print(f"Error logging in to {name}: {e}")
            return None
    return tasty_obj


def tastytrade_holdings(tt_o: Brokerage, loop=None):
    for key in tt_o.get_account_numbers():
        obj: Session = tt_o.get_logged_in_objects(key, "session")
        for index, account in enumerate(tt_o.get_logged_in_objects(key, "accounts")):
            try:
                an = tt_o.get_account_numbers(key)[index]
                positions = account.get_positions(obj)
                for pos in positions:
                    tt_o.set_holdings(
                        key,
                        an,
                        pos.symbol,
                        pos.quantity,
                        pos.average_daily_market_close_price,
                    )
            except Exception as e:
                printAndDiscord(f"{key}: Error getting account holdings: {e}", loop)
                print(traceback.format_exc())
                continue
    printHoldings(tt_o, loop=loop)


async def tastytrade_execute(tt_o: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Tastytrade")
    print("==============================")
    print()
    for s in orderObj.get_stocks():
        for key in tt_o.get_account_numbers():
            obj: Session = tt_o.get_logged_in_objects(key, "session")
            accounts: Account = tt_o.get_logged_in_objects(key, "accounts")
            printAndDiscord(
                f"{key}: {orderObj.get_action()}ing {orderObj.get_amount()} of {s}",
                loop=loop,
            )
            for i, acct in enumerate(tt_o.get_account_numbers(key)):
                print_account = maskString(acct)
                try:
                    acct: Account = accounts[i]
                    # Set order type
                    if orderObj.get_action() == "buy":
                        order_type = ["Market", "Debit", "Buy to Open"]
                    else:
                        order_type = ["Market", "Credit", "Sell to Close"]
                    # Set stock price
                    stock_price = 0
                    # Skip day trade check for now
                    # Place order
                    new_order = order_setup(
                        obj, order_type, stock_price, s, orderObj.get_amount()
                    )
                    try:
                        placed_order = acct.place_order(
                            obj, new_order, dry_run=orderObj.get_dry()
                        )
                        order_status = placed_order.order.status.value
                    except Exception as e:
                        printAndDiscord(
                            f"{key} {print_account}: Error placing order: {e}",
                            loop=loop,
                        )
                        continue
                    # Check order status
                    if order_status in ["Received", "Routed"]:
                        message = f"{key} {print_account}: {orderObj.get_action()} {orderObj.get_amount()} of {s} Order: {placed_order.order.id} Status: {order_status}"
                        if orderObj.get_dry():
                            message = f"{key} Running in DRY mode. Transaction would've been: {orderObj.get_action()} {orderObj.get_amount()} of {s}"
                        printAndDiscord(message, loop=loop)
                    elif order_status == "Rejected":
                        # Retry with limit order
                        streamer = await DXLinkStreamer.create(obj)
                        stock_limit = await streamer.subscribe(Profile, [s])
                        stock_quote = await streamer.subscribe(Quote, [s])
                        stock_limit = await streamer.get_event(Profile)
                        stock_quote = await streamer.get_event(Quote)
                        printAndDiscord(
                            f"{key} {print_account} Error: {order_status} Trying Limit order...",
                            loop=loop,
                        )
                        # Get limit price
                        if orderObj.get_action() == "buy":
                            stock_limit = D(stock_limit.highLimitPrice)
                            stock_price = (
                                D(stock_quote.askPrice)
                                if stock_limit.is_nan()
                                else stock_limit
                            )
                            order_type = ["Market", "Debit", "Buy to Open"]
                        elif orderObj.get_action() == "sell":
                            stock_limit = D(stock_limit.lowLimitPrice)
                            stock_price = (
                                D(stock_quote.bidPrice)
                                if stock_limit.is_nan()
                                else stock_limit
                            )
                            order_type = ["Market", "Credit", "Sell to Close"]
                        print(f"{s} limit price is: ${round(stock_price, 2)}")
                        # Retry order
                        new_order = order_setup(
                            obj, order_type, stock_price, s, orderObj.get_amount()
                        )
                        placed_order = acct.place_order(
                            obj, new_order, dry_run=orderObj.get_dry()
                        )
                        # Check order status
                        if order_status in ["Received", "Routed"]:
                            message = f"{key} {print_account}: {orderObj.get_action()} {orderObj.get_amount()} of {s} Order: {placed_order.order.id} Status: {order_status}"
                            if orderObj.get_dry():
                                message = f"{key} Running in DRY mode. Transaction would've been: {orderObj.get_action()} {orderObj.get_amount()} of {s}"
                            printAndDiscord(message, loop=loop)
                        elif order_status == "Rejected":
                            # Only want this message if it fails both orders.
                            printAndDiscord(
                                f"{key} Error placing order: {placed_order.order.id} on account {print_account}: {order_status}",
                                loop=loop,
                            )
                except (TastytradeError, KeyError) as te:
                    printAndDiscord(f"{key} {print_account}: Error: {te}", loop=loop)
                    continue


def tastytrade_transaction(tt: Brokerage, orderObj: stockOrder, loop=None):
    asyncio.run(tastytrade_execute(tt_o=tt, orderObj=orderObj, loop=loop))
