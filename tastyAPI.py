import os
import json
import asyncio
import aiohttp
from dataclasses import dataclass
from typing import Optional
from decimal import Decimal as D
from tastytrade.order import (Order, OrderDetails, OrderPriceEffect,
                                     OrderType, TimeInForce)
from tastytrade.session import Session
from tastytrade.account import TradingAccount
from tastytrade.streamer import (DataStreamer, EventType)
from dotenv import load_dotenv

class rsaSession(Session):

    def is_active(self):
        return super().is_valid()


@dataclass
class Equity:
    action: str = None
    ticker: Optional[str] = None
    quantity: int = 1

    def to_tasty_json(self):
        res = {
            'action': self.action,
            'instrument-type': 'Equity',
            'symbol': self.ticker,
            'quantity': self.quantity
        }
        return res


async def day_trade_check(session, acct, cash_balance):
    if acct.is_margin and cash_balance <= 25000:
        api_url = 'https://api.tastyworks.com'
        url = f'{api_url}/accounts/{acct.account_number}/trading-status'
        async with aiohttp.request('GET', url, headers=session.get_request_headers()) as response:
            if response.status != 200:
                raise Exception('Could not get trading accounts trading-status from Tastyworks...')
            data = (await response.json())['data']
            print(f"Tastytrade account {acct.account_number}: day trade count is {int(data['day-trade-count'])}.")
        if int(data['day-trade-count']) > 3:
            return False
        else:
            return True
    else:
        return True


def order_setup(order_type, stock_price, stock, amount):
    if order_type == ['Market', 'Debit', 'Buy to Open']:
        action = 'Buy to Open'
        details = OrderDetails(
                type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                price_effect=OrderPriceEffect.DEBIT,
                price=stock_price,
                source=stock)
        new_order = Order(details)
    elif order_type == ['Limit', 'Debit', 'Buy to Open']:
        action = 'Buy to Open'
        details = OrderDetails(
                type=OrderType.LIMIT,
                time_in_force=TimeInForce.DAY,
                price_effect=OrderPriceEffect.DEBIT,
                price=stock_price,
                source=stock)
        new_order = Order(details)
    elif order_type == ['Market', 'Credit', 'Sell to Close']:
        action = 'Sell to Close'
        details = OrderDetails(
            type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            price=stock_price,
            price_effect=OrderPriceEffect.CREDIT)
        new_order = Order(details)
    else:
        action = 'Sell to Close'
        details = OrderDetails(
            type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            price=stock_price,
            price_effect=OrderPriceEffect.CREDIT)
        new_order = Order(details)

    leg = Equity(
            action=action,
            ticker=stock,
            quantity=amount)
    new_order.add_leg(leg)
    return new_order


def tastytrade_init():
    try:
        load_dotenv()
        # Import Tastytrade account
        if not os.getenv("TASTYTRADE_USERNAME") or not os.getenv("TASTYTRADE_PASSWORD"):
            print("Robinhood not found, skipping...")
            return None
        TASTYTRADE_USERNAME = os.environ["TASTYTRADE_USERNAME"]
        TASTYTRADE_PASSWORD = os.environ["TASTYTRADE_PASSWORD"]
        # Log in to Tastytrade account
        print("Logging in to Tastytrade...")
        tt = rsaSession(TASTYTRADE_USERNAME, TASTYTRADE_PASSWORD)
        print("Logged in to Tastytrade!")
        return tt
    except Exception as e:
        print(f'Error logging in to Tastytrade: {e}')
        return None


async def tastytrade_holdings(tt, ctx):
    print()
    print("==============================")
    print("Tastytrade Holdings")
    print("==============================")
    print()
    if tt is None:
        print("Error: No Tastytrade account")
        return None
    accounts = await TradingAccount.get_accounts(tt)
    all_account_balance = 0
    for acct in accounts:
        balances = await acct.get_balance(tt)
        cash_balance = (balances['cash-balance'])
        all_account_balance += D(cash_balance)
        positions = await acct.get_positions(tt)
        stocks = []
        amounts = []
        current_price = []
        if len(positions) == 1:
           stocks.append(positions[0]['symbol'])
           amounts.append(positions[0]['quantity'])
           current_price.append(positions[0]['average-daily-market-close-price'])
        else:
            for stock in positions:
                stocks.append(stock['symbol'])
                amounts.append(stock['quantity'])
                current_price.append(stock['average-daily-market-close-price'])
        current_value = []
        for value in stocks:
            i = stocks.index(value)
            temp_value = round((float(amounts[i]) * float(current_price[i])), 2)
            current_value.append(temp_value)
        print(f"Holdings on Tastytrade account {acct.account_number}")
        if ctx:
                await ctx.send(f"Holdings on Tastytrade account {acct.account_number}")
        for position in stocks:
            i = stocks.index(position)
            print(f"{position}: {amounts[i]} @ ${current_price[i]} = ${current_value[i]}")
            if ctx:
                await ctx.send(f"{position}: {amounts[i]} @ ${current_price[i]} = ${current_value[i]}")
        print(f'Account cash balance is {cash_balance}.')
        if ctx:
            await ctx.send(f"Account cash balance is {cash_balance}.")
    print(f'All accounts cash balance is {all_account_balance}.')
    if ctx:
        await ctx.send(f"All accounts cash balance is {all_account_balance}.")


async def tastytrade_transaction(tt, action, stock, amount, price, time, DRY=True, ctx=None):
    print()
    print("==============================")
    print("Tastytrade")
    print("==============================")
    print()
    # Streamer takes a list for an argument
    json_response = {}
    stock_list = []
    stock_list.append(stock)
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
    accounts = await TradingAccount.get_accounts(tt)
    streamer = await DataStreamer.create(tt)
    for index, acct in enumerate(accounts):
        if not DRY:
            balances = await acct.get_balance(tt)
            cash_balance = float(balances['cash-balance'])
            day_trade_ok = await day_trade_check(tt, acct, cash_balance)
            if day_trade_ok:
                stock_limit = await streamer.stream(EventType.PROFILE, stock_list)
                stock_quote = await streamer.stream(EventType.QUOTE, stock_list)
                if all_amount:
                        results = await accounts[index].get_positions(tt)
                        for result in results:
                            if stock == result['symbol']:
                                amount = float(result['quantity'])
                if action == 'buy':
                    order_type = ['Market', 'Debit', 'Buy to Open']
                    stock_limit = D(stock_limit[0].highLimitPrice)
                    if stock_limit.is_nan():
                        stock_price = D(stock_quote[0].askPrice)
                    else:
                        stock_price = stock_limit
                    new_order = order_setup(order_type, stock_price, stock, amount)
                elif action == 'sell':
                    order_type = ['Market', 'Credit', 'Sell to Close']
                    stock_limit = D(stock_limit[0].lowLimitPrice)
                    if stock_limit.is_nan():
                        stock_price = D(stock_quote[0].bidPrice)
                    else:
                        stock_price = stock_limit
                    new_order = order_setup(order_type, stock_price, stock, amount)
                try:
                    json_response = await accounts[index].execute_order(new_order, tt, dry_run=DRY)
                    if json_response != {}:
                        if json_response['order']['status'] == 'Routed':
                            print(f"Tastytrade account {acct.account_number}: {action} {amount} of {stock}")
                            if ctx:
                                await ctx.send(f"Tastytrade account {acct.account_number}: {action} {amount} of {stock}")
                            await asyncio.sleep(2)
                        else:
                            print(f"Tastytrade account {acct.account_number} Error: {error}")
                            if ctx:
                                await ctx.send(f"Tastytrade account {acct.account_number} Error: {error}")
                except Exception as error_json:
                    error_json = str(error_json)
                    error = error_json.split(':')
                    error_string = ''
                    count = 0
                    for char in error_json:
                        if char == ':' and count == 0:
                            count += 1
                        elif count > 0:
                            error_string += char
                    
                    if error[0] == 'Unknown remote error 422' or error[0] in 'Order execution failed ':
                        print("Tastytrade: Error placing MARKET order trying LIMIT...")
                        if ctx:
                            await ctx.send("Tastytrade: Error placing MARKET order trying LIMIT...")
                        stock_limit = await streamer.stream(EventType.PROFILE, stock_list)
                        stock_quote = await streamer.stream(EventType.QUOTE, stock_list)
                        if all_amount:
                            results = await accounts[index].get_positions(tt)
                            for result in results:
                                if stock == result['symbol']:
                                    amount = float(result['quantity'])
                        if action == 'buy':
                            stock_limit = D(stock_limit[0].highLimitPrice)
                            if stock_limit.is_nan():
                                stock_price = D(stock_quote[0].askPrice)
                                print(f'Tastytrade Ticker {stock} ask price is: ${round(stock_price, 2)}')
                            else:
                                stock_price = stock_limit
                                print(f'Tastytrade Ticker {stock} high limit price is: ${round(stock_price, 2)}')
                            order_type = ['Market', 'Debit', 'Buy to Open']
                            new_order = order_setup(order_type, stock_price, stock, amount)
                        elif action == 'sell':
                            stock_limit = D(stock_limit[0].lowLimitPrice)
                            if stock_limit.is_nan():
                                stock_price = D(stock_quote[0].bidPrice)
                                print(f'Tastytrade Ticker {stock} low bid price is: ${round(stock_price, 2)}')
                            else:
                                stock_price = stock_limit
                                print(f'Tastytrade Ticker {stock} low limit price is: ${round(stock_price, 2)}')
                            order_type = ['Market', 'Credit', 'Sell to Close']
                            new_order = order_setup(order_type, stock_price, stock, amount)
                        try:
                            json_response = await accounts[index].execute_order(new_order, tt, dry_run=DRY)
                        except Exception as error_json:
                            error_json = str(error_json)
                            error_string = ''
                            count = 0
                            for char in error_json:
                                if char == ':' and count == 0:
                                    count += 1
                                elif count > 0:
                                    error_string += char
                            error_json = json.loads(error_string)
                            error = error_json['error']['errors'][0]['message']
                            print(f"Tastytrade: {error}")
                            if ctx:
                                await ctx.send(f"Tastytrade: {error}")  
                    else:
                        error_json = json.loads(error_string)
                        error = error_json['error']['errors'][0]['message']
                        print(f"Tastytrade: Error occured placing order... {error}")
                        if ctx:
                            await ctx.send(f"Tastytrade: Error occured placing order... {error}")
                    if json_response != {}:
                        if json_response['order']['status'] == 'Routed':
                            print(f"Tastytrade account {acct.account_number}: {action} {amount} of {stock}")
                            if ctx:
                                await ctx.send(f"Tastytrade account {acct.account_number}: {action} {amount} of {stock}")
                            await asyncio.sleep(2)
                        else:
                            print(f"Tastytrade account {acct.account_number} Error: {error}")
                            if ctx:
                                   await ctx.send(f"Tastytrade account {acct.account_number} Error: {error}")
            else:
                print(f"Tastytrade account {acct.account_number}: day trade count is >= 3 skipping...")
                print("More than 3 day trades will cause a strike on your account!")
                if ctx:
                    await ctx.send(f"Tastytrade account {acct.account_number}: day trade count is >= 3 skipping...")
                    await ctx.send("More than 3 day trades will cause a strike on your account!")
            await asyncio.sleep(2)
        else:
            print(f"Tastytrade: Running in DRY mode. Transaction would've been: {action} {amount} of {stock}")
            if ctx:
                await ctx.send(f"Tastytrade: Running in DRY mode. Transaction would've been: {action} {amount} of {stock}")
    await streamer.close()
