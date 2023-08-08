# Donald Ryan Gullett
# TastyTrade API

import asyncio
import os
import traceback
from decimal import Decimal as D

from dotenv import load_dotenv
from tastytrade.account import Account
from tastytrade.dxfeed.event import EventType
from tastytrade.instruments import Equity
from tastytrade.order import (
    NewOrder,
    OrderAction,
    OrderTimeInForce,
    OrderType,
    PriceEffect,
)
from tastytrade.session import Session
from tastytrade.streamer import DataStreamer

from helperAPI import Brokerage, printAndDiscord, printHoldings, stockOrder


def day_trade_check(tt: Session, acct: Account, cash_balance, ctx=None, loop=None):
    trading_status = acct.get_trading_status(tt)
    day_trade_count = trading_status.day_trade_count
    if (
        acct.margin_or_cash == "Margin"
        and float(cash_balance) <= 25000
        and day_trade_count > 3
    ):
        printAndDiscord(
            f"Tastytrade account {acct.account_number}: day trade count is {day_trade_count}. More than 3 day trades will cause a strike on your account!",
            ctx=ctx,
            loop=loop,
        )
        return False
    return True


def order_setup(tt: Session, order_type, stock_price, stock, amount):
    symbol = Equity.get_equity(tt, stock)
    if order_type[2] == "Buy to Open":
        leg = symbol.build_leg(D(amount), OrderAction.BUY_TO_OPEN)
        new_order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.MARKET,
            legs=[leg],
            price=stock_price if order_type[0] == "Limit" else None,
            price_effect=PriceEffect.DEBIT,
        )
    elif order_type[2] == "Sell to Close":
        leg = symbol.build_leg(D(amount), OrderAction.SELL_TO_CLOSE)
        new_order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.MARKET,
            legs=[leg],
            price=stock_price if order_type[0] == "Limit" else None,
            price_effect=PriceEffect.CREDIT,
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
                    name, acct.account_number, acct.get_balances(tasty)["cash-balance"]
                )
            print("Logged in to Tastytrade!")
        except Exception as e:
            print(f"Error logging in to {name}: {e}")
            return None
    return tasty_obj


def tastytrade_holdings(tt_o: Brokerage, ctx=None, loop=None):
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
                printAndDiscord(
                    f"{key}: Error getting account holdings: {e}", ctx, loop
                )
                print(traceback.format_exc())
                continue
        printHoldings(tt_o, ctx=ctx, loop=loop)


async def tastytrade_execute(
    tt_o: Brokerage, orderObj: stockOrder, ctx=None, loop=None
):
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
                ctx=ctx,
                loop=loop,
            )
            for i, acct in enumerate(tt_o.get_account_numbers(key)):
                try:
                    # Set order type
                    if orderObj.get_action() == "buy":
                        order_type = ["Market", "Debit", "Buy to Open"]
                    else:
                        order_type = ["Market", "Credit", "Sell to Close"]
                    # Set stock price
                    stock_price = 0
                    # Day trade check
                    balances = acct.get_balances(obj)
                    cash_balance = float(balances["cash-balance"])
                    if day_trade_check(obj, acct, cash_balance):
                        # Place order
                        new_order = order_setup(
                            obj, order_type, stock_price, s, orderObj.get_amount()
                        )
                        placed_order = accounts[i].place_order(
                            obj, new_order, dry_run=orderObj.get_dry()
                        )
                        # Check order status
                        if placed_order.order.status.value == "Routed":
                            message = f"{key} {acct.account_number}: {orderObj.get_action()} {orderObj.get_amount()} of {s}"
                            if orderObj.get_dry():
                                message = f"{key} Running in DRY mode. Transaction would've been: {orderObj.get_action()} {orderObj.get_amount()} of {s}"
                            printAndDiscord(message, ctx=ctx, loop=loop)
                        elif placed_order.order.status.value == "Rejected":
                            # Retry with limit order
                            streamer = await DataStreamer.create(obj)
                            stock_limit = await streamer.oneshot(EventType.PROFILE, [s])
                            stock_quote = await streamer.oneshot(EventType.QUOTE, [s])
                            printAndDiscord(
                                f"{key} {acct.account_number} Error: Order Rejected! Trying Limit order...",
                                ctx=ctx,
                                loop=loop,
                            )
                            # Get limit price
                            if orderObj.get_action() == "buy":
                                stock_limit = D(stock_limit[0].highLimitPrice)
                                stock_price = (
                                    D(stock_quote[0].askPrice)
                                    if stock_limit.is_nan()
                                    else stock_limit
                                )
                                order_type = ["Market", "Debit", "Buy to Open"]
                            elif orderObj.get_action() == "sell":
                                stock_limit = D(stock_limit[0].lowLimitPrice)
                                stock_price = (
                                    D(stock_quote[0].bidPrice)
                                    if stock_limit.is_nan()
                                    else stock_limit
                                )
                                order_type = ["Market", "Credit", "Sell to Close"]
                            print(f"{s} limit price is: ${round(stock_price, 2)}")
                            # Retry order
                            new_order = order_setup(
                                obj, order_type, stock_price, s, orderObj.get_amount()
                            )
                            placed_order = accounts[i].place_order(
                                obj, new_order, dry_run=orderObj.get_dry()
                            )
                            # Check order status
                            if placed_order.order.status.value == "Routed":
                                message = f"{key} {acct.account_number}: {orderObj.get_action()} {orderObj.get_amount()} of {s}"
                                if orderObj.get_dry():
                                    message = f"{key} Running in DRY mode. Transaction would've been: {orderObj.get_action()} {orderObj.get_amount()} of {s}"
                                printAndDiscord(message, ctx=ctx, loop=loop)
                            elif placed_order.order.status.value == "Rejected":
                                printAndDiscord(
                                    f"{key} {acct.account_number}: Error: Limit Order Rejected! Skipping Account...",
                                    ctx=ctx,
                                    loop=loop,
                                )
                        printAndDiscord(
                            f"{key} {acct.account_number}: Error placing order: {placed_order.order.id} on account {acct.account_number}: {placed_order.order.status.value}",
                            ctx=ctx,
                            loop=loop,
                        )
                except Exception as te:
                    printAndDiscord(
                        f"{key} {acct.account_number}: Error: {te}", ctx=ctx, loop=loop
                    )


def tastytrade_transaction(tt: Brokerage, orderObj: stockOrder, ctx=None, loop=None):
    asyncio.run(tastytrade_execute(tt_o=tt, orderObj=orderObj, ctx=ctx, loop=loop))
