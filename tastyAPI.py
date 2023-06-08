import os
import asyncio
from decimal import Decimal as D
from tastytrade.order import (NewOrder, OrderAction, OrderTimeInForce,
                              OrderType, PriceEffect)
from tastytrade.session import Session
from tastytrade.dxfeed.event import EventType
from tastytrade.account import Account
from tastytrade.instruments import Equity
from tastytrade.streamer import DataStreamer
from tastytrade.utils import TastytradeError as TE
from dotenv import load_dotenv


def day_trade_check(tt, acct, cash_balance):
    trading_status = acct.get_trading_status(tt)
    day_trade_count = trading_status.day_trade_count
    if acct.margin_or_cash == 'Margin' and cash_balance <= 25000:
        print(f"Tastytrade account {acct.account_number}: day trade count is {day_trade_count}.")
        return not bool(day_trade_count > 3)
    return True


def order_setup(tt, order_type, stock_price, stock, amount):
    symbol = Equity.get_equity(tt, stock)
    if order_type == ['Market', 'Debit', 'Buy to Open']:
        leg = symbol.build_leg(D(amount), OrderAction.BUY_TO_OPEN)
        new_order = NewOrder(
                            time_in_force=OrderTimeInForce.DAY,
                            order_type=OrderType.MARKET,
                            legs=[leg],
                            price_effect=PriceEffect.DEBIT)
    elif order_type == ['Limit', 'Debit', 'Buy to Open']:
        leg = symbol.build_leg(D(amount), OrderAction.BUY_TO_OPEN)
        new_order = NewOrder(
                            time_in_force=OrderTimeInForce.DAY,
                            order_type=OrderType.LIMIT,
                            legs=[leg],
                            price=stock_price,
                            price_effect=PriceEffect.DEBIT)
    elif order_type == ['Market', 'Credit', 'Sell to Close']:
        leg = symbol.build_leg(D(amount), OrderAction.SELL_TO_CLOSE)
        new_order = NewOrder(
                            time_in_force=OrderTimeInForce.DAY,
                            order_type=OrderType.MARKET,
                            legs=[leg],
                            price_effect=PriceEffect.CREDIT)
    else:
        leg = symbol.build_leg(D(amount), OrderAction.SELL_TO_CLOSE)
        new_order = NewOrder(
                            time_in_force=OrderTimeInForce.DAY,
                            order_type=OrderType.LIMIT,
                            legs=[leg],
                            price=stock_price,
                            price_effect=PriceEffect.CREDIT)
    return new_order


def tastytrade_init():
    try:
        load_dotenv()
        # Import Tastytrade account
        if not os.getenv("TASTYTRADE_USERNAME") or not os.getenv("TASTYTRADE_PASSWORD"):
            print("Tastytrade not found, skipping...")
            return None
        TASTYTRADE_USERNAME = os.environ["TASTYTRADE_USERNAME"]
        TASTYTRADE_PASSWORD = os.environ["TASTYTRADE_PASSWORD"]
        # Log in to Tastytrade account
        print("Logging in to Tastytrade...")
        tt = Session(TASTYTRADE_USERNAME, TASTYTRADE_PASSWORD)
        print("Logged in to Tastytrade!")
        return tt
    except Exception as e:
        print(f'Error logging in to Tastytrade: {e}')
        return None


def tastytrade_holdings(tt, ctx, loop=None):
    print()
    print("==============================")
    print("Tastytrade Holdings")
    print("==============================")
    print()
    if tt is None:
        print("Error: No Tastytrade account")
        return None
    accounts = Account.get_accounts(tt)
    all_account_balance = 0
    for acct in accounts:
        balances = acct.get_balances(tt)
        cash_balance = (balances['cash-balance'])
        all_account_balance += D(cash_balance)
        positions = acct.get_positions(tt)
        stocks = []
        amounts = []
        current_price = []
        for stock in positions:
            stocks.append(stock.symbol)
            amounts.append(stock.quantity)
            current_price.append(stock.average_daily_market_close_price)
        current_value = []
        for value in stocks:
            i = stocks.index(value)
            temp_value = round((float(amounts[i]) * float(current_price[i])), 2)
            current_value.append(temp_value)
        message = f"Holdings on Tastytrade account {acct.account_number}"
        print(message)
        if ctx and loop:
            asyncio.ensure_future(ctx.send(message), loop=loop)
        for position in stocks:
            i = stocks.index(position)
            message = f"{position}: {amounts[i]} @ ${current_price[i]} = ${current_value[i]}"
            print(message)
            if ctx and loop:
                asyncio.ensure_future(ctx.send(message), loop=loop)
        message = f'Account cash balance is ${round(float(cash_balance), 2)}.'
        print(message)
        if ctx and loop:
            asyncio.ensure_future(ctx.send(message), loop=loop)
    message = f'All accounts cash balance is ${round(float(all_account_balance), 2)}.'
    print(message)
    if ctx and loop:
        asyncio.ensure_future(ctx.send(message), loop=loop)


async def tastytrade_execute(tt, action, stock, amount, price, time, DRY=True, ctx=None, loop=None):
    print()
    print("==============================")
    print("Tastytrade")
    print("==============================")
    print()
    # Streamer takes a list for an argument
    stock_list = [stock]
    action = action.lower()
    stock = stock.upper()
    if amount == "all" and action == "sell":
        all_amount = True
    elif amount < 1:
        amount = float(amount)
    else:
        amount = int(amount)
        all_amount = False
    # Make sure init didn't return None
    if tt is None:
        print("Error: No Tastytrade account")
        return None
    accounts = Account.get_accounts(tt)
    for index, acct in enumerate(accounts):
        try:
            if not DRY:
                balances = acct.get_balances(tt)
                cash_balance = float(balances['cash-balance'])
                day_trade_ok = day_trade_check(tt, acct, cash_balance)
                if day_trade_ok:
                    if all_amount:
                        results = accounts[index].get_positions(tt)
                        for result in results:
                            if stock == result.symbol:
                                amount = result.quantity
                    if action == 'buy':
                        order_type = ['Market', 'Debit', 'Buy to Open']
                        stock_price = 0
                        new_order = order_setup(tt, order_type, stock_price, stock, amount)
                    elif action == 'sell':
                        order_type = ['Market', 'Credit', 'Sell to Close']
                        stock_price = 0
                        new_order = order_setup(tt, order_type, stock_price, stock, amount)
                    placed_order = accounts[index].place_order(tt, new_order, dry_run=DRY)
                    if placed_order.order.status.value == "Routed":
                        message = f"Tastytrade account {acct.account_number}: {action} {amount} of {stock}"
                        print(message)
                        if ctx and loop:
                            asyncio.ensure_future(ctx.send(message), loop=loop)
                    elif placed_order.order.status.value == "Rejected":
                        message = f"Tastytrade account {acct.account_number} Error: Order Rejected! Trying LIMIT order."
                        streamer = await DataStreamer.create(tt)
                        stock_limit = await streamer.oneshot(EventType.PROFILE, stock_list)
                        print(message)
                        if ctx:
                            asyncio.ensure_future(ctx.send(message), loop=loop)
                        if all_amount:
                            results = accounts[index].get_positions(tt)
                            for result in results:
                                if stock == result['symbol']:
                                    amount = float(result['quantity'])
                        if action == 'buy':
                            stock_limit = D(stock_limit[0].highLimitPrice)
                            if stock_limit.is_nan():
                                stock_quote = await streamer.oneshot(EventType.QUOTE, stock_list)
                                stock_price = D(stock_quote[0].askPrice)
                                print(f'Tastytrade Ticker {stock} ask price is: ${round(stock_price, 2)}')
                            else:
                                stock_price = stock_limit
                                print(f'Tastytrade Ticker {stock} high limit price is: ${round(stock_price, 2)}')
                            order_type = ['Market', 'Debit', 'Buy to Open']
                            new_order = order_setup(tt, order_type, stock_price, stock, amount)
                        elif action == 'sell':
                            stock_limit = D(stock_limit[0].lowLimitPrice)
                            if stock_limit.is_nan():
                                stock_quote = await streamer.oneshot(EventType.QUOTE, stock_list)
                                stock_price = D(stock_quote[0].bidPrice)
                                print(f'Tastytrade Ticker {stock} low bid price is: ${round(stock_price, 2)}')
                            else:
                                stock_price = stock_limit
                                print(f'Tastytrade Ticker {stock} low limit price is: ${round(stock_price, 2)}')
                            order_type = ['Market', 'Credit', 'Sell to Close']
                            new_order = order_setup(tt, order_type, stock_price, stock, amount)
                        placed_order = accounts[index].place_order(tt, new_order, dry_run=DRY)
                        if placed_order.order.status.value == "Routed":
                            message = f"Tastytrade account {acct.account_number}: {action} {amount} of {stock}"
                            print(message)
                            if ctx and loop:
                                asyncio.ensure_future(ctx.send(message), loop=loop)
                        elif placed_order.order.status.value == "Rejected":
                            message = f"Tastytrade account {acct.account_number} Error: Order Rejected! Skipping Account."
                            print(message)
                            if ctx:
                                asyncio.ensure_future(ctx.send(message), loop=loop)
                    else:
                        message_one = f"Tastytrade: Error occured placing order: {placed_order.id} on account {acct.account_number} with the following {action} {amount} of {stock}"
                        message_two = f"Tastytrade: Returned order status {placed_order.order.status.value}"
                        print(message_one)
                        print(message_two)
                        if ctx and loop:
                            asyncio.ensure_future(ctx.send(message_one), loop=loop)
                            asyncio.ensure_future(ctx.send(message_two), loop=loop)
                else:
                    message_one = f"Tastytrade account {acct.account_number}: day trade count is >= 3 skipping..."
                    message_two = "More than 3 day trades will cause a strike on your account!"
                    print(message_one)
                    print(message_two)
                    if ctx and loop:
                        asyncio.ensure_future(ctx.send(message_one), loop=loop)
                        asyncio.ensure_future(ctx.send(message_two), loop=loop)
            else:
                # DRY Run
                if action == 'buy':
                    order_type = ['Market', 'Debit', 'Buy to Open']
                else:
                    order_type = ['Market', 'Credit', 'Sell to Close']
                streamer = await DataStreamer.create(tt)
                stock_quote = await streamer.oneshot(EventType.QUOTE, stock_list)
                stock_price = D(stock_quote[0].bidPrice)
                new_order = order_setup(tt, order_type, stock_price, stock, amount)
                placed_order = accounts[index].place_order(tt, new_order, dry_run=DRY)
                if placed_order.order.status.value == "Received":
                    message = f"Tastytrade: Running in DRY mode. Transaction would've been: {placed_order.order.order_type.value} {placed_order.order.size} of {placed_order.order.underlying_symbol}"
                    print(message)
                    if ctx and loop:
                        asyncio.ensure_future(ctx.send(message), loop=loop)
                else:
                    message = "Tastytrade: Running in DRY mode. Transaction did not complete!"
                    print(message)
                    if ctx and loop:
                        asyncio.ensure_future(ctx.send(message), loop=loop)
        except TE as te:
            message = f"Tastytrade: Error: {te}"
            print(message)
            if ctx and loop:
                asyncio.ensure_future(ctx.send(message), loop=loop)


def tastytrade_transaction(tt, action, stock, amount, price, time, DRY=True, ctx=None, loop=None):
    asyncio.run(tastytrade_execute(tt, action, stock, amount, price, time, DRY, ctx, loop))
