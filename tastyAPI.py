# Donald Ryan Gullett
# TastyTrade API

import asyncio
import os
import traceback
from decimal import Decimal as D

from dotenv import load_dotenv
from helperAPI import Brokerage, printAndDiscord, printHoldings
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
from tastytrade.utils import TastytradeError as TE


def day_trade_check(tt: Session, acct: Account, cash_balance):
    trading_status = acct.get_trading_status(tt)
    day_trade_count = trading_status.day_trade_count
    if acct.margin_or_cash == "Margin" and cash_balance <= 25000:
        print(
            f"Tastytrade account {acct.account_number}: day trade count is {day_trade_count}."
        )
        return not bool(day_trade_count > 3)
    return True


def order_setup(tt: Session, order_type, stock_price, stock, amount):
    symbol = Equity.get_equity(tt, stock)
    if order_type == ["Market", "Debit", "Buy to Open"]:
        leg = symbol.build_leg(D(amount), OrderAction.BUY_TO_OPEN)
        new_order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.MARKET,
            legs=[leg],
            price_effect=PriceEffect.DEBIT,
        )
    elif order_type == ["Limit", "Debit", "Buy to Open"]:
        leg = symbol.build_leg(D(amount), OrderAction.BUY_TO_OPEN)
        new_order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.LIMIT,
            legs=[leg],
            price=stock_price,
            price_effect=PriceEffect.DEBIT,
        )
    elif order_type == ["Market", "Credit", "Sell to Close"]:
        leg = symbol.build_leg(D(amount), OrderAction.SELL_TO_CLOSE)
        new_order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.MARKET,
            legs=[leg],
            price_effect=PriceEffect.CREDIT,
        )
    else:
        leg = symbol.build_leg(D(amount), OrderAction.SELL_TO_CLOSE)
        new_order = NewOrder(
            time_in_force=OrderTimeInForce.DAY,
            order_type=OrderType.LIMIT,
            legs=[leg],
            price=stock_price,
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
    accounts = os.environ["TASTYTRADE"].strip().split(",") if TASTYTRADE_EXTERNAL is None else TASTYTRADE_EXTERNAL.strip().split(",")
    tasty_obj = Brokerage("Tastytrade")
    # Log in to Tastytrade account
    print("Logging in to Tastytrade...")
    for account in accounts:
        index = accounts.index(account) + 1
        account = account.strip().split(":")
        name = f"Tastytrade {index}"
        try:
            tasty = Session(account[0], account[1])
            tasty_obj.set_logged_in_object(name, tasty)
            an = Account.get_accounts(tasty)
            for acct in an:
                print(type(acct))
                tasty_obj.set_account_number(name, acct.account_number)
                tasty_obj.set_account_totals(name, acct.account_number, acct.get_balances(tasty)["cash-balance"])
            print("Logged in to Tastytrade!")
        except Exception as e:
            print(f"Error logging in to {name}: {e}")
            return None
    return tasty_obj


def tastytrade_holdings(tt_o: Brokerage, ctx=None, loop=None):
    for key in tt_o.get_account_numbers():
        obj: Session = tt_o.get_logged_in_objects(key)
        for index, account in enumerate(Account.get_accounts(obj)):
            try:
                an = tt_o.get_account_numbers(key)[index]
                positions = account.get_positions(obj)
                for stock in positions:
                    tt_o.set_holdings(key, an, stock.symbol, stock.quantity, stock.average_daily_market_close_price)
            except Exception as e:
                printAndDiscord(f"{key}: Error getting account holdings: {e}", ctx, loop)
                print(traceback.format_exc())
                continue
        printHoldings(tt_o, ctx, loop)


async def tastytrade_execute(
        tt_o: Brokerage, action, stock, amount, price, time, DRY=True, ctx=None, loop=None
):
    print()
    print("==============================")
    print("Tastytrade")
    print("==============================")
    print()
    action = action.lower()
    stock = [x.upper() for x in stock]
    if amount == "all" and action == "sell":
        all_amount = True
    elif amount < 1:
        amount = float(amount)
    else:
        amount = int(amount)
        all_amount = False
    for s in stock:
        for key in tt_o.get_account_numbers():
            obj: Session = tt_o.get_logged_in_objects(key)
            stock_list = [s]
            printAndDiscord(f"{key}: {action}ing {amount} of {s}", ctx, loop)
            accounts = Account.get_accounts(obj)
            for i, acct in enumerate(accounts):
                try:
                    if not DRY:
                        balances = acct.get_balances(obj)
                        cash_balance = float(balances["cash-balance"])
                        day_trade_ok = day_trade_check(obj, acct, cash_balance)
                        if day_trade_ok:
                            if all_amount:
                                results = accounts[i].get_positions(obj)
                                for result in results:
                                    if s == result.symbol:
                                        amount = result.quantity
                            if action == "buy":
                                order_type = ["Market", "Debit", "Buy to Open"]
                                stock_price = 0
                                new_order = order_setup(
                                    obj, order_type, stock_price, s, amount
                                )
                            elif action == "sell":
                                order_type = ["Market", "Credit", "Sell to Close"]
                                stock_price = 0
                                new_order = order_setup(
                                    obj, order_type, stock_price, s, amount
                                )
                            placed_order = accounts[i].place_order(
                                obj, new_order, dry_run=DRY
                            )
                            if placed_order.order.status.value == "Routed":
                                printAndDiscord(
                                    f"{key} {acct.account_number}: {action} {amount} of {s}",
                                    ctx,
                                    loop,
                                )
                            elif placed_order.order.status.value == "Rejected":
                                streamer = await DataStreamer.create(obj)
                                stock_limit = await streamer.oneshot(
                                    EventType.PROFILE, stock_list
                                )
                                printAndDiscord(
                                    f"{key} {acct.account_number} Error: Order Rejected! Trying LIMIT order.",
                                    ctx,
                                    loop,
                                )
                                if all_amount:
                                    results = accounts[i].get_positions(obj)
                                    for result in results:
                                        if s == result["symbol"]:
                                            amount = float(result["quantity"])
                                if action == "buy":
                                    stock_limit = D(stock_limit[0].highLimitPrice)
                                    if stock_limit.is_nan():
                                        stock_quote = await streamer.oneshot(
                                            EventType.QUOTE, stock_list
                                        )
                                        stock_price = D(stock_quote[0].askPrice)
                                        print(
                                            f"Tastytrade Ticker {s} ask price is: ${round(stock_price, 2)}"
                                        )
                                    else:
                                        stock_price = stock_limit
                                        print(
                                            f"Tastytrade Ticker {s} high limit price is: ${round(stock_price, 2)}"
                                        )
                                    order_type = ["Market", "Debit", "Buy to Open"]
                                    new_order = order_setup(
                                        obj, order_type, stock_price, s, amount
                                    )
                                elif action == "sell":
                                    stock_limit = D(stock_limit[0].lowLimitPrice)
                                    if stock_limit.is_nan():
                                        stock_quote = await streamer.oneshot(
                                            EventType.QUOTE, stock_list
                                        )
                                        stock_price = D(stock_quote[0].bidPrice)
                                        print(
                                            f"Tastytrade Ticker {s} low bid price is: ${round(stock_price, 2)}"
                                        )
                                    else:
                                        stock_price = stock_limit
                                        print(
                                            f"Tastytrade Ticker {s} low limit price is: ${round(stock_price, 2)}"
                                        )
                                    order_type = ["Market", "Credit", "Sell to Close"]
                                    new_order = order_setup(
                                        obj, order_type, stock_price, s, amount
                                    )
                                placed_order = accounts[i].place_order(
                                    obj, new_order, dry_run=DRY
                                )
                                if placed_order.order.status.value == "Routed":
                                    printAndDiscord(
                                        f"{key} {acct.account_number}: {action} {amount} of {s}",
                                        ctx,
                                        loop,
                                    )
                                elif placed_order.order.status.value == "Rejected":
                                    printAndDiscord(
                                        f"{key} {acct.account_number} Error: Order Rejected! Skipping Account.",
                                        ctx,
                                        loop,
                                    )
                            else:
                                printAndDiscord(
                                    f"{key} {acct.account_number}: Error occured placing order: {placed_order.id} on account {acct.account_number} with the following {action} {amount} of {s}",
                                    ctx,
                                    loop,
                                )
                                printAndDiscord(
                                    f"{key} {acct.account_number}: Returned order status {placed_order.order.status.value}",
                                    ctx,
                                    loop,
                                )
                        else:
                            printAndDiscord(
                                f"{key} {acct.account_number}: day trade count is >= 3 skipping...",
                                ctx,
                                loop,
                            )
                            printAndDiscord(
                                "More than 3 day trades will cause a strike on your account!",
                                ctx,
                                loop,
                            )
                    else:
                        # DRY Run
                        if action == "buy":
                            order_type = ["Market", "Debit", "Buy to Open"]
                        else:
                            order_type = ["Market", "Credit", "Sell to Close"]
                        streamer = await DataStreamer.create(obj)
                        stock_quote = await streamer.oneshot(EventType.QUOTE, stock_list)
                        stock_price = D(stock_quote[0].bidPrice)
                        new_order = order_setup(obj, order_type, stock_price, s, amount)
                        placed_order = accounts[i].place_order(obj, new_order, dry_run=DRY)
                        if placed_order.order.status.value == "Received":
                            printAndDiscord(
                                f"{key} {acct.account_number}: Running in DRY mode. Transaction would've been: {placed_order.order.order_type.value} {placed_order.order.size} of {placed_order.order.underlying_symbol}",
                                ctx,
                                loop,
                            )
                        else:
                            printAndDiscord(
                                f"{key} {acct.account_number}: Running in DRY mode. Transaction did not complete!",
                                ctx,
                                loop,
                            )
                except TE as te:
                    printAndDiscord(
                        f"{key} {acct.account_number}: Error: {te}",
                        ctx,
                        loop,
                    )


def tastytrade_transaction(
    tt: Brokerage, action, stock, amount, price, time, DRY=True, ctx=None, loop=None
):
    asyncio.run(
        tastytrade_execute(tt, action, stock, amount, price, time, DRY, ctx, loop)
    )
