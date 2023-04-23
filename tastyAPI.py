from dataclasses import dataclass, field
from typing import Optional
from datetime import date
import os
from decimal import Decimal as D
import asyncio

from tastytrade.order import (Order, OrderDetails, OrderPriceEffect,
                                     OrderType, TimeInForce)
from tastytrade.session import Session
from tastytrade.account import TradingAccount
from tastytrade.streamer import ( DataStreamer, EventType )
from time import sleep
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
        TASTY_USERNAME = os.environ["TASTYTRADE_USERNAME"]
        TASTY_PASSWORD = os.environ["TASTYTRADE_PASSWORD"]

        # Log in to Tastytrade account
        print("Logging in to Tastytrade...")
        tt = rsaSession(TASTY_USERNAME, TASTY_PASSWORD)
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
    for account in accounts:
        balances = await account.get_balance(tt)
        cash_balance = (balances['cash-balance'])
        all_account_balance += D(cash_balance)
        positions = await account.get_positions(tt)
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
        print(f"Holdings on Tastytrade account {account.account_number}")
        if ctx:
                await ctx.send(f"Holdings on Tastytrade account {account.account_number}")
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


async def tastytrade_transaction(tt_session, action, stock, amount, price, time, DRY=True, ctx=None):
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
    if tt_session is None:
        print("Error: No Tastytrade account")
        return None
    accounts = await TradingAccount.get_accounts(tt_session)
    streamer = await DataStreamer.create(tt_session)
    for index, acct in enumerate(accounts):
        if not DRY:
            stock_limit = await streamer.stream(EventType.PROFILE, stock_list)
            stock_quote = await streamer.stream(EventType.QUOTE, stock_list)
            
            if all_amount:
                    results = await accounts[index].get_positions(tt_session)
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
                json_response = await accounts[index].execute_order(new_order, tt_session, dry_run=DRY)
            except Exception as error_json:
                error_json = str(error_json)
                error = error_json.split(':')
                if error[0] == 'Unknown remote error 422' or error[0] in 'Order execution failed ':
                    print("Tastytrade: Error placing MARKET order trying LIMIT...")
                    if ctx:
                        await ctx.send("Tastytrade: Error placing MARKET order trying LIMIT...")
                    stock_limit = await streamer.stream(EventType.PROFILE, stock_list)
                    stock_quote = await streamer.stream(EventType.QUOTE, stock_list)
                    if all_amount:
                            results = await accounts[index].get_positions(tt_session)
                            for result in results:
                                if stock == result['symbol']:
                                    amount = float(result['quantity'])
                    if action == 'buy':
                        stock_limit = stock_limit[0].highLimitPrice
                        if stock_limit.is_nan():
                            stock_price = D(stock_quote[0].askPrice)
                            print(f'Tastyworks Ticker {stock} ask price is: ${round(stock_price, 2)}')
                        else:
                            stock_price = stock_limit
                            print(f'Tastyworks Ticker {stock} high limit price is: ${round(stock_price, 2)}')
                        order_type = ['Market', 'Debit', 'Buy to Open']
                        new_order = order_setup(order_type, stock_price, stock, amount)
                    elif action == 'sell':
                        stock_limit = D(stock_limit[0].lowLimitPrice)
                        if stock_limit.is_nan():
                            stock_price = D(stock_quote[0].bidPrice)
                            print(f'Tastyworks Ticker {stock} low bid price is: ${round(stock_price, 2)}')
                        else:
                            stock_price = stock_limit
                            print(f'Tastyworks Ticker {stock} low limit price is: ${round(stock_price, 2)}')
                        order_type = ['Market', 'Credit', 'Sell to Close']
                        new_order = order_setup(order_type, stock_price, stock, amount)
                         
                    try:
                        json_response = await accounts[index].execute_order(new_order, tt_session, dry_run=DRY)
                    except Exception as error_json:
                        print(f"Tastytrade: Error occured placing LIMIT order... {error_json}")
                        if ctx:
                            await ctx.send(f"Tastytrade: Error occured placing order... {error_json}")  
                else:
                    print(f"Tastytrade: Error occured placing order... {error_json}")
                    if ctx:
                        await ctx.send(f"Tastytrade: Error occured placing order... {error_json}")   
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
            print(f"Tastytrade: Running in DRY mode. Trasaction would've been: {action} {amount} of {stock}")
            if ctx:
                await ctx.send(f"Tastytrade: Running in DRY mode. Trasaction would've been: {action} {amount} of {stock}")
    await streamer.close()
